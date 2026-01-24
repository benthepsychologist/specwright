"""Multi-repo target resolution for specs.

This module handles parsing and resolving the `targets` block in specs,
allowing a single spec to apply across multiple repositories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@dataclass
class RepoTarget:
    """A resolved target repository for a spec."""

    name: str
    path: Path
    suggested_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "path": str(self.path),
            "suggested_paths": self.suggested_paths,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoTarget:
        """Create from dictionary."""
        return cls(
            name=data["name"],
            path=Path(data["path"]),
            suggested_paths=data.get("suggested_paths", []),
        )


class TargetResolver:
    """Resolves repository targets from spec definitions.

    Supports both explicit paths and registry-based resolution.
    """

    def __init__(self, registry: dict[str, Path] | None = None):
        """Initialize resolver with optional registry.

        Args:
            registry: Mapping of repo names to paths (e.g., from autogov)
        """
        self.registry = registry or {}

    def resolve(self, targets_block: list[dict[str, Any]]) -> list[RepoTarget]:
        """Resolve targets block into RepoTarget objects.

        Args:
            targets_block: List of target definitions from spec YAML

        Returns:
            List of resolved RepoTarget objects

        Raises:
            TargetResolutionError: If a target cannot be resolved
        """
        resolved = []

        for target in targets_block:
            name = target.get("repo") or target.get("name")
            if not name:
                raise TargetResolutionError("Target missing 'repo' or 'name' field")

            # Resolve path: explicit path > registry > error
            path_str = target.get("path")
            if path_str:
                path = Path(path_str).expanduser().resolve()
            elif name in self.registry:
                path = self.registry[name]
            else:
                raise TargetResolutionError(
                    f"Cannot resolve target '{name}': no path provided and not in registry"
                )

            # Validate path exists
            if not path.exists():
                raise TargetResolutionError(
                    f"Target '{name}' path does not exist: {path}"
                )

            resolved.append(
                RepoTarget(
                    name=name,
                    path=path,
                    suggested_paths=target.get("suggested_paths", ["**/*"]),
                )
            )

        return resolved

    def validate_scopes(self, targets: list[RepoTarget]) -> list[str]:
        """Validate that scope paths exist in target repos.

        Args:
            targets: Resolved targets to validate

        Returns:
            List of warning messages (empty if all valid)
        """
        warnings = []

        for target in targets:
            for pattern in target.suggested_paths:
                # Skip glob patterns - can't validate without expansion
                if "*" in pattern:
                    continue

                check_path = target.path / pattern
                if not check_path.exists():
                    warnings.append(
                        f"Target '{target.name}': suggested_path '{pattern}' does not exist"
                    )

        return warnings


class TargetResolutionError(Exception):
    """Error resolving a spec target."""

    pass
