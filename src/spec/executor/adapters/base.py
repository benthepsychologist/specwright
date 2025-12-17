"""
Base Agent Adapter

Abstract base class for agent adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class AdapterError(Exception):
    """Base exception for adapter errors."""

    pass


class ToolNotFoundError(AdapterError):
    """Raised when the adapter's tool is not found in PATH."""

    def __init__(self, tool_name: str, message: str | None = None) -> None:
        self.tool_name = tool_name
        super().__init__(message or f"{tool_name} not found in PATH")


class ProtocolError(AdapterError):
    """Raised when the adapter's protocol is violated (hard failure)."""

    def __init__(
        self,
        message: str,
        failure_category: str | None = None,
    ) -> None:
        self.failure_category = failure_category
        super().__init__(message)


class EscalationRequired(AdapterError):
    """Raised when human review is required (soft failure).

    This maps to termination_reason=ESCALATE_NEEDS_HUMAN, not FAIL_ADAPTER_PROTOCOL.
    The execution may have succeeded, but the commands used require human approval.
    """

    def __init__(
        self,
        message: str,
        violations: list[str] | None = None,
    ) -> None:
        self.violations = violations or []
        super().__init__(message)


class AgentAdapter(ABC):
    """Abstract base class for agent adapters."""

    @abstractmethod
    def verify(self) -> None:
        """
        Verify the adapter's tool is available and compatible.

        Raises:
            ToolNotFoundError: If tool not found
            ProtocolError: If tool doesn't support required features
        """

    @abstractmethod
    def execute(
        self,
        input_dir: Path,
        output_dir: Path,
        repo_root: Path,
        timeout: int = 600,
    ) -> None:
        """
        Execute the agent.

        Args:
            input_dir: Directory containing contract.yaml, prompt.md, repo_state.json
            output_dir: Directory where adapter writes patch.diff, agent.json, cmdlog.txt
            repo_root: Repository root for --cd flag
            timeout: Timeout in seconds (default 10 minutes)

        Raises:
            ToolNotFoundError: If tool not found
            ProtocolError: If adapter contract violated
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return adapter name (e.g., 'claude')."""
