"""
Execution backends for the v2 executor.

Backends handle step dispatch and produce StepCapture evidence bundles.

Available backends:
- cmd: Execute shell commands
- llm: Call model APIs
- claude-code: Spawn Claude Code agent sessions
- codex: Spawn Codex agent sessions
- copilot: Spawn GitHub Copilot CLI agent sessions
"""

from spec.executor.backends.base import (
    BackendBase,
    BackendError,
    UnknownBackendError,
)
from spec.executor.backends.registry import (
    get_backend,
    list_backends,
    register_backend,
)

__all__ = [
    # Base
    "BackendBase",
    "BackendError",
    "UnknownBackendError",
    # Registry
    "get_backend",
    "list_backends",
    "register_backend",
]
