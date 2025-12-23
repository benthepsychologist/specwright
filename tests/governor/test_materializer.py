"""Tests for materializer module."""

from pathlib import Path

import pytest
import yaml

from spec.governor.locator import GovernorPaths
from spec.governor.materializer import (
    MaterializationError,
    Materializer,
    TargetRepoNotFoundError,
)


@pytest.fixture
def mock_paths(tmp_path: Path) -> GovernorPaths:
    """Create mock governor paths with project structure and sample AIP."""
    governor = tmp_path / "local-governor"
    project = governor / "projects" / "test-project"
    (project / "specs").mkdir(parents=True)
    (project / "aips").mkdir()
    (project / "errors").mkdir()
    (project / "runs").mkdir()

    # Create sample AIP
    aip = {
        "aip_id": "AIP-test-001",
        "title": "Test AIP",
        "plan": [{"step_id": "step-001"}],
    }
    (project / "aips" / "AIP-test-001.yaml").write_text(yaml.dump(aip))

    return GovernorPaths.from_root(governor, "test-project")


@pytest.fixture
def mock_repo(tmp_path: Path) -> Path:
    """Create mock repository."""
    repo = tmp_path / "test-repo"
    (repo / ".specwright").mkdir(parents=True)
    (repo / ".specwright.yaml").write_text("version: '0.5'")
    return repo


class TestMaterializer:
    """Tests for Materializer class."""

    def test_materialize_aip_copies_to_tmp(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """AIP is copied to repo's .specwright/tmp/."""
        materializer = Materializer(mock_paths)

        path = materializer.materialize_aip("AIP-test-001", mock_repo)

        assert path.exists()
        assert path.parent.name == "tmp"
        assert ".specwright" in str(path)

        loaded = yaml.safe_load(path.read_text())
        assert loaded["aip_id"] == "AIP-test-001"

    def test_materialize_creates_tmp_directory(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """Creates tmp/ directory if it doesn't exist."""
        materializer = Materializer(mock_paths)

        # Ensure tmp doesn't exist
        tmp_dir = mock_repo / ".specwright" / "tmp"
        assert not tmp_dir.exists()

        materializer.materialize_aip("AIP-test-001", mock_repo)

        assert tmp_dir.exists()
        assert tmp_dir.is_dir()

    def test_materialize_aip_not_found(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """Raises FileNotFoundError when AIP doesn't exist."""
        materializer = Materializer(mock_paths)

        with pytest.raises(FileNotFoundError) as exc_info:
            materializer.materialize_aip("nonexistent", mock_repo)

        assert "nonexistent" in str(exc_info.value)

    def test_materialize_existing_without_force(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """Raises MaterializationError when file exists without force."""
        materializer = Materializer(mock_paths)

        # First materialization
        materializer.materialize_aip("AIP-test-001", mock_repo)

        # Second materialization without force
        with pytest.raises(MaterializationError) as exc_info:
            materializer.materialize_aip("AIP-test-001", mock_repo)

        assert "already exists" in str(exc_info.value)

    def test_materialize_with_force_overwrites(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """Force flag allows overwriting existing file."""
        materializer = Materializer(mock_paths)

        # First materialization
        path1 = materializer.materialize_aip("AIP-test-001", mock_repo)

        # Modify the file
        path1.write_text("modified content")

        # Second materialization with force
        path2 = materializer.materialize_aip(
            "AIP-test-001", mock_repo, force=True
        )

        assert path2.exists()
        loaded = yaml.safe_load(path2.read_text())
        assert loaded["aip_id"] == "AIP-test-001"

    def test_materialize_with_step_dir(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """Creates step artifacts directory."""
        materializer = Materializer(mock_paths)

        aip_path, step_dir = materializer.materialize_aip_with_step_dir(
            "AIP-test-001", mock_repo, step_num=1
        )

        assert aip_path.exists()
        assert step_dir.exists()
        assert step_dir.name == "step-001"

    def test_cleanup_removes_contents(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """cleanup() removes all contents from tmp/."""
        materializer = Materializer(mock_paths)

        # Materialize some files
        materializer.materialize_aip("AIP-test-001", mock_repo)
        materializer.materialize_aip_with_step_dir(
            "AIP-test-001", mock_repo, step_num=1, force=True
        )

        count = materializer.cleanup(mock_repo)

        assert count >= 1
        tmp_dir = mock_repo / ".specwright" / "tmp"
        assert list(tmp_dir.iterdir()) == []

    def test_cleanup_nonexistent_returns_zero(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """cleanup() returns 0 when tmp/ doesn't exist."""
        materializer = Materializer(mock_paths)

        count = materializer.cleanup(mock_repo)

        assert count == 0

    def test_cleanup_step_removes_directory(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """cleanup_step() removes specific step directory."""
        materializer = Materializer(mock_paths)

        # Create step directories
        _, step1 = materializer.materialize_aip_with_step_dir(
            "AIP-test-001", mock_repo, step_num=1
        )
        _, step2 = materializer.materialize_aip_with_step_dir(
            "AIP-test-001", mock_repo, step_num=2, force=True
        )

        result = materializer.cleanup_step(mock_repo, 1)

        assert result is True
        assert not step1.exists()
        assert step2.exists()

    def test_is_materialized_true(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """is_materialized returns True when file exists."""
        materializer = Materializer(mock_paths)
        materializer.materialize_aip("AIP-test-001", mock_repo)

        assert materializer.is_materialized(mock_repo, "AIP-test-001") is True

    def test_is_materialized_false(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """is_materialized returns False when file doesn't exist."""
        materializer = Materializer(mock_paths)

        assert (
            materializer.is_materialized(mock_repo, "nonexistent") is False
        )

    def test_get_step_artifacts(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """get_step_artifacts returns correct paths."""
        materializer = Materializer(mock_paths)

        artifacts = materializer.get_step_artifacts(mock_repo, 1)

        assert "input" in artifacts
        assert "output" in artifacts
        assert "transcript" in artifacts
        assert "gate" in artifacts
        assert artifacts["input"].name == "input.yaml"
        assert "step-001" in str(artifacts["input"])


class TestResolveTargetWorkspaces:
    """Tests for resolve_target_workspaces method."""

    def test_resolve_explicit_path(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """Resolves explicit path from target."""
        materializer = Materializer(mock_paths)
        targets = [{"repo": "test-repo", "path": str(mock_repo)}]

        results = materializer.resolve_target_workspaces(targets)

        assert len(results) == 1
        assert results[0][0] == "test-repo"
        assert results[0][1] == mock_repo

    def test_resolve_from_registry(
        self, mock_paths: GovernorPaths, mock_repo: Path
    ) -> None:
        """Resolves from registry when path not explicit."""
        materializer = Materializer(mock_paths)
        targets = [{"repo": "test-repo"}]
        registry = {"test-repo": str(mock_repo)}

        results = materializer.resolve_target_workspaces(targets, registry)

        assert len(results) == 1
        assert results[0][0] == "test-repo"
        assert results[0][1] == mock_repo

    def test_resolve_not_found(
        self, mock_paths: GovernorPaths, tmp_path: Path
    ) -> None:
        """Raises TargetRepoNotFoundError when not found."""
        materializer = Materializer(mock_paths)
        targets = [{"repo": "nonexistent"}]

        with pytest.raises(TargetRepoNotFoundError) as exc_info:
            materializer.resolve_target_workspaces(targets)

        assert exc_info.value.repo == "nonexistent"
