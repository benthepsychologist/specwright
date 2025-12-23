"""Provenance tracking: execution history for local-governor.

This module defines the ProvenanceSnapshot dataclass for capturing
execution provenance, including governance state, git snapshots,
and execution metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class RunStatus(str, Enum):
    """Status of an execution run."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class GovernanceSnapshot:
    """Snapshot of governance state at execution time."""

    governor_commit: str | None = None
    spec_hash: str | None = None
    aip_hash: str | None = None
    tier: str | None = None
    policies_applied: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {}
        if self.governor_commit is not None:
            result["governor_commit"] = self.governor_commit
        if self.spec_hash is not None:
            result["spec_hash"] = self.spec_hash
        if self.aip_hash is not None:
            result["aip_hash"] = self.aip_hash
        if self.tier is not None:
            result["tier"] = self.tier
        if self.policies_applied:
            result["policies_applied"] = self.policies_applied
        if self.constraints:
            result["constraints"] = self.constraints
        return result


@dataclass
class GitSnapshot:
    """Snapshot of git state during execution."""

    start_commit: str | None = None
    end_commit: str | None = None
    branch: str | None = None
    commits_created: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {}
        if self.start_commit is not None:
            result["start_commit"] = self.start_commit
        if self.end_commit is not None:
            result["end_commit"] = self.end_commit
        if self.branch is not None:
            result["branch"] = self.branch
        if self.commits_created:
            result["commits_created"] = self.commits_created
        if self.files_changed:
            result["files_changed"] = self.files_changed
        return result


@dataclass
class ExecutionMetrics:
    """Metrics from an execution run."""

    duration_seconds: float | None = None
    iterations_total: int | None = None
    retries_total: int | None = None
    errors_total: int | None = None
    files_created: int | None = None
    files_modified: int | None = None
    files_deleted: int | None = None
    tests_run: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None
    coverage_percent: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {}
        for attr in [
            "duration_seconds",
            "iterations_total",
            "retries_total",
            "errors_total",
            "files_created",
            "files_modified",
            "files_deleted",
            "tests_run",
            "tests_passed",
            "tests_failed",
            "coverage_percent",
        ]:
            value = getattr(self, attr)
            if value is not None:
                result[attr] = value
        return result


@dataclass
class AdapterInfo:
    """Information about the agent adapter used."""

    name: str | None = None
    model: str | None = None
    tokens_used: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {}
        if self.name is not None:
            result["name"] = self.name
        if self.model is not None:
            result["model"] = self.model
        if self.tokens_used is not None:
            result["tokens_used"] = self.tokens_used
        return result


@dataclass
class ProvenanceSnapshot:
    """Execution provenance record for local-governor storage."""

    run_id: str
    aip_ref: str
    repo: str
    started_at: datetime
    status: RunStatus

    spec_ref: str | None = None
    repo_path: str | None = None
    completed_at: datetime | None = None
    executor: str | None = None
    steps_executed: list[int] = field(default_factory=list)
    steps_total: int | None = None
    gates_approved: list[str] = field(default_factory=list)
    governance_snapshot: GovernanceSnapshot | None = None
    git_snapshot: GitSnapshot | None = None
    metrics: ExecutionMetrics | None = None
    adapter_info: AdapterInfo | None = None
    error_refs: list[str] = field(default_factory=list)
    artifacts_path: str | None = None
    notes: str | None = None
    related_runs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {
            "run_id": self.run_id,
            "aip_ref": self.aip_ref,
            "repo": self.repo,
            "started_at": self.started_at.isoformat(),
            "status": self.status.value,
        }

        if self.spec_ref is not None:
            result["spec_ref"] = self.spec_ref
        if self.repo_path is not None:
            result["repo_path"] = self.repo_path
        if self.completed_at is not None:
            result["completed_at"] = self.completed_at.isoformat()
        if self.executor is not None:
            result["executor"] = self.executor
        if self.steps_executed:
            result["steps_executed"] = self.steps_executed
        if self.steps_total is not None:
            result["steps_total"] = self.steps_total
        if self.gates_approved:
            result["gates_approved"] = self.gates_approved
        if self.governance_snapshot is not None:
            result["governance_snapshot"] = self.governance_snapshot.to_dict()
        if self.git_snapshot is not None:
            result["git_snapshot"] = self.git_snapshot.to_dict()
        if self.metrics is not None:
            result["metrics"] = self.metrics.to_dict()
        if self.adapter_info is not None:
            result["adapter_info"] = self.adapter_info.to_dict()
        if self.error_refs:
            result["error_refs"] = self.error_refs
        if self.artifacts_path is not None:
            result["artifacts_path"] = self.artifacts_path
        if self.notes is not None:
            result["notes"] = self.notes
        if self.related_runs:
            result["related_runs"] = self.related_runs

        return result


class ProvenanceGenerator:
    """Generates provenance records with sequential IDs."""

    def __init__(self, governor_runs_path: Path) -> None:
        """Initialize the generator.

        Args:
            governor_runs_path: Path to governor/runs/
        """
        self._runs_path = governor_runs_path

    def generate_id(self, repo: str | None = None) -> str:
        """Generate the next run ID for today.

        Args:
            repo: Optional repo slug to scope the ID sequence

        Returns:
            Run ID in format RUN-YYYY-MM-DD-NNN
        """
        today = datetime.now().strftime("%Y-%m-%d")
        prefix = f"RUN-{today}"

        # Count existing runs for today
        if repo:
            search_path = self._runs_path / repo / today
        else:
            search_path = self._runs_path

        existing_count = 0
        if search_path.exists():
            for p in search_path.rglob("RUN-*.yaml"):
                if p.stem.startswith(prefix):
                    existing_count += 1

        next_num = existing_count + 1
        return f"{prefix}-{next_num:03d}"

    def create_snapshot(
        self,
        aip_ref: str,
        repo: str,
        status: RunStatus = RunStatus.RUNNING,
        **kwargs: Any,
    ) -> ProvenanceSnapshot:
        """Create a new provenance snapshot with auto-generated ID.

        Args:
            aip_ref: Reference to AIP file
            repo: Repository slug
            status: Initial run status
            **kwargs: Additional ProvenanceSnapshot fields

        Returns:
            New ProvenanceSnapshot instance
        """
        return ProvenanceSnapshot(
            run_id=self.generate_id(repo),
            aip_ref=aip_ref,
            repo=repo,
            started_at=datetime.now(),
            status=status,
            **kwargs,
        )
