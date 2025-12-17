"""Tests for Claude Code CLI Adapter."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spec.executor.adapters import (
    AgentAdapter,
    ClaudeAdapter,
    ProtocolError,
    ToolNotFoundError,
    get_adapter,
    list_adapters,
)


class TestClaudeAdapterProperties:
    """Tests for ClaudeAdapter properties."""

    def test_name_property(self) -> None:
        """Test name property returns 'claude'."""
        adapter = ClaudeAdapter()
        assert adapter.name == "claude"

    def test_adapter_is_agent_adapter(self) -> None:
        """Test ClaudeAdapter is an AgentAdapter."""
        adapter = ClaudeAdapter()
        assert isinstance(adapter, AgentAdapter)


class TestClaudeAdapterVerify:
    """Tests for ClaudeAdapter.verify()."""

    def test_verify_claude_exists(self) -> None:
        """Test verify succeeds when claude CLI exists."""
        adapter = ClaudeAdapter()

        with patch("shutil.which") as mock_which:
            # claude exists, script exists
            mock_which.side_effect = lambda x: f"/usr/bin/{x}" if x in ("claude", "script") else None
            adapter.verify()

            assert adapter._verified is True
            assert adapter._script_available is True

    def test_verify_claude_missing(self) -> None:
        """Test verify raises ToolNotFoundError when claude missing."""
        adapter = ClaudeAdapter()

        with patch("shutil.which", return_value=None):
            with pytest.raises(ToolNotFoundError) as exc:
                adapter.verify()

            assert exc.value.tool_name == "claude"

    def test_verify_script_fallback(self) -> None:
        """Test verify succeeds with PTY fallback when script missing."""
        adapter = ClaudeAdapter()

        def mock_which(cmd: str) -> str | None:
            if cmd == "claude":
                return "/usr/bin/claude"
            return None  # script not found

        with patch("shutil.which", side_effect=mock_which):
            adapter.verify()

            assert adapter._verified is True
            assert adapter._script_available is False


class TestClaudeAdapterModeSelection:
    """Tests for mode selection from contract.yaml."""

    def test_mode_parsing_default(self) -> None:
        """Test default mode is 'interactive' when no adapter section."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir)

            # No contract.yaml at all
            mode = adapter._get_mode(input_dir)
            assert mode == "interactive"

    def test_mode_parsing_no_adapter_section(self) -> None:
        """Test default mode when contract.yaml exists but no adapter section."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir)
            (input_dir / "contract.yaml").write_text("aip_id: test\n")

            mode = adapter._get_mode(input_dir)
            assert mode == "interactive"

    def test_mode_parsing_interactive_explicit(self) -> None:
        """Test explicit interactive mode."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir)
            (input_dir / "contract.yaml").write_text(
                "adapter:\n  name: claude\n  mode: interactive\n"
            )

            mode = adapter._get_mode(input_dir)
            assert mode == "interactive"

    def test_mode_parsing_oneshot(self) -> None:
        """Test oneshot mode selection."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir)
            (input_dir / "contract.yaml").write_text(
                "adapter:\n  name: claude\n  mode: oneshot\n"
            )

            mode = adapter._get_mode(input_dir)
            assert mode == "oneshot"

    def test_mode_parsing_invalid_yaml(self) -> None:
        """Test fallback to interactive on invalid YAML."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir)
            (input_dir / "contract.yaml").write_text("invalid: yaml: content: [")

            mode = adapter._get_mode(input_dir)
            assert mode == "interactive"


class TestClaudeAdapterAgentJsonValidation:
    """Tests for agent.json validation."""

    def test_validate_agent_json_valid(self) -> None:
        """Test valid agent.json passes validation."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            agent_json_path = Path(tmpdir) / "agent.json"
            agent_json_path.write_text(
                json.dumps(
                    {
                        "completion_status": "success",
                        "confidence": 0.9,
                        "files_modified": ["file.py"],
                        "commands_executed": ["ruff check ."],
                    }
                )
            )

            # Should not raise
            adapter._validate_agent_json(agent_json_path)

    def test_validate_agent_json_missing_keys(self) -> None:
        """Test agent.json missing required keys raises ProtocolError."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            agent_json_path = Path(tmpdir) / "agent.json"
            agent_json_path.write_text(
                json.dumps(
                    {
                        "completion_status": "success",
                        # Missing: confidence, files_modified, commands_executed
                    }
                )
            )

            with pytest.raises(ProtocolError) as exc:
                adapter._validate_agent_json(agent_json_path)

            assert exc.value.failure_category == "invalid_output"
            assert "missing required fields" in str(exc.value)

    def test_validate_agent_json_not_found(self) -> None:
        """Test agent.json not found raises ProtocolError."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            agent_json_path = Path(tmpdir) / "agent.json"

            with pytest.raises(ProtocolError) as exc:
                adapter._validate_agent_json(agent_json_path)

            assert exc.value.failure_category == "missing_output"

    def test_validate_agent_json_invalid_json(self) -> None:
        """Test invalid JSON raises ProtocolError."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            agent_json_path = Path(tmpdir) / "agent.json"
            agent_json_path.write_text("not valid json")

            with pytest.raises(ProtocolError) as exc:
                adapter._validate_agent_json(agent_json_path)

            assert exc.value.failure_category == "invalid_output"


class TestClaudeAdapterBackfill:
    """Tests for artifact backfill functionality."""

    def test_backfill_patch_diff(self) -> None:
        """Test patch.diff backfill from git diff."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()
            repo_root = Path(tmpdir)

            # patch.diff doesn't exist
            assert not (output_dir / "patch.diff").exists()

            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = "diff --git a/file.py b/file.py\n"
                mock_run.return_value = mock_result

                warnings = adapter._backfill_artifacts(output_dir, repo_root)

            assert (output_dir / "patch.diff").exists()
            assert "patch.diff backfilled from git diff" in warnings

    def test_backfill_cmdlog(self) -> None:
        """Test cmdlog.txt backfill with stub."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()
            repo_root = Path(tmpdir)

            # Create patch.diff so it doesn't get backfilled
            (output_dir / "patch.diff").write_text("")

            # Create agent.json so it doesn't get backfilled
            (output_dir / "agent.json").write_text(
                json.dumps(
                    {
                        "completion_status": "success",
                        "confidence": 0.9,
                        "files_modified": [],
                        "commands_executed": [],
                    }
                )
            )

            # cmdlog.txt doesn't exist
            assert not (output_dir / "cmdlog.txt").exists()

            warnings = adapter._backfill_artifacts(output_dir, repo_root)

            assert (output_dir / "cmdlog.txt").exists()
            assert "cmdlog.txt backfilled with stub" in warnings

    def test_backfill_agent_json(self) -> None:
        """Test agent.json backfill with partial status."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()
            repo_root = Path(tmpdir)

            # Create other artifacts
            (output_dir / "patch.diff").write_text("")
            (output_dir / "cmdlog.txt").write_text("")

            # agent.json doesn't exist
            assert not (output_dir / "agent.json").exists()

            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = "file1.py\nfile2.py\n"
                mock_run.return_value = mock_result

                warnings = adapter._backfill_artifacts(output_dir, repo_root)

            assert (output_dir / "agent.json").exists()
            assert "agent.json backfilled with partial status" in warnings

            # Verify content
            with open(output_dir / "agent.json") as f:
                agent = json.load(f)

            assert agent["completion_status"] == "partial"
            assert agent["confidence"] == 0.0
            assert "file1.py" in agent["files_modified"]
            assert "Backfilled" in agent["notes"]

    def test_no_backfill_when_artifacts_exist(self) -> None:
        """Test no backfill when all artifacts already exist."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()
            repo_root = Path(tmpdir)

            # Create all artifacts
            (output_dir / "patch.diff").write_text("existing diff")
            (output_dir / "cmdlog.txt").write_text("existing log")
            (output_dir / "agent.json").write_text(
                json.dumps(
                    {
                        "completion_status": "success",
                        "confidence": 0.9,
                        "files_modified": [],
                        "commands_executed": [],
                    }
                )
            )

            warnings = adapter._backfill_artifacts(output_dir, repo_root)

            assert len(warnings) == 0
            # Original content preserved
            assert (output_dir / "patch.diff").read_text() == "existing diff"


class TestClaudeAdapterRepoState:
    """Tests for repo state capture."""

    def test_capture_repo_state(self) -> None:
        """Test repo state capture returns commit and status."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch("subprocess.run") as mock_run:
                def mock_run_side_effect(*args, **kwargs):
                    cmd = args[0]
                    result = MagicMock()
                    result.returncode = 0
                    if "rev-parse" in cmd:
                        result.stdout = "abc123def456\n"
                    elif "status" in cmd:
                        result.stdout = "M file.py\n"
                    return result

                mock_run.side_effect = mock_run_side_effect

                state = adapter._capture_repo_state(repo_root)

            assert state["commit"] == "abc123def456"
            assert state["status"] == "M file.py"

    def test_capture_repo_state_handles_errors(self) -> None:
        """Test repo state capture handles subprocess errors gracefully."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.CalledProcessError(1, "git")

                state = adapter._capture_repo_state(repo_root)

            assert state["commit"] == "unknown"
            assert state["status"] == "unknown"


class TestClaudeAdapterExecute:
    """Tests for ClaudeAdapter.execute()."""

    def test_execute_missing_prompt(self) -> None:
        """Test execute raises if prompt.md missing."""
        adapter = ClaudeAdapter()
        adapter._verified = True
        adapter._script_available = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            input_dir.mkdir()
            output_dir = Path(tmpdir) / "output"

            # No prompt.md
            with pytest.raises(ProtocolError) as exc:
                adapter.execute(input_dir, output_dir, Path(tmpdir))

            assert exc.value.failure_category == "missing_input"
            assert "prompt.md" in str(exc.value)

    def test_execute_oneshot_timeout(self) -> None:
        """Test oneshot mode enforces hard timeout."""
        adapter = ClaudeAdapter()
        adapter._verified = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            input_dir.mkdir()
            output_dir = Path(tmpdir) / "output"

            # Create prompt and contract for oneshot mode
            (input_dir / "prompt.md").write_text("Test prompt")
            (input_dir / "contract.yaml").write_text(
                "adapter:\n  name: claude\n  mode: oneshot\n"
            )

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("claude", 600)

                with pytest.raises(ProtocolError) as exc:
                    adapter.execute(input_dir, output_dir, Path(tmpdir))

                assert exc.value.failure_category == "timeout"

    def test_execute_oneshot_error(self) -> None:
        """Test oneshot mode handles Claude non-zero exit."""
        adapter = ClaudeAdapter()
        adapter._verified = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            input_dir.mkdir()
            output_dir = Path(tmpdir) / "output"

            (input_dir / "prompt.md").write_text("Test prompt")
            (input_dir / "contract.yaml").write_text(
                "adapter:\n  name: claude\n  mode: oneshot\n"
            )

            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "Claude error"

            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(ProtocolError) as exc:
                    adapter.execute(input_dir, output_dir, Path(tmpdir))

                assert exc.value.failure_category == "claude_error"

    def test_execute_oneshot_success(self) -> None:
        """Test successful oneshot execution."""
        adapter = ClaudeAdapter()
        adapter._verified = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            input_dir.mkdir()
            output_dir = Path(tmpdir) / "output"

            (input_dir / "prompt.md").write_text("Test prompt")
            (input_dir / "contract.yaml").write_text(
                "adapter:\n  name: claude\n  mode: oneshot\n"
            )

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(
                {
                    "patch_diff": "--- a/file.py\n+++ b/file.py\n-old\n+new",
                    "completion_status": "success",
                    "confidence": 0.9,
                    "files_modified": ["file.py"],
                    "commands_executed": ["ruff check ."],
                }
            )
            mock_result.stderr = ""

            with patch("subprocess.run", return_value=mock_result):
                adapter.execute(input_dir, output_dir, Path(tmpdir))

            # Check artifacts were created
            assert (output_dir / "patch.diff").exists()
            assert (output_dir / "agent.json").exists()
            assert (output_dir / "cmdlog.txt").exists()

            # Check content
            assert "file.py" in (output_dir / "patch.diff").read_text()

            with open(output_dir / "agent.json") as f:
                agent = json.load(f)
            assert agent["completion_status"] == "success"
            assert agent["confidence"] == 0.9


class TestClaudeAdapterRegistry:
    """Tests for Claude adapter in registry."""

    def test_get_claude_adapter(self) -> None:
        """Test getting claude adapter by name."""
        adapter = get_adapter("claude")
        assert isinstance(adapter, ClaudeAdapter)
        assert adapter.name == "claude"

    def test_get_adapter_case_insensitive(self) -> None:
        """Test adapter lookup is case-insensitive."""
        adapter = get_adapter("CLAUDE")
        assert isinstance(adapter, ClaudeAdapter)

    def test_list_adapters_includes_claude(self) -> None:
        """Test listing adapters includes claude."""
        adapters = list_adapters()
        assert "claude" in adapters
        assert "codex" not in adapters  # Codex has been removed
