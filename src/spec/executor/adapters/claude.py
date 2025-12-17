"""
Claude Code CLI Adapter

Adapter for invoking Claude Code CLI with dual-mode support:
- interactive: TUI mode with transcript recording (default)
- oneshot: non-interactive JSON output mode
"""

from __future__ import annotations

import json
import logging
import os
import pty
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from spec.executor.adapters.base import (
    AgentAdapter,
    ProtocolError,
    ToolNotFoundError,
)

logger = logging.getLogger(__name__)

# Default timeout for Claude execution (10 minutes)
CLAUDE_TIMEOUT_SECONDS = 600

# Required fields in agent.json
REQUIRED_AGENT_JSON_FIELDS = [
    "completion_status",
    "confidence",
    "files_modified",
    "commands_executed",
]

# Interactive mode prompt template
INTERACTIVE_PROMPT_TEMPLATE = """{task_prompt}

## Output Requirements

Before exiting, you MUST create these files in the output directory:

Output directory: {output_dir}

1. **patch.diff**: Run `git diff > {output_dir}/patch.diff`

2. **cmdlog.txt**: Create `{output_dir}/cmdlog.txt` with a log of commands you executed

3. **agent.json**: Create `{output_dir}/agent.json` with this structure:
   ```json
   {{
     "completion_status": "success",
     "confidence": 0.85,
     "files_modified": ["path/to/file.py"],
     "commands_executed": ["ruff check ."],
     "notes": "optional notes"
   }}
   ```

The output directory is also available as $SPEC_OUTPUT_DIR environment variable.
"""


class ClaudeAdapter(AgentAdapter):
    """Adapter for Claude Code CLI with dual-mode support."""

    def __init__(self) -> None:
        self._verified = False
        self._script_available = False

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "claude"

    def verify(self) -> None:
        """
        Verify Claude CLI exists and check transcript recording capability.

        Raises:
            ToolNotFoundError: If claude not in PATH
        """
        # Check claude CLI exists
        if shutil.which("claude") is None:
            raise ToolNotFoundError("claude", "claude not found in PATH")

        # Check if script command is available for transcript recording
        self._script_available = shutil.which("script") is not None
        if not self._script_available:
            logger.info(
                "script command not found; will use PTY fallback for transcript recording"
            )

        self._verified = True

    def execute(
        self,
        input_dir: Path,
        output_dir: Path,
        repo_root: Path,
        timeout: int = CLAUDE_TIMEOUT_SECONDS,
    ) -> None:
        """
        Execute Claude CLI in configured mode.

        Args:
            input_dir: Directory containing contract.yaml, prompt.md, repo_state.json
            output_dir: Directory where adapter writes patch.diff, agent.json, cmdlog.txt
            repo_root: Repository root for working directory
            timeout: Timeout in seconds (advisory for interactive, hard for oneshot)

        Raises:
            ToolNotFoundError: If claude not found
            ProtocolError: If adapter contract violated
        """
        # Ensure verified
        if not self._verified:
            self.verify()

        # Read mode from contract.yaml
        mode = self._get_mode(input_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if mode == "oneshot":
            self._execute_oneshot(input_dir, output_dir, repo_root, timeout)
        else:
            self._execute_interactive(input_dir, output_dir, repo_root, timeout)

    def _get_mode(self, input_dir: Path) -> str:
        """
        Extract adapter mode from contract.yaml.

        Returns 'interactive' (default) or 'oneshot'.
        """
        contract_path = input_dir / "contract.yaml"
        if not contract_path.exists():
            return "interactive"

        try:
            with open(contract_path) as f:
                contract = yaml.safe_load(f)

            adapter_config = contract.get("adapter", {})
            return adapter_config.get("mode", "interactive")
        except (yaml.YAMLError, OSError):
            return "interactive"

    def _execute_interactive(
        self,
        input_dir: Path,
        output_dir: Path,
        repo_root: Path,
        timeout: int,
    ) -> None:
        """
        Execute Claude in interactive (TUI) mode with transcript recording.

        Timeout is advisory only - logs warning but doesn't kill.
        """
        # Capture repo state before
        repo_state_before = self._capture_repo_state(repo_root)
        (output_dir / "repo_state_before.json").write_text(
            json.dumps(repo_state_before, indent=2)
        )

        # Read and build prompt
        prompt_path = input_dir / "prompt.md"
        if not prompt_path.exists():
            raise ProtocolError(
                f"prompt.md not found in {input_dir}",
                failure_category="missing_input",
            )

        task_prompt = prompt_path.read_text()
        full_prompt = INTERACTIVE_PROMPT_TEMPLATE.format(
            task_prompt=task_prompt,
            output_dir=str(output_dir),
        )

        # Set up environment
        env = os.environ.copy()
        env["SPEC_OUTPUT_DIR"] = str(output_dir)

        # Build claude command
        transcript_path = output_dir / "claude.transcript.txt"

        # Launch claude with transcript recording
        if self._script_available:
            self._run_with_script(
                full_prompt, transcript_path, repo_root, env, timeout
            )
        else:
            self._run_with_pty(full_prompt, transcript_path, repo_root, env, timeout)

        # Capture repo state after
        repo_state_after = self._capture_repo_state(repo_root)
        (output_dir / "repo_state_after.json").write_text(
            json.dumps(repo_state_after, indent=2)
        )

        # Validate and backfill artifacts
        warnings = self._backfill_artifacts(output_dir, repo_root)
        for warning in warnings:
            logger.warning(f"Artifact backfill: {warning}")

        # Validate agent.json
        self._validate_agent_json(output_dir / "agent.json")

    def _run_with_script(
        self,
        prompt: str,
        transcript_path: Path,
        repo_root: Path,
        env: dict[str, str],
        timeout: int,
    ) -> None:
        """Run claude with script command for transcript recording."""
        # Write prompt to temp file for -p flag
        prompt_file = transcript_path.parent / ".prompt.tmp"
        prompt_file.write_text(prompt)

        try:
            # script -q -c "claude ..." transcript.txt
            claude_cmd = f'claude --dangerously-skip-permissions -p "{prompt_file}"'
            cmd = ["script", "-q", "-c", claude_cmd, str(transcript_path)]

            logger.info(f"Launching claude (interactive mode) in {repo_root}")
            subprocess.run(
                cmd,
                cwd=repo_root,
                env=env,
                # No timeout - interactive mode is advisory
            )
        finally:
            prompt_file.unlink(missing_ok=True)

    def _run_with_pty(
        self,
        prompt: str,
        transcript_path: Path,
        repo_root: Path,
        env: dict[str, str],
        timeout: int,
    ) -> None:
        """Run claude with PTY fallback for transcript recording."""
        # Write prompt to temp file
        prompt_file = transcript_path.parent / ".prompt.tmp"
        prompt_file.write_text(prompt)

        transcript_lines: list[bytes] = []

        def read_output(fd: int) -> bytes:
            data = os.read(fd, 1024)
            if data:
                transcript_lines.append(data)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            return data

        try:
            cmd = ["claude", "--dangerously-skip-permissions", "-p", str(prompt_file)]
            logger.info(f"Launching claude (interactive mode, PTY fallback) in {repo_root}")

            # Use pty.spawn for interactive session
            old_cwd = os.getcwd()
            os.chdir(repo_root)

            # Update environment
            for key, value in env.items():
                os.environ[key] = value

            try:
                pty.spawn(cmd, read_output)
            finally:
                os.chdir(old_cwd)

            # Write transcript
            transcript_path.write_bytes(b"".join(transcript_lines))
        finally:
            prompt_file.unlink(missing_ok=True)

    def _execute_oneshot(
        self,
        input_dir: Path,
        output_dir: Path,
        repo_root: Path,
        timeout: int,
    ) -> None:
        """
        Execute Claude in oneshot (non-interactive) mode.

        Uses --print --output-format json for structured output.
        Timeout is enforced (hard kill).
        """
        # Read prompt
        prompt_path = input_dir / "prompt.md"
        if not prompt_path.exists():
            raise ProtocolError(
                f"prompt.md not found in {input_dir}",
                failure_category="missing_input",
            )

        prompt = prompt_path.read_text()

        # Build command
        cmd = [
            "claude",
            "--print",
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
            "-p",
            prompt,
        ]

        # Check for schema file
        schema_path = repo_root / ".specwright/artifacts/schemas/claude_output.schema.json"
        if schema_path.exists():
            cmd.extend(["--json-schema", str(schema_path)])

        # Execute with hard timeout
        try:
            logger.info(f"Launching claude (oneshot mode) in {repo_root}")
            result = subprocess.run(
                cmd,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as err:
            raise ProtocolError(
                f"Claude timed out after {timeout}s",
                failure_category="timeout",
            ) from err

        if result.returncode != 0:
            raise ProtocolError(
                f"Claude exited with code {result.returncode}: {result.stderr[:500]}",
                failure_category="claude_error",
            )

        # Parse JSON output
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as err:
            raise ProtocolError(
                f"Claude output is not valid JSON: {err}",
                failure_category="invalid_output",
            ) from err

        # Extract and write artifacts
        self._extract_oneshot_artifacts(output, output_dir)

    def _extract_oneshot_artifacts(
        self, output: dict[str, Any], output_dir: Path
    ) -> None:
        """Extract artifacts from oneshot JSON output."""
        # Extract patch_diff
        patch_diff = output.get("patch_diff", "")
        (output_dir / "patch.diff").write_text(patch_diff)

        # Extract agent report
        agent_report = {
            "completion_status": output.get("completion_status", "partial"),
            "confidence": output.get("confidence", 0.0),
            "files_modified": output.get("files_modified", []),
            "commands_executed": output.get("commands_executed", []),
            "notes": output.get("notes", ""),
        }
        (output_dir / "agent.json").write_text(json.dumps(agent_report, indent=2))

        # Write cmdlog
        commands = output.get("commands_executed", [])
        cmdlog = "\n".join(f"CMD: {cmd}" for cmd in commands)
        (output_dir / "cmdlog.txt").write_text(cmdlog)

    def _capture_repo_state(self, repo_root: Path) -> dict[str, str]:
        """Capture current git state (commit SHA and status)."""
        state: dict[str, str] = {}

        # Get current commit
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
            state["commit"] = result.stdout.strip()
        except subprocess.CalledProcessError:
            state["commit"] = "unknown"

        # Get status
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
            state["status"] = result.stdout.strip()
        except subprocess.CalledProcessError:
            state["status"] = "unknown"

        return state

    def _backfill_artifacts(self, output_dir: Path, repo_root: Path) -> list[str]:
        """
        Backfill missing artifacts from git state.

        Returns list of warnings for backfilled artifacts.
        """
        warnings: list[str] = []

        # Backfill patch.diff
        patch_path = output_dir / "patch.diff"
        if not patch_path.exists():
            try:
                result = subprocess.run(
                    ["git", "diff"],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                patch_path.write_text(result.stdout)
                warnings.append("patch.diff backfilled from git diff")
            except subprocess.CalledProcessError:
                patch_path.write_text("# No diff available\n")
                warnings.append("patch.diff backfilled with empty stub")

        # Backfill cmdlog.txt
        cmdlog_path = output_dir / "cmdlog.txt"
        if not cmdlog_path.exists():
            transcript_path = output_dir / "claude.transcript.txt"
            if transcript_path.exists():
                cmdlog_path.write_text(
                    f"# Commands not logged separately\n# See transcript: {transcript_path.name}\n"
                )
            else:
                cmdlog_path.write_text("# No commands logged\n")
            warnings.append("cmdlog.txt backfilled with stub")

        # Backfill agent.json
        agent_json_path = output_dir / "agent.json"
        if not agent_json_path.exists():
            # Get files modified from git
            files_modified: list[str] = []
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only"],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                files_modified = [f for f in result.stdout.strip().split("\n") if f]
            except subprocess.CalledProcessError:
                pass

            agent_report = {
                "completion_status": "partial",
                "confidence": 0.0,
                "files_modified": files_modified,
                "commands_executed": [],
                "notes": "Backfilled by adapter - Claude did not produce agent.json",
            }
            agent_json_path.write_text(json.dumps(agent_report, indent=2))
            warnings.append("agent.json backfilled with partial status")

        return warnings

    def _validate_agent_json(self, agent_json_path: Path) -> None:
        """
        Validate agent.json has required fields.

        Raises:
            ProtocolError: If validation fails
        """
        if not agent_json_path.exists():
            raise ProtocolError(
                "agent.json not found after backfill attempt",
                failure_category="missing_output",
            )

        try:
            with open(agent_json_path) as f:
                agent_report = json.load(f)
        except json.JSONDecodeError as err:
            raise ProtocolError(
                f"agent.json is not valid JSON: {err}",
                failure_category="invalid_output",
            ) from err

        # Check required fields
        missing_fields = [
            field for field in REQUIRED_AGENT_JSON_FIELDS if field not in agent_report
        ]
        if missing_fields:
            raise ProtocolError(
                f"agent.json missing required fields: {missing_fields}",
                failure_category="invalid_output",
            )
