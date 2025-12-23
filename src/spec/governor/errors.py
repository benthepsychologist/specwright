"""Error records: structured error tracking for local-governor.

This module defines the ErrorRecord dataclass for capturing and
storing structured error information during spec compilation
and AIP execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class ErrorType(str, Enum):
    """Classification of error types."""

    # Execution failures
    FAIL_SCOPE = "FAIL_SCOPE"
    FAIL_PATCH_APPLY = "FAIL_PATCH_APPLY"
    FAIL_VERIFY = "FAIL_VERIFY"
    FAIL_VERIFY_RETRYABLE = "FAIL_VERIFY_RETRYABLE"
    FAIL_ADAPTER_PROTOCOL = "FAIL_ADAPTER_PROTOCOL"
    FAIL_DIRTY_WORKTREE = "FAIL_DIRTY_WORKTREE"

    # Gate failures
    GATE_REJECTED = "GATE_REJECTED"

    # Compilation/validation errors
    COMPILE_ERROR = "COMPILE_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # Configuration errors
    CONFIG_ERROR = "CONFIG_ERROR"
    GOVERNOR_ERROR = "GOVERNOR_ERROR"


@dataclass
class ErrorContext:
    """Additional context about an error."""

    command: str | None = None
    exit_code: int | None = None
    output_snippet: str | None = None
    files_touched: list[str] = field(default_factory=list)
    scope_violations: list[str] = field(default_factory=list)
    adapter: str | None = None
    agent_response_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, omitting None values."""
        result: dict[str, Any] = {}
        if self.command is not None:
            result["command"] = self.command
        if self.exit_code is not None:
            result["exit_code"] = self.exit_code
        if self.output_snippet is not None:
            result["output_snippet"] = self.output_snippet
        if self.files_touched:
            result["files_touched"] = self.files_touched
        if self.scope_violations:
            result["scope_violations"] = self.scope_violations
        if self.adapter is not None:
            result["adapter"] = self.adapter
        if self.agent_response_id is not None:
            result["agent_response_id"] = self.agent_response_id
        return result


@dataclass
class ErrorRecord:
    """Structured error record for local-governor storage."""

    error_id: str
    error_type: ErrorType
    message: str
    timestamp: datetime
    repo: str
    aip_ref: str
    spec_ref: str | None = None
    step: int | None = None
    step_id: str | None = None
    iteration: int | None = None
    context: ErrorContext | None = None
    related_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {
            "error_id": self.error_id,
            "error_type": self.error_type.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "repo": self.repo,
            "aip_ref": self.aip_ref,
        }

        if self.spec_ref is not None:
            result["spec_ref"] = self.spec_ref
        if self.step is not None:
            result["step"] = self.step
        if self.step_id is not None:
            result["step_id"] = self.step_id
        if self.iteration is not None:
            result["iteration"] = self.iteration
        if self.context is not None:
            result["context"] = self.context.to_dict()
        if self.related_errors:
            result["related_errors"] = self.related_errors

        return result


class ErrorRecordGenerator:
    """Generates error records with sequential IDs."""

    def __init__(self, governor_errors_path: Path) -> None:
        """Initialize the generator.

        Args:
            governor_errors_path: Path to governor/errors/
        """
        self._errors_path = governor_errors_path

    def generate_id(self, repo: str | None = None) -> str:
        """Generate the next error ID for today.

        Args:
            repo: Optional repo slug to scope the ID sequence

        Returns:
            Error ID in format ERR-YYYY-MM-DD-NNN
        """
        today = datetime.now().strftime("%Y-%m-%d")
        prefix = f"ERR-{today}"

        # Count existing errors for today
        if repo:
            search_path = self._errors_path / repo / today
        else:
            search_path = self._errors_path

        existing_count = 0
        if search_path.exists():
            for p in search_path.rglob("ERR-*.yaml"):
                if p.stem.startswith(prefix):
                    existing_count += 1

        next_num = existing_count + 1
        return f"{prefix}-{next_num:03d}"

    def create_record(
        self,
        error_type: ErrorType,
        message: str,
        repo: str,
        aip_ref: str,
        spec_ref: str | None = None,
        step: int | None = None,
        step_id: str | None = None,
        iteration: int | None = None,
        context: ErrorContext | None = None,
    ) -> ErrorRecord:
        """Create a new error record with auto-generated ID.

        Args:
            error_type: Type of error
            message: Human-readable error message
            repo: Repository slug
            aip_ref: Reference to AIP file
            spec_ref: Optional reference to spec file
            step: Optional step number (1-based)
            step_id: Optional step identifier
            iteration: Optional retry iteration
            context: Optional additional context

        Returns:
            New ErrorRecord instance
        """
        return ErrorRecord(
            error_id=self.generate_id(repo),
            error_type=error_type,
            message=message,
            timestamp=datetime.now(),
            repo=repo,
            aip_ref=aip_ref,
            spec_ref=spec_ref,
            step=step,
            step_id=step_id,
            iteration=iteration,
            context=context,
        )
