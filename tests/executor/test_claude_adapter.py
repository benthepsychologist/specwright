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
        """Test default mode is 'oneshot' when no adapter section."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir)

            # No contract.yaml at all
            mode = adapter._get_mode(input_dir)
            assert mode == "oneshot"

    def test_mode_parsing_no_adapter_section(self) -> None:
        """Test default mode when contract.yaml exists but no adapter section."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir)
            (input_dir / "contract.yaml").write_text("aip_id: test\n")

            mode = adapter._get_mode(input_dir)
            assert mode == "oneshot"

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
        """Test fallback to oneshot on invalid YAML."""
        adapter = ClaudeAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir)
            (input_dir / "contract.yaml").write_text("invalid: yaml: content: [")

            mode = adapter._get_mode(input_dir)
            assert mode == "oneshot"


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
        """Test oneshot mode enforces hard timeout with process group kill."""
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

            # Mock Popen since oneshot now uses Popen for process group kill
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.communicate.side_effect = subprocess.TimeoutExpired("claude", 600)
            mock_proc.wait.return_value = None

            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
                 patch("os.killpg") as mock_killpg, \
                 patch("os.getpgid", return_value=12345):

                with pytest.raises(ProtocolError) as exc:
                    adapter.execute(input_dir, output_dir, Path(tmpdir))

                assert exc.value.failure_category == "timeout"
                # Verify process group kill was attempted
                mock_killpg.assert_called_once()

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

            # Mock Popen since oneshot now uses Popen
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.returncode = 1
            mock_proc.communicate.return_value = ("", "Claude error")

            with patch("subprocess.Popen", return_value=mock_proc):
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

            # Mock Popen since oneshot now uses Popen
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (
                json.dumps(
                    {
                        "patch_diff": "--- a/file.py\n+++ b/file.py\n-old\n+new",
                        "completion_status": "success",
                        "confidence": 0.9,
                        "files_modified": ["file.py"],
                        "commands_executed": ["ruff check ."],
                    }
                ),
                ""
            )

            with patch("subprocess.Popen", return_value=mock_proc):
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


class TestOneshotConstraints:
    """Tests for oneshot mode security constraints."""

    def test_oneshot_uses_allowlist(self) -> None:
        """Test that oneshot mode uses --allowedTools with allowlist."""
        from spec.executor.adapters.claude import ALLOWED_TOOLS_ONESHOT

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

            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (
                json.dumps({
                    "patch_diff": "",
                    "completion_status": "success",
                    "confidence": 1.0,
                    "files_modified": [],
                    "commands_executed": [],
                }),
                ""
            )

            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                adapter.execute(input_dir, output_dir, Path(tmpdir))

                # Verify command includes --allowedTools with allowlist
                call_args = mock_popen.call_args
                cmd = call_args[0][0]  # First positional arg is the command list

                assert "--allowedTools" in cmd
                allowedtools_idx = cmd.index("--allowedTools")
                assert cmd[allowedtools_idx + 1] == ALLOWED_TOOLS_ONESHOT

                # Verify prompt passed via stdin
                call_kwargs = mock_popen.call_args[1]
                assert call_kwargs.get("stdin") == subprocess.PIPE

    def test_oneshot_uses_skip_permissions(self) -> None:
        """Test that oneshot mode uses --dangerously-skip-permissions."""
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

            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (
                json.dumps({
                    "patch_diff": "",
                    "completion_status": "success",
                    "confidence": 1.0,
                    "files_modified": [],
                    "commands_executed": [],
                }),
                ""
            )

            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                adapter.execute(input_dir, output_dir, Path(tmpdir))

                cmd = mock_popen.call_args[0][0]
                assert "--dangerously-skip-permissions" in cmd

    def test_oneshot_creates_process_group(self) -> None:
        """Test that oneshot mode creates a new process group for clean kill."""
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

            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (
                json.dumps({
                    "patch_diff": "",
                    "completion_status": "success",
                    "confidence": 1.0,
                    "files_modified": [],
                    "commands_executed": [],
                }),
                ""
            )

            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                adapter.execute(input_dir, output_dir, Path(tmpdir))

                # Verify start_new_session=True was passed
                call_kwargs = mock_popen.call_args[1]
                assert call_kwargs.get("start_new_session") is True

    def test_allowed_tools_contains_safe_git_commands(self) -> None:
        """Test that ALLOWED_TOOLS_ONESHOT includes safe git read commands."""
        from spec.executor.adapters.claude import ALLOWED_TOOLS_ONESHOT

        # Should include git status, diff, log, show for reporting
        assert "Bash(git status:*)" in ALLOWED_TOOLS_ONESHOT
        assert "Bash(git diff:*)" in ALLOWED_TOOLS_ONESHOT
        assert "Bash(git log:*)" in ALLOWED_TOOLS_ONESHOT
        assert "Bash(git show:*)" in ALLOWED_TOOLS_ONESHOT

        # Should include git branch --list (explicit, not bare)
        assert "Bash(git branch --list:*)" in ALLOWED_TOOLS_ONESHOT

        # Should include safe recovery commands
        assert "Bash(git restore:*)" in ALLOWED_TOOLS_ONESHOT

        # Should NOT include git reset at all (pattern matching risk)
        assert "Bash(git reset" not in ALLOWED_TOOLS_ONESHOT

        # Should NOT include bare git branch (could accept -d, -m flags)
        assert "Bash(git branch)" not in ALLOWED_TOOLS_ONESHOT

    def test_blocked_dangerous_commands(self) -> None:
        """Test that dangerous commands are NOT in allowlist."""
        from spec.executor.adapters.claude import ALLOWED_TOOLS_ONESHOT

        # Git mutation commands - must be blocked
        # These are checked as full Bash() patterns to avoid false positives
        blocked_patterns = [
            "Bash(git commit",
            "Bash(git push",
            "Bash(git checkout",
            "Bash(git merge",
            "Bash(git rebase",
            "Bash(git reset",  # All forms blocked
            "Bash(git branch)",  # Bare branch blocked (could accept -d, -m)
            "Bash(git branch -d",  # Delete branch
            "Bash(git branch -D",  # Force delete branch
            "Bash(git branch -m",  # Rename branch
            "Bash(git branch -M",  # Force rename branch
            # Network commands
            "Bash(curl",
            "Bash(wget",
            "Bash(ssh",
            # Shell escapes
            "Bash(bash",
            "Bash(sh:",  # Note: "sh" would match "git show" substring, use "sh:"
            "Bash(zsh",
        ]

        for pattern in blocked_patterns:
            # Check that pattern doesn't appear in allowlist
            assert pattern not in ALLOWED_TOOLS_ONESHOT, f"Dangerous pattern '{pattern}' found in allowlist"

        # Also verify git branch --list IS allowed (positive check)
        assert "Bash(git branch --list:*)" in ALLOWED_TOOLS_ONESHOT

    def test_allowed_tools_contains_file_ops(self) -> None:
        """Test that ALLOWED_TOOLS_ONESHOT includes file operation tools."""
        from spec.executor.adapters.claude import ALLOWED_TOOLS_ONESHOT

        assert "Read" in ALLOWED_TOOLS_ONESHOT
        assert "Edit" in ALLOWED_TOOLS_ONESHOT
        assert "Write" in ALLOWED_TOOLS_ONESHOT
        assert "Glob" in ALLOWED_TOOLS_ONESHOT
        assert "Grep" in ALLOWED_TOOLS_ONESHOT

    def test_allowed_tools_contains_dev_tools(self) -> None:
        """Test that ALLOWED_TOOLS_ONESHOT includes dev tools."""
        from spec.executor.adapters.claude import ALLOWED_TOOLS_ONESHOT

        assert "Bash(python:*)" in ALLOWED_TOOLS_ONESHOT
        assert "Bash(pytest:*)" in ALLOWED_TOOLS_ONESHOT
        assert "Bash(ruff:*)" in ALLOWED_TOOLS_ONESHOT
        assert "Bash(mypy:*)" in ALLOWED_TOOLS_ONESHOT

    def test_allowlist_has_version(self) -> None:
        """Test that allowlist has a version for auditing."""
        from spec.executor.adapters.claude import ALLOWED_TOOLS_ONESHOT_VERSION

        assert ALLOWED_TOOLS_ONESHOT_VERSION == "v1"

    def test_timeout_kills_process_group_not_just_parent(self) -> None:
        """Test that timeout kills the entire process group, not just parent PID."""
        import signal

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

            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.communicate.side_effect = subprocess.TimeoutExpired("claude", 600)
            mock_proc.wait.return_value = None

            with patch("subprocess.Popen", return_value=mock_proc), \
                 patch("os.killpg") as mock_killpg, \
                 patch("os.getpgid", return_value=99999) as mock_getpgid:

                with pytest.raises(ProtocolError) as exc:
                    adapter.execute(input_dir, output_dir, Path(tmpdir))

                # Verify we got the process group ID, not just the PID
                mock_getpgid.assert_called_once_with(12345)

                # Verify we killed the process GROUP (99999), not just the process (12345)
                mock_killpg.assert_called_once_with(99999, signal.SIGKILL)

                # Verify we reaped the zombie
                mock_proc.wait.assert_called_once()

                assert exc.value.failure_category == "timeout"
                assert "process group killed" in str(exc.value)


class TestInteractiveModeConstraints:
    """Tests for interactive mode behavior (no auto-permissions)."""

    def test_interactive_no_skip_permissions_script(self) -> None:
        """Test that interactive mode (script) does NOT use --dangerously-skip-permissions."""
        adapter = ClaudeAdapter()
        adapter._verified = True
        adapter._script_available = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            input_dir.mkdir()
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            (input_dir / "prompt.md").write_text("Test prompt")
            (input_dir / "contract.yaml").write_text(
                "adapter:\n  name: claude\n  mode: interactive\n"
            )

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="commit123\n")

                try:
                    adapter.execute(input_dir, output_dir, Path(tmpdir))
                except Exception:
                    pass  # We expect validation to fail, that's OK

                # Check all calls to subprocess.run
                for call in mock_run.call_args_list:
                    cmd = call[0][0]
                    if isinstance(cmd, list):
                        cmd_str = " ".join(cmd)
                    else:
                        cmd_str = str(cmd)

                    # The claude command itself should NOT have --dangerously-skip-permissions
                    if "claude" in cmd_str and "script" in cmd_str:
                        assert "--dangerously-skip-permissions" not in cmd_str


class TestModeOverride:
    """Tests for mode override through contract building."""

    def test_build_contract_default_mode_oneshot(self) -> None:
        """Test that build_contract defaults to oneshot mode."""
        from spec.executor.contract import build_contract

        aip = {
            "aip_id": "test-001",
            "plan": [{"step_id": "step-001"}],
        }

        contract = build_contract(aip, 0)
        assert contract.adapter["mode"] == "oneshot"

    def test_build_contract_mode_override_interactive(self) -> None:
        """Test that mode_override overrides to interactive."""
        from spec.executor.contract import build_contract

        aip = {
            "aip_id": "test-001",
            "plan": [{"step_id": "step-001"}],
        }

        contract = build_contract(aip, 0, mode_override="interactive")
        assert contract.adapter["mode"] == "interactive"

    def test_build_contract_mode_override_oneshot_explicit(self) -> None:
        """Test that mode_override can explicitly set oneshot."""
        from spec.executor.contract import build_contract

        aip = {
            "aip_id": "test-001",
            "plan": [{"step_id": "step-001"}],
        }

        contract = build_contract(aip, 0, mode_override="oneshot")
        assert contract.adapter["mode"] == "oneshot"
