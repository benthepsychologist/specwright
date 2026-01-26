"""Spec Runner - Claude Code invocation for spec execution.

This package provides the runner that invokes Claude Code as a subprocess
(background mode) or TUI (interactive mode) to execute specs.
"""

from spec.runner.background import RunResult, run_background
from spec.runner.context import render_task_md
from spec.runner.interactive import run_interactive

__all__ = [
    "RunResult",
    "render_task_md",
    "run_background",
    "run_interactive",
]
