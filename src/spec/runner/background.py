"""AIP v3 Background Runner - Claude Code subprocess execution.

This module invokes Claude Code as a background subprocess using
--dangerously-skip-permissions --print --output-format stream-json
and captures the output for artifact collection.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import selectors
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from spec.autogov.exceptions import SpecwrightError
from spec.runner.context import render_task_md, write_task_md

if TYPE_CHECKING:
    from spec.aip.models import AIPv3


class RunnerError(SpecwrightError):
    """Error during Claude invocation."""

    exit_code = 6


@dataclass
class RunResult:
    """Result of a background Claude run."""

    exit_code: int
    duration_seconds: float
    timeout_reached: bool = False
    transcript_path: Path | None = None
    started_at: str = ""
    completed_at: str = ""
    command: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = datetime.now(UTC).isoformat()


def find_claude_binary() -> str:
    """Find the claude binary.

    Returns:
        Path to claude binary

    Raises:
        RunnerError: If claude is not found
    """
    # Check if claude is in PATH
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    # Common locations
    common_paths = [
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
    ]

    for path in common_paths:
        if path.exists() and os.access(path, os.X_OK):
            return str(path)

    raise RunnerError(
        "Claude binary not found. Install Claude Code: "
        "npm install -g @anthropic-ai/claude-code"
    )


def run_background(
    aip: AIPv3,
    timeout: int | None = None,
    transcript_path: Path | None = None,
    print_output: bool = False,
) -> RunResult:
    """Run Claude Code in background mode.

    Invokes: claude --dangerously-skip-permissions --print --output-format stream-json

    Args:
        aip: The AIP to execute
        timeout: Timeout in seconds (default: from aip.execution or 1800)
        transcript_path: Path to save transcript (default: temp file)
        print_output: Also print output to stdout

    Returns:
        RunResult with execution details

    Raises:
        RunnerError: If Claude invocation fails
    """
    repo_path = Path(aip.workspace.repo_path)

    # Resolve timeout
    if timeout is None:
        timeout = aip.execution.timeout_seconds if aip.execution else 1800

    # Write TASK.md
    write_task_md(aip, repo_path)
    task_md = render_task_md(aip)

    # Claude --print requires input via stdin or as a prompt argument.
    # Prefer prompt argument (more reliable than stdin across versions), but
    # fall back to stdin if the prompt is unusually large.
    prompt = task_md if task_md.endswith("\n") else f"{task_md}\n"
    use_prompt_arg = len(prompt.encode("utf-8")) <= 32_000

    # Build command
    claude_bin = find_claude_binary()
    cmd = [
        claude_bin,
        "--dangerously-skip-permissions",
        "--print",
        "--verbose",
        "--output-format",
        "stream-json",
    ]

    if use_prompt_arg:
        cmd.append(prompt)

    # Prepare transcript file
    if transcript_path is None:
        transcript_path = repo_path / ".claude" / "transcript.jsonl"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(UTC).isoformat()
    start_time = time.time()
    timeout_reached = False
    error: str | None = None
    exit_code = 0

    try:
        # Run Claude with output capture
        with open(transcript_path, "w", encoding="utf-8") as transcript_file:
            process = subprocess.Popen(
                cmd,
                cwd=repo_path,
                stdin=subprocess.DEVNULL if use_prompt_arg else subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
            )

            if not use_prompt_arg and process.stdin is not None:
                try:
                    process.stdin.write(prompt.encode("utf-8"))
                    process.stdin.flush()
                finally:
                    process.stdin.close()

            # Stream output to file (and optionally stdout) without blocking
            # indefinitely on readline(). This allows timeout enforcement even
            # when the subprocess is silent.
            sel: selectors.BaseSelector | None = None
            if process.stdout is not None:
                sel = selectors.DefaultSelector()
                sel.register(process.stdout, selectors.EVENT_READ)

            while True:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    timeout_reached = True
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break

                # If process ended, drain any remaining output and exit.
                if process.poll() is not None:
                    if process.stdout is not None:
                        fd = process.stdout.fileno()
                        while True:
                            rest_b = os.read(fd, 64 * 1024)
                            if not rest_b:
                                break
                            rest = rest_b.decode("utf-8", errors="replace")
                            transcript_file.write(rest)
                            transcript_file.flush()
                            if print_output:
                                print(rest, end="")
                    break

                # Wait briefly for output availability.
                if sel is None:
                    time.sleep(0.05)
                    continue

                events = sel.select(timeout=0.1)
                if not events:
                    continue

                for key, _mask in events:
                    stream = key.fileobj
                    try:
                        fd = stream.fileno()
                        chunk_b = os.read(fd, 64 * 1024)
                    except Exception:
                        chunk_b = b""
                    if not chunk_b:
                        continue
                    chunk = chunk_b.decode("utf-8", errors="replace")
                    transcript_file.write(chunk)
                    transcript_file.flush()
                    if print_output:
                        print(chunk, end="")

            if sel is not None:
                try:
                    sel.close()
                except Exception:
                    pass

            exit_code = process.returncode or 0

    except FileNotFoundError as e:
        error = f"Claude binary not found: {e}"
        exit_code = 127
    except PermissionError as e:
        error = f"Permission denied: {e}"
        exit_code = 126
    except Exception as e:
        error = f"Execution error: {e}"
        exit_code = 1
    finally:
        # Clean up TASK.md (optional - keep for debugging)
        # cleanup_task_md(repo_path)
        pass

    duration = time.time() - start_time
    completed_at = datetime.now(UTC).isoformat()

    return RunResult(
        exit_code=exit_code,
        duration_seconds=duration,
        timeout_reached=timeout_reached,
        transcript_path=transcript_path,
        started_at=started_at,
        completed_at=completed_at,
        command=cmd,
        error=error,
    )
