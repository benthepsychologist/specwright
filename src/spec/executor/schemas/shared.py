"""
Shared enums and types for executor schemas.
"""

from enum import Enum


class Backend(str, Enum):
    """Execution backend types."""

    cmd = "cmd"
    llm = "llm"
    claude_code = "claude-code"
    codex = "codex"
    python = "python"
