"""Tests for governor writer module."""

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from spec.governor.errors import ErrorContext, ErrorRecord, ErrorType
from spec.governor.locator import GovernorPaths
from spec.governor.provenance import ProvenanceSnapshot, RunStatus
from spec.governor.writer import GovernorWriter


@pytest.fixture
def mock_paths(tmp_path: Path) -> GovernorPaths:
    """Create mock governor paths with project structure."""
    governor = tmp_path / "local-governor"
    project = governor / "projects" / "test-project"
    (project / "specs").mkdir(parents=True)
    (project / "aips").mkdir()
    (project / "errors").mkdir()
    (project / "runs").mkdir()
    return GovernorPaths.from_root(governor, "test-project")


class TestGovernorWriter:
    """Tests for GovernorWriter class."""

    def test_write_spec_creates_file(self, mock_paths: GovernorPaths) -> None:
        """Writes spec to governor/specs/."""
        writer = GovernorWriter(mock_paths)
        content = "# Test Spec\n\nContent here."

        path = writer.write_spec("test-feature", content)

        assert path.exists()
        assert path.read_text() == content
        assert path == mock_paths.specs / "test-feature.md"

    def test_write_aip_creates_file(self, mock_paths: GovernorPaths) -> None:
        """Writes AIP to governor/aips/."""
        writer = GovernorWriter(mock_paths)
        aip = {
            "aip_id": "AIP-test-001",
            "title": "Test AIP",
            "plan": [{"step_id": "step-001"}],
        }

        path = writer.write_aip("AIP-test-001", aip)

        assert path.exists()
        loaded = yaml.safe_load(path.read_text())
        assert loaded["aip_id"] == "AIP-test-001"
        assert path == mock_paths.aips / "AIP-test-001.yaml"

    def test_write_error_creates_indexed_file(
        self, mock_paths: GovernorPaths
    ) -> None:
        """Writes error to governor/errors/{repo}/{date}/."""
        writer = GovernorWriter(mock_paths)
        error = ErrorRecord(
            error_id="ERR-2025-12-22-001",
            error_type=ErrorType.FAIL_VERIFY,
            message="Test failed",
            timestamp=datetime(2025, 12, 22, 12, 0, 0),
            repo="test-repo",
            aip_ref="aips/AIP-test-001.yaml",
            step=1,
            context=ErrorContext(command="pytest", exit_code=1),
        )

        path = writer.write_error(error)

        assert path.exists()
        assert "test-repo" in str(path)
        loaded = yaml.safe_load(path.read_text())
        assert loaded["error_id"] == "ERR-2025-12-22-001"
        assert loaded["error_type"] == "FAIL_VERIFY"

    def test_write_provenance_creates_indexed_file(
        self, mock_paths: GovernorPaths
    ) -> None:
        """Writes provenance to governor/runs/{repo}/{date}/."""
        writer = GovernorWriter(mock_paths)
        snapshot = ProvenanceSnapshot(
            run_id="RUN-2025-12-22-001",
            aip_ref="aips/AIP-test-001.yaml",
            repo="test-repo",
            started_at=datetime(2025, 12, 22, 12, 0, 0),
            status=RunStatus.COMPLETED,
            steps_executed=[1, 2, 3],
        )

        path = writer.write_provenance(snapshot)

        assert path.exists()
        assert "test-repo" in str(path)
        loaded = yaml.safe_load(path.read_text())
        assert loaded["run_id"] == "RUN-2025-12-22-001"
        assert loaded["status"] == "COMPLETED"

    def test_atomic_write_creates_parent_dirs(
        self, mock_paths: GovernorPaths
    ) -> None:
        """Write creates parent directories automatically."""
        # Remove the specs dir
        mock_paths.specs.rmdir()
        assert not mock_paths.specs.exists()

        writer = GovernorWriter(mock_paths)
        writer.write_spec("nested/deep/spec", "content")

        assert (mock_paths.specs / "nested/deep/spec.md").exists()

    def test_delete_spec_removes_file(self, mock_paths: GovernorPaths) -> None:
        """delete_spec removes the file."""
        (mock_paths.specs / "to-delete.md").write_text("content")

        writer = GovernorWriter(mock_paths)
        result = writer.delete_spec("to-delete")

        assert result is True
        assert not (mock_paths.specs / "to-delete.md").exists()

    def test_delete_spec_returns_false_if_missing(
        self, mock_paths: GovernorPaths
    ) -> None:
        """delete_spec returns False if file doesn't exist."""
        writer = GovernorWriter(mock_paths)
        result = writer.delete_spec("nonexistent")

        assert result is False

    def test_delete_aip_removes_file(self, mock_paths: GovernorPaths) -> None:
        """delete_aip removes the file."""
        (mock_paths.aips / "AIP-delete.yaml").write_text("aip_id: AIP-delete")

        writer = GovernorWriter(mock_paths)
        result = writer.delete_aip("AIP-delete")

        assert result is True
        assert not (mock_paths.aips / "AIP-delete.yaml").exists()

    def test_overwrite_existing_spec(self, mock_paths: GovernorPaths) -> None:
        """Overwrites existing spec file."""
        spec_path = mock_paths.specs / "overwrite.md"
        spec_path.write_text("original content")

        writer = GovernorWriter(mock_paths)
        writer.write_spec("overwrite", "new content")

        assert spec_path.read_text() == "new content"
