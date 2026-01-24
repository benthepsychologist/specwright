"""
claude-code backend: Spawn Claude Code agent sessions.

Runs Claude Code CLI in dangerous mode with a tool allowlist.

SECURITY NOTE:
    This backend uses a tool allowlist approach rather than the SandboxEnforcer
    used by the cmd backend. The allowlist blocks direct git push/merge commands,
    but indirect execution (e.g., via Python subprocess) is not blocked.

    For high-security scenarios, use the cmd backend with explicit commands.
    The allowlist provides defense-in-depth but is not a hard sandbox.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from spec.executor.backends.base import BackendBase, BackendError
from spec.executor.sandbox.capture import capture_git_state, capture_pre_step_state

if TYPE_CHECKING:
    from spec.executor.schemas import Policy, StepCapture, StepManifest


class ClaudeCodeBackend(BackendBase):
    """
    Claude Code agent session backend.

    Spawns Claude Code in dangerous mode (--dangerously-skip-permissions)
    with --print for non-interactive execution.

    Payload schema:
        prompt: str - The prompt/instruction for Claude
        aip_path: str | None - Path to AIP YAML file (alternative to prompt)
        repo_path: str | None - Repository path (default: common.repo_path)
        allowed_tools: list[str] | None - Tool allowlist (default: all)
        model: str | None - Model to use
        max_turns: int | None - Maximum conversation turns
        capture_git: bool - Whether to capture git state (default True)
    """

    @property
    def name(self) -> str:
        return "claude-code"

    def verify(self) -> None:
        """Verify claude CLI is available."""
        if shutil.which("claude") is None:
            raise BackendError(
                "claude CLI not found in PATH",
                backend=self.name,
            )

    def dispatch(
        self,
        manifest: StepManifest,
        artifacts_dir: Path,
        policy: Policy,
        capture_patch: bool = False,
    ) -> StepCapture:
        """Spawn Claude Code session and capture output."""
        from spec.executor.schemas import AgentCapture, GitCapture, StepCapture

        payload = manifest.payload
        common = manifest.common

        # Extract payload fields
        prompt = payload.get("prompt")
        aip_path = payload.get("aip_path")
        aip_data = payload.get("aip")  # Direct AIP dict from envelope

        if not prompt and not aip_path and not aip_data:
            raise BackendError(
                "claude-code backend requires 'prompt', 'aip_path', or 'aip' in payload",
                backend=self.name,
                step_id=manifest.step_id,
            )

        # If we have AIP data directly, build prompt from it
        if aip_data and not prompt:
            prompt = self._build_prompt_from_aip_data(aip_data)
        # If we have an AIP path, build prompt from it
        elif aip_path and not prompt:
            prompt = self._build_prompt_from_aip(Path(aip_path))

        # At this point prompt must be set
        assert prompt is not None

        repo_path = Path(payload.get("repo_path", common.repo_path))
        allowed_tools = payload.get("allowed_tools")
        model = payload.get("model")
        max_turns = payload.get("max_turns")
        capture_git = payload.get("capture_git", True)
        timeout_s = common.timeout_s

        # Ensure artifacts directory exists
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Capture pre-step git state
        pre_git_state = None
        if capture_git:
            try:
                pre_git_state = capture_pre_step_state(
                    repo_path,
                    common.branch,
                    common.base_commit,
                    validate=True,
                )
            except Exception as e:
                pre_git_state = {"error": str(e)}

        # Build command
        cmd = self._build_command(
            prompt=prompt,
            repo_path=repo_path,
            allowed_tools=allowed_tools,
            model=model,
            max_turns=max_turns,
            policy=policy,
        )

        # Prepare output files
        stdout_path = artifacts_dir / "stdout.txt"
        stderr_path = artifacts_dir / "stderr.txt"
        transcript_path = artifacts_dir / "transcript.jsonl"

        # Execute
        exit_code = 0

        try:
            exit_code = self._execute_claude(
                cmd=cmd,
                prompt=prompt,
                repo_path=repo_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_s=timeout_s,
            )
        except Exception as e:
            exit_code = 1
            stderr_path.write_text(f"Execution error: {e}\n")
            if not stdout_path.exists():
                stdout_path.write_text("")

        # Try to extract transcript if available
        self._extract_transcript(repo_path, transcript_path)

        # Capture post-step git state
        git_capture = None
        if capture_git:
            try:
                # Only generate patch file if capture_patch is True
                patch_path = artifacts_dir / "changes.patch" if capture_patch else None
                git_capture = capture_git_state(
                    repo_path,
                    common.base_commit,
                    patch_output_path=patch_path,
                )
                if pre_git_state and "pre_status" in pre_git_state:
                    git_capture = GitCapture(
                        base_commit=git_capture.base_commit,
                        pre_status=pre_git_state["pre_status"],
                        post_status=git_capture.post_status,
                        patch_file=git_capture.patch_file,
                        changed_files=git_capture.changed_files,
                        commit_sha=git_capture.commit_sha,
                        working_tree_dirty=git_capture.working_tree_dirty,
                    )
            except Exception:
                pass

        return StepCapture(
            step_n=manifest.step_n,
            step_id=manifest.step_id,
            git=git_capture,
            agent=AgentCapture(
                stdout_file=stdout_path.name,
                stderr_file=stderr_path.name,
                exit_code=exit_code,
                transcript_file=transcript_path.name if transcript_path.exists() else None,
            ),
        )

    def _build_prompt_from_aip(self, aip_path: Path) -> str:
        """Build a prompt from an AIP YAML file."""
        import yaml

        if not aip_path.exists():
            raise BackendError(
                f"AIP file not found: {aip_path}",
                backend=self.name,
            )

        with open(aip_path) as f:
            aip = yaml.safe_load(f)

        return self._build_prompt_from_aip_data(aip)

    def _build_prompt_from_aip_data(self, aip: dict) -> str:
        """Build a prompt from an AIP dict."""
        parts = []

        # Handle AIPv3 structure (metadata.title, goal) or legacy (title, description)
        title = aip.get("title")
        if not title and "metadata" in aip:
            title = aip["metadata"].get("title") or aip["metadata"].get("spec_id")
        if title:
            parts.append(f"# {title}")

        # Goal (AIPv3) or description (legacy)
        goal = aip.get("goal") or aip.get("description")
        if goal:
            parts.append(f"\n{goal}")

        # Acceptance criteria
        if "acceptance_criteria" in aip:
            parts.append("\n## Acceptance Criteria")
            for criterion in aip["acceptance_criteria"]:
                parts.append(f"- {criterion}")

        # Final verification (AIPv3)
        if "final_verification" in aip:
            parts.append("\n## Verification Commands")
            for v in aip["final_verification"]:
                if isinstance(v, dict):
                    parts.append(f"- `{v.get('cmd', v)}`")
                else:
                    parts.append(f"- `{v}`")

        # Phases (AIPv3) or legacy phases
        if "phases" in aip:
            parts.append("\n## Implementation Phases")
            for i, phase in enumerate(aip["phases"], 1):
                phase_title = phase.get("title", f"Phase {i}")
                parts.append(f"\n### {phase_title}")
                if "description" in phase:
                    parts.append(phase["description"])
                if "tasks" in phase:
                    for task in phase["tasks"]:
                        if isinstance(task, dict):
                            parts.append(f"- {task.get('description', task)}")
                        else:
                            parts.append(f"- {task}")

        return "\n".join(parts)

    def _build_command(
        self,
        prompt: str,
        repo_path: Path,
        allowed_tools: list[str] | None,
        model: str | None,
        max_turns: int | None,
        policy: Policy,
    ) -> list[str]:
        """Build the claude CLI command."""
        cmd = [
            "claude",
            "--print",  # Non-interactive mode
            "--dangerously-skip-permissions",  # Required for automation
            "--output-format", "text",  # Text output for stdout capture
        ]

        # Add allowed tools if specified
        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])
        else:
            # Build default allowlist based on policy
            default_tools = self._build_default_tools(policy)
            if default_tools:
                cmd.extend(["--allowedTools", ",".join(default_tools)])

        # Add model if specified
        if model:
            cmd.extend(["--model", model])

        # Add max turns if specified
        if max_turns:
            cmd.extend(["--max-turns", str(max_turns)])

        return cmd

    def _build_default_tools(self, policy: Policy) -> list[str]:
        """Build default tool allowlist based on policy."""
        tools = [
            # File operations
            "Read",
            "Edit",
            "Write",
            "Glob",
            "Grep",
            # Git read-only
            "Bash(git status:*)",
            "Bash(git diff:*)",
            "Bash(git log:*)",
            "Bash(git show:*)",
            "Bash(git branch --list:*)",
            # Git recovery
            "Bash(git restore:*)",
            # Dev tools
            "Bash(python:*)",
            "Bash(pytest:*)",
            "Bash(ruff:*)",
            "Bash(mypy:*)",
            "Bash(make:*)",
            "Bash(npm:*)",
            "Bash(ls:*)",
            "Bash(cat:*)",
            "Bash(head:*)",
            "Bash(tail:*)",
            "Bash(wc:*)",
            "Bash(find:*)",
            "Bash(echo:*)",
        ]

        # Add git commit if allowed
        if policy.allow_commit:
            tools.extend([
                "Bash(git add:*)",
                "Bash(git commit:*)",
            ])

        # Note: We never add git push or git merge to the allowlist
        # even if policy allows them - that would be done in a separate step

        return tools

    def _execute_claude(
        self,
        cmd: list[str],
        prompt: str,
        repo_path: Path,
        stdout_path: Path,
        stderr_path: Path,
        timeout_s: int,
    ) -> int:
        """Execute claude CLI and capture output."""
        # Start process with new session for clean timeout handling
        proc = subprocess.Popen(
            cmd,
            cwd=repo_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        try:
            stdout, stderr = proc.communicate(input=prompt, timeout=timeout_s)
            stdout_path.write_text(stdout)
            stderr_path.write_text(stderr)
            return proc.returncode
        except subprocess.TimeoutExpired:
            # Kill the entire process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            proc.wait()

            stdout_path.write_text("")
            stderr_path.write_text(f"Claude timed out after {timeout_s}s\n")
            return 124  # Standard timeout exit code

    def _extract_transcript(self, repo_path: Path, transcript_path: Path) -> None:
        """Try to extract conversation transcript if available."""
        # Claude Code stores conversation in ~/.claude/conversations/
        # This is best-effort - may not always be available
        claude_dir = Path.home() / ".claude" / "conversations"
        if not claude_dir.exists():
            return

        # Find most recent conversation file
        conversations = sorted(
            claude_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if conversations:
            # Copy most recent conversation as transcript
            try:
                shutil.copy(conversations[0], transcript_path)
            except (OSError, shutil.Error):
                pass
