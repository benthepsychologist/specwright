"""Tests for AIP v3 compiler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spec.aip.compiler import (
    CompileError,
    SpecNotFoundError,
    compile_from_aip_file,
    compile_from_epic,
)
from spec.aip.models import WorkspaceMode


@pytest.fixture
def mock_epic():
    """Create a mock epic for testing."""
    epic = MagicMock()
    epic.id = "test-epic"
    epic.owner = "tester"
    epic.intent = MagicMock()
    epic.intent.goal = "Test goal for the epic"

    # Mock target
    target = MagicMock()
    target.id = "specwright"
    target.repo_path = "/workspace/test"
    target.default_branch = "main"

    # Mock spec
    spec = MagicMock()
    spec.id = "test-spec"
    spec.repo = "specwright"
    spec.branch = "feat/test"
    spec.expectations = ["Expectation 1", "Expectation 2"]
    spec.constraints = ["Constraint 1"]
    spec.checks = ["CHK-001"]

    epic.targets = [target]
    epic.specs = [spec]
    epic.get_spec.return_value = spec
    epic.get_target.return_value = target

    return epic


class TestCompileFromEpic:
    """Tests for compile_from_epic function."""

    @patch("spec.aip.compiler.load_epic")
    def test_compile_creates_aip(self, mock_load_epic, mock_epic):
        """Test that compile creates a valid AIP."""
        mock_load_epic.return_value = mock_epic

        aip = compile_from_epic("test-epic", "test-spec")

        assert aip.version == "3.0"
        assert aip.kind == "context-packet"
        assert aip.metadata.epic_id == "test-epic"
        assert aip.metadata.spec_id == "test-spec"
        assert aip.metadata.owner == "tester"
        assert aip.workspace.mode == WorkspaceMode.SINGLE_REPO
        assert aip.workspace.repo_path == "/workspace/test"
        assert aip.workspace.branch == "feat/test"
        assert aip.workspace.base_branch == "main"
        assert aip.goal == "Test goal for the epic"
        assert aip.expectations == ["Expectation 1", "Expectation 2"]
        assert aip.constraints == ["Constraint 1"]
        assert aip.checks == ["CHK-001"]

    @patch("spec.aip.compiler.load_epic")
    def test_compile_spec_not_found(self, mock_load_epic, mock_epic):
        """Test that compile raises SpecNotFoundError for missing spec."""
        mock_epic.get_spec.return_value = None
        mock_load_epic.return_value = mock_epic

        with pytest.raises(SpecNotFoundError) as exc_info:
            compile_from_epic("test-epic", "nonexistent-spec")

        assert "nonexistent-spec" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()

    @patch("spec.aip.compiler.load_epic")
    def test_compile_target_not_found(self, mock_load_epic, mock_epic):
        """Test that compile raises CompileError for missing target."""
        mock_epic.get_target.return_value = None
        mock_load_epic.return_value = mock_epic

        with pytest.raises(CompileError) as exc_info:
            compile_from_epic("test-epic", "test-spec")

        assert "Target" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()


class TestCompileFromAipFile:
    """Tests for compile_from_aip_file function."""

    def test_load_nonexistent_file(self):
        """Test that loading a nonexistent file raises CompileError."""
        with pytest.raises(CompileError) as exc_info:
            compile_from_aip_file(Path("/nonexistent/path/aip.yaml"))

        assert "not found" in str(exc_info.value).lower()

    def test_load_valid_aip_file(self, tmp_path):
        """Test loading a valid AIP file."""
        aip_content = """
version: "3.0"
kind: context-packet
metadata:
  epic_id: test-epic
  spec_id: test-spec
  owner: tester
  created: "2026-01-01T00:00:00+00:00"
workspace:
  mode: single-repo
  repo_path: /workspace/test
  branch: feat/test
  base_branch: main
goal: Test goal
"""
        aip_file = tmp_path / "aip.yaml"
        aip_file.write_text(aip_content)

        aip = compile_from_aip_file(aip_file)

        assert aip.metadata.epic_id == "test-epic"
        assert aip.goal == "Test goal"
