"""Epic management CLI commands.

This module provides Typer commands for managing epics - multi-spec
implementation plans with dependency tracking and status management.
"""

from __future__ import annotations

import functools
from typing import List

import typer

from spec.autogov.exceptions import SpecwrightError

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


@epic_app.command()
@_epic_exception_handler
def create(
    title: str = typer.Argument(..., help="Epic title"),
    id: str | None = typer.Option(None, "--id", help="Epic ID (auto-generated if not provided)"),
    goal: str = typer.Option(..., "--goal", "-g", help="One-line goal statement"),
    owner: str | None = typer.Option(None, "--owner", help="Owner username"),
) -> None:
    """Create a new epic.

    Creates an epic with the standard directory structure:
    - checks/: Check prompt files
    - reports/: Check execution reports
    - artifacts/snapshots/: Artifact snapshots
    - notes.md: Epic notes
    - epic.yaml: Epic definition

    Examples:
        spec epic create "Add OAuth" --goal "Implement OAuth2 authentication"
        spec epic create "Refactor DB" --id e002-db-refactor --goal "Migrate to PostgreSQL"
    """
    from spec.epic.writer import create_epic as do_create_epic

    # Auto-generate ID if not provided
    if id is None:
        # Generate ID from title: e001-my-epic-title
        import re

        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"[-\s]+", "-", slug).strip("-")

        # Find next available number
        from spec.epic.loader import list_epics

        existing = list_epics()
        existing_nums = []
        for eid in existing:
            match = re.match(r"e(\d+)-", eid)
            if match:
                existing_nums.append(int(match.group(1)))
        next_num = max(existing_nums, default=0) + 1
        id = f"e{next_num:03d}-{slug}"

    # Get owner from config if not provided
    if owner is None:
        from spec.cli.spec import find_config, get_user_default

        _, cfg = find_config()
        owner = get_user_default(cfg, "default_owner")
        if owner is None:
            typer.secho("Error: No owner specified", fg=typer.colors.RED, err=True)
            typer.echo(
                "  Use --owner flag or set default owner with: spec config user <username>",
                err=True,
            )
            raise typer.Exit(1)
        typer.echo(f"Using default owner: {owner}")

    # Create the epic
    epic = do_create_epic(
        id=id,
        title=title,
        owner=owner,
        goal=goal,
    )

    from spec.epic.loader import get_epic_path

    epic_dir = get_epic_path(epic.id)

    typer.secho(f"✓ Created epic: {epic.id}", fg=typer.colors.GREEN)
    typer.echo(f"  Title: {epic.title}")
    typer.echo(f"  Path: {epic_dir}")
    typer.echo("\nNext steps:")
    typer.echo(f"  1. Add targets: spec epic add-target {epic.id} --id myrepo --repo-path /path/to/repo")
    typer.echo(f"  2. Add specs: spec epic add-spec {epic.id} --id spec-01 --repo myrepo ...")
    typer.echo(f"  3. View status: spec epic status {epic.id}")


@epic_app.command("add-target")
@_epic_exception_handler
def add_target(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    target_id: str = typer.Option(..., "--id", help="Target ID"),
    repo_path: str = typer.Option(..., "--repo-path", help="Absolute path to repo"),
    default_branch: str = typer.Option("main", "--branch", help="Default branch"),
    governor_project: str | None = typer.Option(
        None, "--governor-project", help="Link to governor project"
    ),
) -> None:
    """Add a target repository to an epic.

    Examples:
        spec epic add-target e001-auth --id myrepo --repo-path /workspace/myrepo
        spec epic add-target e001-auth --id myrepo --repo-path /workspace/myrepo --branch main
    """
    from spec.epic.loader import load_epic
    from spec.epic.schema import Target
    from spec.epic.writer import add_target as do_add_target

    epic = load_epic(epic_id)

    target = Target(
        id=target_id,
        repo_path=repo_path,
        default_branch=default_branch,
        governor_project=governor_project,
    )

    do_add_target(epic, target)

    typer.secho(f"✓ Added target '{target_id}' to epic '{epic_id}'", fg=typer.colors.GREEN)


@epic_app.command("add-spec")
@_epic_exception_handler
def add_spec(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    spec_id: str = typer.Option(..., "--id", help="Spec ID"),
    repo: str = typer.Option(..., "--repo", help="Target repo ID"),
    branch: str = typer.Option(..., "--branch", help="Working branch"),
    path: str = typer.Option(..., "--path", help="Spec path relative to governor"),
    depends_on: List[str] = typer.Option([], "--depends-on", help="Dependency spec IDs"),
    expectation: List[str] = typer.Option([], "--expectation", "-e", help="Expectations"),
) -> None:
    """Add a spec reference to an epic.

    Validates that the target repo exists and that adding the spec
    doesn't create a dependency cycle.

    Examples:
        spec epic add-spec e001-auth --id spec-01 --repo myrepo --branch feat/auth --path specs/auth.md
        spec epic add-spec e001-auth --id spec-02 --repo myrepo --branch feat/auth --path specs/tokens.md --depends-on spec-01
    """
    from spec.epic.loader import load_epic
    from spec.epic.schema import SpecRef, SpecStatus
    from spec.epic.writer import add_spec as do_add_spec

    epic = load_epic(epic_id)

    spec = SpecRef(
        id=spec_id,
        repo=repo,
        branch=branch,
        path=path,
        status=SpecStatus.PLANNED,
        depends_on=list(depends_on),
        expectations=list(expectation),
    )

    do_add_spec(epic, spec)

    typer.secho(f"✓ Added spec '{spec_id}' to epic '{epic_id}'", fg=typer.colors.GREEN)
    if depends_on:
        typer.echo(f"  Dependencies: {', '.join(depends_on)}")


@epic_app.command("set-current")
@_epic_exception_handler
def set_current(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    spec_id: str = typer.Option(..., "--spec", "-s", help="Spec ID to set as current"),
) -> None:
    """Set the current active spec for an epic.

    Marks the spec as active and sets it as the epic's current working spec.

    Examples:
        spec epic set-current e001-auth --spec spec-01
    """
    from spec.epic.loader import load_epic
    from spec.epic.writer import set_current_spec

    epic = load_epic(epic_id)
    set_current_spec(epic, spec_id)

    typer.secho(f"✓ Set current spec to '{spec_id}'", fg=typer.colors.GREEN)


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
        typer.echo(f"  Set as current with: spec epic set-current {epic_id} --spec {next_spec}")
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
        typer.echo(f"Status: ", nl=False)
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
        typer.echo("  Create one with: spec epic create <title> --goal <goal>")
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
        epic = load_epic(epic_id)
        typer.secho(f"✓ Epic '{epic_id}' is valid", fg=typer.colors.GREEN)
        raise typer.Exit(0)
    except EpicValidationError as e:
        typer.secho(f"✗ Validation failed for '{epic_id}':", fg=typer.colors.RED, err=True)
        typer.echo(str(e), err=True)
        raise typer.Exit(3)


@epic_app.command()
@_epic_exception_handler
def check(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    check_id: str | None = typer.Option(None, "--check", "-c", help="Specific check to run"),
) -> None:
    """Run LLM checks for an epic (requires LLM integration).

    This command is a placeholder for the LLM integration module.
    Full implementation will be in e001-03-epic-llm-integration.

    Exit code 4 indicates LLM integration is not yet available.

    Examples:
        spec epic check e001-auth
        spec epic check e001-auth --check CHECK-e001-core
    """
    typer.secho(
        "LLM integration not yet implemented.",
        fg=typer.colors.YELLOW,
        err=True,
    )
    typer.echo(
        "This feature will be available after completing spec e001-03-epic-llm-integration.",
        err=True,
    )
    raise typer.Exit(4)
