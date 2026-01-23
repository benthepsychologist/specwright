"""
Git sandbox enforcement and capture.

Provides:
- Policy enforcement (blocks push/merge, allows commits)
- Git state capture (pre/post step)
- Patch generation
"""

from spec.executor.sandbox.capture import (
    capture_git_state,
    generate_patch,
    get_changed_files,
    get_current_commit,
)
from spec.executor.sandbox.enforcer import (
    PolicyViolation,
    SandboxEnforcer,
    check_command,
)

__all__ = [
    # Enforcer
    "PolicyViolation",
    "SandboxEnforcer",
    "check_command",
    # Capture
    "get_current_commit",
    "get_changed_files",
    "generate_patch",
    "capture_git_state",
]
