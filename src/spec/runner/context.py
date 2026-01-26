"""AIP v3 Context Rendering - Generate TASK.md for Claude.

This module renders an AIP v3 into a .claude/TASK.md file that Claude
will follow during execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_task_md(aip: Any) -> str:
    """Render an AIP v3 as a TASK.md file for Claude.

    Args:
        aip: The AIP to render

    Returns:
        Markdown content for TASK.md
    """
    lines: list[str] = []

    # Header
    lines.append(f"# Task: {aip.metadata.spec_id}")
    lines.append("")
    lines.append(f"**Epic:** {aip.metadata.epic_id}")
    lines.append(f"**Branch:** {aip.workspace.branch}")
    lines.append("")

    # Goal
    lines.append("## Goal")
    lines.append("")
    lines.append(aip.goal)
    lines.append("")

    # Expectations
    if aip.expectations:
        lines.append("## Expectations")
        lines.append("")
        for exp in aip.expectations:
            lines.append(f"- {exp}")
        lines.append("")

    # Constraints
    if aip.constraints:
        lines.append("## Constraints")
        lines.append("")
        for constraint in aip.constraints:
            lines.append(f"- {constraint}")
        lines.append("")

    # Phases (implementation steps)
    if aip.phases:
        lines.append("## Implementation Phases")
        lines.append("")
        for phase in aip.phases:
            lines.append(f"### {phase.id}: {phase.title}")
            lines.append("")
            lines.append(phase.objective)
            lines.append("")

            if phase.guidance:
                if phase.guidance.likely_files:
                    lines.append("**Likely files:**")
                    for f in phase.guidance.likely_files:
                        lines.append(f"- `{f}`")
                    lines.append("")

                if phase.guidance.patterns_to_follow:
                    lines.append("**Patterns to follow:**")
                    for p in phase.guidance.patterns_to_follow:
                        note = f" - {p.note}" if p.note else ""
                        lines.append(f"- `{p.file}`{note}")
                    lines.append("")

                if phase.guidance.approach:
                    lines.append("**Approach:**")
                    lines.append("")
                    lines.append(phase.guidance.approach)
                    lines.append("")

                if phase.guidance.watch_out_for:
                    lines.append("**Watch out for:**")
                    for w in phase.guidance.watch_out_for:
                        lines.append(f"- {w}")
                    lines.append("")

            if phase.verification:
                lines.append("**Verification:**")
                for v in phase.verification:
                    lines.append(f"- `{v.cmd}`")
                lines.append("")

    # Final verification
    if aip.final_verification:
        lines.append("## Final Verification")
        lines.append("")
        lines.append("Run these commands to verify the implementation is complete:")
        lines.append("")
        for v in aip.final_verification:
            lines.append("```bash")
            lines.append(v.cmd)
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def write_task_md(aip: Any, repo_path: Path) -> Path:
    """Write TASK.md to the repository.

    Args:
        aip: The AIP to render
        repo_path: Path to the repository root

    Returns:
        Path to the written TASK.md file
    """
    claude_dir = repo_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    task_path = claude_dir / "TASK.md"
    content = render_task_md(aip)
    task_path.write_text(content, encoding="utf-8")

    return task_path


def cleanup_task_md(repo_path: Path) -> None:
    """Remove TASK.md from the repository.

    Args:
        repo_path: Path to the repository root
    """
    task_path = repo_path / ".claude" / "TASK.md"
    if task_path.exists():
        task_path.unlink()
