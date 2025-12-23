"""AIP splitting for multi-repo specs.

This module handles splitting a single spec into multiple repo-scoped AIPs,
one per target repository.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

from .targets import RepoTarget


@dataclass
class SplitAIP:
    """A repo-scoped AIP split from a multi-repo spec."""

    aip_id: str
    target: RepoTarget
    aip_data: dict[str, Any]
    parent_spec_ref: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "aip_id": self.aip_id,
            "target": self.target.to_dict(),
            "aip_data": self.aip_data,
            "parent_spec_ref": self.parent_spec_ref,
        }


class AIPSplitter:
    """Splits a multi-repo spec into individual repo-scoped AIPs.

    Each generated AIP:
    - Has a unique ID derived from parent spec + target
    - References the parent spec
    - Has isolated allowed_paths for the target repo
    - Contains only relevant plan steps
    """

    def __init__(self, spec_ref: str):
        """Initialize splitter.

        Args:
            spec_ref: Reference to the parent spec (e.g., "specs/my-feature.md")
        """
        self.spec_ref = spec_ref

    def split(
        self,
        aip_data: dict[str, Any],
        targets: list[RepoTarget],
    ) -> list[SplitAIP]:
        """Split AIP data into repo-scoped AIPs.

        Args:
            aip_data: Compiled AIP data from spec
            targets: Resolved target repositories

        Returns:
            List of SplitAIP objects, one per target
        """
        split_aips = []
        base_aip_id = aip_data.get("aip_id", "AIP-unknown")
        today = datetime.now().strftime("%Y-%m-%d")

        for idx, target in enumerate(targets, start=1):
            # Generate unique AIP ID for this target
            target_aip_id = f"{base_aip_id}-{target.name}-{idx:03d}"

            # Deep copy to avoid mutations
            target_aip = deepcopy(aip_data)

            # Update AIP with target-specific data
            target_aip["aip_id"] = target_aip_id
            target_aip["parent_spec"] = self.spec_ref
            target_aip["target_repo"] = target.name

            # Update repo section
            if "repo" not in target_aip:
                target_aip["repo"] = {}
            target_aip["repo"]["path"] = str(target.path)
            target_aip["repo"]["name"] = target.name

            # Update scope in plan steps
            target_aip = self._apply_target_scope(target_aip, target)

            # Update meta
            if "meta" not in target_aip:
                target_aip["meta"] = {}
            target_aip["meta"]["split_from"] = base_aip_id
            target_aip["meta"]["split_index"] = idx
            target_aip["meta"]["split_date"] = today

            split_aips.append(
                SplitAIP(
                    aip_id=target_aip_id,
                    target=target,
                    aip_data=target_aip,
                    parent_spec_ref=self.spec_ref,
                )
            )

        return split_aips

    def _apply_target_scope(
        self,
        aip: dict[str, Any],
        target: RepoTarget,
    ) -> dict[str, Any]:
        """Apply target-specific scope constraints to AIP plan steps.

        Args:
            aip: AIP data to modify
            target: Target with scope constraints

        Returns:
            Modified AIP data
        """
        plan = aip.get("plan", [])

        for step in plan:
            if "scope" not in step:
                step["scope"] = {}

            # Merge target scope with step scope
            # Target scope takes precedence for security
            step_scope = step["scope"]

            # Intersect allowed_paths (target restricts step)
            if target.allowed_paths:
                # Use target's allowed_paths, filtered by step's
                step_scope["allowed_paths"] = target.allowed_paths

            # Union forbidden_paths (both apply)
            step_forbidden = step_scope.get("forbidden_paths", [])
            combined_forbidden = list(set(step_forbidden + target.forbidden_paths))
            step_scope["forbidden_paths"] = combined_forbidden

            # Append target verification commands
            step_verify = step_scope.get("verification_commands", [])
            if target.verification_commands:
                step_scope["verification_commands"] = (
                    step_verify + target.verification_commands
                )

        return aip


def compile_multi_repo_spec(
    spec_data: dict[str, Any],
    targets: list[RepoTarget],
    spec_ref: str,
) -> list[SplitAIP]:
    """Convenience function to compile a multi-repo spec into split AIPs.

    Args:
        spec_data: Parsed spec/AIP data
        targets: Resolved target repositories
        spec_ref: Reference to the source spec

    Returns:
        List of SplitAIP objects
    """
    splitter = AIPSplitter(spec_ref)
    return splitter.split(spec_data, targets)
