"""
CLI commands for the v2 executor engine.

Commands (registered at top-level of spec CLI per e008-05):
- spec compile: Compile JobDef + spec to JobInstance
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
    execute_instance,
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

# Required frontmatter fields for .md specs
REQUIRED_FRONTMATTER = {"tier", "title", "owner", "goal"}
VALID_TIERS = {"A", "B", "C"}


def _echo_error(message: str) -> None:
    """Print error message in red."""
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)


def _echo_success(message: str) -> None:
    """Print success message in green."""
    typer.secho(message, fg=typer.colors.GREEN)


def _echo_warning(message: str) -> None:
    """Print warning message in yellow."""
    typer.secho(message, fg=typer.colors.YELLOW)


def _parse_spec_frontmatter(content: str) -> dict[str, Any]:
    """Parse and validate YAML frontmatter from .md spec.

    Args:
        content: Full markdown content of spec file

    Returns:
        Parsed and validated frontmatter dict

    Raises:
        ValueError: If frontmatter is missing, malformed, or invalid
    """
    if not content.startswith("---\n"):
        raise ValueError("Spec must start with YAML frontmatter (---)")

    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Frontmatter not closed (missing ---)")

    frontmatter_text = content[4:end]
    frontmatter = yaml.safe_load(frontmatter_text) or {}

    # Validate required fields
    missing = REQUIRED_FRONTMATTER - set(frontmatter.keys())
    if missing:
        raise ValueError(f"Missing required frontmatter fields: {missing}")

    # Validate tier
    tier = str(frontmatter.get("tier", "")).upper()
    if tier not in VALID_TIERS:
        raise ValueError(f"Invalid tier '{frontmatter.get('tier')}'. Must be one of {VALID_TIERS}")
    frontmatter["tier"] = tier  # Normalize to uppercase

    # Validate non-empty strings for required fields
    for key in REQUIRED_FRONTMATTER:
        val = frontmatter[key]
        if key == "tier":
            continue  # Already validated
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"Frontmatter field '{key}' must be a non-empty string")

    return frontmatter


def _update_frontmatter(content: str, updates: dict[str, Any]) -> str:
    """Update frontmatter fields in spec content.

    Args:
        content: Full markdown content
        updates: Dict of fields to add/update in frontmatter

    Returns:
        Updated content with modified frontmatter
    """
    if not content.startswith("---\n"):
        raise ValueError("Spec must start with YAML frontmatter (---)")

    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Frontmatter not closed (missing ---)")

    frontmatter_text = content[4:end]
    frontmatter = yaml.safe_load(frontmatter_text) or {}

    # Apply updates
    frontmatter.update(updates)

    # Rebuild content
    new_frontmatter = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)
    body = content[end + 5:]  # After closing ---

    return f"---\n{new_frontmatter}---\n{body}"


def _get_spec_path(epic_id: str, spec_id: str) -> Path:
    """Get path to .md spec file from governor storage.

    Looks in: ~/.local/local-governor/projects/*/specs/{epic_id}/{spec_id}.md
    """
    governor_root = Path.home() / ".local/local-governor/projects"
    if not governor_root.exists():
        raise FileNotFoundError(f"Governor root not found: {governor_root}")

    # Search all projects for the spec
    for project_dir in governor_root.iterdir():
        if not project_dir.is_dir():
            continue
        specs_dir = project_dir / "specs" / epic_id
        if specs_dir.exists():
            spec_file = specs_dir / f"{spec_id}.md"
            if spec_file.exists():
                return spec_file

    raise FileNotFoundError(f"Spec not found: {epic_id}/{spec_id}.md")


def _extract_check_paths(epic: Any, spec_id: str) -> list[str]:
    """Extract file paths from epic checks that apply to this spec.

    Args:
        epic: The Epic object
        spec_id: The spec ID to get checks for

    Returns:
        List of file paths that checks will verify
    """
    paths = []

    spec = epic.get_spec(spec_id)
    if not spec:
        return paths

    for check_id in spec.checks:
        check = epic.get_check(check_id)
        if check:
            for inp in check.inputs:
                if inp.type == "file" and inp.path:
                    paths.append(inp.path)
                elif inp.type == "directory" and inp.path:
                    paths.append(inp.path.rstrip("/") + "/")

    return paths


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


def compile_command(
    job_id: str = typer.Argument(..., help="Job template ID (e.g., 'aip-1')"),
    spec_path: Path = typer.Argument(..., help="Path to spec .md file"),
    output: Path = typer.Option(
        None, "--output", "-o", help="Output path for JobInstance (default: stdout)"
    ),
    repo_path: Path = typer.Option(
        None, "--repo", "-r", help="Repository path (default: current directory)"
    ),
    branch: str = typer.Option(
        None, "--branch", "-b", help="Feature branch name (default: from spec or auto-generated)"
    ),
) -> None:
    """Compile a JobDef + spec into a JobInstance.

    Builds an envelope from the spec file and compiles it into a JobInstance
    that can be executed with 'spec execute'.

    Examples:
        spec compile aip-1 ./my-feature.md
        spec compile aip-1 ./my-feature.md --output job.yaml
        spec compile aip-1 ./my-feature.md --repo /workspace/target
    """
    # Validate inputs
    if not spec_path.exists():
        _echo_error(f"Spec file not found: {spec_path}")
        raise typer.Exit(1)

    if job_id not in list_job_defs():
        _echo_error(f"Unknown job_id: {job_id}")
        typer.echo(f"Available job IDs: {', '.join(list_job_defs())}")
        raise typer.Exit(1)

    # Load spec markdown
    try:
        spec_md = spec_path.read_text()
        frontmatter = _parse_spec_frontmatter(spec_md)
    except ValueError as e:
        _echo_error(f"Invalid spec: {e}")
        raise typer.Exit(1)
    except Exception as e:
        _echo_error(f"Failed to load spec: {e}")
        raise typer.Exit(1)

    # Resolve repo path
    if repo_path is None:
        repo_path = Path.cwd()
    repo_path = repo_path.resolve()

    # Resolve branch from frontmatter or generate from title
    if branch is None:
        branch = frontmatter.get("repo", {}).get("working_branch")
        if not branch:
            title_slug = frontmatter["title"].lower().replace(" ", "-")
            branch = f"feat/{title_slug}"

    # Build envelope
    envelope = {
        "job_id": job_id,
        "payload": {
            "spec_md": spec_md,  # Full markdown content
            "spec_path": str(spec_path.resolve()),
            "repo_path": str(repo_path),
            "feature_branch": branch,
            "epic_spec": None,  # No epic context when compiling from file
        },
        "ctx": {
            "spec_id": spec_path.stem,
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

    # Execute directly from JobInstance (no recompilation)
    store = RunStore()

    try:
        result = execute_instance(job_instance, store=store, run_id=run_id)
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


def run_command(
    job_id: str = typer.Argument(..., help="Job template ID (e.g., 'aip-1')"),
    spec_path: Path = typer.Argument(None, help="Path to spec .md file (optional if --epic/--spec used)"),
    repo_path: Path = typer.Option(
        None, "--repo", "-r", help="Repository path (default: current directory)"
    ),
    branch: str = typer.Option(
        None, "--branch", "-b", help="Feature branch name (default: from spec or auto-generated)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Compile and print JobInstance without executing"
    ),
    run_id: str = typer.Option(
        None, "--run-id", help="Custom run ID (default: auto-generated)"
    ),
    epic_id: str = typer.Option(
        None, "--epic", "-e", help="Epic ID to load spec from (use with --spec)"
    ),
    spec_id: str = typer.Option(
        None, "--spec", "-s", help="Spec ID to load from (use with --epic)"
    ),
) -> None:
    """Compile and execute a job in one step.

    Builds an envelope from the spec file, compiles it to a JobInstance,
    and executes the steps.

    Examples:
        spec run aip-1 ./my-feature.md
        spec run aip-1 ./my-feature.md --repo /workspace/target
        spec run aip-1 ./my-feature.md --dry-run
        spec run aip-1 --epic e005-command-plane --spec e005-01-schemas
    """
    # Validate inputs - must have either spec_path or epic/spec
    if spec_path is None and (epic_id is None or spec_id is None):
        _echo_error("Must provide either SPEC_PATH or both --epic and --spec")
        raise typer.Exit(1)

    if spec_path is not None and (epic_id is not None or spec_id is not None):
        _echo_error("Cannot use both SPEC_PATH and --epic/--spec")
        raise typer.Exit(1)

    if job_id not in list_job_defs():
        _echo_error(f"Unknown job_id: {job_id}")
        typer.echo(f"Available job IDs: {', '.join(list_job_defs())}")
        raise typer.Exit(1)

    # Load spec - either from file or from epic/spec
    epic_spec = None  # Will be populated for epic/spec mode
    resolved_spec_id = spec_id  # For ctx

    if epic_id and spec_id:
        # Load .md from governor
        from spec.epic.loader import load_epic

        try:
            spec_path = _get_spec_path(epic_id, spec_id)
        except FileNotFoundError as e:
            _echo_error(f"Failed to load spec from epic/spec: {e}")
            raise typer.Exit(1)

        # Load epic to get spec expectations for drift checking
        try:
            epic = load_epic(epic_id)
            spec_ref = epic.get_spec(spec_id)
            if spec_ref:
                epic_spec = {
                    "expectations": spec_ref.expectations,
                    "constraints": spec_ref.constraints,
                    "check_paths": _extract_check_paths(epic, spec_id),
                }
                # Get repo path from epic spec if available
                if repo_path is None and hasattr(spec_ref, "repo_path") and spec_ref.repo_path:
                    repo_path = Path(spec_ref.repo_path)
        except Exception as e:
            # Non-fatal - epic_spec is optional enhancement
            typer.secho(f"Warning: Could not load epic context: {e}", fg=typer.colors.YELLOW, err=True)

    # Load spec markdown
    if not spec_path.exists():
        _echo_error(f"Spec file not found: {spec_path}")
        raise typer.Exit(1)

    try:
        spec_md = spec_path.read_text()
        frontmatter = _parse_spec_frontmatter(spec_md)
    except ValueError as e:
        _echo_error(f"Invalid spec: {e}")
        raise typer.Exit(1)
    except Exception as e:
        _echo_error(f"Failed to load spec: {e}")
        raise typer.Exit(1)

    # Use filename as spec_id if not from epic mode
    if resolved_spec_id is None:
        resolved_spec_id = spec_path.stem

    # Resolve repo path
    if repo_path is None:
        repo_path = Path.cwd()
    repo_path = repo_path.resolve()

    # Resolve branch from frontmatter or generate from title
    if branch is None:
        branch = frontmatter.get("repo", {}).get("working_branch")
        if not branch:
            title_slug = frontmatter["title"].lower().replace(" ", "-")
            branch = f"feat/{title_slug}"

    # Build envelope
    envelope = {
        "job_id": job_id,
        "payload": {
            "spec_md": spec_md,  # Full markdown content
            "spec_path": str(spec_path.resolve()),
            "repo_path": str(repo_path),
            "feature_branch": branch,
            "epic_id": epic_id,
            "spec_id": resolved_spec_id,
            "epic_spec": epic_spec,  # Epic expectations for drift checking (may be None)
        },
        "ctx": {
            "spec_id": resolved_spec_id,
            "epic_id": epic_id,
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
        run_id = generate_run_id(spec_id=resolved_spec_id)

    typer.echo(f"Running job: {job_id}")
    typer.echo(f"  Run ID:   {run_id}")
    if epic_id and spec_id:
        typer.echo(f"  Epic:     {epic_id}")
        typer.echo(f"  Spec:     {resolved_spec_id}")
    else:
        typer.echo(f"  Spec:     {spec_path}")
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


# =============================================================================
# spec validate
# =============================================================================


def validate_command(
    spec_path: Path = typer.Argument(None, help="Path to spec .md file (uses current if omitted)"),
    check_only: bool = typer.Option(
        False, "--check", "-c", help="Check only, don't write validated flag"
    ),
) -> None:
    """Validate a spec file and mark it as validated.

    Validates the full spec structure:
    - YAML frontmatter with required fields (tier, title, owner, goal)
    - Plan section with at least one step
    - Proper markdown structure

    If valid, writes 'validated: true' to the frontmatter.

    Examples:
        spec validate ./my-feature.md
        spec validate ./my-feature.md --check
        spec validate  # uses current spec from config
    """
    from spec.compiler.parser import SpecParser

    # Resolve spec path from config if not provided
    if spec_path is None:
        from spec.cli.spec import find_config
        _, cfg = find_config()
        current_spec = cfg.get("current", {}).get("spec")
        if not current_spec:
            _echo_error("No spec path provided and no current spec set.")
            typer.echo("  Run: spec config current.spec <path-to-spec.md>")
            raise typer.Exit(1)
        spec_path = Path(current_spec)
        typer.echo(f"Using current spec: {spec_path}")

    if not spec_path.exists():
        _echo_error(f"Spec file not found: {spec_path}")
        raise typer.Exit(1)

    if spec_path.suffix != ".md":
        _echo_error(f"Spec must be a .md file (got {spec_path.suffix})")
        raise typer.Exit(1)

    # Full validation using SpecParser
    try:
        content = spec_path.read_text()
        parser = SpecParser(content, source_path=spec_path)
        parser.parse()  # This validates frontmatter, sections, and plan
        typer.secho("✓ Spec structure valid", fg=typer.colors.GREEN)
    except ValueError as e:
        _echo_error(f"Invalid spec: {e}")
        raise typer.Exit(1)
    except Exception as e:
        _echo_error(f"Failed to validate spec: {e}")
        raise typer.Exit(1)

    # Check if already validated
    if parser.frontmatter.get("validated"):
        _echo_success(f"Spec already validated: {spec_path}")
        return

    if check_only:
        _echo_success(f"Spec is valid: {spec_path}")
        typer.echo("  (use without --check to write 'validated: true')")
        return

    # Write validated flag
    try:
        updated_content = _update_frontmatter(content, {"validated": True})
        spec_path.write_text(updated_content)
        _echo_success(f"Spec validated: {spec_path}")
        typer.echo("  Added 'validated: true' to frontmatter")
    except Exception as e:
        _echo_error(f"Failed to update spec: {e}")
        raise typer.Exit(1)
