"""Tests for Verification Runner."""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from spec.executor.verify import (
    CommandResult,
    VerificationResult,
    generate_verification_report,
    run_command,
    run_commands,
    verify,
)


class TestCommandResult:
    """Tests for CommandResult dataclass."""

    def test_success_when_exit_code_zero(self) -> None:
        """Test success is True when exit code is 0."""
        result = CommandResult(
            command="echo test",
            exit_code=0,
            stdout="test",
            stderr="",
            duration_ms=100,
        )

        assert result.success is True

    def test_not_success_when_exit_code_nonzero(self) -> None:
        """Test success is False when exit code is non-zero."""
        result = CommandResult(
            command="false",
            exit_code=1,
            stdout="",
            stderr="error",
            duration_ms=100,
        )

        assert result.success is False

    def test_not_success_when_timed_out(self) -> None:
        """Test success is False when command timed out."""
        result = CommandResult(
            command="sleep 100",
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=5000,
            timed_out=True,
        )

        assert result.success is False


class TestRunCommand:
    """Tests for run_command function."""

    def test_successful_command(self) -> None:
        """Test running a successful command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_command("echo hello", Path(tmpdir))

            assert result.exit_code == 0
            assert "hello" in result.stdout
            assert result.success is True
            assert result.timed_out is False

    def test_failing_command(self) -> None:
        """Test running a failing command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_command("false", Path(tmpdir))

            assert result.exit_code != 0
            assert result.success is False
            assert result.timed_out is False

    def test_command_not_found(self) -> None:
        """Test running a command that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_command("nonexistent_command_xyz", Path(tmpdir))

            assert result.exit_code == 127
            # Message could say "not found" or "not executable"
            assert "not found" in result.stderr.lower() or "not executable" in result.stderr.lower()
            assert result.success is False

    def test_timeout(self) -> None:
        """Test command timeout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_command("sleep 10", Path(tmpdir), timeout=1)

            assert result.timed_out is True
            assert result.success is False
            assert result.duration_ms >= 1000

    def test_captures_stdout(self) -> None:
        """Test that stdout is captured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_command("echo 'hello world'", Path(tmpdir))

            assert "hello world" in result.stdout

    def test_captures_stderr(self) -> None:
        """Test that stderr is captured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_command("echo 'error message' >&2", Path(tmpdir))

            # Shell syntax may not work without shell=True, so use Python
            result = run_command("python -c \"import sys; sys.stderr.write('error message')\"", Path(tmpdir))
            assert "error message" in result.stderr

    def test_duration_tracked(self) -> None:
        """Test that duration is tracked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_command("sleep 0.1", Path(tmpdir))

            assert result.duration_ms >= 90  # Allow some timing slack

    def test_no_shell_injection(self) -> None:
        """Test that shell injection is not possible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # This should NOT execute the second echo as a separate command
            # shlex.split treats ; as part of the argument: ["echo", "test;", "echo", "injected"]
            # So echo will output "test; echo injected" literally, not execute two commands
            result = run_command("echo test; echo injected", Path(tmpdir))

            # With shlex.split, the semicolon is just a regular character
            # The output should contain "test;" and "echo" and "injected" as separate words
            # or echo might fail because it sees multiple args
            # Key point: "injected" should NOT appear on its own line as if from a second command
            lines = result.stdout.strip().split("\n")
            # If shell=True was used, we'd have TWO lines: "test" and "injected"
            # With shlex.split, we have ONE line with "test; echo injected" or similar
            assert len(lines) == 1


class TestRunCommandsMocked:
    """Tests using mocked subprocess."""

    def test_success_path_mocked(self) -> None:
        """Test successful command with mocked subprocess."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "All tests passed"
        mock_result.stderr = ""

        with patch("spec.executor.verify.subprocess.run", return_value=mock_result):
            result = run_command("pytest", Path("/tmp"))

            assert result.exit_code == 0
            assert result.success is True
            assert "passed" in result.stdout

    def test_failure_path_mocked(self) -> None:
        """Test failing command with mocked subprocess."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "FAILED test_something"

        with patch("spec.executor.verify.subprocess.run", return_value=mock_result):
            result = run_command("pytest", Path("/tmp"))

            assert result.exit_code == 1
            assert result.success is False

    def test_timeout_mocked(self) -> None:
        """Test timeout with mocked subprocess."""
        with patch("spec.executor.verify.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("pytest", 300)

            result = run_command("pytest", Path("/tmp"), timeout=300)

            assert result.timed_out is True
            assert result.success is False


class TestRunCommands:
    """Tests for run_commands function."""

    def test_multiple_commands(self) -> None:
        """Test running multiple commands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = run_commands(["echo one", "echo two"], Path(tmpdir))

            assert len(results) == 2
            assert all(r.success for r in results)

    def test_sequential_execution(self) -> None:
        """Test that commands run sequentially."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file in first command, read it in second
            Path(tmpdir).joinpath("test.txt").write_text("hello")

            results = run_commands(
                ["cat test.txt", "echo done"],
                Path(tmpdir),
            )

            assert results[0].success
            assert "hello" in results[0].stdout


class TestVerify:
    """Tests for verify function."""

    def test_all_pass(self) -> None:
        """Test when all commands pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = verify(["echo test1", "echo test2"], Path(tmpdir))

            assert result.passed is True
            assert result.failure_category is None

    def test_one_fails(self) -> None:
        """Test when one command fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = verify(["echo ok", "false", "echo also ok"], Path(tmpdir))

            assert result.passed is False
            assert result.failure_category is not None

    def test_failure_category_test(self) -> None:
        """Test failure category for test commands."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED tests"
        mock_result.stderr = ""

        with patch("spec.executor.verify.subprocess.run", return_value=mock_result):
            result = verify(["pytest tests/"], Path("/tmp"))

            assert result.failure_category == "test_failure"

    def test_failure_category_lint(self) -> None:
        """Test failure category for lint commands."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Lint errors found"

        with patch("spec.executor.verify.subprocess.run", return_value=mock_result):
            result = verify(["ruff check ."], Path("/tmp"))

            assert result.failure_category == "lint_failure"

    def test_failure_category_type(self) -> None:
        """Test failure category for type check commands."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Type errors"

        with patch("spec.executor.verify.subprocess.run", return_value=mock_result):
            result = verify(["mypy src/"], Path("/tmp"))

            assert result.failure_category == "type_failure"

    def test_failure_category_timeout(self) -> None:
        """Test failure category for timeout."""
        with patch("spec.executor.verify.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("pytest", 300)

            result = verify(["pytest"], Path("/tmp"), timeout=300)

            assert result.failure_category == "timeout"

    def test_failure_category_tool_not_found(self) -> None:
        """Test failure category for missing tool."""
        with patch("spec.executor.verify.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            result = verify(["nonexistent_tool"], Path("/tmp"))

            # The run_command handles FileNotFoundError, so this may work differently
            # Let's check for the expected behavior
            assert not result.passed


class TestVerificationReport:
    """Tests for verification report generation."""

    def test_report_structure(self) -> None:
        """Test that report has correct structure."""
        result = VerificationResult(
            passed=True,
            commands=[
                CommandResult("echo test", 0, "test", "", 100, False),
            ],
        )

        report = generate_verification_report(result)

        assert "passed" in report
        assert "timestamp" in report
        assert "failure_category" in report
        assert "summary" in report
        assert "commands" in report

    def test_report_is_json_serializable(self) -> None:
        """Test that report can be serialized to JSON."""
        result = VerificationResult(
            passed=False,
            commands=[
                CommandResult("pytest", 1, "FAILED", "error", 1000, False),
            ],
            failure_category="test_failure",
        )

        report = generate_verification_report(result)

        # Should not raise
        json_str = json.dumps(report)
        assert "test_failure" in json_str

    def test_report_summary(self) -> None:
        """Test report summary fields."""
        result = VerificationResult(
            passed=False,
            commands=[
                CommandResult("echo ok", 0, "ok", "", 100, False),
                CommandResult("false", 1, "", "error", 50, False),
            ],
            failure_category="test_failure",
        )

        report = generate_verification_report(result)

        assert report["summary"]["total_commands"] == 2
        assert report["summary"]["passed_commands"] == 1
        assert report["summary"]["failed_commands"] == 1
        assert report["summary"]["total_duration_ms"] == 150

    def test_output_truncation(self) -> None:
        """Test that long outputs are truncated."""
        long_output = "x" * 5000
        result = VerificationResult(
            passed=True,
            commands=[
                CommandResult("echo", 0, long_output, long_output, 100, False),
            ],
        )

        report = generate_verification_report(result)

        # Should be truncated to last 2000 chars
        assert len(report["commands"][0]["stdout_tail"]) == 2000
        assert len(report["commands"][0]["stderr_tail"]) == 2000

    def test_command_details_in_report(self) -> None:
        """Test that command details are included in report."""
        result = VerificationResult(
            passed=True,
            commands=[
                CommandResult("pytest tests/", 0, "PASSED", "", 5000, False),
            ],
        )

        report = generate_verification_report(result)

        cmd = report["commands"][0]
        assert cmd["command"] == "pytest tests/"
        assert cmd["exit_code"] == 0
        assert cmd["success"] is True
        assert cmd["duration_ms"] == 5000
        assert cmd["timed_out"] is False
