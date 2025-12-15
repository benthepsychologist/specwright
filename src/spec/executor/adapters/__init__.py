"""
Agent Adapters

Provides adapters for invoking AI coding agents (Codex, etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spec.executor.adapters.base import (
    AdapterError,
    AgentAdapter,
    EscalationRequired,
    ProtocolError,
    ToolNotFoundError,
)
from spec.executor.adapters.codex import CodexAdapter

if TYPE_CHECKING:
    pass

# Registry of available adapters (folded into __init__ for simplicity)
_ADAPTERS: dict[str, type[AgentAdapter]] = {
    "codex": CodexAdapter,
}


def get_adapter(name: str) -> AgentAdapter:
    """
    Get an adapter instance by name.

    Args:
        name: Adapter name (e.g., 'codex')

    Returns:
        AgentAdapter instance

    Raises:
        ValueError: If adapter not found
    """
    adapter_class = _ADAPTERS.get(name.lower())
    if adapter_class is None:
        available = ", ".join(_ADAPTERS.keys())
        raise ValueError(f"Unknown adapter: {name}. Available: {available}")

    return adapter_class()


def list_adapters() -> list[str]:
    """
    List available adapter names.

    Returns:
        List of adapter names
    """
    return list(_ADAPTERS.keys())


def register_adapter(name: str, adapter_class: type[AgentAdapter]) -> None:
    """
    Register a new adapter.

    Args:
        name: Adapter name
        adapter_class: Adapter class (not instance)
    """
    _ADAPTERS[name.lower()] = adapter_class


__all__ = [
    "AdapterError",
    "AgentAdapter",
    "CodexAdapter",
    "EscalationRequired",
    "ProtocolError",
    "ToolNotFoundError",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]
