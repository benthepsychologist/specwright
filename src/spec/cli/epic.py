"""Epic management CLI commands.

This module provides Typer commands for managing epics - multi-spec
implementation plans with dependency tracking and status management.
"""

from __future__ import annotations

import functools
from pathlib import Path

import typer
from rich.console import Console

from spec.core.exceptions import SpecwrightError

epic_app = typer.Typer(help="Epic management commands")
console = Console()


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
    llm: bool = typer.Option(False, "--llm", help="Use LLM to draft epic content"),
    context: Path | None = typer.Option(
        None, "--context", "-c", help="Additional context file"
    ),
    model: str = typer.Option(
        "claude-sonnet-4-20250514", "--model", "-m", help="Model for --llm mode"
    ),
) -> None:
    """Create a new epic.

    Creates an epic with the standard directory structure:
    - checks/: Check prompt files
    - reports/: Check execution reports
    - artifacts/snapshots/: Artifact snapshots
    - notes.md: Epic notes
    - epic.yaml: Epic definition

    With --llm, the command will use Claude Code to explore the current
    repository and generate meaningful narrative, specs, and dependencies.

    Examples:
        spec epic create "Add OAuth" --goal "Implement OAuth2 authentication"
        spec epic create "Refactor DB" --id e002-db-refactor --goal "Migrate to PostgreSQL"
        spec epic create "Add caching" --goal "Add Redis caching" --llm
        spec epic create "Migrate API" --goal "GraphQL migration" --llm --context notes.md
    """
    import re

    from spec.epic.loader import get_epic_path
    from spec.epic.writer import create_epic as do_create_epic

    # Auto-generate ID if not provided
    if id is None:
        # Generate ID from title: e001-my-epic-title
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

    # Create skeleton epic first
    epic = do_create_epic(
        id=id,
        title=title,
        owner=owner,
        goal=goal,
    )

    epic_dir = get_epic_path(epic.id)

    typer.secho(f"✓ Created epic skeleton: {epic.id}", fg=typer.colors.GREEN)
    typer.echo(f"  Title: {epic.title}")
    typer.echo(f"  Path: {epic_dir}")

    # If --llm, draft content and merge
    if llm:
        from spec.governance.epic_drafter import EpicDrafter

        # Load additional context if provided
        context_content: str | None = None
        if context:
            if not context.exists():
                typer.secho(f"Error: Context file not found: {context}", fg=typer.colors.RED, err=True)
                raise typer.Exit(1)
            context_content = context.read_text()

        console.print("\n[bold]Using LLM to draft epic content...[/]")
        console.print(f"[dim]Model: {model}[/]")

        try:
            drafter = EpicDrafter(
                title=title,
                goal=goal,
                owner=owner,
                repo_path=Path.cwd(),
                context=context_content,
                model=model,
            )

            with console.status("Claude Code is exploring and drafting..."):
                patch = drafter.draft()

            # Apply patch to epic
            _apply_epic_patch(epic, patch)

            console.print("[green]✓[/] Applied LLM-drafted content")

            # Show what was generated
            if patch.get("intent", {}).get("narrative"):
                console.print(f"\n[bold]Narrative:[/]\n{patch['intent']['narrative'][:200]}...")

            if patch.get("targets"):
                console.print(f"\n[bold]Targets:[/] {len(patch['targets'])} target(s)")

            if patch.get("specs"):
                console.print(f"\n[bold]Specs:[/] {len(patch['specs'])} spec(s)")
                for spec in patch["specs"][:5]:
                    mode = spec.get("mode", "headless")
                    console.print(f"  - {spec.get('id')}: {spec.get('title')} [dim]({mode})[/]")

        except FileNotFoundError as e:
            console.print(f"[red]Error:[/] {e}")
            console.print("[dim]Make sure the claude CLI is installed and in PATH[/]")
            console.print("\n[yellow]Epic skeleton was created, but LLM drafting failed.[/]")
            raise typer.Exit(1)
        except RuntimeError as e:
            console.print(f"[red]Error:[/] {e}")
            console.print("\n[yellow]Epic skeleton was created, but LLM drafting failed.[/]")
            raise typer.Exit(1)

        typer.echo("\nNext steps:")
        typer.echo(f"  1. Review epic: spec epic status {epic.id}")
        typer.echo(f"  2. Validate: spec epic validate {epic.id}")
        typer.echo(f"  3. Start drafting specs: spec draft {epic.id}/<spec-id>")
    else:
        typer.echo("\nNext steps:")
        typer.echo(f"  1. Add targets: spec epic add-target {epic.id} --id myrepo --repo-path /path/to/repo")
        typer.echo(f"  2. Add specs: spec epic add-spec {epic.id} --id spec-01 --repo myrepo ...")
        typer.echo(f"  3. View status: spec epic status {epic.id}")


def _apply_epic_patch(epic, patch: dict) -> None:
    """Apply a patch dict to an epic and save.

    Args:
        epic: Epic instance to modify.
        patch: Patch dict with intent, targets, specs to merge.
    """
    from spec.epic.schema import SpecRef, SpecStatus, Target
    from spec.epic.writer import save_epic

    # Update narrative
    if "intent" in patch:
        if patch["intent"].get("narrative"):
            epic.intent.narrative = patch["intent"]["narrative"]

    # Add targets
    if "targets" in patch:
        existing_target_ids = {t.id for t in epic.targets}
        for t in patch["targets"]:
            if t["id"] not in existing_target_ids:
                epic.targets.append(
                    Target(
                        id=t["id"],
                        repo_path=t.get("repo_path", str(Path.cwd())),
                        default_branch=t.get("default_branch", "main"),
                        governor_project=t.get("governor_project"),
                    )
                )

    # Add specs
    if "specs" in patch:
        existing_spec_ids = {s.id for s in epic.specs}
        for s in patch["specs"]:
            if s["id"] not in existing_spec_ids:
                spec = SpecRef(
                    id=s["id"],
                    repo=s.get("repo", epic.targets[0].id if epic.targets else "default"),
                    branch=s.get("branch", f"feat/{s['id']}"),
                    title=s.get("title"),
                    path=s.get("path", f"specs/{s['id']}.md"),
                    status=SpecStatus.PLANNED,
                    depends_on=s.get("depends_on", []),
                    expectations=s.get("expectations", []),
                    constraints=s.get("constraints", []),
                )
                epic.specs.append(spec)

    save_epic(epic)


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
    description: str | None = typer.Argument(
        None, help="Description of work (for --llm mode)"
    ),
    # Manual mode options (existing)
    spec_id: str | None = typer.Option(None, "--id", help="Spec ID (manual mode)"),
    repo: str | None = typer.Option(None, "--repo", help="Target repo ID"),
    branch: str | None = typer.Option(None, "--branch", help="Working branch"),
    path: str | None = typer.Option(None, "--path", help="Spec path relative to governor"),
    mode: str = typer.Option(
        "headless", "--mode", help="Recommended mode: interactive|headless"
    ),
    depends_on: list[str] = typer.Option([], "--depends-on", help="Dependency spec IDs"),
    expectation: list[str] = typer.Option([], "--expectation", "-e", help="Expectations"),
    constraint: list[str] = typer.Option([], "--constraint", help="Constraints"),
    # LLM mode options
    llm: bool = typer.Option(False, "--llm", help="Use LLM to draft spec entries"),
    target: str | None = typer.Option(
        None, "--target", help="Primary target repo ID (LLM mode)"
    ),
    context: Path | None = typer.Option(
        None, "--context", "-c", help="Additional context file"
    ),
    model: str = typer.Option(
        "claude-sonnet-4-20250514", "--model", "-m", help="Model for --llm mode"
    ),
) -> None:
    """Add spec reference(s) to an epic.

    Two modes:
    1. Manual mode: Provide all fields (--id, --repo, --branch, --path)
    2. LLM mode: Provide description and --llm flag

    With --llm, Claude Code explores the repo and generates one or more
    spec entries with expectations, constraints, and dependencies.

    Examples:
        # Manual mode (all fields required)
        spec epic add-spec e001-auth --id spec-01 --repo myrepo --branch feat/auth --path specs/auth.md
        spec epic add-spec e001-auth --id spec-02 --repo myrepo --branch feat/auth --path specs/tokens.md --depends-on spec-01

        # LLM mode (description required)
        spec epic add-spec t004 "add caching layer" --llm
        spec epic add-spec t004 "break down the API refactor into specs" --llm --target myrepo
        spec epic add-spec t004 "implement OAuth" --llm --context notes.md
    """
    from spec.epic.loader import load_epic
    from spec.epic.schema import SpecRef, SpecStatus
    from spec.epic.writer import add_spec as do_add_spec

    epic = load_epic(epic_id)

    if llm:
        # LLM mode: requires description
        if not description:
            typer.secho(
                "Error: Description required for --llm mode",
                fg=typer.colors.RED,
                err=True,
            )
            typer.echo("  Usage: spec epic add-spec <epic-id> \"description\" --llm", err=True)
            raise typer.Exit(1)

        # Load additional context if provided
        context_content: str | None = None
        if context:
            if not context.exists():
                typer.secho(
                    f"Error: Context file not found: {context}",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(1)
            context_content = context.read_text()

        console.print(f"\n[bold]Adding specs to epic:[/] {epic.id}")
        console.print(f"[bold]Description:[/] {description}")
        console.print(f"[dim]Model: {model}[/]")

        try:
            from spec.governance.spec_entry_drafter import SpecEntryDrafter

            drafter = SpecEntryDrafter(
                epic=epic,
                description=description,
                target_id=target,
                context=context_content,
                model=model,
            )

            with console.status("Claude Code is exploring and drafting..."):
                spec_entries = drafter.draft()

            if not spec_entries:
                console.print("[yellow]Warning:[/] No specs were generated")
                raise typer.Exit(0)

            console.print(f"\n[green]✓[/] Generated {len(spec_entries)} spec(s):")

            # Add each generated spec
            added_count = 0
            for entry in spec_entries:
                spec = SpecRef(
                    id=entry["id"],
                    repo=entry.get("repo", epic.targets[0].id if epic.targets else "default"),
                    branch=entry.get("branch", f"feat/{entry['id']}"),
                    title=entry.get("title"),
                    path=entry.get("path", f"specs/{entry['id']}.md"),
                    status=SpecStatus.PLANNED,
                    depends_on=entry.get("depends_on", []),
                    expectations=entry.get("expectations", []),
                    constraints=entry.get("constraints", []),
                )

                try:
                    do_add_spec(epic, spec)
                    spec_mode = entry.get("mode", "headless")
                    console.print(
                        f"  [green]✓[/] {spec.id}: {spec.title or '(no title)'} "
                        f"[dim]({spec_mode})[/]"
                    )
                    if spec.depends_on:
                        console.print(f"      depends_on: {', '.join(spec.depends_on)}")
                    added_count += 1
                except Exception as e:
                    console.print(f"  [red]✗[/] {spec.id}: {e}")

            console.print(f"\n[bold]Added {added_count} spec(s) to epic '{epic_id}'[/]")

        except FileNotFoundError as e:
            console.print(f"[red]Error:[/] {e}")
            console.print("[dim]Make sure the claude CLI is installed and in PATH[/]")
            raise typer.Exit(1)
        except RuntimeError as e:
            console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1)
        except ValueError as e:
            console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1)

    else:
        # Manual mode: requires all fields
        if description and not spec_id:
            # User provided description but not --llm
            typer.secho(
                "Error: Description provided without --llm flag",
                fg=typer.colors.RED,
                err=True,
            )
            typer.echo(
                "  Either add --llm to use LLM drafting, or provide manual fields "
                "(--id, --repo, --branch, --path)",
                err=True,
            )
            raise typer.Exit(1)

        # Validate required fields for manual mode
        if not all([spec_id, repo, branch, path]):
            typer.secho(
                "Error: Manual mode requires --id, --repo, --branch, and --path",
                fg=typer.colors.RED,
                err=True,
            )
            typer.echo(
                "  For LLM-assisted drafting, use: spec epic add-spec <epic-id> \"description\" --llm",
                err=True,
            )
            raise typer.Exit(1)

        spec = SpecRef(
            id=spec_id,
            repo=repo,
            branch=branch,
            path=path,
            status=SpecStatus.PLANNED,
            depends_on=list(depends_on),
            expectations=list(expectation),
            constraints=list(constraint),
        )

        do_add_spec(epic, spec)

        typer.secho(f"✓ Added spec '{spec_id}' to epic '{epic_id}'", fg=typer.colors.GREEN)
        typer.echo(f"  Mode: {mode}")
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
