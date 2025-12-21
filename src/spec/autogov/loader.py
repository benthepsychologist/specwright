"""Governance loader for project.build.yaml files from local-governor."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import (
    AutogovNotInstalledError,
    GovernanceInvalidError,
    GovernanceNotFoundError,
)


@dataclass
class Decision:
    """An architectural decision record from a project build file."""

    id: str
    title: str
    status: str
    rationale: str | None = None
    decision: str | None = None


@dataclass
class Rule:
    """A placement or semantic rule from a project build file."""

    id: str
    message: str
    severity: str
    kind: str  # "placement" or "semantic"


@dataclass
class AppliedPolicy:
    """A reference to an applied policy."""

    ref: str  # e.g., "org::policy/credential-hygiene@0.1.0"
    name: str  # e.g., "credential-hygiene"
    version: str  # e.g., "0.1.0"


@dataclass
class AppliedPattern:
    """A reference to an applied pattern."""

    ref: str  # e.g., "patterns::pattern/registry-kernel@0.1.0"
    name: str  # e.g., "registry-kernel"
    version: str  # e.g., "0.1.0"


@dataclass
class GovernanceBundle:
    """Container for governance data loaded from a project.build.yaml file.

    This replaces the old PolicyPack/ArchPack/StatePack model with direct
    extraction from project build files.
    """

    # Project metadata
    project: str
    source: str
    version: str
    description: str

    # Architectural decisions (from decisions section)
    decisions: list[Decision] = field(default_factory=list)

    # Rules (from rules section)
    rules: list[Rule] = field(default_factory=list)

    # Applied policies and patterns (from applies section)
    policies: list[AppliedPolicy] = field(default_factory=list)
    patterns: list[AppliedPattern] = field(default_factory=list)

    # Kernel invariants
    invariants: list[str] = field(default_factory=list)

    # Frozen paths (files that should not be modified)
    frozen_paths: list[str] = field(default_factory=list)


def _parse_ref(ref: str) -> tuple[str, str]:
    """Parse a reference like 'org::policy/credential-hygiene@0.1.0'.

    Returns:
        Tuple of (name, version)
    """
    # Format: source::kind/name@version
    # e.g., "org::policy/credential-hygiene@0.1.0"
    #       "patterns::pattern/registry-kernel@0.1.0"
    try:
        # Split off version
        if "@" in ref:
            base, version = ref.rsplit("@", 1)
        else:
            base, version = ref, "unknown"

        # Get the name (last part after /)
        if "/" in base:
            name = base.rsplit("/", 1)[1]
        else:
            name = base

        return name, version
    except Exception:
        return ref, "unknown"


def _get_local_governor_root() -> Path:
    """Get the local-governor root path.

    Returns:
        Path to local-governor directory

    Raises:
        AutogovNotInstalledError: If local-governor is not found
    """
    # Check environment variable first
    env_path = os.environ.get("LOCAL_GOVERNOR_HOME")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path

    # Default location
    default_path = Path.home() / ".local" / "local-governor"
    if default_path.exists():
        return default_path

    raise AutogovNotInstalledError(
        "local-governor not found. Set LOCAL_GOVERNOR_HOME or ensure "
        "~/.local/local-governor exists."
    )


class GovernanceLoader:
    """Loads governance from project.build.yaml files in local-governor.

    The loader reads project build files from:
    - ~/.local/local-governor/projects/<project>/<project>.build.yaml
    - Or path specified by LOCAL_GOVERNOR_HOME environment variable
    """

    def __init__(self) -> None:
        self._root: Path | None = None

    def _get_root(self) -> Path:
        """Get cached local-governor root path."""
        if self._root is None:
            self._root = _get_local_governor_root()
        return self._root

    def _find_build_file(self, project: str) -> Path:
        """Find the build file for a project.

        Args:
            project: Project name

        Returns:
            Path to the build file

        Raises:
            GovernanceNotFoundError: If build file not found
        """
        root = self._get_root()
        build_file = root / "projects" / project / f"{project}.build.yaml"

        if not build_file.exists():
            raise GovernanceNotFoundError(
                f"Project build file not found: {build_file}"
            )

        return build_file

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        """Load and parse a YAML file.

        Args:
            path: Path to YAML file

        Returns:
            Parsed YAML data

        Raises:
            GovernanceInvalidError: If YAML is invalid
        """
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise GovernanceInvalidError(
                    f"Invalid build file format: {path} (expected mapping)"
                )
            return data
        except yaml.YAMLError as e:
            raise GovernanceInvalidError(
                f"Failed to parse build file {path}: {e}"
            ) from e

    def _parse_decisions(self, data: dict[str, Any]) -> list[Decision]:
        """Extract decisions from build file data."""
        decisions = []
        for d in data.get("decisions", []):
            decisions.append(
                Decision(
                    id=d.get("id", ""),
                    title=d.get("title", ""),
                    status=d.get("status", "unknown"),
                    rationale=d.get("rationale"),
                    decision=d.get("decision"),
                )
            )
        return decisions

    def _parse_rules(self, data: dict[str, Any]) -> list[Rule]:
        """Extract rules from build file data."""
        rules_section = data.get("rules", {})
        rules = []

        # Placement rules
        for r in rules_section.get("placement", []):
            rules.append(
                Rule(
                    id=r.get("id", ""),
                    message=r.get("message", ""),
                    severity=r.get("severity", "warning"),
                    kind="placement",
                )
            )

        # Semantic rules
        for r in rules_section.get("semantic", []):
            rules.append(
                Rule(
                    id=r.get("id", ""),
                    message=r.get("check", r.get("message", "")),
                    severity=r.get("severity", "warning"),
                    kind="semantic",
                )
            )

        return rules

    def _parse_applies(
        self, data: dict[str, Any]
    ) -> tuple[list[AppliedPolicy], list[AppliedPattern]]:
        """Extract applied policies and patterns from build file data."""
        applies = data.get("applies", {})
        policies = []
        patterns = []

        for ref in applies.get("policies", []):
            name, version = _parse_ref(ref)
            policies.append(AppliedPolicy(ref=ref, name=name, version=version))

        for ref in applies.get("patterns", []):
            name, version = _parse_ref(ref)
            patterns.append(AppliedPattern(ref=ref, name=name, version=version))

        return policies, patterns

    def _parse_invariants(self, data: dict[str, Any]) -> list[str]:
        """Extract kernel invariants from build file data."""
        kernel = data.get("kernel", {})
        return kernel.get("invariants", [])

    def _parse_frozen_paths(self, data: dict[str, Any]) -> list[str]:
        """Extract frozen paths from build file data."""
        frozen = data.get("frozen", [])
        return [f.get("path", "") for f in frozen if isinstance(f, dict)]

    def load_all(self, project: str, source: str) -> GovernanceBundle:
        """Load governance bundle from a project build file.

        Args:
            project: Project name (e.g., "injest", "life")
            source: Registry source (ignored for local-governor, kept for API compat)

        Returns:
            GovernanceBundle with extracted governance data

        Raises:
            AutogovNotInstalledError: If local-governor not found
            GovernanceNotFoundError: If project build file not found
            GovernanceInvalidError: If build file is malformed
        """
        build_file = self._find_build_file(project)
        data = self._load_yaml(build_file)

        # Validate kind
        if data.get("kind") != "project.build":
            raise GovernanceInvalidError(
                f"Invalid build file kind: {data.get('kind')} (expected 'project.build')"
            )

        # Extract metadata
        metadata = data.get("metadata", {})
        kernel = data.get("kernel", {})

        # Parse all sections
        decisions = self._parse_decisions(data)
        rules = self._parse_rules(data)
        policies, patterns = self._parse_applies(data)
        invariants = self._parse_invariants(data)
        frozen_paths = self._parse_frozen_paths(data)

        return GovernanceBundle(
            project=project,
            source=source,
            version=metadata.get("semver", "0.0.0"),
            description=kernel.get("description", ""),
            decisions=decisions,
            rules=rules,
            policies=policies,
            patterns=patterns,
            invariants=invariants,
            frozen_paths=frozen_paths,
        )
