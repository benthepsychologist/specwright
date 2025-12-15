"""
Scope Checker

Validates that touched files are within allowed paths and not in forbidden paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spec.executor.contract import StepContract


class ViolationType(str, Enum):
    """Type of scope violation."""

    NOT_ALLOWED = "not_allowed"
    FORBIDDEN = "forbidden"


@dataclass
class ScopeViolation:
    """A single scope violation."""

    file_path: str
    violation_type: ViolationType
    matched_pattern: str | None = None
    message: str = ""

    def __post_init__(self) -> None:
        if not self.message:
            if self.violation_type == ViolationType.NOT_ALLOWED:
                self.message = f"File '{self.file_path}' is not in any allowed path pattern"
            else:
                self.message = (
                    f"File '{self.file_path}' matches forbidden pattern '{self.matched_pattern}'"
                )


@dataclass
class ScopeResult:
    """Result of scope checking."""

    passed: bool
    violations: list[ScopeViolation] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


class PathTraversalError(Exception):
    """Raised when a path contains traversal sequences or is absolute."""


def _normalize_path(path: str) -> str:
    """
    Normalize a file path for consistent matching.

    - Strips leading ./
    - Strips leading/trailing whitespace
    - Converts backslashes to forward slashes
    - Rejects path traversal (../) and absolute paths

    Raises:
        PathTraversalError: If path contains traversal or is absolute
    """
    path = path.strip()
    path = path.replace("\\", "/")

    # Reject absolute paths
    if path.startswith("/"):
        raise PathTraversalError(f"Absolute paths not allowed: {path}")

    # Reject path traversal
    if ".." in path.split("/"):
        raise PathTraversalError(f"Path traversal not allowed: {path}")

    # Strip leading ./
    if path.startswith("./"):
        path = path[2:]

    return path


def _matches_glob(file_path: str, pattern: str) -> bool:
    """
    Check if a file path matches a glob pattern.

    Supports:
    - ** for any directory depth
    - * for any characters within a path segment (does NOT cross directories)
    - ? for single character
    """
    file_path = _normalize_path(file_path)
    pattern = _normalize_path(pattern)

    # Handle ** patterns specially
    if "**" in pattern:
        # Split pattern at **
        parts = pattern.split("**")
        if len(parts) == 2:
            prefix, suffix = parts
            prefix = prefix.rstrip("/")
            suffix = suffix.lstrip("/")

            # For patterns like "src/**" - match anything under src/
            if not suffix:
                if not prefix:
                    return True  # Pattern is just "**" - matches everything
                # File must start with prefix + /
                return file_path.startswith(prefix + "/") or file_path == prefix

            # For patterns like "**/*.py" or "src/**/*.py"
            file_parts = file_path.split("/")
            suffix_parts = suffix.split("/") if suffix else []

            # Check if prefix matches
            if prefix and not file_path.startswith(prefix + "/"):
                return False

            # Check if suffix matches the end of the path
            if suffix_parts:
                if len(file_parts) < len(suffix_parts):
                    return False
                for i, suffix_part in enumerate(reversed(suffix_parts)):
                    file_part = file_parts[-(i + 1)]
                    if not fnmatch(file_part, suffix_part):
                        return False
                return True

    # For patterns without **, match component by component
    # This ensures * doesn't cross directory boundaries
    file_parts = file_path.split("/")
    pattern_parts = pattern.split("/")

    # Must have same number of path components
    if len(file_parts) != len(pattern_parts):
        return False

    # Match each component
    for file_part, pattern_part in zip(file_parts, pattern_parts, strict=True):
        if not fnmatch(file_part, pattern_part):
            return False

    return True


def _is_allowed(file_path: str, allowed_paths: list[str]) -> bool:
    """Check if a file is allowed by any of the allowed path patterns."""
    file_path = _normalize_path(file_path)
    for pattern in allowed_paths:
        if _matches_glob(file_path, pattern):
            return True
    return False


def _is_forbidden(file_path: str, forbidden_paths: list[str]) -> tuple[bool, str | None]:
    """
    Check if a file matches any forbidden path pattern.

    Returns (is_forbidden, matched_pattern).
    """
    file_path = _normalize_path(file_path)
    for pattern in forbidden_paths:
        if _matches_glob(file_path, pattern):
            return True, pattern
    return False, None


def check_scope(touched: list[str], contract: StepContract) -> ScopeResult:
    """
    Check if all touched files are within scope.

    A file is in scope if:
    1. It matches at least one allowed_paths pattern, AND
    2. It does NOT match any forbidden_paths pattern

    Forbidden paths ALWAYS win - a file in a forbidden path is rejected
    even if it matches an allowed path.

    Args:
        touched: List of file paths from git diff --name-only
        contract: StepContract with allowed_paths and forbidden_paths

    Returns:
        ScopeResult with passed=True if all files are in scope
    """
    violations: list[ScopeViolation] = []
    checked_files = [_normalize_path(f) for f in touched]

    for file_path in checked_files:
        # Check forbidden paths first (forbidden always wins)
        is_forbidden, matched_pattern = _is_forbidden(file_path, contract.forbidden_paths)
        if is_forbidden:
            violations.append(
                ScopeViolation(
                    file_path=file_path,
                    violation_type=ViolationType.FORBIDDEN,
                    matched_pattern=matched_pattern,
                )
            )
            continue

        # Check allowed paths
        if not _is_allowed(file_path, contract.allowed_paths):
            violations.append(
                ScopeViolation(
                    file_path=file_path,
                    violation_type=ViolationType.NOT_ALLOWED,
                )
            )

    return ScopeResult(
        passed=len(violations) == 0,
        violations=violations,
        checked_files=checked_files,
    )


def generate_policy_report(
    result: ScopeResult,
    touched_metadata: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Generate a machine-readable policy report from a scope check result.

    Args:
        result: ScopeResult from check_scope()
        touched_metadata: Optional metadata about touched files from runner
            (touched_total, touched_tracked, touched_untracked, touched_excluded_artifacts)

    Returns a dict suitable for JSON serialization.
    """
    summary = {
        "total_files": len(result.checked_files),
        "violations_count": len(result.violations),
    }

    # Add touched file breakdown if metadata provided
    if touched_metadata:
        summary["touched_tracked"] = touched_metadata.get("touched_tracked", 0)
        summary["touched_untracked"] = touched_metadata.get("touched_untracked", 0)
        summary["touched_excluded_artifacts"] = touched_metadata.get(
            "touched_excluded_artifacts", 0
        )

    return {
        "passed": result.passed,
        "timestamp": result.timestamp,
        "summary": summary,
        "checked_files": result.checked_files,
        "violations": [
            {
                "file_path": v.file_path,
                "violation_type": v.violation_type.value,
                "matched_pattern": v.matched_pattern,
                "message": v.message,
            }
            for v in result.violations
        ],
    }
