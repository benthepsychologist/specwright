"""Tests for epic CLI commands."""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from spec.cli.spec import app


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_governor(tmp_path: Path):
    """Create a temporary governor directory with an epic."""
    epics_dir = tmp_path / "epics"
    epics_dir.mkdir()

    # Create a valid epic
    epic_dir = epics_dir / "test-epic"
    epic_dir.mkdir()
    (epic_dir / "checks").mkdir()
    (epic_dir / "reports").mkdir()
    (epic_dir / "artifacts" / "snapshots").mkdir(parents=True)
    (epic_dir / "notes.md").write_text("# Test Epic\n")

    epic_yaml = '''version: "0.1"
kind: epic
id: test-epic
title: "Test Epic"
owner: testuser
created: 2025-12-26T00:00:00Z
updated: 2025-12-26T00:00:00Z

intent:
  goal: "Test the epic system"
  narrative: "A test narrative."

targets:
  - id: myrepo
    repo_path: /workspace/myrepo
    default_branch: main

specs:
  - id: spec-001
    repo: myrepo
    branch: feat/test
    path: specs/test.md
    status: active

state:
  status: active
  current_spec: spec-001
  history:
    - id: EVT-0001
      at: 2025-12-26T00:00:00Z
      event: epic.created
      actor: human
'''
    (epic_dir / "epic.yaml").write_text(epic_yaml)

    old_env = os.environ.get("SPECWRIGHT_GOVERNOR_ROOT")
    os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = str(tmp_path)

    yield tmp_path

    if old_env:
        os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = old_env
    else:
        del os.environ["SPECWRIGHT_GOVERNOR_ROOT"]


class TestEpicHelp:
    """Tests for --help on epic commands."""

    def test_epic_help(self, runner: CliRunner):
        """epic --help works."""
        result = runner.invoke(app, ["epic", "--help"])
        assert result.exit_code == 0
        assert "Epic management commands" in result.output

    def test_epic_authoring_commands_removed(self, runner: CliRunner):
        """Creation/authoring subcommands are gone (t013-02).

        specwright runs + validates + records; it no longer creates or authors
        epics/specs. create/add-target/add-spec/set-current must not exist.
        """
        for cmd in ("create", "add-target", "add-spec", "set-current"):
            result = runner.invoke(app, ["epic", cmd, "--help"])
            assert result.exit_code != 0, f"epic {cmd} should not exist"

        help_result = runner.invoke(app, ["epic", "--help"])
        out = help_result.output.lower()
        assert "create" not in out
        assert "add-target" not in out
        assert "add-spec" not in out
        assert "set-current" not in out

    def test_epic_mark_done_help(self, runner: CliRunner):
        """epic mark-done --help works."""
        result = runner.invoke(app, ["epic", "mark-done", "--help"])
        assert result.exit_code == 0
        assert "--note" in result.output

    def test_epic_status_help(self, runner: CliRunner):
        """epic status --help works."""
        result = runner.invoke(app, ["epic", "status", "--help"])
        assert result.exit_code == 0
        assert "DAG visualization" in result.output

    def test_epic_list_help(self, runner: CliRunner):
        """epic list --help works."""
        result = runner.invoke(app, ["epic", "list", "--help"])
        assert result.exit_code == 0

    def test_epic_validate_help(self, runner: CliRunner):
        """epic validate --help works."""
        result = runner.invoke(app, ["epic", "validate", "--help"])
        assert result.exit_code == 0
        assert "Validate" in result.output

    def test_epic_check_help(self, runner: CliRunner):
        """epic check --help works."""
        result = runner.invoke(app, ["epic", "check", "--help"])
        assert result.exit_code == 0
        assert "LLM" in result.output


class TestEpicStatus:
    """Tests for epic status command."""

    def test_status_shows_title(self, runner: CliRunner, temp_governor: Path):
        """Status shows epic title."""
        result = runner.invoke(app, ["epic", "status", "test-epic"])
        assert result.exit_code == 0
        assert "Test Epic" in result.output

    def test_status_shows_specs(self, runner: CliRunner, temp_governor: Path):
        """Status shows specs."""
        result = runner.invoke(app, ["epic", "status", "test-epic"])
        assert result.exit_code == 0
        assert "spec-001" in result.output

    def test_status_shows_icons(self, runner: CliRunner, temp_governor: Path):
        """Status shows status icons."""
        result = runner.invoke(app, ["epic", "status", "test-epic"])
        assert result.exit_code == 0
        # Active spec should show arrow
        assert "→" in result.output

    def test_status_not_found(self, runner: CliRunner, temp_governor: Path):
        """Status returns exit 2 for unknown epic."""
        result = runner.invoke(app, ["epic", "status", "nonexistent"])
        assert result.exit_code == 2


class TestEpicValidate:
    """Tests for epic validate command."""

    def test_validate_valid(self, runner: CliRunner, temp_governor: Path):
        """Validate returns 0 for valid epic."""
        result = runner.invoke(app, ["epic", "validate", "test-epic"])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_validate_not_found(self, runner: CliRunner, temp_governor: Path):
        """Validate returns 2 for unknown epic."""
        result = runner.invoke(app, ["epic", "validate", "nonexistent"])
        assert result.exit_code == 2

    def test_validate_invalid_returns_3(self, runner: CliRunner, temp_governor: Path):
        """Validate returns 3 for invalid epic."""
        # Break the epic
        epic_file = temp_governor / "epics" / "test-epic" / "epic.yaml"
        content = epic_file.read_text()
        # Change repo to unknown
        content = content.replace("repo: myrepo", "repo: unknown-repo")
        epic_file.write_text(content)

        result = runner.invoke(app, ["epic", "validate", "test-epic"])
        assert result.exit_code == 3


class TestEpicList:
    """Tests for epic list command."""

    def test_list_shows_epics(self, runner: CliRunner, temp_governor: Path):
        """List shows existing epics."""
        result = runner.invoke(app, ["epic", "list"])
        assert result.exit_code == 0
        assert "test-epic" in result.output

    def test_list_empty(self, runner: CliRunner, tmp_path: Path):
        """List handles empty governor."""
        epics_dir = tmp_path / "epics"
        epics_dir.mkdir(parents=True)

        old_env = os.environ.get("SPECWRIGHT_GOVERNOR_ROOT")
        os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = str(tmp_path)

        try:
            result = runner.invoke(app, ["epic", "list"])
            assert result.exit_code == 0
            assert "No epics found" in result.output
        finally:
            if old_env:
                os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = old_env
            else:
                del os.environ["SPECWRIGHT_GOVERNOR_ROOT"]


class TestEpicCheck:
    """Tests for epic check command."""

    def test_check_returns_4_when_llm_not_enabled(self, runner: CliRunner, temp_governor: Path):
        """Check returns exit 4 when LLM is not enabled."""
        from unittest.mock import patch

        from spec.llm.config import LLMConfig

        # Mock load_llm_config to return disabled config
        with patch("spec.llm.config.load_llm_config", return_value=LLMConfig(enabled=False)):
            result = runner.invoke(app, ["epic", "check", "test-epic"])
            assert result.exit_code == 4
            assert "not enabled" in result.output.lower() or "llm" in result.output.lower()


class TestEpicMarkDone:
    """Tests for epic mark-done command."""

    def test_mark_done(self, runner: CliRunner, temp_governor: Path):
        """mark-done marks spec done."""
        result = runner.invoke(
            app,
            ["epic", "mark-done", "test-epic", "--spec", "spec-001"],
        )
        assert result.exit_code == 0
        assert "Marked spec" in result.output
        assert "done" in result.output.lower()

