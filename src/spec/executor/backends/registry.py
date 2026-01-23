"""
Backend registry for v2 executor.

Manages registration and lookup of execution backends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spec.executor.backends.base import BackendBase, UnknownBackendError

if TYPE_CHECKING:
    pass

# Registry of backend classes (populated by imports)
_BACKENDS: dict[str, type[BackendBase]] = {}

# Disabled backends (can be set via config)
_DISABLED: set[str] = set()


def register_backend(name: str, backend_class: type[BackendBase]) -> None:
    """
    Register a backend class.

    Args:
        name: Backend name (e.g., 'cmd', 'claude-code')
        backend_class: Backend class (not instance)
    """
    _BACKENDS[name.lower()] = backend_class


def get_backend(name: str) -> BackendBase:
    """
    Get a backend instance by name.

    Args:
        name: Backend name

    Returns:
        BackendBase instance

    Raises:
        UnknownBackendError: If backend not found or disabled
    """
    name_lower = name.lower()

    if name_lower in _DISABLED:
        raise UnknownBackendError(f"{name} (disabled)")

    backend_class = _BACKENDS.get(name_lower)
    if backend_class is None:
        raise UnknownBackendError(name)

    return backend_class()


def list_backends() -> list[str]:
    """
    List available (non-disabled) backend names.

    Returns:
        List of backend names
    """
    return [name for name in _BACKENDS if name not in _DISABLED]


def disable_backend(name: str) -> None:
    """
    Disable a backend.

    Args:
        name: Backend name to disable
    """
    _DISABLED.add(name.lower())


def enable_backend(name: str) -> None:
    """
    Enable a previously disabled backend.

    Args:
        name: Backend name to enable
    """
    _DISABLED.discard(name.lower())


def is_backend_available(name: str) -> bool:
    """
    Check if a backend is available (registered and not disabled).

    Args:
        name: Backend name

    Returns:
        True if backend is available
    """
    name_lower = name.lower()
    return name_lower in _BACKENDS and name_lower not in _DISABLED


# Auto-register backends on import
def _auto_register() -> None:
    """Register all built-in backends."""
    # Import here to avoid circular imports
    from spec.executor.backends.claude_code import ClaudeCodeBackend
    from spec.executor.backends.cmd import CmdBackend
    from spec.executor.backends.codex import CodexBackend
    from spec.executor.backends.llm import LlmBackend

    register_backend("cmd", CmdBackend)
    register_backend("llm", LlmBackend)
    register_backend("claude-code", ClaudeCodeBackend)
    register_backend("codex", CodexBackend)


_auto_register()
