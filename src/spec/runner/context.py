"""AIP v3 Context Rendering - Generate TASK.md for Claude.

This module renders an AIP v3 into a .claude/TASK.md file that Claude
will follow during execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec.aip.models import AIPv3


def render_task_md(aip: AIPv3) -> str:
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

    # Steps
    if aip.steps:
        lines.append("## Implementation Steps")
        lines.append("")
        for step in aip.steps:
            lines.append(f"### {step.id}: {step.title}")
            lines.append("")
            lines.append(step.objective)
            lines.append("")

            if step.guidance:
                if step.guidance.likely_files:
                    lines.append("**Likely files:**")
                    for f in step.guidance.likely_files:
                        lines.append(f"- `{f}`")
                    lines.append("")

                if step.guidance.patterns_to_follow:
                    lines.append("**Patterns to follow:**")
                    for p in step.guidance.patterns_to_follow:
                        note = f" - {p.note}" if p.note else ""
                        lines.append(f"- `{p.file}`{note}")
                    lines.append("")

                if step.guidance.approach:
                    lines.append("**Approach:**")
                    lines.append("")
                    lines.append(step.guidance.approach)
                    lines.append("")

                if step.guidance.watch_out_for:
                    lines.append("**Watch out for:**")
                    for w in step.guidance.watch_out_for:
                        lines.append(f"- {w}")
                    lines.append("")

            if step.verification:
                lines.append("**Verification:**")
                for v in step.verification:
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


def write_task_md(aip: AIPv3, repo_path: Path) -> Path:
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
