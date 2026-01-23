"""
CLI commands for the v2 executor engine.

Commands:
- spec compile: Compile JobDef + AIP to JobInstance
- spec execute: Execute a pre-compiled JobInstance
- spec run: Compile and execute in one step
- spec status: Show run status
- spec logs: Show run logs
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml

from spec.executor.engine import (
    CompileError,
    ExecutorError,
    compile_job,
    execute,
    generate_run_id,
    get_job_def,
    list_job_defs,
)
from spec.executor.schemas import (
    JobInstance,
    OutcomeStatus,
    RunStatus,
)
from spec.executor.store import RunStore

# Create the typer app for exec commands
exec_app = typer.Typer(help="Executor commands for v2 job-based execution")


def _echo_error(message: str) -> None:
    """Print error message in red."""
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)


def _echo_success(message: str) -> None:
    """Print success message in green."""
    typer.secho(message, fg=typer.colors.GREEN)


def _echo_warning(message: str) -> None:
    """Print warning message in yellow."""
    typer.secho(message, fg=typer.colors.YELLOW)


def _echo_step(step_n: int, total: int, step_id: str, backend: str, status: str = "running") -> None:
    """Print step progress."""
    if status == "running":
        typer.echo(f"[{step_n}/{total}] Running step '{step_id}' ({backend})...")
    elif status == "completed":
        typer.secho(f"[{step_n}/{total}] ✓ {step_id}", fg=typer.colors.GREEN)
    elif status == "failed":
        typer.secho(f"[{step_n}/{total}] ✗ {step_id}", fg=typer.colors.RED)
    elif status == "skipped":
        typer.secho(f"[{step_n}/{total}] - {step_id} (skipped)", fg=typer.colors.YELLOW)


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# =============================================================================
# spec compile
# =============================================================================


@exec_app.command("compile")
def compile_command(
    job_id: str = typer.Argument(..., help="Job template ID (e.g., 'aip-1')"),
    aip_path: Path = typer.Argument(..., help="Path to AIP YAML file"),
    output: Path = typer.Option(
        None, "--output", "-o", help="Output path for JobInstance (default: stdout)"
    ),
    repo_path: Path = typer.Option(
        None, "--repo", "-r", help="Repository path (default: current directory)"
    ),
    branch: str = typer.Option(
        None, "--branch", "-b", help="Feature branch name (default: from AIP or auto-generated)"
    ),
) -> None:
    """Compile a JobDef + AIP into a JobInstance.

    Builds an envelope from the AIP file and compiles it into a JobInstance
    that can be executed with 'spec execute'.

    Examples:
        spec compile aip-1 ./my-feature.aip.yaml
        spec compile aip-1 ./my-feature.aip.yaml --output job.yaml
        spec compile aip-1 ./my-feature.aip.yaml --repo /workspace/target
    """
    # Validate inputs
    if not aip_path.exists():
        _echo_error(f"AIP file not found: {aip_path}")
        raise typer.Exit(1)

    if job_id not in list_job_defs():
        _echo_error(f"Unknown job_id: {job_id}")
        typer.echo(f"Available job IDs: {', '.join(list_job_defs())}")
        raise typer.Exit(1)

    # Load AIP
    try:
        aip_data = _load_yaml(aip_path)
    except Exception as e:
        _echo_error(f"Failed to load AIP: {e}")
        raise typer.Exit(1)

    # Resolve repo path
    if repo_path is None:
        repo_path = Path.cwd()
    repo_path = repo_path.resolve()

    # Resolve branch
    if branch is None:
        branch = aip_data.get("workspace", {}).get("branch")
        if not branch:
            aip_id = aip_data.get("aip_id", aip_path.stem)
            branch = f"feat/{aip_id}"

    # Build envelope
    envelope = {
        "job_id": job_id,
        "payload": {
            "aip_path": str(aip_path.resolve()),
            "repo_path": str(repo_path),
            "feature_branch": branch,
        },
        "ctx": {
            "aip_id": aip_data.get("aip_id", aip_path.stem),
        },
    }

    # Get JobDef and compile
    try:
        job_def = get_job_def(job_id)
        job_instance = compile_job(job_def, envelope)
    except CompileError as e:
        _echo_error(f"Compilation failed: {e}")
        raise typer.Exit(1)

    # Output
    instance_dict = job_instance.model_dump(mode="json")

    if output:
        _write_yaml(output, instance_dict)
        _echo_success(f"JobInstance written to: {output}")
        typer.echo(f"  Job ID:     {job_instance.job_id}")
        typer.echo(f"  Job Hash:   {job_instance.job_hash}")
        typer.echo(f"  Steps:      {len(job_instance.steps)}")
    else:
        # Print to stdout
        print(yaml.dump(instance_dict, default_flow_style=False, allow_unicode=True, sort_keys=False))


# =============================================================================
# spec execute
# =============================================================================


@exec_app.command("execute")
def execute_command(
    job_instance_path: Path = typer.Argument(..., help="Path to JobInstance YAML file"),
    run_id: str = typer.Option(
        None, "--run-id", help="Custom run ID (default: auto-generated)"
    ),
) -> None:
    """Execute a pre-compiled JobInstance.

    Runs the steps in the JobInstance without recompiling.
    Useful for testing job definitions or replaying a run.

    Examples:
        spec execute ./job_instance.yaml
        spec execute ./job_instance.yaml --run-id custom-run-001
    """
    # Validate input
    if not job_instance_path.exists():
        _echo_error(f"JobInstance file not found: {job_instance_path}")
        raise typer.Exit(1)

    # Load JobInstance
    try:
        instance_data = _load_yaml(job_instance_path)
        job_instance = JobInstance.model_validate(instance_data)
    except Exception as e:
        _echo_error(f"Failed to load JobInstance: {e}")
        raise typer.Exit(1)

    # Generate run_id if not provided
    if run_id is None:
        run_id = generate_run_id()

    typer.echo(f"Executing JobInstance: {job_instance.job_id}")
    typer.echo(f"  Run ID:   {run_id}")
    typer.echo(f"  Steps:    {len(job_instance.steps)}")
    typer.echo("")

    # Execute steps directly (bypass compile)
    store = RunStore()

    # Build minimal envelope from JobInstance
    first_step = job_instance.steps[0]
    envelope = {
        "job_id": job_instance.job_id,
        "payload": {
            "repo_path": str(first_step.common.repo_path),
            "feature_branch": first_step.common.branch,
        },
        "ctx": {},
    }

    try:
        result = execute(envelope, store=store, run_id=run_id)
    except ExecutorError as e:
        _echo_error(f"Execution failed: {e}")
        raise typer.Exit(1)

    # Show results
    _show_run_summary(result, store)

    # Exit code based on status
    if result.status == RunStatus.failed:
        raise typer.Exit(1)
    elif result.status == RunStatus.completed_with_errors:
        raise typer.Exit(2)


# =============================================================================
# spec run
# =============================================================================


@exec_app.command("run")
def run_command(
    job_id: str = typer.Argument(..., help="Job template ID (e.g., 'aip-1')"),
    aip_path: Path = typer.Argument(..., help="Path to AIP YAML file"),
    repo_path: Path = typer.Option(
        None, "--repo", "-r", help="Repository path (default: current directory)"
    ),
    branch: str = typer.Option(
        None, "--branch", "-b", help="Feature branch name (default: from AIP or auto-generated)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Compile and print JobInstance without executing"
    ),
    run_id: str = typer.Option(
        None, "--run-id", help="Custom run ID (default: auto-generated)"
    ),
) -> None:
    """Compile and execute a job in one step.

    Builds an envelope from the AIP file, compiles it to a JobInstance,
    and executes the steps.

    Examples:
        spec run aip-1 ./my-feature.aip.yaml
        spec run aip-1 ./my-feature.aip.yaml --repo /workspace/target
        spec run aip-1 ./my-feature.aip.yaml --dry-run
    """
    # Validate inputs
    if not aip_path.exists():
        _echo_error(f"AIP file not found: {aip_path}")
        raise typer.Exit(1)

    if job_id not in list_job_defs():
        _echo_error(f"Unknown job_id: {job_id}")
        typer.echo(f"Available job IDs: {', '.join(list_job_defs())}")
        raise typer.Exit(1)

    # Load AIP
    try:
        aip_data = _load_yaml(aip_path)
    except Exception as e:
        _echo_error(f"Failed to load AIP: {e}")
        raise typer.Exit(1)

    # Resolve repo path
    if repo_path is None:
        repo_path = Path.cwd()
    repo_path = repo_path.resolve()

    # Resolve branch
    if branch is None:
        branch = aip_data.get("workspace", {}).get("branch")
        if not branch:
            aip_id = aip_data.get("aip_id", aip_path.stem)
            branch = f"feat/{aip_id}"

    # Build envelope
    envelope = {
        "job_id": job_id,
        "payload": {
            "aip_path": str(aip_path.resolve()),
            "repo_path": str(repo_path),
            "feature_branch": branch,
        },
        "ctx": {
            "aip_id": aip_data.get("aip_id", aip_path.stem),
        },
    }

    if dry_run:
        # Compile and print without executing
        try:
            job_def = get_job_def(job_id)
            job_instance = compile_job(job_def, envelope)
        except CompileError as e:
            _echo_error(f"Compilation failed: {e}")
            raise typer.Exit(1)

        typer.echo("Dry run - JobInstance compiled but not executed:")
        typer.echo("")
        instance_dict = job_instance.model_dump(mode="json")
        print(yaml.dump(instance_dict, default_flow_style=False, allow_unicode=True, sort_keys=False))
        return

    # Generate run_id if not provided
    if run_id is None:
        run_id = generate_run_id()

    typer.echo(f"Running job: {job_id}")
    typer.echo(f"  Run ID:   {run_id}")
    typer.echo(f"  AIP:      {aip_path}")
    typer.echo(f"  Repo:     {repo_path}")
    typer.echo(f"  Branch:   {branch}")
    typer.echo("")

    # Execute
    store = RunStore()

    try:
        result = execute(envelope, store=store, run_id=run_id)
    except ExecutorError as e:
        _echo_error(f"Execution failed: {e}")
        raise typer.Exit(1)

    # Show results
    _show_run_summary(result, store)

    # Exit code based on status
    if result.status == RunStatus.failed:
        raise typer.Exit(1)
    elif result.status == RunStatus.completed_with_errors:
        raise typer.Exit(2)


# =============================================================================
# spec status
# =============================================================================


@exec_app.command("status")
def status_command(
    run_id: str = typer.Argument(None, help="Run ID to show status for (optional)"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of recent runs to show"),
) -> None:
    """Show run status.

    Without run_id: List recent runs.
    With run_id: Show detailed run status.

    Examples:
        spec status
        spec status run-20260123-143052-abc123
        spec status --limit 20
    """
    store = RunStore()

    if run_id is None:
        # List recent runs
        runs = store.list_runs()
        if not runs:
            typer.echo("No runs found.")
            return

        # Show most recent first
        runs = sorted(runs, reverse=True)[:limit]

        typer.echo(f"Recent runs ({len(runs)} shown):")
        typer.echo("")
        typer.echo(f"{'RUN ID':<40} {'STATUS':<20} {'JOB':<15}")
        typer.echo("-" * 75)

        for rid in runs:
            try:
                record = store.read_run_record(rid)
                status_color = _status_color(record.status)
                typer.echo(f"{rid:<40} ", nl=False)
                typer.secho(f"{record.status.value:<20}", fg=status_color, nl=False)
                typer.echo(f" {record.job_id:<15}")
            except Exception:
                typer.echo(f"{rid:<40} {'<error reading>':<20}")
    else:
        # Show specific run
        if not store.run_exists(run_id):
            _echo_error(f"Run not found: {run_id}")
            raise typer.Exit(1)

        record = store.read_run_record(run_id)
        _show_run_details(record, store)


# =============================================================================
# spec logs
# =============================================================================


@exec_app.command("logs")
def logs_command(
    run_id: str = typer.Argument(..., help="Run ID to show logs for"),
    step_n: int = typer.Argument(None, help="Step number to show logs for (optional)"),
    patch: bool = typer.Option(False, "--patch", "-p", help="Show git diff patch"),
    stderr: bool = typer.Option(False, "--stderr", "-e", help="Show stderr instead of stdout"),
) -> None:
    """Show run logs.

    Without step_n: Show run summary.
    With step_n: Show step stdout/stderr.

    Examples:
        spec logs run-20260123-143052-abc123
        spec logs run-20260123-143052-abc123 2
        spec logs run-20260123-143052-abc123 2 --stderr
        spec logs run-20260123-143052-abc123 2 --patch
    """
    store = RunStore()

    if not store.run_exists(run_id):
        _echo_error(f"Run not found: {run_id}")
        raise typer.Exit(1)

    if step_n is None:
        # Show run summary
        record = store.read_run_record(run_id)
        _show_run_details(record, store)
    else:
        # Show step logs
        step_path = store.get_step_path(run_id, step_n)
        if not step_path.exists():
            _echo_error(f"Step {step_n} not found in run {run_id}")
            raise typer.Exit(1)

        if patch:
            # Show git diff
            patch_file = step_path / "changes.patch"
            if patch_file.exists():
                typer.echo(f"Git diff for step {step_n}:")
                typer.echo("-" * 40)
                print(patch_file.read_text())
            else:
                typer.echo(f"No patch file for step {step_n}")
        else:
            # Show stdout or stderr
            if stderr:
                log_file = step_path / "stderr.txt"
                log_type = "stderr"
            else:
                log_file = step_path / "stdout.txt"
                log_type = "stdout"

            if log_file.exists():
                content = log_file.read_text()
                if content:
                    typer.echo(f"Step {step_n} {log_type}:")
                    typer.echo("-" * 40)
                    print(content)
                else:
                    typer.echo(f"Step {step_n} {log_type} is empty")
            else:
                typer.echo(f"No {log_type} file for step {step_n}")


# =============================================================================
# Helper Functions
# =============================================================================


def _status_color(status: RunStatus) -> str:
    """Get color for status."""
    if status == RunStatus.completed:
        return typer.colors.GREEN
    elif status == RunStatus.completed_with_errors:
        return typer.colors.YELLOW
    elif status == RunStatus.failed:
        return typer.colors.RED
    elif status == RunStatus.running:
        return typer.colors.BLUE
    else:
        return typer.colors.WHITE


def _show_run_summary(result, store: RunStore) -> None:
    """Show run summary after execution."""
    typer.echo("")
    typer.echo("=" * 50)

    status_color = _status_color(result.status)
    typer.echo("Run completed: ", nl=False)
    typer.secho(result.status.value, fg=status_color)

    typer.echo(f"  Run ID:     {result.run_id}")
    typer.echo(f"  Job:        {result.job_id}")

    # Show step summary
    steps = store.list_steps(result.run_id)
    completed = 0
    failed = 0
    for step_n in steps:
        try:
            outcome = store.read_step_outcome(result.run_id, step_n)
            if outcome.outcome == OutcomeStatus.completed:
                completed += 1
            else:
                failed += 1
        except Exception:
            pass

    typer.echo(f"  Steps:      {completed} completed, {failed} failed")
    typer.echo(f"  Artifacts:  {store.get_run_path(result.run_id)}")

    if result.error:
        _echo_error(f"Error: {result.error}")


def _show_run_details(record, store: RunStore) -> None:
    """Show detailed run information."""
    status_color = _status_color(record.status)

    typer.echo(f"Run: {record.run_id}")
    typer.echo("  Status:     ", nl=False)
    typer.secho(record.status.value, fg=status_color)
    typer.echo(f"  Job:        {record.job_id}")
    typer.echo(f"  Job Hash:   {record.job_hash}")
    typer.echo(f"  Repo:       {record.repo.repo_path}")
    typer.echo(f"  Branch:     {record.repo.branch}")
    typer.echo(f"  Base:       {record.repo.base_commit[:8]}")
    typer.echo(f"  Created:    {record.created_at}")

    if record.error:
        typer.echo("  Error:      ", nl=False)
        typer.secho(record.error, fg=typer.colors.RED)

    # Show steps
    steps = store.list_steps(record.run_id)
    if steps:
        typer.echo("")
        typer.echo("Steps:")
        for step_n in steps:
            try:
                outcome = store.read_step_outcome(record.run_id, step_n)
                if outcome.outcome == OutcomeStatus.completed:
                    status_icon = "✓"
                    color = typer.colors.GREEN
                elif outcome.outcome == OutcomeStatus.failed:
                    status_icon = "✗"
                    color = typer.colors.RED
                elif outcome.outcome == OutcomeStatus.timeout:
                    status_icon = "⏱"
                    color = typer.colors.YELLOW
                else:
                    status_icon = "?"
                    color = typer.colors.WHITE

                typer.echo(f"  [{step_n}] ", nl=False)
                typer.secho(f"{status_icon} ", fg=color, nl=False)
                typer.echo(f"{outcome.step_id} ({outcome.duration_ms}ms)")

                if outcome.error:
                    typer.echo("      ", nl=False)
                    typer.secho(outcome.error, fg=typer.colors.RED)
            except Exception as e:
                typer.echo(f"  [{step_n}] <error: {e}>")

    # Show attempts
    attempts = store.list_attempts(record.run_id)
    if attempts:
        typer.echo("")
        typer.echo(f"Attempts: {len(attempts)}")
