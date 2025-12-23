"""Cross-repo execution coordination.

This module handles executing multiple repo-scoped AIPs in sequence,
aggregating errors and producing unified provenance records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

from .provenance import ProvenanceSnapshot, RunStatus
from .splitter import SplitAIP


@dataclass
class RepoExecutionResult:
    """Result of executing an AIP in a single repo."""

    aip_id: str
    repo_name: str
    repo_path: Path
    status: RunStatus
    steps_executed: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "aip_id": self.aip_id,
            "repo_name": self.repo_name,
            "repo_path": str(self.repo_path),
            "status": self.status.value,
            "steps_executed": self.steps_executed,
            "errors": self.errors,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class MultiRepoExecutionResult:
    """Aggregated result of executing AIPs across multiple repos."""

    parent_spec_ref: str
    overall_status: RunStatus
    repo_results: list[RepoExecutionResult] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def all_errors(self) -> list[str]:
        """Get all errors across repos."""
        errors = []
        for result in self.repo_results:
            for error in result.errors:
                errors.append(f"[{result.repo_name}] {error}")
        return errors

    @property
    def all_steps_executed(self) -> list[int]:
        """Get union of all steps executed across repos."""
        steps = set()
        for result in self.repo_results:
            steps.update(result.steps_executed)
        return sorted(steps)

    def to_provenance(self, run_id: str) -> ProvenanceSnapshot:
        """Convert to a unified provenance snapshot.

        Args:
            run_id: Unique run identifier

        Returns:
            ProvenanceSnapshot capturing the multi-repo execution
        """
        return ProvenanceSnapshot(
            run_id=run_id,
            aip_ref=self.parent_spec_ref,
            repo=",".join(r.repo_name for r in self.repo_results),
            started_at=self.started_at or datetime.now(),
            completed_at=self.completed_at,
            status=self.overall_status,
            steps_executed=self.all_steps_executed,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "parent_spec_ref": self.parent_spec_ref,
            "overall_status": self.overall_status.value,
            "repo_results": [r.to_dict() for r in self.repo_results],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "all_errors": self.all_errors,
        }


class MultiRepoCoordinator:
    """Coordinates execution of AIPs across multiple repositories.

    Executes AIPs in target order, aggregating results and errors
    into a unified execution record.
    """

    def __init__(self, parent_spec_ref: str):
        """Initialize coordinator.

        Args:
            parent_spec_ref: Reference to the parent spec
        """
        self.parent_spec_ref = parent_spec_ref
        self.results: list[RepoExecutionResult] = []
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None

    def execute_all(
        self,
        split_aips: list[SplitAIP],
        executor_fn: Any,  # Callable[[SplitAIP], RepoExecutionResult]
        stop_on_failure: bool = True,
    ) -> MultiRepoExecutionResult:
        """Execute all split AIPs in order.

        Args:
            split_aips: List of repo-scoped AIPs to execute
            executor_fn: Function to execute a single AIP, returns RepoExecutionResult
            stop_on_failure: If True, stop on first failure

        Returns:
            Aggregated execution result
        """
        self.started_at = datetime.now()
        self.results = []

        for split_aip in split_aips:
            try:
                result = executor_fn(split_aip)
                self.results.append(result)

                if stop_on_failure and result.status == RunStatus.FAILED:
                    break

            except Exception as e:
                # Capture unexpected errors
                self.results.append(
                    RepoExecutionResult(
                        aip_id=split_aip.aip_id,
                        repo_name=split_aip.target.name,
                        repo_path=split_aip.target.path,
                        status=RunStatus.FAILED,
                        errors=[str(e)],
                        started_at=datetime.now(),
                        completed_at=datetime.now(),
                    )
                )
                if stop_on_failure:
                    break

        self.completed_at = datetime.now()
        return self._aggregate_results()

    def _aggregate_results(self) -> MultiRepoExecutionResult:
        """Aggregate individual repo results into overall result."""
        # Determine overall status
        if not self.results:
            overall_status = RunStatus.CANCELLED  # No results means nothing ran
        elif all(r.status == RunStatus.COMPLETED for r in self.results):
            overall_status = RunStatus.COMPLETED
        elif any(r.status == RunStatus.FAILED for r in self.results):
            overall_status = RunStatus.FAILED
        else:
            overall_status = RunStatus.RUNNING

        return MultiRepoExecutionResult(
            parent_spec_ref=self.parent_spec_ref,
            overall_status=overall_status,
            repo_results=self.results,
            started_at=self.started_at,
            completed_at=self.completed_at,
        )

    def record_result(self, result: RepoExecutionResult) -> None:
        """Manually record a repo execution result.

        Useful when execution is handled externally.

        Args:
            result: Execution result to record
        """
        if self.started_at is None:
            self.started_at = datetime.now()
        self.results.append(result)

    def finalize(self) -> MultiRepoExecutionResult:
        """Finalize and return aggregated results.

        Call after all results have been recorded.

        Returns:
            Aggregated execution result
        """
        self.completed_at = datetime.now()
        return self._aggregate_results()
