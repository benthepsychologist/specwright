"""
cmd backend: Execute shell commands.

Runs shell commands from payload.command, captures stdout/stderr/exit_code.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from spec.executor.backends.base import BackendBase, BackendError
from spec.executor.sandbox import PolicyViolation, SandboxEnforcer
from spec.executor.sandbox.capture import capture_git_state, capture_pre_step_state

if TYPE_CHECKING:
    from spec.executor.schemas import Policy, StepCapture, StepManifest


class CmdBackend(BackendBase):
    """
    Shell command execution backend.

    Payload schema:
        command: str - Shell command to execute
        shell: bool - Whether to use shell (default True)
        cwd: str | None - Working directory (default: common.repo_path)
        env: dict | None - Additional environment variables
        capture_git: bool - Whether to capture git state (default True)
    """

    @property
    def name(self) -> str:
        return "cmd"

    def dispatch(
        self,
        manifest: StepManifest,
        artifacts_dir: Path,
        policy: Policy,
    ) -> StepCapture:
        """Execute shell command and capture output."""
        from spec.executor.schemas import AgentCapture, GitCapture, StepCapture

        payload = manifest.payload
        common = manifest.common

        # Extract payload fields
        command = payload.get("command")
        if not command:
            raise BackendError(
                "cmd backend requires 'command' in payload",
                backend=self.name,
                step_id=manifest.step_id,
            )

        use_shell = payload.get("shell", True)
        cwd = Path(payload.get("cwd", common.repo_path))
        extra_env = payload.get("env", {})
        capture_git = payload.get("capture_git", True)
        timeout_s = common.timeout_s

        # Ensure artifacts directory exists
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Create sandbox enforcer
        enforcer = SandboxEnforcer(
            policy=policy,
            repo_path=common.repo_path,
            expected_branch=common.branch,
        )

        # Validate command against policy
        try:
            enforcer.full_check(command)
        except PolicyViolation as e:
            # Write violation to stderr and return failed capture
            stderr_path = artifacts_dir / "stderr.txt"
            stderr_path.write_text(f"Policy violation: {e}\n")

            return StepCapture(
                step_n=manifest.step_n,
                step_id=manifest.step_id,
                agent=AgentCapture(
                    stdout_file=str(artifacts_dir / "stdout.txt"),
                    stderr_file=str(stderr_path),
                    exit_code=126,  # Command cannot execute
                ),
            )

        # Capture pre-step git state if requested
        pre_git_state = None
        if capture_git:
            try:
                pre_git_state = capture_pre_step_state(
                    common.repo_path,
                    common.branch,
                    common.base_commit,
                    validate=True,
                )
            except Exception as e:
                # Log but don't fail - git capture is best-effort
                pre_git_state = {"error": str(e)}

        # Prepare file handles for output capture
        stdout_path = artifacts_dir / "stdout.txt"
        stderr_path = artifacts_dir / "stderr.txt"

        # Build environment
        import os

        env = os.environ.copy()
        env.update(extra_env)

        # Execute command
        try:
            with (
                open(stdout_path, "w") as stdout_file,
                open(stderr_path, "w") as stderr_file,
            ):
                result = subprocess.run(
                    command if use_shell else command.split(),
                    shell=use_shell,
                    cwd=cwd,
                    env=env,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=timeout_s,
                )
                exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124  # Standard timeout exit code
            with open(stderr_path, "a") as f:
                f.write(f"\nCommand timed out after {timeout_s}s\n")
        except Exception as e:
            exit_code = 1
            with open(stderr_path, "a") as f:
                f.write(f"\nCommand execution error: {e}\n")

        # Capture post-step git state
        git_capture = None
        if capture_git:
            try:
                patch_path = artifacts_dir / "changes.patch"
                git_capture = capture_git_state(
                    common.repo_path,
                    common.base_commit,
                    patch_output_path=patch_path,
                )
                # Fill in pre_status from pre-step capture
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
                # Git capture failed - continue without it
                pass

        return StepCapture(
            step_n=manifest.step_n,
            step_id=manifest.step_id,
            git=git_capture,
            agent=AgentCapture(
                stdout_file=str(stdout_path),
                stderr_file=str(stderr_path),
                exit_code=exit_code,
            ),
        )
