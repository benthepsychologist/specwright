"""
codex backend: Spawn Codex agent sessions.

Runs OpenAI Codex CLI in sandbox mode.

NOTE: This is a stub implementation. The Codex CLI may not be available
in all environments. The interface mirrors claude-code for consistency.
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


class CodexBackend(BackendBase):
    """
    Codex agent session backend.

    Spawns OpenAI Codex CLI for code generation tasks.

    Payload schema:
        prompt: str - The prompt/instruction for Codex
        repo_path: str | None - Repository path (default: common.repo_path)
        model: str | None - Model to use (default: codex)
        capture_git: bool - Whether to capture git state (default True)
    """

    @property
    def name(self) -> str:
        return "codex"

    def verify(self) -> None:
        """Verify codex CLI is available."""
        if shutil.which("codex") is None:
            raise BackendError(
                "codex CLI not found in PATH. "
                "Install from: https://github.com/openai/codex-cli",
                backend=self.name,
            )

    def dispatch(
        self,
        manifest: StepManifest,
        artifacts_dir: Path,
        policy: Policy,
    ) -> StepCapture:
        """Spawn Codex session and capture output."""
        from spec.executor.schemas import AgentCapture, GitCapture, StepCapture

        payload = manifest.payload
        common = manifest.common

        # Check if codex is available
        if shutil.which("codex") is None:
            # Return a stub capture indicating codex is not available
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = artifacts_dir / "stdout.txt"
            stderr_path = artifacts_dir / "stderr.txt"
            stdout_path.write_text("")
            stderr_path.write_text(
                "codex CLI not found in PATH. "
                "This backend is stubbed - install codex CLI to enable.\n"
            )
            return StepCapture(
                step_n=manifest.step_n,
                step_id=manifest.step_id,
                agent=AgentCapture(
                    stdout_file=stdout_path.name,
                    stderr_file=stderr_path.name,
                    exit_code=127,  # Command not found
                ),
            )

        # Extract payload fields
        prompt = payload.get("prompt")
        if not prompt:
            raise BackendError(
                "codex backend requires 'prompt' in payload",
                backend=self.name,
                step_id=manifest.step_id,
            )

        repo_path = Path(payload.get("repo_path", common.repo_path))
        model = payload.get("model", "codex")
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
        cmd = self._build_command(prompt, model)

        # Prepare output files
        stdout_path = artifacts_dir / "stdout.txt"
        stderr_path = artifacts_dir / "stderr.txt"

        # Execute
        exit_code = 0

        try:
            exit_code = self._execute_codex(
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

        # Capture post-step git state
        git_capture = None
        if capture_git:
            try:
                patch_path = artifacts_dir / "changes.patch"
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
            ),
        )

    def _build_command(self, prompt: str, model: str) -> list[str]:
        """Build the codex CLI command."""
        # NOTE: This is a hypothetical command structure
        # The actual codex CLI may have different arguments
        return [
            "codex",
            "--model", model,
            "--non-interactive",
        ]

    def _execute_codex(
        self,
        cmd: list[str],
        prompt: str,
        repo_path: Path,
        stdout_path: Path,
        stderr_path: Path,
        timeout_s: int,
    ) -> int:
        """Execute codex CLI and capture output."""
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
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            proc.wait()

            stdout_path.write_text("")
            stderr_path.write_text(f"Codex timed out after {timeout_s}s\n")
            return 124
