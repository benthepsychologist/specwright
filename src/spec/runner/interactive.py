"""AIP v3 Interactive Runner - Claude Code TUI execution.

This module invokes Claude Code in interactive TUI mode for human-guided
execution of AIP v3 specs.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec.autogov.exceptions import SpecwrightError
from spec.runner.background import find_claude_binary
from spec.runner.context import write_task_md


class InteractiveRunnerError(SpecwrightError):
    """Error during interactive Claude invocation."""

    exit_code = 6


@dataclass
class InteractiveResult:
    """Result of an interactive Claude run."""

    exit_code: int
    started_at: str
    completed_at: str | None = None


def run_interactive(
    aip: Any,
    resume: bool = False,
) -> InteractiveResult:
    """Run Claude Code in interactive TUI mode.

    This launches the Claude TUI, allowing human-guided execution.
    TASK.md is written for Claude to reference.

    Note: Interactive mode doesn't produce stream-json output,
    so artifact capture is different (relies on git diff after).

    Args:
        aip: The AIP to execute
        resume: Whether to resume a previous session

    Returns:
        InteractiveResult with execution details

    Raises:
        InteractiveRunnerError: If Claude invocation fails
    """
    repo_path = Path(aip.workspace.repo_path)

    # Write TASK.md
    write_task_md(aip, repo_path)

    # Build command
    claude_bin = find_claude_binary()
    cmd = [claude_bin]

    if resume:
        cmd.append("--resume")

    started_at = datetime.now(UTC).isoformat()

    try:
        # Run Claude TUI (blocking, interactive)
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            check=False,
        )
        exit_code = result.returncode

    except FileNotFoundError as e:
        raise InteractiveRunnerError(f"Claude binary not found: {e}")
    except Exception as e:
        raise InteractiveRunnerError(f"Failed to launch Claude: {e}")

    completed_at = datetime.now(UTC).isoformat()

    return InteractiveResult(
        exit_code=exit_code,
        started_at=started_at,
        completed_at=completed_at,
    )
