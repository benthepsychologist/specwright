"""Tests for spec drafter (LLM-assisted drafting)."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from spec.governance.intent_parser import ParsedIntent
from spec.governance.spec_drafter import (
    DRAFTING_ALLOWLIST,
    SpecDrafter,
    check_claude_available,
)
from spec.governance.spec_scaffolder import SpecScaffolder


class TestSpecDrafter:
    """Tests for SpecDrafter class."""

    @pytest.fixture
    def scaffolder(self, tmp_path):
        """Create a scaffolder for testing."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(
            id="test-spec",
            title="Test Feature",
            goal="Make it work",
            expectations=["First criterion"],
        )
        return SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")

    def test_drafting_allowlist_is_read_only(self):
        """Allowlist contains only read-only tools."""
        # No write tools should be in the allowlist
        write_tools = ["Write", "Edit", "NotebookEdit"]
        for tool in write_tools:
            assert tool not in DRAFTING_ALLOWLIST

        # Should have common read tools
        assert "Read" in DRAFTING_ALLOWLIST
        assert "Glob" in DRAFTING_ALLOWLIST
        assert "Grep" in DRAFTING_ALLOWLIST

    def test_build_prompt_includes_scaffold(self, scaffolder):
        """Build prompt includes the scaffolded spec."""
        drafter = SpecDrafter(scaffolder)
        scaffold = scaffolder.scaffold()
        prompt = drafter._build_prompt(scaffold)

        assert "Scaffolded Spec" in prompt
        assert scaffold in prompt
        assert "test-spec" in prompt
        assert "Test Feature" in prompt

    def test_build_prompt_has_instructions(self, scaffolder):
        """Build prompt includes clear instructions."""
        drafter = SpecDrafter(scaffolder)
        prompt = drafter._build_prompt("")

        assert "explore the codebase" in prompt.lower()
        assert "fill in" in prompt.lower()
        assert "TODO" in prompt
        assert "Output ONLY the spec YAML" in prompt

    @patch("spec.governance.spec_drafter.shutil.which")
    def test_claude_not_found_raises(self, mock_which, scaffolder):
        """Missing claude CLI raises FileNotFoundError."""
        mock_which.return_value = None
        drafter = SpecDrafter(scaffolder)

        with pytest.raises(FileNotFoundError) as exc_info:
            drafter._call_claude_code("test prompt")

        assert "claude CLI not found" in str(exc_info.value)

    @patch("spec.governance.spec_drafter.shutil.which")
    @patch("spec.governance.spec_drafter.subprocess.Popen")
    def test_successful_claude_call(self, mock_popen, mock_which, scaffolder):
        """Successful Claude Code call returns output."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        # Return something that starts with --- to skip extraction
        mock_proc.communicate.return_value = ("---\nid: test\n\nContent here", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        drafter = SpecDrafter(scaffolder)
        result = drafter._call_claude_code("test prompt")

        assert result == "---\nid: test\n\nContent here"
        mock_proc.communicate.assert_called_once()

    @patch("spec.governance.spec_drafter.shutil.which")
    @patch("spec.governance.spec_drafter.subprocess.Popen")
    def test_claude_failure_raises_runtime_error(
        self, mock_popen, mock_which, scaffolder
    ):
        """Claude Code failure raises RuntimeError."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "Error: something went wrong")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        drafter = SpecDrafter(scaffolder)

        with pytest.raises(RuntimeError) as exc_info:
            drafter._call_claude_code("test prompt")

        assert "Claude Code failed" in str(exc_info.value)

    @patch("spec.governance.spec_drafter.shutil.which")
    @patch("spec.governance.spec_drafter.subprocess.Popen")
    @patch("spec.governance.spec_drafter.os.killpg")
    @patch("spec.governance.spec_drafter.os.getpgid")
    def test_timeout_kills_process(
        self, mock_getpgid, mock_killpg, mock_popen, mock_which, scaffolder
    ):
        """Timeout kills the process and raises RuntimeError."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("claude", 1)
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        mock_getpgid.return_value = 12345

        drafter = SpecDrafter(scaffolder, timeout_s=1)

        with pytest.raises(RuntimeError) as exc_info:
            drafter._call_claude_code("test prompt")

        assert "timed out" in str(exc_info.value)
        mock_killpg.assert_called()

    @patch("spec.governance.spec_drafter.shutil.which")
    @patch("spec.governance.spec_drafter.subprocess.Popen")
    def test_draft_calls_scaffold_and_claude(self, mock_popen, mock_which, scaffolder):
        """draft() generates scaffold and calls Claude Code."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        # Return something that starts with --- to skip extraction
        mock_proc.communicate.return_value = ("---\nid: completed\n\n# Completed spec", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        drafter = SpecDrafter(scaffolder)
        result = drafter.draft()

        assert "---\nid: completed" in result

        # Verify command includes key arguments
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "claude" in cmd
        assert "--print" in cmd
        assert "--allowedTools" in cmd

    @patch("spec.governance.spec_drafter.shutil.which")
    @patch("spec.governance.spec_drafter.subprocess.Popen")
    def test_draft_uses_model_parameter(self, mock_popen, mock_which, scaffolder):
        """draft() uses specified model."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("result", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        drafter = SpecDrafter(scaffolder, model="claude-opus-4-20250514")
        drafter.draft()

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-opus-4-20250514"

    @patch("spec.governance.spec_drafter.shutil.which")
    @patch("spec.governance.spec_drafter.subprocess.Popen")
    def test_draft_runs_in_repo_directory(self, mock_popen, mock_which, scaffolder):
        """draft() runs claude in the repo directory."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("result", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        drafter = SpecDrafter(scaffolder)
        drafter.draft()

        call_args = mock_popen.call_args
        assert call_args[1]["cwd"] == scaffolder.repo_path


class TestCheckClaudeAvailable:
    """Tests for check_claude_available helper."""

    @patch("spec.governance.spec_drafter.shutil.which")
    def test_claude_available(self, mock_which):
        """Returns True when claude is in PATH."""
        mock_which.return_value = "/usr/bin/claude"
        assert check_claude_available() is True

    @patch("spec.governance.spec_drafter.shutil.which")
    def test_claude_not_available(self, mock_which):
        """Returns False when claude is not in PATH."""
        mock_which.return_value = None
        assert check_claude_available() is False
