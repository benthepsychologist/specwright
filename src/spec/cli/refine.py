"""spec refine command: iteratively improve existing specs with LLM assistance.

This command takes an existing spec file and uses LLM assistance to analyze,
suggest improvements, and optionally apply refinements while preserving
user-written content.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()


def spec_refine(
    spec_path: Path = typer.Argument(
        ...,
        help="Path to an existing spec file (.md)",
        exists=True,
        readable=True,
    ),
    context: Path | None = typer.Option(
        None,
        "--context",
        "-c",
        help="Additional context file (e.g., feedback, requirements) to guide refinement",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview suggestions without writing changes",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply refinements directly to the spec file",
    ),
    model: str = typer.Option(
        "claude-sonnet-4-20250514",
        "--model",
        "-m",
        help="Model to use for LLM refinement",
    ),
) -> None:
    """Refine an existing spec using LLM assistance.

    Analyzes the spec for completeness, consistency, and alignment with
    project patterns. Suggests improvements while preserving user content.

    \b
    Modes:
        --dry-run    Show suggestions without modifying the file
        --apply      Update the spec file in place
        (neither)    Show a diff of proposed changes

    \b
    Examples:
        spec refine specs/my-feature.md                    # Show diff of changes
        spec refine specs/my-feature.md --dry-run          # Preview suggestions
        spec refine specs/my-feature.md --apply            # Apply refinements
        spec refine specs/my-feature.md --context notes.md # Include feedback
    """
    # Validate mutually exclusive options
    if dry_run and apply:
        console.print("[red]Error:[/] Cannot use --dry-run and --apply together")
        raise typer.Exit(1)

    # Load the existing spec
    spec_path = spec_path.resolve()
    if not spec_path.exists():
        console.print(f"[red]Error:[/] Spec file not found: {spec_path}")
        raise typer.Exit(1)

    original_content = spec_path.read_text()

    # Load additional context if provided
    context_content: str | None = None
    if context:
        if not context.exists():
            console.print(f"[red]Error:[/] Context file not found: {context}")
            raise typer.Exit(1)
        context_content = context.read_text()

    console.print(f"[bold]Refining spec:[/] {spec_path}")
    if context:
        console.print(f"[bold]Using context:[/] {context}")

    # Determine repo path from spec location
    repo_path = _find_repo_root(spec_path)
    if repo_path:
        console.print(f"[bold]Repository:[/] {repo_path}")

    try:
        from spec.governance.spec_refiner import SpecRefiner

        refiner = SpecRefiner(
            spec_path=spec_path,
            original_content=original_content,
            repo_path=repo_path,
            model=model,
            context=context_content,
        )

        if dry_run:
            # Preview mode: show suggestions only
            with console.status("Analyzing spec and generating suggestions..."):
                suggestions = refiner.analyze()
            console.print("\n[bold]Suggested Improvements:[/]\n")
            console.print(suggestions)
        else:
            # Refinement mode: generate refined spec
            with console.status("Claude Code is analyzing and refining..."):
                refined_content = refiner.refine()

            if apply:
                # Apply changes directly
                spec_path.write_text(refined_content)
                console.print(f"[green]✓[/] Applied refinements to {spec_path}")
            else:
                # Show diff
                _show_diff(original_content, refined_content, spec_path.name)

    except ImportError:
        console.print(
            "[yellow]Warning:[/] spec_refiner module not available. "
            "Ensure all dependencies are installed."
        )
        raise typer.Exit(1)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        console.print("[dim]Make sure the claude CLI is installed and in PATH[/]")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _find_repo_root(spec_path: Path) -> Path | None:
    """Find the repository root from a spec file path.

    Walks up the directory tree looking for .git directory.

    Args:
        spec_path: Path to the spec file.

    Returns:
        Repository root path, or None if not in a git repo.
    """
    current = spec_path.parent
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def _show_diff(original: str, refined: str, filename: str) -> None:
    """Display a unified diff between original and refined content.

    Args:
        original: Original spec content.
        refined: Refined spec content.
        filename: Name of the file for diff header.
    """
    import difflib

    original_lines = original.splitlines(keepends=True)
    refined_lines = refined.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        refined_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )

    diff_text = "".join(diff)

    if not diff_text.strip():
        console.print("[green]No changes suggested.[/]")
        return

    console.print("\n[bold]Proposed Changes:[/]\n")

    # Colorize diff output
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            console.print(f"[bold]{line}[/]")
        elif line.startswith("+"):
            console.print(f"[green]{line}[/]")
        elif line.startswith("-"):
            console.print(f"[red]{line}[/]")
        elif line.startswith("@@"):
            console.print(f"[cyan]{line}[/]")
        else:
            console.print(line)
