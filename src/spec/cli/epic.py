"""Epic management CLI commands.

This module provides Typer commands for managing epics - multi-spec
implementation plans with dependency tracking and status management.
"""

from __future__ import annotations

import functools

import typer

from spec.core.exceptions import SpecwrightError

epic_app = typer.Typer(help="Epic management commands")


def _epic_exception_handler(func):
    """Decorator to catch SpecwrightError and exit with proper exit code."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SpecwrightError as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(e.exit_code)

    return wrapper


@epic_app.command("mark-done")
@_epic_exception_handler
def mark_done(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    spec_id: str = typer.Option(..., "--spec", "-s", help="Spec ID to mark done"),
    note: str | None = typer.Option(None, "--note", "-n", help="Completion note"),
) -> None:
    """Mark a spec as done.

    Updates the spec status to 'done' and suggests the next ready spec.

    Examples:
        spec epic mark-done e001-auth --spec spec-01
        spec epic mark-done e001-auth --spec spec-01 --note "OAuth flow implemented"
    """
    from spec.epic.loader import load_epic
    from spec.epic.writer import mark_spec_done

    epic = load_epic(epic_id)
    next_spec = mark_spec_done(epic, spec_id, note)

    typer.secho(f"✓ Marked spec '{spec_id}' as done", fg=typer.colors.GREEN)

    if next_spec:
        typer.echo(f"\nSuggested next spec: {next_spec}")
    else:
        typer.echo("\nNo more ready specs. Epic may be complete!")


@epic_app.command()
@_epic_exception_handler
def status(
    epic_id: str = typer.Argument(..., help="Epic ID"),
) -> None:
    """Show epic status with DAG visualization.

    Displays:
    - Epic title and overall status
    - Current spec indicator (→)
    - DAG with status icons: ✓ done, → active, ○ planned, ✗ blocked, ⊘ abandoned
    - Check summary

    Examples:
        spec epic status e001-auth
    """
    from spec.epic.loader import load_epic
    from spec.epic.schema import SpecStatus

    epic = load_epic(epic_id)

    # Status icons
    status_icons = {
        SpecStatus.DONE: ("✓", typer.colors.GREEN),
        SpecStatus.ACTIVE: ("→", typer.colors.CYAN),
        SpecStatus.PLANNED: ("○", typer.colors.WHITE),
        SpecStatus.BLOCKED: ("✗", typer.colors.RED),
        SpecStatus.ABANDONED: ("⊘", typer.colors.YELLOW),
    }

    # Header
    typer.echo(f"\n{'='*60}")
    typer.secho(f"Epic: {epic.title}", bold=True)
    typer.echo(f"ID: {epic.id}")
    typer.echo(f"Owner: {epic.owner}")

    if epic.state:
        state_icon, state_color = status_icons.get(
            epic.state.status, ("?", typer.colors.WHITE)
        )
        typer.echo("Status: ", nl=False)
        typer.secho(f"{state_icon} {epic.state.status.value}", fg=state_color)
        if epic.state.current_spec:
            typer.echo(f"Current: {epic.state.current_spec}")

    typer.echo(f"{'='*60}")

    # Goal
    typer.echo(f"\nGoal: {epic.intent.goal}")

    # Specs DAG
    typer.secho("\nSpecs:", bold=True)

    if not epic.specs:
        typer.echo("  (no specs)")
    else:
        # Get topological order for display
        try:
            ordered = epic.topological_order()
        except ValueError:
            ordered = epic.specs  # Fallback if cycle

        current_spec_id = epic.state.current_spec if epic.state else None

        for spec in ordered:
            icon, color = status_icons.get(spec.status, ("?", typer.colors.WHITE))

            # Highlight current spec
            if spec.id == current_spec_id:
                icon = "→"
                color = typer.colors.CYAN

            prefix = "  "
            if spec.depends_on:
                deps = ", ".join(spec.depends_on)
                prefix = f"  (← {deps}) "

            typer.secho(f"{prefix}{icon} ", fg=color, nl=False)
            typer.echo(f"{spec.id}", nl=False)
            if spec.status != SpecStatus.PLANNED:
                typer.secho(f" [{spec.status.value}]", fg=color, dim=True, nl=False)
            typer.echo()

    # Checks summary
    if epic.checks:
        typer.secho(f"\nChecks ({len(epic.checks)}):", bold=True)
        for check in epic.checks:
            typer.echo(f"  - {check.id}: {check.name}")

    # Recent history
    if epic.state and epic.state.history:
        typer.secho("\nRecent History:", bold=True)
        for event in epic.state.history[-5:]:  # Last 5 events
            typer.echo(f"  [{event.id}] {event.event.value}", nl=False)
            if event.spec_id:
                typer.echo(f" ({event.spec_id})", nl=False)
            if event.note:
                typer.echo(f" - {event.note[:40]}...", nl=False) if len(
                    event.note
                ) > 40 else typer.echo(f" - {event.note}", nl=False)
            typer.echo()

    typer.echo()


@epic_app.command("list")
@_epic_exception_handler
def list_epics() -> None:
    """List all epics in the governor.

    Examples:
        spec epic list
    """
    from spec.epic.loader import list_epics as do_list_epics
    from spec.epic.loader import load_epic

    epic_ids = do_list_epics()

    if not epic_ids:
        typer.echo("No epics found.")
        return

    typer.secho(f"\nEpics ({len(epic_ids)}):", bold=True)

    for epic_id in epic_ids:
        try:
            epic = load_epic(epic_id)
            status = epic.state.status.value if epic.state else "unknown"
            typer.echo(f"  - {epic_id}: {epic.title} [{status}]")
        except Exception as e:
            typer.echo(f"  - {epic_id}: (error loading: {e})")

    typer.echo()


@epic_app.command()
@_epic_exception_handler
def validate(
    epic_id: str = typer.Argument(..., help="Epic ID"),
) -> None:
    """Validate an epic's structure and references.

    Checks:
    - All spec repo references exist in targets
    - No cycles in dependency graph
    - All check references exist
    - Current spec is active (if set)

    Exit codes:
        0 = Valid
        3 = Validation errors

    Examples:
        spec epic validate e001-auth
    """
    from spec.epic.loader import EpicValidationError, load_epic

    try:
        load_epic(epic_id)
        typer.secho(f"✓ Epic '{epic_id}' is valid", fg=typer.colors.GREEN)
        raise typer.Exit(0)
    except EpicValidationError as e:
        typer.secho(f"✗ Validation failed for '{epic_id}':", fg=typer.colors.RED, err=True)
        typer.echo(str(e), err=True)
        raise typer.Exit(3)


class CheckNotFoundError(SpecwrightError):
    """Check not found in epic."""

    exit_code = 2


@epic_app.command()
@_epic_exception_handler
def check(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    check_id: str | None = typer.Option(None, "--check", "-c", help="Specific check to run"),
) -> None:
    """Run LLM checks for an epic.

    Executes LLM-based checks defined in the epic. Requires LLM to be enabled
    in the local-governor config.

    Exit codes:
        0 = Success (all checks passed or no checks defined)
        2 = Epic or check not found
        4 = LLM config error (not enabled or invalid config)
        5 = LLM execution error

    Examples:
        spec epic check e001-auth
        spec epic check e001-auth --check CHECK-e001-core
    """
    from spec.epic.loader import get_epic_path, load_epic
    from spec.llm.client import LLMClient
    from spec.llm.config import require_llm_enabled

    # Load the epic (raises EpicNotFoundError with exit_code=2 if not found)
    epic = load_epic(epic_id)

    # Validate LLM is enabled (raises LLMConfigError with exit_code=4 if not)
    llm_config = require_llm_enabled()

    # Handle case where no checks are defined
    if not epic.checks:
        typer.secho("No checks defined for this epic.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    # If specific check requested, validate it exists
    if check_id is not None:
        target_check = epic.get_check(check_id)
        if target_check is None:
            raise CheckNotFoundError(f"Check not found: {check_id}")
        checks_to_run = [target_check]
    else:
        checks_to_run = epic.checks

    # Get default model from epic defaults or use a fallback
    default_model = epic.defaults.model if epic.defaults and epic.defaults.model else "gpt-4"

    epic_path = get_epic_path(epic_id)

    # Run each check
    for check_def in checks_to_run:
        typer.echo(f"Running check: {check_def.name} ({check_def.id})")

        # Load prompt from prompt_ref
        prompt_path = epic_path / check_def.prompt_ref
        if not prompt_path.exists():
            raise CheckNotFoundError(f"Check prompt file not found: {check_def.prompt_ref}")

        prompt_text = prompt_path.read_text(encoding="utf-8")

        # Determine which model to use (check-specific or default)
        model_name = check_def.model if check_def.model else default_model

        # Create client and execute
        client = LLMClient(llm_config, model_name)
        response = client.prompt(prompt_text)

        typer.secho(f"  ✓ Check completed: {check_def.id}", fg=typer.colors.GREEN)
        typer.echo(f"  Response preview: {response[:200]}..." if len(response) > 200 else f"  Response: {response}")

    typer.secho(f"\n✓ All checks completed ({len(checks_to_run)} total)", fg=typer.colors.GREEN)
