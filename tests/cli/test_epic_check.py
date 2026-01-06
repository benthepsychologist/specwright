"""Tests for epic check command."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from spec.cli.spec import app


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_governor(tmp_path: Path):
    """Create a temporary governor directory with an epic and check."""
    epics_dir = tmp_path / "epics"
    epics_dir.mkdir()

    # Create a valid epic with a check
    epic_dir = epics_dir / "test-epic"
    epic_dir.mkdir()
    checks_dir = epic_dir / "checks"
    checks_dir.mkdir()
    (epic_dir / "reports").mkdir()
    (epic_dir / "artifacts" / "snapshots").mkdir(parents=True)
    (epic_dir / "notes.md").write_text("# Test Epic\n")

    # Create a check prompt file
    (checks_dir / "test-check.md").write_text("# Test Check Prompt\nReview the code.\n")

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

checks:
  - id: CHECK-test-001
    name: "Test Check"
    scope: epic
    prompt_ref: checks/test-check.md

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


class TestEpicCheckHelp:
    """Tests for epic check --help."""

    def test_check_help(self, runner: CliRunner):
        """epic check --help works."""
        result = runner.invoke(app, ["epic", "check", "--help"])
        assert result.exit_code == 0
        assert "LLM" in result.output
        assert "--check" in result.output


class TestEpicCheckExitCode2:
    """Tests for exit code 2 (epic or check not found)."""

    def test_epic_not_found_exits_2(self, runner: CliRunner, temp_governor: Path):
        """Non-existent epic returns exit code 2."""
        result = runner.invoke(app, ["epic", "check", "nonexistent-epic"])
        assert result.exit_code == 2
        assert "not found" in result.output.lower()

    def test_check_not_found_exits_2(self, runner: CliRunner, temp_governor: Path):
        """Non-existent check returns exit code 2."""
        # Mock LLM config so we get past the config check
        with patch("spec.llm.config.require_llm_enabled") as mock_config:
            from spec.llm.config import LLMConfig
            mock_config.return_value = LLMConfig(enabled=True, timeout_s=120)

            result = runner.invoke(
                app,
                ["epic", "check", "test-epic", "--check", "NONEXISTENT-CHECK"],
            )
            assert result.exit_code == 2
            assert "not found" in result.output.lower()


class TestEpicCheckExitCode4:
    """Tests for exit code 4 (LLM config error)."""

    def test_llm_not_enabled_exits_4(self, runner: CliRunner, temp_governor: Path):
        """LLM not enabled returns exit code 4."""
        # Clear any LLM config
        config_path = Path("~/.local/local-governor/config.yaml").expanduser()
        if config_path.exists():
            original_content = config_path.read_text()
        else:
            original_content = None

        try:
            # Ensure LLM is disabled by writing empty config
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("llm:\n  enabled: false\n")

            result = runner.invoke(app, ["epic", "check", "test-epic"])
            assert result.exit_code == 4
            assert "not enabled" in result.output.lower() or "llm" in result.output.lower()
        finally:
            if original_content is not None:
                config_path.write_text(original_content)
            elif config_path.exists():
                config_path.unlink()


class TestEpicCheckExitCode5:
    """Tests for exit code 5 (LLM execution error)."""

    def test_llm_execution_error_exits_5(self, runner: CliRunner, temp_governor: Path):
        """LLM execution error returns exit code 5."""
        from spec.llm.client import LLMExecutionError

        with patch("spec.llm.config.require_llm_enabled") as mock_config:
            from spec.llm.config import LLMConfig
            mock_config.return_value = LLMConfig(enabled=True, timeout_s=120)

            # Mock LLMClient to raise execution error
            with patch("spec.llm.client.LLMClient") as mock_client_class:
                mock_client = mock_client_class.return_value
                mock_client.prompt.side_effect = LLMExecutionError("Model not found")

                result = runner.invoke(
                    app,
                    ["epic", "check", "test-epic", "--check", "CHECK-test-001"],
                )
                assert result.exit_code == 5


class TestEpicCheckNoChecks:
    """Tests for epics with no checks."""

    def test_no_checks_defined(self, runner: CliRunner, tmp_path: Path):
        """Epic with no checks exits cleanly."""
        epics_dir = tmp_path / "epics"
        epics_dir.mkdir()

        epic_dir = epics_dir / "empty-epic"
        epic_dir.mkdir()
        (epic_dir / "checks").mkdir()
        (epic_dir / "reports").mkdir()

        epic_yaml = '''version: "0.1"
kind: epic
id: empty-epic
title: "Empty Epic"
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

specs: []
checks: []
'''
        (epic_dir / "epic.yaml").write_text(epic_yaml)

        old_env = os.environ.get("SPECWRIGHT_GOVERNOR_ROOT")
        os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = str(tmp_path)

        try:
            with patch("spec.llm.config.require_llm_enabled") as mock_config:
                from spec.llm.config import LLMConfig
                mock_config.return_value = LLMConfig(enabled=True, timeout_s=120)

                result = runner.invoke(app, ["epic", "check", "empty-epic"])
                assert result.exit_code == 0
                assert "no checks" in result.output.lower()
        finally:
            if old_env:
                os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = old_env
            else:
                del os.environ["SPECWRIGHT_GOVERNOR_ROOT"]
