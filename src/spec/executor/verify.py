"""
Verification Runner

Runs verification commands (tests, lint, build) with timeout and output capture.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class CommandResult:
    """Result of a single command execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def success(self) -> bool:
        """Command succeeded if exit code is 0 and didn't time out."""
        return self.exit_code == 0 and not self.timed_out


@dataclass
class VerificationResult:
    """Result of running all verification commands."""

    passed: bool
    commands: list[CommandResult] = field(default_factory=list)
    failure_category: str | None = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


def _categorize_failure(command: str, stderr: str, stdout: str) -> str:
    """
    Determine the failure category based on command and output.

    Returns one of: test_failure, lint_failure, type_failure, build_failure, timeout, tool_not_found
    """
    command_lower = command.lower()

    # Check for tool not found
    if "not found" in stderr.lower() or "command not found" in stderr.lower():
        return "tool_not_found"

    # Categorize by command name
    if "pytest" in command_lower or "test" in command_lower:
        return "test_failure"
    if "ruff" in command_lower or "lint" in command_lower or "flake" in command_lower:
        return "lint_failure"
    if "mypy" in command_lower or "pyright" in command_lower or "type" in command_lower:
        return "type_failure"
    if "build" in command_lower or "make" in command_lower or "pip" in command_lower:
        return "build_failure"

    # Default to test failure for unknown commands
    return "test_failure"


def run_command(
    command: str,
    cwd: Path,
    timeout: int = 300,
) -> CommandResult:
    """
    Run a single command with timeout and output capture.

    Args:
        command: Shell command to run (will be parsed safely with shlex)
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        CommandResult with execution details

    Note:
        Uses shlex.split() to parse the command, avoiding shell=True.
        This prevents shell injection vulnerabilities.
    """
    start_time = time.monotonic()

    try:
        # Parse command safely - no shell injection possible
        args = shlex.split(command)

        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            # Explicitly no shell=True - commands are parsed with shlex
        )

        duration_ms = int((time.monotonic() - start_time) * 1000)

        return CommandResult(
            command=command,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
            timed_out=False,
        )

    except subprocess.TimeoutExpired as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        # e.stdout and e.stderr can be bytes or str depending on text mode
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return CommandResult(
            command=command,
            exit_code=-1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=True,
        )

    except (FileNotFoundError, PermissionError) as e:
        # Command not found or not executable
        duration_ms = int((time.monotonic() - start_time) * 1000)
        cmd_name = shlex.split(command)[0] if command else "unknown"
        return CommandResult(
            command=command,
            exit_code=127,  # Standard "command not found" exit code
            stdout="",
            stderr=f"Command not found or not executable: {cmd_name} ({e})",
            duration_ms=duration_ms,
            timed_out=False,
        )


def run_commands(
    commands: list[str],
    cwd: Path,
    timeout: int = 300,
) -> list[CommandResult]:
    """
    Run multiple commands sequentially with timeout.

    Args:
        commands: List of shell commands to run
        cwd: Working directory
        timeout: Timeout in seconds per command

    Returns:
        List of CommandResult, one per command
    """
    results: list[CommandResult] = []

    for command in commands:
        result = run_command(command, cwd, timeout)
        results.append(result)

    return results


def verify(
    commands: list[str],
    cwd: Path,
    timeout: int = 300,
) -> VerificationResult:
    """
    Run verification commands and determine overall result.

    Args:
        commands: List of verification commands (tests, lint, etc.)
        cwd: Working directory
        timeout: Timeout in seconds per command

    Returns:
        VerificationResult with passed status and failure category
    """
    results = run_commands(commands, cwd, timeout)

    # Check if all commands passed
    all_passed = all(r.success for r in results)

    # Find failure category if any command failed
    failure_category = None
    if not all_passed:
        for result in results:
            if not result.success:
                if result.timed_out:
                    failure_category = "timeout"
                else:
                    failure_category = _categorize_failure(
                        result.command,
                        result.stderr,
                        result.stdout,
                    )
                break  # Use first failure's category

    return VerificationResult(
        passed=all_passed,
        commands=results,
        failure_category=failure_category,
    )


def generate_verification_report(result: VerificationResult) -> dict[str, Any]:
    """
    Generate a machine-readable verification report.

    Returns a dict suitable for JSON serialization.
    """
    return {
        "passed": result.passed,
        "timestamp": result.timestamp,
        "failure_category": result.failure_category,
        "summary": {
            "total_commands": len(result.commands),
            "passed_commands": sum(1 for c in result.commands if c.success),
            "failed_commands": sum(1 for c in result.commands if not c.success),
            "total_duration_ms": sum(c.duration_ms for c in result.commands),
        },
        "commands": [
            {
                "command": c.command,
                "exit_code": c.exit_code,
                "success": c.success,
                "duration_ms": c.duration_ms,
                "timed_out": c.timed_out,
                "stdout_tail": c.stdout[-2000:] if len(c.stdout) > 2000 else c.stdout,
                "stderr_tail": c.stderr[-2000:] if len(c.stderr) > 2000 else c.stderr,
            }
            for c in result.commands
        ],
    }
