"""Tests for Agent Adapters."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spec.executor.adapters import (
    AdapterError,
    AgentAdapter,
    CodexAdapter,
    EscalationRequired,
    ProtocolError,
    ToolNotFoundError,
    get_adapter,
    list_adapters,
)
from spec.executor.adapters.codex import (
    REQUIRED_FLAGS,
    VIOLATION_PREFIX_ESCALATE,
    VIOLATION_PREFIX_HARD,
    _check_single_command,
    check_forbidden_commands,
    is_escalation_violation,
    is_hard_violation,
    parse_commands_from_cmdlog,
)


class TestAdapterErrors:
    """Tests for adapter error classes."""

    def test_tool_not_found_error(self) -> None:
        """Test ToolNotFoundError."""
        err = ToolNotFoundError("codex")
        assert err.tool_name == "codex"
        assert "codex not found" in str(err)

    def test_tool_not_found_error_custom_message(self) -> None:
        """Test ToolNotFoundError with custom message."""
        err = ToolNotFoundError("codex", "custom message")
        assert err.tool_name == "codex"
        assert str(err) == "custom message"

    def test_protocol_error(self) -> None:
        """Test ProtocolError."""
        err = ProtocolError("something went wrong", failure_category="test_failure")
        assert err.failure_category == "test_failure"
        assert "something went wrong" in str(err)

    def test_protocol_error_no_category(self) -> None:
        """Test ProtocolError without category."""
        err = ProtocolError("error message")
        assert err.failure_category is None

    def test_adapter_error_is_exception(self) -> None:
        """Test AdapterError is an Exception."""
        err = AdapterError("test")
        assert isinstance(err, Exception)

    def test_tool_not_found_inherits_adapter_error(self) -> None:
        """Test ToolNotFoundError inherits from AdapterError."""
        err = ToolNotFoundError("codex")
        assert isinstance(err, AdapterError)

    def test_protocol_error_inherits_adapter_error(self) -> None:
        """Test ProtocolError inherits from AdapterError."""
        err = ProtocolError("error")
        assert isinstance(err, AdapterError)

    def test_escalation_required(self) -> None:
        """Test EscalationRequired exception."""
        err = EscalationRequired("need human review", violations=["escalate:shell_compound:&&"])
        assert "need human review" in str(err)
        assert err.violations == ["escalate:shell_compound:&&"]

    def test_escalation_required_no_violations(self) -> None:
        """Test EscalationRequired with no violations."""
        err = EscalationRequired("need review")
        assert err.violations == []

    def test_escalation_required_inherits_adapter_error(self) -> None:
        """Test EscalationRequired inherits from AdapterError."""
        err = EscalationRequired("test")
        assert isinstance(err, AdapterError)

    def test_escalation_required_not_protocol_error(self) -> None:
        """Test EscalationRequired is NOT a ProtocolError (distinct exception types)."""
        err = EscalationRequired("test")
        assert not isinstance(err, ProtocolError)


class TestCodexAdapterVerify:
    """Tests for CodexAdapter.verify()."""

    def test_verify_tool_not_found(self) -> None:
        """Test verify raises ToolNotFoundError if codex not in PATH."""
        adapter = CodexAdapter()

        with patch("shutil.which", return_value=None):
            with pytest.raises(ToolNotFoundError) as exc:
                adapter.verify()

            assert exc.value.tool_name == "codex"

    def test_verify_checks_required_flags(self) -> None:
        """Test verify checks for required flags."""
        adapter = CodexAdapter()

        # Build help output from primary flags
        help_output = " ".join(f[0] for f in REQUIRED_FLAGS)

        with patch("shutil.which", return_value="/usr/bin/codex"):
            mock_result = MagicMock()
            mock_result.stdout = help_output
            mock_result.stderr = ""

            with patch("subprocess.run", return_value=mock_result):
                # Should not raise
                adapter.verify()

    def test_verify_accepts_short_flags(self) -> None:
        """Test verify accepts short flag alternatives."""
        adapter = CodexAdapter()

        # Use -o instead of --output-last-message
        help_output = "--cd --sandbox --output-schema -o --json"

        with patch("shutil.which", return_value="/usr/bin/codex"):
            mock_result = MagicMock()
            mock_result.stdout = help_output
            mock_result.stderr = ""

            with patch("subprocess.run", return_value=mock_result):
                # Should not raise - -o satisfies --output-last-message requirement
                adapter.verify()

    def test_verify_missing_flags(self) -> None:
        """Test verify raises ProtocolError if flags clearly missing."""
        adapter = CodexAdapter()

        # Missing --dangerously-bypass-approvals-and-sandbox entirely
        # Need enough text to not be "too short" (>50 chars)
        help_output = """
Usage: codex exec [OPTIONS] PROMPT
Options:
  --cd PATH              Set working directory
  --output-schema PATH   Schema for output
  --output-last-message  Output last message
  --json                 JSON output mode
  --help                 Show this help
"""

        with patch("shutil.which", return_value="/usr/bin/codex"):
            mock_result = MagicMock()
            mock_result.stdout = help_output
            mock_result.stderr = ""

            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(ProtocolError) as exc:
                    adapter.verify()

                assert exc.value.failure_category == "tool_contract_mismatch"
                assert "--dangerously-bypass-approvals-and-sandbox" in str(exc.value)

    def test_verify_help_timeout_inconclusive(self) -> None:
        """Test verify handles timeout gracefully (inconclusive, not failure)."""
        adapter = CodexAdapter()

        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("codex", 30)

                # Should NOT raise - timeout is inconclusive, not failure
                adapter.verify()

                assert adapter.preflight_status == "inconclusive"
                assert "timed out" in adapter.preflight_reason

    def test_verify_short_help_inconclusive(self) -> None:
        """Test verify handles very short help output as inconclusive."""
        adapter = CodexAdapter()

        with patch("shutil.which", return_value="/usr/bin/codex"):
            mock_result = MagicMock()
            mock_result.stdout = "codex v1.0"  # Too short
            mock_result.stderr = ""

            with patch("subprocess.run", return_value=mock_result):
                adapter.verify()

                assert adapter.preflight_status == "inconclusive"
                assert "too short" in adapter.preflight_reason


class TestCodexAdapterExecute:
    """Tests for CodexAdapter.execute()."""

    def _setup_input_dir(self, tmpdir: Path) -> tuple[Path, Path]:
        """Set up input directory with required files."""
        input_dir = tmpdir / "input"
        input_dir.mkdir()

        # Create prompt.md
        (input_dir / "prompt.md").write_text("Test prompt")

        # Create repo_state.json
        repo_state = {
            "commit": "abc123" * 7,
            "branch": "main",
            "dirty_files": [],
            "timestamp": "2024-12-13T10:00:00Z",
            "repo_root": str(tmpdir),
            "codex_output_schema_path": "artifacts/schemas/codex_output.schema.json",
            "codex_sandbox_mode": "read-only",
        }
        (input_dir / "repo_state.json").write_text(json.dumps(repo_state))

        output_dir = tmpdir / "output"
        return input_dir, output_dir

    def _mock_codex_output(self) -> dict[str, Any]:
        """Return mock Codex structured output."""
        return {
            "patch_diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new",
            "agent": {
                "files_modified": ["file.py"],
                "commands_executed": [
                    {"command": "cat file.py", "exit_code": 0},
                ],
                "confidence": 0.9,
                "completion_status": "complete",
            },
        }

    def test_execute_missing_prompt(self) -> None:
        """Test execute raises if prompt.md missing."""
        adapter = CodexAdapter()
        adapter._verified = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            input_dir.mkdir()

            # Create repo_state but NOT prompt.md
            (input_dir / "repo_state.json").write_text(
                json.dumps({"codex_sandbox_mode": "read-only"})
            )

            output_dir = Path(tmpdir) / "output"

            with pytest.raises(ProtocolError) as exc:
                adapter.execute(input_dir, output_dir, Path(tmpdir))

            assert exc.value.failure_category == "missing_input"
            assert "prompt.md" in str(exc.value)

    def test_execute_missing_repo_state(self) -> None:
        """Test execute raises if repo_state.json missing."""
        adapter = CodexAdapter()
        adapter._verified = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            input_dir.mkdir()

            # Create prompt but NOT repo_state
            (input_dir / "prompt.md").write_text("test")

            output_dir = Path(tmpdir) / "output"

            with pytest.raises(ProtocolError) as exc:
                adapter.execute(input_dir, output_dir, Path(tmpdir))

            assert exc.value.failure_category == "missing_input"
            assert "repo_state.json" in str(exc.value)

    def test_execute_codex_timeout(self) -> None:
        """Test execute handles Codex timeout."""
        adapter = CodexAdapter()
        adapter._verified = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir, output_dir = self._setup_input_dir(Path(tmpdir))

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("codex", 600)

                with pytest.raises(ProtocolError) as exc:
                    adapter.execute(input_dir, output_dir, Path(tmpdir))

                assert exc.value.failure_category == "timeout"

    def test_execute_codex_error(self) -> None:
        """Test execute handles Codex non-zero exit."""
        adapter = CodexAdapter()
        adapter._verified = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir, output_dir = self._setup_input_dir(Path(tmpdir))

            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "Codex error"

            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(ProtocolError) as exc:
                    adapter.execute(input_dir, output_dir, Path(tmpdir))

                assert exc.value.failure_category == "codex_error"

    def test_execute_success(self) -> None:
        """Test successful execution."""
        adapter = CodexAdapter()
        adapter._verified = True

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir, output_dir = self._setup_input_dir(Path(tmpdir))

            # Create last_message.json that Codex would write
            output_dir.mkdir(parents=True, exist_ok=True)
            codex_output = self._mock_codex_output()

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""  # No command events
            mock_result.stderr = ""

            def mock_run_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
                # Write last_message.json when codex runs
                (output_dir / "last_message.json").write_text(json.dumps(codex_output))
                return mock_result

            with patch("subprocess.run", side_effect=mock_run_side_effect):
                adapter.execute(input_dir, output_dir, Path(tmpdir))

            # Check artifacts were created
            assert (output_dir / "patch.diff").exists()
            assert (output_dir / "agent.json").exists()
            assert (output_dir / "cmdlog.txt").exists()

            # Check patch content
            patch_content = (output_dir / "patch.diff").read_text()
            assert "file.py" in patch_content

            # Check agent.json
            with open(output_dir / "agent.json") as f:
                agent = json.load(f)
            assert agent["files_modified"] == ["file.py"]
            assert agent["confidence"] == 0.9


class TestForbiddenCommands:
    """Tests for forbidden command detection using token-aware matching."""

    def test_forbidden_rm_rf(self) -> None:
        """Test rm -rf is detected."""
        commands = ["rm -rf /tmp/foo"]
        violations = check_forbidden_commands(commands)
        assert any("rm_recursive" in v for v in violations)

    def test_forbidden_rm_with_separated_flags(self) -> None:
        """Test rm with -r flag anywhere in args."""
        # Token-aware: catches -r anywhere, not just adjacent to rm
        commands = ["rm -f -r /tmp/foo"]
        violations = check_forbidden_commands(commands)
        assert any("rm_recursive" in v for v in violations)

    def test_forbidden_sudo(self) -> None:
        """Test sudo is detected."""
        commands = ["sudo apt update"]
        violations = check_forbidden_commands(commands)
        assert any("privilege_escalation" in v for v in violations)

    def test_forbidden_git_commit(self) -> None:
        """Test git commit is detected."""
        commands = ["git commit -m 'test'"]
        violations = check_forbidden_commands(commands)
        assert any("git_write" in v for v in violations)

    def test_forbidden_git_add(self) -> None:
        """Test git add is detected."""
        commands = ["git add ."]
        violations = check_forbidden_commands(commands)
        assert any("git_write" in v for v in violations)

    def test_forbidden_pip_install(self) -> None:
        """Test pip install is detected."""
        commands = ["pip install requests"]
        violations = check_forbidden_commands(commands)
        assert any("package_install" in v for v in violations)

    def test_forbidden_python_m_pip_install(self) -> None:
        """Test python -m pip install is detected (token-aware)."""
        commands = ["python -m pip install requests"]
        violations = check_forbidden_commands(commands)
        assert any("package_install" in v for v in violations)

    def test_forbidden_curl(self) -> None:
        """Test curl is detected."""
        commands = ["curl https://example.com"]
        violations = check_forbidden_commands(commands)
        assert any("network_tool" in v for v in violations)

    def test_forbidden_wget(self) -> None:
        """Test wget is detected."""
        commands = ["wget https://example.com"]
        violations = check_forbidden_commands(commands)
        assert any("network_tool" in v for v in violations)

    def test_forbidden_chmod(self) -> None:
        """Test chmod is detected."""
        commands = ["chmod 755 script.sh"]
        violations = check_forbidden_commands(commands)
        assert any("system_tool" in v for v in violations)

    def test_allowed_commands(self) -> None:
        """Test common allowed commands pass."""
        commands = [
            "cat src/main.py",
            "ls -la",
            "grep -r 'pattern' src/",
            "pytest tests/",
            "ruff check .",
            "mypy src/",
            "git status",
            "git diff",
            "git log",
            "git show HEAD",
            "git blame file.py",
            "python -c \"print('hello')\"",
            "rm single_file.txt",  # rm without -r is fine
        ]
        violations = check_forbidden_commands(commands)
        assert violations == []

    def test_case_insensitive(self) -> None:
        """Test forbidden patterns are case-insensitive."""
        commands = ["SUDO apt update"]
        violations = check_forbidden_commands(commands)
        assert any("privilege_escalation" in v for v in violations)

    def test_no_false_positive_from_output_text(self) -> None:
        """Test that forbidden words in OUTPUT don't trigger violations.

        This is the critical test: if 'sudo' appears in test output,
        documentation, or code snippets (but not in actual commands),
        it should NOT be flagged.

        The key insight is that we ONLY pass actual command strings to
        check_forbidden_commands(), not arbitrary output text.
        """
        # These are actual commands - none are forbidden
        commands = [
            "cat README.md",  # README might mention sudo in its content
            "pytest tests/",  # Test output might print 'curl' in assertions
            "find docs/ -name '*.md'",  # Find docs that might mention sudo
        ]
        violations = check_forbidden_commands(commands)
        assert violations == []

    def test_design_only_checks_commands_not_output(self) -> None:
        """Verify the design: only command strings are checked, not output.

        This test documents the architectural decision: the forbidden
        command checker receives a list of actual command strings extracted
        from JSONL events, NOT the full event stream or command output.
        """
        # We only check actual commands, not output text
        actual_commands = ["cat README.md"]
        violations = check_forbidden_commands(actual_commands)
        assert violations == []  # No false positive!

    def test_duplicate_violations_not_repeated(self) -> None:
        """Test that same violation type isn't repeated."""
        commands = ["sudo apt update", "sudo apt install foo"]
        violations = check_forbidden_commands(commands)
        # Should only have one 'sudo' violation, not two
        sudo_count = sum(1 for v in violations if "privilege_escalation" in v)
        assert sudo_count == 1

    def test_path_to_command_handled(self) -> None:
        """Test that /usr/bin/curl is caught, not just 'curl'."""
        commands = ["/usr/bin/curl https://example.com"]
        violations = check_forbidden_commands(commands)
        assert any("network_tool" in v for v in violations)


class TestTokenAwareMatching:
    """Tests specifically for token-aware forbidden command matching."""

    def test_rm_recursive_variations(self) -> None:
        """Test various rm recursive patterns."""
        # All should be caught
        dangerous = [
            "rm -rf /",
            "rm -r -f /tmp",
            "rm -fr /tmp",
            "rm --recursive /tmp",
            "rm -R /tmp",
        ]
        for cmd in dangerous:
            violation = _check_single_command(cmd)
            assert violation is not None, f"Should catch: {cmd}"
            assert "rm_recursive" in violation

    def test_rm_single_file_allowed(self) -> None:
        """Test that rm without -r is allowed."""
        safe = [
            "rm file.txt",
            "rm -f file.txt",  # -f alone is fine
            "rm -i file.txt",
        ]
        for cmd in safe:
            violation = _check_single_command(cmd)
            assert violation is None, f"Should allow: {cmd}"

    def test_git_read_commands_allowed(self) -> None:
        """Test that git read commands are allowed."""
        safe = [
            "git status",
            "git diff",
            "git log",
            "git show HEAD",
            "git blame file.py",
            "git branch -a",
            "git remote -v",
        ]
        for cmd in safe:
            violation = _check_single_command(cmd)
            assert violation is None, f"Should allow: {cmd}"

    def test_git_write_commands_forbidden(self) -> None:
        """Test that git write commands are forbidden."""
        forbidden = [
            "git add .",
            "git commit -m 'test'",
            "git push origin main",
            "git reset --hard",
            "git checkout main",
            "git merge feature",
            "git rebase main",
            "git cherry-pick abc123",
            "git apply patch.diff",
        ]
        for cmd in forbidden:
            violation = _check_single_command(cmd)
            assert violation is not None, f"Should catch: {cmd}"
            assert "git_write" in violation

    def test_python_m_module_detection(self) -> None:
        """Test python -m <module> pattern detection."""
        # python -m pip install should be caught
        violation = _check_single_command("python -m pip install requests")
        assert violation is not None
        assert "package_install" in violation

        # python3 -m pip install should be caught
        violation = _check_single_command("python3 -m pip install requests")
        assert violation is not None
        assert "package_install" in violation

        # python -c "..." should be allowed
        violation = _check_single_command("python -c 'print(1)'")
        assert violation is None

    def test_network_tools_as_arguments_allowed(self) -> None:
        """Test that 'curl' as an argument (not command) is allowed."""
        # echo "use curl" should be allowed - curl is not the command
        violation = _check_single_command("echo 'use curl to download'")
        assert violation is None

        # But curl as command is forbidden
        violation = _check_single_command("curl http://example.com")
        assert violation is not None

    def test_shell_compound_operators_rejected(self) -> None:
        """Test that shell compound operators inside commands are rejected."""
        compound_commands = [
            "echo ok && rm -rf /",
            "echo ok; rm -rf /",
            "echo $(whoami)",
            "echo `whoami`",
            "ls || true",
        ]
        for cmd in compound_commands:
            violation = _check_single_command(cmd)
            assert violation is not None, f"Should reject: {cmd}"
            assert "shell_compound" in violation, f"Wrong violation type for: {cmd}"

    def test_shell_wrapped_safe_commands_allowed(self) -> None:
        """Test that shell-wrapped safe commands are allowed.

        Codex emits shell invocations like 'bash -lc ls' even in read-only mode.
        We parse the inner command and check it, not the shell wrapper.
        """
        safe_shell_commands = [
            "bash -lc ls",
            "bash -lc 'ls -la'",
            "sh -c 'cat file.txt'",
            "bash -lc 'find . -maxdepth 2 -type f'",
            "bash -lc 'grep -R TODO src/'",
            "bash -lc 'git status'",
            "bash -lc 'git diff'",
            "/bin/bash -lc 'cat README.md'",
        ]
        for cmd in safe_shell_commands:
            violation = _check_single_command(cmd)
            assert violation is None, f"Should allow: {cmd}"

    def test_shell_wrapped_dangerous_commands_rejected(self) -> None:
        """Test that shell-wrapped dangerous commands are rejected.

        Even when wrapped in bash -c, dangerous inner commands are caught.
        """
        dangerous_shell_commands = [
            ("bash -lc 'rm -rf /'", "rm_recursive"),
            ("sh -c 'curl http://evil.com'", "network_tool"),
            ("bash -c 'sudo apt update'", "privilege_escalation"),
            ("bash -lc 'git commit -m test'", "git_write"),
            ("sh -c 'pip install malware'", "package_install"),
        ]
        for cmd, expected_violation in dangerous_shell_commands:
            violation = _check_single_command(cmd)
            assert violation is not None, f"Should reject: {cmd}"
            assert expected_violation in violation, f"Wrong violation for: {cmd}, got: {violation}"

    def test_shell_wrapped_compound_rejected(self) -> None:
        """Test that compound operators inside shell commands are rejected."""
        compound_shell_commands = [
            "bash -lc 'ls && rm -rf /'",
            "sh -c 'echo ok; cat /etc/passwd'",
            "bash -c 'echo $(whoami)'",
        ]
        for cmd in compound_shell_commands:
            violation = _check_single_command(cmd)
            assert violation is not None, f"Should reject: {cmd}"
            assert "shell_compound" in violation

    def test_parameter_expansion_allowed(self) -> None:
        """Test that ${ parameter expansion is allowed.

        ${ is parameter expansion (common, harmless), not command substitution.
        Only $( and backticks are command substitution.
        """
        # ${VAR} is fine - it's parameter expansion
        violation = _check_single_command("echo ${HOME}")
        assert violation is None

        # Also allowed inside shell wrapper
        violation = _check_single_command("bash -lc 'echo ${HOME}'")
        assert violation is None

    def test_simple_commands_allowed(self) -> None:
        """Test that simple commands pass."""
        simple_commands = [
            "cat file.txt",
            "ls -la",
            "grep pattern file",
            "python script.py",
            "pytest tests/",
        ]
        for cmd in simple_commands:
            violation = _check_single_command(cmd)
            assert violation is None, f"Should allow: {cmd}"


class TestViolationCategorization:
    """Tests for hard vs escalation violation categorization."""

    def test_hard_violation_prefix(self) -> None:
        """Test hard violation prefix constant."""
        assert VIOLATION_PREFIX_HARD == "hard:"

    def test_escalation_violation_prefix(self) -> None:
        """Test escalation violation prefix constant."""
        assert VIOLATION_PREFIX_ESCALATE == "escalate:"

    def test_is_hard_violation(self) -> None:
        """Test is_hard_violation helper."""
        assert is_hard_violation("hard:network_tool:curl") is True
        assert is_hard_violation("hard:rm_recursive:-rf") is True
        assert is_hard_violation("escalate:shell_compound:&&") is False
        assert is_hard_violation("something_else") is False

    def test_is_escalation_violation(self) -> None:
        """Test is_escalation_violation helper."""
        assert is_escalation_violation("escalate:shell_compound:&&") is True
        assert is_escalation_violation("escalate:unusual_shell_form:bash") is True
        assert is_escalation_violation("hard:network_tool:curl") is False
        assert is_escalation_violation("something_else") is False

    def test_dangerous_tools_are_hard_violations(self) -> None:
        """Test that dangerous tools produce hard violations."""
        hard_fail_commands = [
            "curl http://example.com",
            "wget http://example.com",
            "ssh user@host",
            "sudo apt update",
            "rm -rf /",
            "git commit -m 'test'",
            "pip install requests",
            "chmod 777 file",
        ]
        for cmd in hard_fail_commands:
            violation = _check_single_command(cmd)
            assert violation is not None, f"Should have violation for: {cmd}"
            assert is_hard_violation(violation), f"Should be hard violation: {cmd} -> {violation}"

    def test_compound_operators_are_escalation_violations(self) -> None:
        """Test that compound operators produce escalation (soft) violations."""
        escalation_commands = [
            "ls && echo done",
            "cat file || true",
            "echo $(whoami)",
            "echo `date`",
            "echo a; echo b",
        ]
        for cmd in escalation_commands:
            violation = _check_single_command(cmd)
            assert violation is not None, f"Should have violation for: {cmd}"
            assert is_escalation_violation(violation), f"Should be escalation violation: {cmd} -> {violation}"

    def test_forbidden_shells_are_hard_violations(self) -> None:
        """Test that forbidden shells (zsh, fish, etc.) produce hard violations."""
        forbidden_shell_commands = [
            "zsh -c 'ls'",
            "fish -c 'ls'",
            "powershell -Command 'Get-Process'",
            "pwsh -c 'ls'",
            "/usr/bin/zsh -c 'echo test'",
        ]
        for cmd in forbidden_shell_commands:
            violation = _check_single_command(cmd)
            assert violation is not None, f"Should have violation for: {cmd}"
            assert is_hard_violation(violation), f"Should be hard violation for forbidden shell: {cmd} -> {violation}"
            assert "forbidden_shell" in violation

    def test_allowed_shell_wrappers_pass(self) -> None:
        """Test that allowed Codex shell wrappers are not violations."""
        allowed_wrappers = [
            "bash -c ls",
            "bash -lc ls",
            "sh -c ls",
            "sh -lc ls",
            "/bin/bash -lc 'cat file.txt'",
            "/bin/sh -c 'echo test'",
        ]
        for cmd in allowed_wrappers:
            violation = _check_single_command(cmd)
            assert violation is None, f"Should allow Codex wrapper: {cmd}"

    def test_check_forbidden_commands_returns_categorized_violations(self) -> None:
        """Test that check_forbidden_commands returns properly categorized violations."""
        commands = [
            "ls",  # allowed
            "curl http://evil.com",  # hard: network_tool
            "echo $(whoami)",  # escalate: shell_compound
        ]
        violations = check_forbidden_commands(commands)
        assert len(violations) == 2

        hard_count = sum(1 for v in violations if is_hard_violation(v))
        escalate_count = sum(1 for v in violations if is_escalation_violation(v))
        assert hard_count == 1
        assert escalate_count == 1


class TestParseCommandsFromCmdlog:
    """Tests for parsing commands from cmdlog.txt."""

    def test_parse_basic_cmdlog(self) -> None:
        """Test parsing commands from cmdlog format."""
        cmdlog = """[2024-12-13T10:00:00Z] CMD: cat file.py
[2024-12-13T10:00:00Z] EXIT: 0
[2024-12-13T10:00:00Z] DURATION: 10ms
---
[2024-12-13T10:00:01Z] CMD: pytest tests/
[2024-12-13T10:00:01Z] EXIT: 0
[2024-12-13T10:00:01Z] DURATION: 5000ms
---"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(cmdlog)
            f.flush()
            commands = parse_commands_from_cmdlog(Path(f.name))

        assert commands == ["cat file.py", "pytest tests/"]

    def test_parse_empty_cmdlog(self) -> None:
        """Test parsing empty cmdlog."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            f.flush()
            commands = parse_commands_from_cmdlog(Path(f.name))

        assert commands == []


class TestEventStreamParsing:
    """Tests for JSON event stream parsing."""

    def test_parse_command_events(self) -> None:
        """Test parsing command events from JSON stream."""
        adapter = CodexAdapter()

        events = [
            {"type": "command", "timestamp": "2024-12-13T10:00:00Z", "command": "cat file.py", "exit_code": 0, "duration_ms": 100},
            {"type": "other", "data": "ignored"},
            {"type": "command", "timestamp": "2024-12-13T10:00:01Z", "command": "pytest", "exit_code": 0, "duration_ms": 5000},
        ]

        stdout = "\n".join(json.dumps(e) for e in events)
        cmdlog, commands = adapter._parse_event_stream(stdout)

        assert "cat file.py" in cmdlog
        assert "pytest" in cmdlog
        assert "EXIT: 0" in cmdlog
        assert "DURATION: 100ms" in cmdlog
        assert "DURATION: 5000ms" in cmdlog
        assert cmdlog.count("---") == 2

        # Also verify commands list
        assert commands == ["cat file.py", "pytest"]

    def test_parse_empty_stream(self) -> None:
        """Test parsing empty event stream."""
        adapter = CodexAdapter()
        cmdlog, commands = adapter._parse_event_stream("")
        assert cmdlog == ""
        assert commands == []

    def test_parse_invalid_json_lines(self) -> None:
        """Test invalid JSON lines are skipped."""
        adapter = CodexAdapter()

        stdout = """{"type": "command", "timestamp": "T1", "command": "echo", "exit_code": 0, "duration_ms": 10}
not json
{"type": "command", "timestamp": "T2", "command": "cat", "exit_code": 0, "duration_ms": 20}"""

        cmdlog, commands = adapter._parse_event_stream(stdout)

        assert "echo" in cmdlog
        assert "cat" in cmdlog
        assert cmdlog.count("---") == 2
        assert commands == ["echo", "cat"]

    def test_parse_command_execution_event_type(self) -> None:
        """Test that command_execution event type is also handled."""
        adapter = CodexAdapter()

        events = [
            {"type": "command_execution", "timestamp": "T1", "command": "ls -la", "exit_code": 0, "duration_ms": 10},
        ]

        stdout = "\n".join(json.dumps(e) for e in events)
        cmdlog, commands = adapter._parse_event_stream(stdout)

        assert "ls -la" in cmdlog
        assert commands == ["ls -la"]


class TestArtifactExtraction:
    """Tests for artifact extraction."""

    def test_extract_missing_last_message(self) -> None:
        """Test extraction fails if last_message.json missing."""
        adapter = CodexAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            with pytest.raises(ProtocolError) as exc:
                adapter._extract_artifacts(
                    Path(tmpdir) / "missing.json",
                    output_dir,
                )

            assert exc.value.failure_category == "missing_output"

    def test_extract_invalid_json(self) -> None:
        """Test extraction fails on invalid JSON."""
        adapter = CodexAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            last_message = Path(tmpdir) / "last_message.json"
            last_message.write_text("not json")

            with pytest.raises(ProtocolError) as exc:
                adapter._extract_artifacts(last_message, output_dir)

            assert exc.value.failure_category == "invalid_output"

    def test_extract_missing_patch_diff(self) -> None:
        """Test extraction fails if patch_diff missing."""
        adapter = CodexAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            last_message = Path(tmpdir) / "last_message.json"
            last_message.write_text(json.dumps({"agent": {}}))

            with pytest.raises(ProtocolError) as exc:
                adapter._extract_artifacts(last_message, output_dir)

            assert exc.value.failure_category == "invalid_output"
            assert "patch_diff" in str(exc.value)

    def test_extract_missing_agent(self) -> None:
        """Test extraction fails if agent missing."""
        adapter = CodexAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            last_message = Path(tmpdir) / "last_message.json"
            last_message.write_text(json.dumps({"patch_diff": "test"}))

            with pytest.raises(ProtocolError) as exc:
                adapter._extract_artifacts(last_message, output_dir)

            assert exc.value.failure_category == "invalid_output"
            assert "agent" in str(exc.value)

    def test_extract_missing_agent_fields(self) -> None:
        """Test extraction fails if agent missing required fields."""
        adapter = CodexAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            last_message = Path(tmpdir) / "last_message.json"
            last_message.write_text(
                json.dumps(
                    {
                        "patch_diff": "test",
                        "agent": {"files_modified": []},  # Missing other fields
                    }
                )
            )

            with pytest.raises(ProtocolError) as exc:
                adapter._extract_artifacts(last_message, output_dir)

            assert exc.value.failure_category == "invalid_output"
            assert "commands_executed" in str(exc.value) or "confidence" in str(exc.value)

    def test_extract_inconsistent_output(self) -> None:
        """Test extraction fails on inconsistent patch vs files_modified."""
        adapter = CodexAdapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            last_message = Path(tmpdir) / "last_message.json"
            last_message.write_text(
                json.dumps(
                    {
                        "patch_diff": "--- a/file.py\n+++ b/file.py\n-old\n+new",
                        "agent": {
                            "files_modified": [],  # Empty but patch is not!
                            "commands_executed": [],
                            "confidence": 0.9,
                            "completion_status": "complete",
                        },
                    }
                )
            )

            with pytest.raises(ProtocolError) as exc:
                adapter._extract_artifacts(last_message, output_dir)

            assert exc.value.failure_category == "inconsistent_output"


class TestAdapterRegistry:
    """Tests for adapter registry."""

    def test_get_codex_adapter(self) -> None:
        """Test getting codex adapter by name."""
        adapter = get_adapter("codex")
        assert isinstance(adapter, CodexAdapter)
        assert adapter.name == "codex"

    def test_get_adapter_case_insensitive(self) -> None:
        """Test adapter lookup is case-insensitive."""
        adapter = get_adapter("CODEX")
        assert isinstance(adapter, CodexAdapter)

    def test_get_unknown_adapter(self) -> None:
        """Test getting unknown adapter raises ValueError."""
        with pytest.raises(ValueError) as exc:
            get_adapter("unknown")

        assert "Unknown adapter" in str(exc.value)
        assert "codex" in str(exc.value)  # Should list available

    def test_list_adapters(self) -> None:
        """Test listing available adapters."""
        adapters = list_adapters()
        assert "codex" in adapters


class TestCodexAdapterProperties:
    """Tests for CodexAdapter properties."""

    def test_name_property(self) -> None:
        """Test name property returns 'codex'."""
        adapter = CodexAdapter()
        assert adapter.name == "codex"

    def test_adapter_is_agent_adapter(self) -> None:
        """Test CodexAdapter is an AgentAdapter."""
        adapter = CodexAdapter()
        assert isinstance(adapter, AgentAdapter)


class TestRequiredFlags:
    """Tests for required flags constant."""

    def test_all_required_flags_present(self) -> None:
        """Test all required flags are defined."""
        # REQUIRED_FLAGS is now list of tuples with alternatives
        flag_primaries = [f[0] for f in REQUIRED_FLAGS]
        assert "--cd" in flag_primaries
        assert "--dangerously-bypass-approvals-and-sandbox" in flag_primaries
        assert "--output-schema" in flag_primaries
        assert "--output-last-message" in flag_primaries
        assert "--json" in flag_primaries

    def test_required_flags_count(self) -> None:
        """Test expected number of required flags."""
        assert len(REQUIRED_FLAGS) == 5

    def test_output_last_message_has_short_form(self) -> None:
        """Test --output-last-message has -o as alternative."""
        for flag_tuple in REQUIRED_FLAGS:
            if "--output-last-message" in flag_tuple:
                assert "-o" in flag_tuple
                break
        else:
            pytest.fail("--output-last-message not found in REQUIRED_FLAGS")


class TestForbiddenPatternSets:
    """Tests for forbidden command pattern constants."""

    def test_network_tools_defined(self) -> None:
        """Test network tools set is defined."""
        from spec.executor.adapters.codex import FORBIDDEN_NETWORK_TOOLS

        assert "curl" in FORBIDDEN_NETWORK_TOOLS
        assert "wget" in FORBIDDEN_NETWORK_TOOLS
        assert "ssh" in FORBIDDEN_NETWORK_TOOLS

    def test_git_subcommands_defined(self) -> None:
        """Test git write subcommands are defined."""
        from spec.executor.adapters.codex import FORBIDDEN_GIT_SUBCOMMANDS

        assert "commit" in FORBIDDEN_GIT_SUBCOMMANDS
        assert "push" in FORBIDDEN_GIT_SUBCOMMANDS
        assert "add" in FORBIDDEN_GIT_SUBCOMMANDS

    def test_package_managers_defined(self) -> None:
        """Test package manager patterns are defined."""
        from spec.executor.adapters.codex import FORBIDDEN_PACKAGE_MANAGERS

        assert "pip" in FORBIDDEN_PACKAGE_MANAGERS
        assert "install" in FORBIDDEN_PACKAGE_MANAGERS["pip"]
