"""spec draft command: generate scaffolded specs from epic entries.

This command generates properly-structured specs from epic spec entries,
grounded in the current build.yaml and explicit about build_delta changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console

if TYPE_CHECKING:
    from spec.epic.schema import Epic, SpecRef

console = Console()


def spec_draft(
    spec_ref: str = typer.Argument(
        ...,
        help="Epic/spec reference (e.g., t004/t004-04 or t004-04)",
    ),
    context: Path | None = typer.Option(
        None,
        "--context",
        "-c",
        help="Additional context file (markdown) to include in drafting",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (default: epic's spec.path)",
    ),
    phases: int = typer.Option(
        2,
        "--phases",
        help="Number of placeholder phases to generate",
    ),
    llm: bool = typer.Option(
        False,
        "--llm",
        help="Use LLM to fill in details (requires claude CLI)",
    ),
    model: str = typer.Option(
        "claude-sonnet-4-20250514",
        "--model",
        "-m",
        help="Model to use for --llm mode",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print to stdout instead of writing to file",
    ),
) -> None:
    """Draft a spec from an epic entry.

    Loads the spec entry from the epic, resolves the target repo, and generates
    a scaffolded YAML spec with:
    - Required metadata fields (tier, title, owner, goal)
    - Placeholder phases ready to fill in
    - Acceptance criteria from epic expectations

    The output is written to the epic's spec.path by default.

    \b
    Examples:
        spec draft t004/t004-04           # Draft spec, write to epic's spec.path
        spec draft t004-04                # Short form (resolves across epics)
        spec draft t004/t004-04 --dry-run # Print to stdout
        spec draft t004/t004-04 --llm     # Use LLM to fill in details
        spec draft t004/t004-04 --context notes.md  # Include additional context
    """
    from spec.governance.intent_parser import IntentParser
    from spec.governance.spec_scaffolder import SpecScaffolder

    # Load epic and spec entry
    try:
        epic, spec_entry, epic_dir = _load_epic_spec(spec_ref)
    except typer.BadParameter as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    # Resolve target repo from epic
    target = epic.get_target(spec_entry.repo)
    if target is None:
        console.print(
            f"[red]Error:[/] Target '{spec_entry.repo}' not found in epic targets"
        )
        raise typer.Exit(1)

    repo_path = Path(target.repo_path).expanduser().resolve()

    # Determine output path
    if output:
        output_path = output
    elif spec_entry.path:
        output_path = epic_dir / spec_entry.path
    else:
        output_path = epic_dir / "specs" / f"{spec_entry.id}.yaml"

    # Load additional context if provided
    context_content: str | None = None
    if context:
        if not context.exists():
            console.print(f"[red]Error:[/] Context file not found: {context}")
            raise typer.Exit(1)
        context_content = context.read_text()

    console.print(f"[bold]Drafting spec:[/] {spec_entry.title or spec_entry.id}")
    console.print(f"[bold]Epic:[/] {epic.id}")
    console.print(f"[bold]Target repo:[/] {repo_path}")
    if not dry_run:
        console.print(f"[bold]Output:[/] {output_path}")

    # Parse epic entry into intent
    parser = IntentParser()
    parsed_intent = parser.parse_epic_entry(epic, spec_entry.id)

    # Scaffold
    scaffolder = SpecScaffolder(
        parsed_intent,
        repo_path,
        context=context_content,
    )
    spec_md = scaffolder.scaffold(num_phases=phases)

    # LLM mode
    if llm:
        try:
            from spec.governance.spec_drafter import SpecDrafter

            drafter = SpecDrafter(
                scaffolder,
                model=model,
                context=context_content,
            )
            with console.status("Claude Code is exploring and drafting..."):
                spec_md = drafter.draft()
        except ImportError:
            console.print(
                "[yellow]Warning:[/] LLM mode requires spec_drafter module. "
                "Using scaffold only."
            )
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/] {e}")
            console.print("[dim]Make sure the claude CLI is installed and in PATH[/]")
            raise typer.Exit(1)
        except RuntimeError as e:
            console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1)

    # Output
    if dry_run:
        console.print()
        console.print(spec_md)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(spec_md)
        console.print(f"[green]✓[/] Wrote spec to {output_path}")


def _load_epic_spec(query: str) -> tuple[Epic, SpecRef, Path]:
    """Load epic and spec entry from reference.

    Supports formats:
    - "t004/t004-04" (epic-id/spec-id)
    - "t004-04" (spec-id, resolves across epics)

    Args:
        query: Epic/spec reference string.

    Returns:
        Tuple of (Epic, SpecRef, epic_dir Path).

    Raises:
        typer.BadParameter: If reference cannot be resolved.
    """
    from spec.epic.loader import load_epic_from_path
    from spec.governor.resolver import ResolveError, resolve_epic, resolve_spec

    # Check for explicit epic/spec format
    if "/" in query:
        parts = query.split("/", 1)
        epic_prefix, spec_id = parts[0], parts[1]
    else:
        epic_prefix = None
        spec_id = query

    try:
        if epic_prefix:
            # Explicit epic prefix
            resolved_epic = resolve_epic(epic_prefix)
            epic = load_epic_from_path(resolved_epic.epic_yaml)
            epic_dir = resolved_epic.epic_dir

            # Find spec in this epic
            spec_entry = epic.get_spec(spec_id)
            if spec_entry is None:
                # Try prefix matching
                matching = [s for s in epic.specs if s.id.startswith(spec_id)]
                if len(matching) == 1:
                    spec_entry = matching[0]
                elif len(matching) > 1:
                    options = ", ".join(s.id for s in matching)
                    raise typer.BadParameter(
                        f"Ambiguous spec '{spec_id}' in epic '{epic.id}'. "
                        f"Matches: {options}"
                    )
                else:
                    raise typer.BadParameter(
                        f"Spec '{spec_id}' not found in epic '{epic.id}'"
                    )
        else:
            # Resolve across epics
            resolved = resolve_spec(spec_id)
            epic = load_epic_from_path(resolved.epic.epic_yaml)
            epic_dir = resolved.epic.epic_dir
            spec_entry = epic.get_spec(resolved.spec_id)
            if spec_entry is None:
                raise typer.BadParameter(f"Spec '{spec_id}' not found after resolution")

        return epic, spec_entry, epic_dir

    except ResolveError as e:
        raise typer.BadParameter(str(e))
    except FileNotFoundError as e:
        raise typer.BadParameter(f"Epic file not found: {e}")
    except Exception as e:
        raise typer.BadParameter(f"Could not load '{query}': {e}")
