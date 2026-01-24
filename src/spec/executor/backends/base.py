"""
Base backend class for v2 executor.

All backends must inherit from BackendBase and implement dispatch().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec.executor.schemas import Policy, StepCapture, StepManifest


class BackendError(Exception):
    """Base exception for backend errors."""

    def __init__(
        self,
        message: str,
        *,
        backend: str | None = None,
        step_id: str | None = None,
    ):
        super().__init__(message)
        self.backend = backend
        self.step_id = step_id


class UnknownBackendError(BackendError):
    """Raised when an unknown backend is requested."""

    def __init__(self, backend_name: str):
        super().__init__(
            f"Unknown backend: {backend_name}",
            backend=backend_name,
        )
        self.backend_name = backend_name


class BackendBase(ABC):
    """
    Abstract base class for execution backends.

    Each backend is responsible for:
    1. Executing a step according to its manifest
    2. Capturing evidence (stdout, stderr, exit code, etc.)
    3. Returning a StepCapture with all evidence

    Backends receive:
    - manifest: Fully resolved StepManifest with payload
    - artifacts_dir: Directory to write capture artifacts
    - policy: Execution policy for sandbox enforcement
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name (e.g., 'cmd', 'llm', 'claude-code')."""

    @abstractmethod
    def dispatch(
        self,
        manifest: StepManifest,
        artifacts_dir: Path,
        policy: Policy,
        capture_patch: bool = False,
    ) -> StepCapture:
        """
        Execute a step and return capture evidence.

        Args:
            manifest: Fully resolved step manifest
            artifacts_dir: Directory to write artifacts (stdout.txt, etc.)
            policy: Execution policy for sandbox enforcement
            capture_patch: If True, generate changes.patch in artifacts_dir

        Returns:
            StepCapture with all evidence from execution

        Raises:
            BackendError: If execution fails in a way that can't be captured
        """

    def verify(self) -> None:  # noqa: B027
        """
        Verify the backend is available and functional.

        Override this to check for required tools, APIs, etc.
        This is intentionally not abstract - many backends don't need verification.

        Raises:
            BackendError: If backend is not available
        """
        # Default: no verification needed
