"""
claude-code backend: Spawn Claude Code agent sessions.

Supports two modes:
  - Headless (default): --print + --dangerously-skip-permissions, stdin prompt,
    stdout/stderr captured. Used by aip-1 JobDef.
  - Interactive (payload.interactive=True): No --print, inherits terminal,
    context via .claude/TASK.md. Used by interactive-1 JobDef.

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

    Spawns Claude Code in either headless or interactive mode.

    Payload schema:
        prompt: str - The prompt/instruction for Claude
        aip_path: str | None - Path to AIP YAML file (alternative to prompt)
        repo_path: str | None - Repository path (default: common.repo_path)
        allowed_tools: list[str] | None - Tool allowlist (default: all)
        model: str | None - Model to use
        max_turns: int | None - Maximum conversation turns
        capture_git: bool - Whether to capture git state (default True)
        interactive: bool - If True, launch TUI instead of headless (default False)
        resume: bool - If True, pass --resume to claude CLI (default False)
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
        interactive = payload.get("interactive", False)

        # Extract payload fields
        prompt = payload.get("prompt")
        prompt_type = payload.get("prompt_type")  # drift_fix, drift_verify, etc.
        spec_md = payload.get("spec_md")  # Markdown spec content
        epic_spec = payload.get("epic_spec")  # Epic expectations for ground truth

        # Handle prompt_type for drift steps - build prompt dynamically
        if prompt_type and not prompt:
            prompt = self._build_prompt_for_type(prompt_type, epic_spec, spec_md)

        # Use spec_md directly as prompt if no explicit prompt
        if spec_md and not prompt:
            prompt = spec_md

        if not prompt:
            raise BackendError(
                "claude-code backend requires 'prompt', 'prompt_type', or 'spec_md' in payload",
                backend=self.name,
                step_id=manifest.step_id,
            )

        # At this point prompt must be set
        assert prompt is not None

        repo_path = Path(payload.get("repo_path", common.repo_path))
        allowed_tools = payload.get("allowed_tools")
        model = payload.get("model")
        max_turns = payload.get("max_turns")
        capture_git = payload.get("capture_git", True)
        resume = payload.get("resume", False)
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

        # Prepare output files
        stdout_path = artifacts_dir / "stdout.txt"
        stderr_path = artifacts_dir / "stderr.txt"
        transcript_path = artifacts_dir / "transcript.jsonl"

        # Execute — branch based on interactive mode
        exit_code = 0

        if interactive:
            # Interactive: write TASK.md for reference, pass full spec as prompt
            # (same as headless - the full spec content is the prompt)
            cmd = self._build_interactive_command(
                prompt=prompt,
                model=model,
                resume=resume,
            )
            try:
                exit_code = self._execute_interactive(
                    cmd=cmd,
                    prompt=prompt,
                    repo_path=repo_path,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )
            except Exception as e:
                exit_code = 1
                stderr_path.write_text(f"Execution error: {e}\n")
                if not stdout_path.exists():
                    stdout_path.write_text("")
        else:
            # Headless: --print mode, stdin prompt, capture stdout
            cmd = self._build_command(
                prompt=prompt,
                repo_path=repo_path,
                allowed_tools=allowed_tools,
                model=model,
                max_turns=max_turns,
                policy=policy,
            )
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

    def _build_prompt_for_type(
        self,
        prompt_type: str,
        epic_spec: dict | None,
        spec_md: str | None = None,
    ) -> str:
        """Build a prompt based on type (drift_fix, drift_verify, etc.).

        Args:
            prompt_type: The type of prompt to build
            epic_spec: Optional epic spec expectations
            spec_md: Optional full spec markdown

        Returns:
            Built prompt string
        """
        from spec.executor.engine import _build_drift_fix_prompt, _build_drift_verify_prompt

        if prompt_type == "drift_fix":
            return _build_drift_fix_prompt(epic_spec, spec_md)
        elif prompt_type == "drift_verify":
            return _build_drift_verify_prompt(epic_spec, spec_md)
        else:
            raise BackendError(
                f"Unknown prompt_type: {prompt_type}",
                backend=self.name,
            )

    def _build_command(
        self,
        prompt: str,
        repo_path: Path,
        allowed_tools: list[str] | None,
        model: str | None,
        max_turns: int | None,
        policy: Policy,
    ) -> list[str]:
        """Build the claude CLI command for headless mode."""
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

    def _build_interactive_command(
        self,
        prompt: str,
        model: str | None = None,
        resume: bool = False,
    ) -> list[str]:
        """Build the claude CLI command for interactive TUI mode.

        Uses --dangerously-skip-permissions because specwright operates in
        a sandboxed context where the human has already approved the spec.
        The human still controls the session via the TUI.

        Args:
            prompt: Initial prompt to start the session with
            model: Optional model override
            resume: If True, pass --resume to continue previous session
        """
        cmd = ["claude"]

        if resume:
            cmd.append("--resume")

        if model:
            cmd.extend(["--model", model])

        # Use -- to signal end of options, then add prompt as positional argument
        # This prevents prompts starting with - or --- from being parsed as options
        cmd.append("--")
        cmd.append(prompt)

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
        """Execute claude CLI in headless mode and capture output."""
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

    def _execute_interactive(
        self,
        cmd: list[str],
        prompt: str,
        repo_path: Path,
        stdout_path: Path,
        stderr_path: Path,
    ) -> int:
        """Execute claude CLI in interactive TUI mode.

        Writes spec content to .claude/TASK.md for Claude to reference,
        then launches the TUI with terminal inherited (no PIPE).
        No timeout — the human controls when to exit.

        Args:
            cmd: The claude command to run
            prompt: Spec content to write as TASK.md
            repo_path: Target repository path
            stdout_path: Path to write stdout marker (empty for interactive)
            stderr_path: Path to write stderr marker (empty for interactive)

        Returns:
            Exit code from the claude process
        """
        # Write TASK.md so Claude has context
        self._write_task_md(repo_path, prompt)

        # Build shell command string for os.system (proper TTY handling)
        import shlex
        cmd_str = " ".join(shlex.quote(arg) for arg in cmd)

        try:
            # Launch TUI via os.system for proper terminal inheritance
            # subprocess.run doesn't properly attach PTY for interactive use
            original_cwd = os.getcwd()
            os.chdir(repo_path)
            exit_code = os.system(cmd_str)
            # os.system returns wait status, extract actual exit code
            if os.WIFEXITED(exit_code):
                exit_code = os.WEXITSTATUS(exit_code)
            else:
                exit_code = 1
        finally:
            os.chdir(original_cwd)
            # Write empty marker files for artifact consistency
            stdout_path.write_text("(interactive session — no stdout capture)\n")
            stderr_path.write_text("")

        return exit_code

    @staticmethod
    def _write_task_md(repo_path: Path, content: str) -> Path:
        """Write spec content to .claude/TASK.md in the target repo.

        Args:
            repo_path: Target repository path
            content: Markdown content to write

        Returns:
            Path to the written TASK.md file
        """
        claude_dir = repo_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        task_path = claude_dir / "TASK.md"
        task_path.write_text(content, encoding="utf-8")
        return task_path

    def _extract_transcript(self, repo_path: Path, transcript_path: Path) -> None:
        """Try to extract conversation transcript if available."""
        # Claude Code stores sessions in ~/.claude/projects/<cwd-slug>/
        # cwd slug: forward slashes → hyphens, leading slash stripped
        cwd_slug = str(repo_path).replace("/", "-").lstrip("-")
        claude_dir = Path.home() / ".claude" / "projects" / cwd_slug
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
