"""Tests for provenance tracking module."""

from datetime import datetime
from pathlib import Path

from spec.governor.provenance import (
    AdapterInfo,
    ExecutionMetrics,
    GitSnapshot,
    GovernanceSnapshot,
    ProvenanceGenerator,
    ProvenanceSnapshot,
    RunStatus,
)


class TestProvenanceSnapshot:
    """Tests for ProvenanceSnapshot dataclass."""

    def test_to_dict_required_fields(self) -> None:
        """Required fields are included in dict."""
        snapshot = ProvenanceSnapshot(
            run_id="RUN-2025-12-22-001",
            aip_ref="aips/AIP-001.yaml",
            repo="test-repo",
            started_at=datetime(2025, 12, 22, 12, 0, 0),
            status=RunStatus.COMPLETED,
        )

        d = snapshot.to_dict()

        assert d["run_id"] == "RUN-2025-12-22-001"
        assert d["aip_ref"] == "aips/AIP-001.yaml"
        assert d["repo"] == "test-repo"
        assert "2025-12-22" in d["started_at"]
        assert d["status"] == "COMPLETED"

    def test_to_dict_optional_fields(self) -> None:
        """Optional fields are included when set."""
        snapshot = ProvenanceSnapshot(
            run_id="RUN-2025-12-22-001",
            aip_ref="aips/AIP-001.yaml",
            repo="test-repo",
            started_at=datetime(2025, 12, 22, 12, 0, 0),
            status=RunStatus.COMPLETED,
            spec_ref="specs/feature.md",
            repo_path="/home/user/projects/test-repo",
            completed_at=datetime(2025, 12, 22, 13, 0, 0),
            executor="testuser",
            steps_executed=[1, 2, 3],
            steps_total=5,
            gates_approved=["G0: Plan", "G1: Code"],
        )

        d = snapshot.to_dict()

        assert d["spec_ref"] == "specs/feature.md"
        assert d["repo_path"] == "/home/user/projects/test-repo"
        assert d["completed_at"] is not None
        assert d["executor"] == "testuser"
        assert d["steps_executed"] == [1, 2, 3]
        assert d["steps_total"] == 5
        assert d["gates_approved"] == ["G0: Plan", "G1: Code"]

    def test_to_dict_with_governance_snapshot(self) -> None:
        """Governance snapshot is included when present."""
        snapshot = ProvenanceSnapshot(
            run_id="RUN-2025-12-22-001",
            aip_ref="aips/AIP-001.yaml",
            repo="test-repo",
            started_at=datetime.now(),
            status=RunStatus.RUNNING,
            governance_snapshot=GovernanceSnapshot(
                tier="B",
                policies_applied=["security", "testing"],
            ),
        )

        d = snapshot.to_dict()

        assert "governance_snapshot" in d
        assert d["governance_snapshot"]["tier"] == "B"
        assert d["governance_snapshot"]["policies_applied"] == [
            "security",
            "testing",
        ]

    def test_to_dict_with_git_snapshot(self) -> None:
        """Git snapshot is included when present."""
        snapshot = ProvenanceSnapshot(
            run_id="RUN-2025-12-22-001",
            aip_ref="aips/AIP-001.yaml",
            repo="test-repo",
            started_at=datetime.now(),
            status=RunStatus.COMPLETED,
            git_snapshot=GitSnapshot(
                start_commit="abc123" * 7 + "ab",  # 40 chars
                branch="feat/test",
                files_changed=["src/foo.py", "src/bar.py"],
            ),
        )

        d = snapshot.to_dict()

        assert "git_snapshot" in d
        assert d["git_snapshot"]["branch"] == "feat/test"
        assert d["git_snapshot"]["files_changed"] == [
            "src/foo.py",
            "src/bar.py",
        ]

    def test_to_dict_with_metrics(self) -> None:
        """Execution metrics are included when present."""
        snapshot = ProvenanceSnapshot(
            run_id="RUN-2025-12-22-001",
            aip_ref="aips/AIP-001.yaml",
            repo="test-repo",
            started_at=datetime.now(),
            status=RunStatus.COMPLETED,
            metrics=ExecutionMetrics(
                duration_seconds=120.5,
                iterations_total=3,
                tests_run=42,
                tests_passed=40,
                tests_failed=2,
                coverage_percent=85.5,
            ),
        )

        d = snapshot.to_dict()

        assert "metrics" in d
        assert d["metrics"]["duration_seconds"] == 120.5
        assert d["metrics"]["tests_run"] == 42
        assert d["metrics"]["coverage_percent"] == 85.5


class TestGovernanceSnapshot:
    """Tests for GovernanceSnapshot dataclass."""

    def test_to_dict_omits_empty(self) -> None:
        """Empty fields are not included."""
        snapshot = GovernanceSnapshot(tier="C")

        d = snapshot.to_dict()

        assert d == {"tier": "C"}
        assert "policies_applied" not in d

    def test_to_dict_includes_all_when_set(self) -> None:
        """All fields included when set."""
        snapshot = GovernanceSnapshot(
            governor_commit="abc123" * 7 + "ab",
            spec_hash="sha256:def456",
            aip_hash="sha256:ghi789",
            tier="A",
            policies_applied=["security"],
            constraints=["no-deploy"],
        )

        d = snapshot.to_dict()

        assert d["governor_commit"] == "abc123" * 7 + "ab"
        assert d["spec_hash"] == "sha256:def456"
        assert d["tier"] == "A"
        assert d["policies_applied"] == ["security"]
        assert d["constraints"] == ["no-deploy"]


class TestExecutionMetrics:
    """Tests for ExecutionMetrics dataclass."""

    def test_to_dict_omits_none(self) -> None:
        """None fields are not included."""
        metrics = ExecutionMetrics(duration_seconds=60.0)

        d = metrics.to_dict()

        assert d == {"duration_seconds": 60.0}
        assert "tests_run" not in d


class TestAdapterInfo:
    """Tests for AdapterInfo dataclass."""

    def test_to_dict_includes_set_fields(self) -> None:
        """Set fields are included."""
        info = AdapterInfo(
            name="claude",
            model="claude-sonnet-4-20250514",
            tokens_used=1500,
        )

        d = info.to_dict()

        assert d["name"] == "claude"
        assert d["model"] == "claude-sonnet-4-20250514"
        assert d["tokens_used"] == 1500


class TestProvenanceGenerator:
    """Tests for ProvenanceGenerator class."""

    def test_generate_id_format(self, tmp_path: Path) -> None:
        """Generated ID follows correct format."""
        generator = ProvenanceGenerator(tmp_path)
        run_id = generator.generate_id()

        assert run_id.startswith("RUN-")
        # Format: RUN-YYYY-MM-DD-NNN (5 parts when split by -)
        parts = run_id.split("-")
        assert len(parts) == 5
        assert parts[0] == "RUN"
        assert len(parts[1]) == 4  # Year
        assert len(parts[2]) == 2  # Month
        assert len(parts[3]) == 2  # Day

    def test_generate_id_sequential(self, tmp_path: Path) -> None:
        """Sequential IDs increment correctly."""
        generator = ProvenanceGenerator(tmp_path)

        # Create some existing run files
        today = datetime.now().strftime("%Y-%m-%d")
        repo_dir = tmp_path / "test-repo" / today
        repo_dir.mkdir(parents=True)
        (repo_dir / f"RUN-{today}-001.yaml").write_text("run_id: 1")
        (repo_dir / f"RUN-{today}-002.yaml").write_text("run_id: 2")

        run_id = generator.generate_id("test-repo")

        assert run_id.endswith("-003")

    def test_create_snapshot_auto_id(self, tmp_path: Path) -> None:
        """create_snapshot generates ID automatically."""
        generator = ProvenanceGenerator(tmp_path)

        snapshot = generator.create_snapshot(
            aip_ref="aips/AIP-001.yaml",
            repo="test-repo",
        )

        assert snapshot.run_id.startswith("RUN-")
        assert snapshot.aip_ref == "aips/AIP-001.yaml"
        assert snapshot.repo == "test-repo"
        assert snapshot.status == RunStatus.RUNNING
        assert snapshot.started_at is not None

    def test_create_snapshot_with_status(self, tmp_path: Path) -> None:
        """create_snapshot accepts custom status."""
        generator = ProvenanceGenerator(tmp_path)

        snapshot = generator.create_snapshot(
            aip_ref="aips/AIP-001.yaml",
            repo="test-repo",
            status=RunStatus.COMPLETED,
        )

        assert snapshot.status == RunStatus.COMPLETED


class TestRunStatus:
    """Tests for RunStatus enum."""

    def test_all_statuses(self) -> None:
        """All expected statuses exist."""
        assert RunStatus.RUNNING.value == "RUNNING"
        assert RunStatus.COMPLETED.value == "COMPLETED"
        assert RunStatus.FAILED.value == "FAILED"
        assert RunStatus.PAUSED.value == "PAUSED"
        assert RunStatus.CANCELLED.value == "CANCELLED"
        assert RunStatus.ROLLED_BACK.value == "ROLLED_BACK"
