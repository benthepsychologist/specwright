"""AIP v3 dataclasses - Context Packet models.

This module defines the core data structures for AIP v3, the context packet
format that flows from epic → compile → enrich → run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import dacite
import yaml

if TYPE_CHECKING:
    pass


class WorkspaceMode(str, Enum):
    """Workspace mode for AIP execution."""

    SINGLE_REPO = "single-repo"
    MULTI_REPO = "multi-repo"


@dataclass
class PatternReference:
    """Reference to a file with patterns to follow."""

    file: str
    note: str | None = None


@dataclass
class AIPVerification:
    """Verification command for a step or final verification."""

    cmd: str
    expected: str | None = None


@dataclass
class AIPStepGuidance:
    """Guidance for implementing a step."""

    likely_files: list[str] = field(default_factory=list)
    patterns_to_follow: list[PatternReference] = field(default_factory=list)
    approach: str | None = None
    watch_out_for: list[str] = field(default_factory=list)


@dataclass
class AIPPhase:
    """A phase in the AIP execution plan.

    Phases are logical units of work within an AIP. They are NOT executor steps -
    the entire AIP is passed to a single agent step in the aip-1 job template.
    """

    id: str
    title: str
    objective: str
    guidance: AIPStepGuidance | None = None
    verification: list[AIPVerification] = field(default_factory=list)


# Backwards compatibility alias
AIPStep = AIPPhase


@dataclass
class AIPMetadata:
    """Metadata for an AIP context packet."""

    epic_id: str
    spec_id: str
    owner: str
    created: str  # ISO 8601 timestamp
    updated: str | None = None

    def __post_init__(self) -> None:
        if not self.created:
            self.created = datetime.now(UTC).isoformat()


@dataclass
class AIPWorkspace:
    """Workspace configuration for AIP execution."""

    mode: WorkspaceMode
    repo_path: str
    branch: str
    base_branch: str
    suggested_paths: list[str] = field(default_factory=list)


@dataclass
class AIPExecution:
    """Execution configuration for AIP."""

    timeout_seconds: int = 1800
    auto_resume_on_crash: bool = True
    max_retries: int = 2
    pause_on_timeout: bool = True


@dataclass
class AIPv3:
    """AIP v3 Context Packet.

    The core data structure that flows from epic → compile → enrich → run.

    Note: 'phases' are logical units of work within an AIP. They are NOT executor
    steps - the entire AIP is passed to a single agent step in the aip-1 job template.
    """

    version: str
    kind: str
    metadata: AIPMetadata
    workspace: AIPWorkspace
    goal: str
    expectations: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    execution: AIPExecution | None = None
    phases: list[AIPPhase] = field(default_factory=list)
    final_verification: list[AIPVerification] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.version != "3.0":
            self.version = "3.0"
        if self.kind != "context-packet":
            self.kind = "context-packet"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "version": self.version,
            "kind": self.kind,
            "metadata": _metadata_to_dict(self.metadata),
            "workspace": _workspace_to_dict(self.workspace),
            "goal": self.goal,
        }

        if self.expectations:
            result["expectations"] = self.expectations
        if self.constraints:
            result["constraints"] = self.constraints
        if self.checks:
            result["checks"] = self.checks
        if self.execution:
            result["execution"] = _execution_to_dict(self.execution)
        if self.phases:
            result["phases"] = [_phase_to_dict(p) for p in self.phases]
        if self.final_verification:
            result["final_verification"] = [
                _verification_to_dict(v) for v in self.final_verification
            ]

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AIPv3:
        """Load from dictionary."""
        return dacite.from_dict(
            data_class=cls,
            data=data,
            config=dacite.Config(
                type_hooks={
                    WorkspaceMode: lambda x: WorkspaceMode(x),
                },
                cast=[WorkspaceMode],
            ),
        )

    def save(self, path: Path) -> None:
        """Save to YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        yaml_content = _serialize_aip(self.to_dict())
        path.write_text(yaml_content, encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> AIPv3:
        """Load from YAML file."""
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        return cls.from_dict(data)


def _metadata_to_dict(metadata: AIPMetadata) -> dict[str, Any]:
    """Convert AIPMetadata to dictionary."""
    result: dict[str, Any] = {
        "epic_id": metadata.epic_id,
        "spec_id": metadata.spec_id,
        "owner": metadata.owner,
        "created": metadata.created,
    }
    if metadata.updated:
        result["updated"] = metadata.updated
    return result


def _workspace_to_dict(workspace: AIPWorkspace) -> dict[str, Any]:
    """Convert AIPWorkspace to dictionary."""
    result: dict[str, Any] = {
        "mode": workspace.mode.value,
        "repo_path": workspace.repo_path,
        "branch": workspace.branch,
        "base_branch": workspace.base_branch,
    }
    if workspace.suggested_paths:
        result["suggested_paths"] = workspace.suggested_paths
    return result


def _execution_to_dict(execution: AIPExecution) -> dict[str, Any]:
    """Convert AIPExecution to dictionary."""
    return {
        "timeout_seconds": execution.timeout_seconds,
        "auto_resume_on_crash": execution.auto_resume_on_crash,
        "max_retries": execution.max_retries,
        "pause_on_timeout": execution.pause_on_timeout,
    }


def _phase_to_dict(phase: AIPPhase) -> dict[str, Any]:
    """Convert AIPPhase to dictionary."""
    result: dict[str, Any] = {
        "id": phase.id,
        "title": phase.title,
        "objective": phase.objective,
    }
    if phase.guidance:
        result["guidance"] = _guidance_to_dict(phase.guidance)
    if phase.verification:
        result["verification"] = [_verification_to_dict(v) for v in phase.verification]
    return result


# Backwards compatibility alias
_step_to_dict = _phase_to_dict


def _guidance_to_dict(guidance: AIPStepGuidance) -> dict[str, Any]:
    """Convert AIPStepGuidance to dictionary."""
    result: dict[str, Any] = {}
    if guidance.likely_files:
        result["likely_files"] = guidance.likely_files
    if guidance.patterns_to_follow:
        result["patterns_to_follow"] = [
            _pattern_ref_to_dict(p) for p in guidance.patterns_to_follow
        ]
    if guidance.approach:
        result["approach"] = guidance.approach
    if guidance.watch_out_for:
        result["watch_out_for"] = guidance.watch_out_for
    return result


def _pattern_ref_to_dict(pattern: PatternReference) -> dict[str, Any]:
    """Convert PatternReference to dictionary."""
    result: dict[str, Any] = {"file": pattern.file}
    if pattern.note:
        result["note"] = pattern.note
    return result


def _verification_to_dict(verification: AIPVerification) -> dict[str, Any]:
    """Convert AIPVerification to dictionary."""
    result: dict[str, Any] = {"cmd": verification.cmd}
    if verification.expected:
        result["expected"] = verification.expected
    return result


def _serialize_aip(data: dict[str, Any]) -> str:
    """Serialize AIP data to YAML deterministically.

    - Disables anchors/aliases
    - Uses block style YAML
    - Preserves key order (sort_keys=False)
    """

    class CanonicalDumper(yaml.SafeDumper):
        def ignore_aliases(self, _data: Any) -> bool:  # noqa: ANN401
            return True

    def _normalize_for_pyyaml(value: Any) -> Any:  # noqa: ANN401
        """Convert ruamel.yaml types to plain Python types.

        Epics are loaded via ruamel.yaml (round-trip preservation), which can
        yield ScalarString / CommentedMap / CommentedSeq values. PyYAML cannot
        represent those types by default.
        """
        if isinstance(value, dict):
            return {str(_normalize_for_pyyaml(k)): _normalize_for_pyyaml(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_normalize_for_pyyaml(v) for v in value]
        if isinstance(value, tuple):
            return [_normalize_for_pyyaml(v) for v in value]

        # Avoid hard dependency on ruamel.yaml: detect by module/name.
        value_type = type(value)
        module = getattr(value_type, "__module__", "")
        if module.startswith("ruamel.yaml"):
            # ScalarString is also a subclass of str, but PyYAML sees the
            # concrete type and refuses to represent it.
            return str(value)

        return value

    data = _normalize_for_pyyaml(data)

    yaml_str = yaml.dump(
        data,
        Dumper=CanonicalDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )

    lines = [line.rstrip() for line in yaml_str.split("\n")]
    return "\n".join(lines).rstrip("\n") + "\n"
