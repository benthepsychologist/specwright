"""Tests for multi-repo execution coordination."""

from datetime import datetime
from pathlib import Path

from spec.governor.coordinator import (
    MultiRepoCoordinator,
    MultiRepoExecutionResult,
    RepoExecutionResult,
)
from spec.governor.provenance import RunStatus
from spec.governor.splitter import SplitAIP
from spec.governor.targets import RepoTarget


class TestRepoExecutionResult:
    """Tests for RepoExecutionResult dataclass."""

    def test_to_dict(self, tmp_path: Path) -> None:
        """Test serialization to dictionary."""
        now = datetime.now()
        result = RepoExecutionResult(
            aip_id="AIP-001",
            repo_name="my-repo",
            repo_path=tmp_path,
            status=RunStatus.COMPLETED,
            steps_executed=[1, 2, 3],
            errors=[],
            started_at=now,
            completed_at=now,
        )

        data = result.to_dict()

        assert data["aip_id"] == "AIP-001"
        assert data["repo_name"] == "my-repo"
        assert data["repo_path"] == str(tmp_path)
        assert data["status"] == "COMPLETED"
        assert data["steps_executed"] == [1, 2, 3]


class TestMultiRepoExecutionResult:
    """Tests for MultiRepoExecutionResult dataclass."""

    def test_all_errors(self, tmp_path: Path) -> None:
        """Test aggregating errors across repos."""
        result = MultiRepoExecutionResult(
            parent_spec_ref="specs/test.md",
            overall_status=RunStatus.FAILED,
            repo_results=[
                RepoExecutionResult(
                    aip_id="AIP-001",
                    repo_name="repo1",
                    repo_path=tmp_path,
                    status=RunStatus.FAILED,
                    errors=["Error 1"],
                ),
                RepoExecutionResult(
                    aip_id="AIP-002",
                    repo_name="repo2",
                    repo_path=tmp_path,
                    status=RunStatus.FAILED,
                    errors=["Error 2", "Error 3"],
                ),
            ],
        )

        assert len(result.all_errors) == 3
        assert "[repo1] Error 1" in result.all_errors
        assert "[repo2] Error 2" in result.all_errors
        assert "[repo2] Error 3" in result.all_errors

    def test_all_steps_executed(self, tmp_path: Path) -> None:
        """Test aggregating steps across repos."""
        result = MultiRepoExecutionResult(
            parent_spec_ref="specs/test.md",
            overall_status=RunStatus.COMPLETED,
            repo_results=[
                RepoExecutionResult(
                    aip_id="AIP-001",
                    repo_name="repo1",
                    repo_path=tmp_path,
                    status=RunStatus.COMPLETED,
                    steps_executed=[1, 2],
                ),
                RepoExecutionResult(
                    aip_id="AIP-002",
                    repo_name="repo2",
                    repo_path=tmp_path,
                    status=RunStatus.COMPLETED,
                    steps_executed=[2, 3],
                ),
            ],
        )

        # Should be union of all steps, sorted
        assert result.all_steps_executed == [1, 2, 3]

    def test_to_provenance(self, tmp_path: Path) -> None:
        """Test converting to provenance snapshot."""
        now = datetime.now()
        result = MultiRepoExecutionResult(
            parent_spec_ref="specs/test.md",
            overall_status=RunStatus.COMPLETED,
            repo_results=[
                RepoExecutionResult(
                    aip_id="AIP-001",
                    repo_name="repo1",
                    repo_path=tmp_path,
                    status=RunStatus.COMPLETED,
                    steps_executed=[1, 2],
                ),
                RepoExecutionResult(
                    aip_id="AIP-002",
                    repo_name="repo2",
                    repo_path=tmp_path,
                    status=RunStatus.COMPLETED,
                    steps_executed=[3],
                ),
            ],
            started_at=now,
            completed_at=now,
        )

        provenance = result.to_provenance("run-123")

        assert provenance.run_id == "run-123"
        assert provenance.aip_ref == "specs/test.md"
        assert provenance.repo == "repo1,repo2"
        assert provenance.status == RunStatus.COMPLETED
        assert provenance.steps_executed == [1, 2, 3]

    def test_to_dict(self, tmp_path: Path) -> None:
        """Test serialization to dictionary."""
        result = MultiRepoExecutionResult(
            parent_spec_ref="specs/test.md",
            overall_status=RunStatus.COMPLETED,
            repo_results=[],
        )

        data = result.to_dict()

        assert data["parent_spec_ref"] == "specs/test.md"
        assert data["overall_status"] == "COMPLETED"


class TestMultiRepoCoordinator:
    """Tests for MultiRepoCoordinator."""

    def _make_split_aip(self, tmp_path: Path, name: str) -> SplitAIP:
        """Create a test SplitAIP."""
        return SplitAIP(
            aip_id=f"AIP-{name}",
            target=RepoTarget(name=name, path=tmp_path),
            aip_data={},
            parent_spec_ref="specs/test.md",
        )

    def test_execute_all_success(self, tmp_path: Path) -> None:
        """Test executing all AIPs successfully."""
        coordinator = MultiRepoCoordinator("specs/test.md")
        split_aips = [
            self._make_split_aip(tmp_path, "repo1"),
            self._make_split_aip(tmp_path, "repo2"),
        ]

        def executor(aip: SplitAIP) -> RepoExecutionResult:
            return RepoExecutionResult(
                aip_id=aip.aip_id,
                repo_name=aip.target.name,
                repo_path=aip.target.path,
                status=RunStatus.COMPLETED,
                steps_executed=[1],
            )

        result = coordinator.execute_all(split_aips, executor)

        assert result.overall_status == RunStatus.COMPLETED
        assert len(result.repo_results) == 2

    def test_execute_all_stops_on_failure(self, tmp_path: Path) -> None:
        """Test that execution stops on first failure."""
        coordinator = MultiRepoCoordinator("specs/test.md")
        split_aips = [
            self._make_split_aip(tmp_path, "repo1"),
            self._make_split_aip(tmp_path, "repo2"),
            self._make_split_aip(tmp_path, "repo3"),
        ]

        call_count = 0

        def executor(aip: SplitAIP) -> RepoExecutionResult:
            nonlocal call_count
            call_count += 1
            if aip.target.name == "repo2":
                return RepoExecutionResult(
                    aip_id=aip.aip_id,
                    repo_name=aip.target.name,
                    repo_path=aip.target.path,
                    status=RunStatus.FAILED,
                    errors=["Failed!"],
                )
            return RepoExecutionResult(
                aip_id=aip.aip_id,
                repo_name=aip.target.name,
                repo_path=aip.target.path,
                status=RunStatus.COMPLETED,
            )

        result = coordinator.execute_all(split_aips, executor, stop_on_failure=True)

        assert result.overall_status == RunStatus.FAILED
        assert call_count == 2  # Should stop after repo2 failure
        assert len(result.repo_results) == 2

    def test_execute_all_continues_on_failure(self, tmp_path: Path) -> None:
        """Test that execution continues when stop_on_failure=False."""
        coordinator = MultiRepoCoordinator("specs/test.md")
        split_aips = [
            self._make_split_aip(tmp_path, "repo1"),
            self._make_split_aip(tmp_path, "repo2"),
            self._make_split_aip(tmp_path, "repo3"),
        ]

        def executor(aip: SplitAIP) -> RepoExecutionResult:
            if aip.target.name == "repo2":
                return RepoExecutionResult(
                    aip_id=aip.aip_id,
                    repo_name=aip.target.name,
                    repo_path=aip.target.path,
                    status=RunStatus.FAILED,
                    errors=["Failed!"],
                )
            return RepoExecutionResult(
                aip_id=aip.aip_id,
                repo_name=aip.target.name,
                repo_path=aip.target.path,
                status=RunStatus.COMPLETED,
            )

        result = coordinator.execute_all(split_aips, executor, stop_on_failure=False)

        assert result.overall_status == RunStatus.FAILED
        assert len(result.repo_results) == 3  # All three ran

    def test_execute_all_handles_exceptions(self, tmp_path: Path) -> None:
        """Test that executor exceptions are captured."""
        coordinator = MultiRepoCoordinator("specs/test.md")
        split_aips = [self._make_split_aip(tmp_path, "repo1")]

        def executor(aip: SplitAIP) -> RepoExecutionResult:
            raise RuntimeError("Unexpected error!")

        result = coordinator.execute_all(split_aips, executor)

        assert result.overall_status == RunStatus.FAILED
        assert len(result.repo_results) == 1
        assert "Unexpected error!" in result.repo_results[0].errors[0]

    def test_record_result_manually(self, tmp_path: Path) -> None:
        """Test manually recording results."""
        coordinator = MultiRepoCoordinator("specs/test.md")

        coordinator.record_result(
            RepoExecutionResult(
                aip_id="AIP-001",
                repo_name="repo1",
                repo_path=tmp_path,
                status=RunStatus.COMPLETED,
            )
        )
        coordinator.record_result(
            RepoExecutionResult(
                aip_id="AIP-002",
                repo_name="repo2",
                repo_path=tmp_path,
                status=RunStatus.COMPLETED,
            )
        )

        result = coordinator.finalize()

        assert result.overall_status == RunStatus.COMPLETED
        assert len(result.repo_results) == 2

    def test_empty_results(self) -> None:
        """Test handling empty results."""
        coordinator = MultiRepoCoordinator("specs/test.md")
        result = coordinator.finalize()

        assert result.overall_status == RunStatus.CANCELLED
        assert len(result.repo_results) == 0
