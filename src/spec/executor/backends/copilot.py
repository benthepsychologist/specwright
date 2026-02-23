"""
copilot backend: Spawn GitHub Copilot CLI agent sessions.

Supports two modes:
  - Headless (default): copilot -p "<prompt>" --model <model>, stdout/stderr
    captured. Used by aip-1 JobDef.
  - Interactive (payload.interactive=True): Launch copilot TUI with same
    deny-tool flags, user sees prompt.

Tool safety:
    All git operations are denied via --deny-tool 'shell(git*)'. The agent
    stays in the file-change lane (read, write, edit, test, build). The job
    handles commits as a separate step; user can reset if the job fails.
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

DEFAULT_MODEL = "claude-sonnet-4.5"


class CopilotBackend(BackendBase):
    """
    GitHub Copilot CLI agent session backend.

    Spawns Copilot CLI in either headless or interactive mode.

    Payload schema:
        prompt: str - The prompt/instruction for the agent (required)
        repo_path: str | None - Repository path (default: common.repo_path)
        models: list[str] | None - Ordered model preferences (default: [claude-sonnet-4.5])
        capture_git: bool - Whether to capture git state (default True)
        interactive: bool - If True, launch TUI instead of headless (default False)
        timeout_s: int | None - Step timeout override (default: common.timeout_s)
    """

    @property
    def name(self) -> str:
        return "copilot"

    def verify(self) -> None:
        """Verify Copilot CLI is available and supports required flags.

        Checks:
            1. CLI binary exists on PATH
            2. --deny-tool flag is supported (via --help output)

        Note: Authentication is deferred to dispatch time since it requires
        user interaction or valid credentials. We only verify the CLI exists
        and has the necessary safety flags.

        Raises:
            BackendError: If any check fails with guidance for the user.
        """
        # 1. Check CLI installed
        copilot_path = shutil.which("copilot")
        if copilot_path is None:
            # Check for common VSCode Copilot install location
            vscode_copilot = Path.home() / ".vscode-server/data/User/globalStorage/github.copilot-chat/copilotCli/copilot"
            if vscode_copilot.exists():
                raise BackendError(
                    f"Copilot CLI found at {vscode_copilot} but NOT on PATH. "
                    f"Add to PATH: export PATH=\"{vscode_copilot.parent}:$PATH\"",
                    backend=self.name,
                )
            raise BackendError(
                "Copilot CLI not found in PATH. "
                "Install from: https://github.com/github/copilot-cli",
                backend=self.name,
            )

    def _build_prompt_for_type(
        self,
        prompt_type: str,
        epic_spec: dict | None,
        spec_md: str | None = None,
    ) -> str:
        """Build a prompt based on type (drift_fix, drift_verify, etc.)."""
        from spec.executor.engine import _build_drift_fix_prompt, _build_drift_verify_prompt

        if prompt_type == "drift_fix":
            return _build_drift_fix_prompt(epic_spec, spec_md)
        if prompt_type == "drift_verify":
            return _build_drift_verify_prompt(epic_spec, spec_md)
        raise BackendError(
            f"Unknown prompt_type: {prompt_type}",
            backend=self.name,
        )

        # 2. Check --deny-tool flag support via --help (10s timeout - CLI startup is slow)
        try:
            result = subprocess.run(
                ["copilot", "--help"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
            )
            help_text = result.stdout + result.stderr
            if "--deny-tool" not in help_text:
                raise BackendError(
                    "Copilot CLI does not support --deny-tool flag. "
                    "Upgrade to a newer version of the Copilot CLI.",
                    backend=self.name,
                )
        except subprocess.TimeoutExpired:
            raise BackendError(
                "Copilot CLI --help timed out (10s). CLI startup is slow or network issue.",
                backend=self.name,
            )
        except FileNotFoundError:
            raise BackendError(
                "Copilot CLI not found in PATH. "
                "Install from: https://github.com/github/copilot-cli",
                backend=self.name,
            )

    def dispatch(
        self,
        manifest: StepManifest,
        artifacts_dir: Path,
        policy: Policy,
        capture_patch: bool = False,
    ) -> StepCapture:
        """Spawn Copilot CLI session and capture output."""
        from spec.executor.schemas import AgentCapture, GitCapture, StepCapture

        payload = manifest.payload
        common = manifest.common
        interactive = payload.get("interactive", False)

        # Extract payload fields
        prompt = payload.get("prompt")
        prompt_type = payload.get("prompt_type")
        spec_md = payload.get("spec_md")
        epic_spec = payload.get("epic_spec")

        # Handle prompt_type for drift steps - build prompt dynamically
        if prompt_type and not prompt:
            prompt = self._build_prompt_for_type(prompt_type, epic_spec, spec_md)

        # Use spec_md directly as prompt if no explicit prompt
        if spec_md and not prompt:
            prompt = spec_md

        # For interactive mode with no prompt/spec, provide a minimal starter
        if interactive and not prompt:
            prompt = "(No spec provided - please specify what you'd like to work on)"

        if not prompt and not interactive:
            raise BackendError(
                "copilot backend requires 'prompt', 'prompt_type', or 'spec_md' in payload (or interactive=true)",
                backend=self.name,
                step_id=manifest.step_id,
            )

        repo_path = Path(payload.get("repo_path", common.repo_path))
        models = payload.get("models") or [DEFAULT_MODEL]
        capture_git = payload.get("capture_git", True)
        payload_timeout = payload.get("timeout_s")
        timeout_s = payload_timeout if payload_timeout is not None else common.timeout_s

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

        # Execute — try models in priority order
        exit_code: int | None = None
        used_model: str | None = None

        if interactive:
            # Interactive mode: launch TUI with spec context
            used_model = models[0]
            cmd = self._build_interactive_command(prompt=prompt)
            try:
                exit_code = self._execute_interactive(
                    cmd=cmd,
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
            # Headless mode: try models in order
            errors: list[str] = []
            for model in models:
                cmd = self._build_command(prompt=prompt, model=model)
                try:
                    exit_code = self._execute_copilot(
                        cmd=cmd,
                        prompt=prompt,
                        repo_path=repo_path,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        timeout_s=timeout_s,
                    )
                    if exit_code == 0:
                        used_model = model
                        break
                    # Non-zero exit — check if model-specific error
                    stderr_content = stderr_path.read_text() if stderr_path.exists() else ""
                    model_error_patterns = [
                        "unknown model",
                        "not available",
                        "not supported",
                        "model not found",
                    ]
                    if any(p in stderr_content.lower() for p in model_error_patterns):
                        errors.append(f"{model}: {stderr_content.strip()}")
                        continue
                    # Non-model error — stop trying
                    used_model = model
                    break
                except Exception as e:
                    errors.append(f"{model}: {e}")
                    continue


            # If no model succeeded
            if exit_code is None or (exit_code != 0 and used_model is None):
                exit_code = exit_code if exit_code is not None else 1
                error_detail = "; ".join(errors) if errors else "unknown error"
                stderr_path.write_text(
                    f"No models available from {models}. "
                    f"Check subscription and token.\nErrors: {error_detail}\n"
                )
                if not stdout_path.exists():
                    stdout_path.write_text("")

        # Capture post-step git state
        git_capture = None
        if capture_git:
            try:
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
                exit_code=exit_code if exit_code is not None else 1,
            ),
        )

    def _build_command(self, prompt: str, model: str) -> list[str]:
        """Build the copilot CLI command for headless mode.

        Args:
            prompt: Agent task prompt (passed via -p flag)
            model: Model identifier (e.g., "gpt-5.2", "claude-sonnet-4.5")

        Returns:
            Command list for subprocess execution.
        """
        return [
            "copilot",
            "-p", prompt,
            "--model", model,
            "--allow-all-tools",
            "--deny-tool", "shell(git*)",
        ]

    def _build_interactive_command(self, prompt: str) -> list[str]:
        """Build the copilot CLI command for interactive TUI mode.

        Args:
            prompt: Initial context/prompt to pass to the interactive session

        Returns:
            Command list for interactive execution.

        Note: In interactive mode, the Copilot CLI TUI opens with the provided prompt
        as context. Users can interact with the session and switch models via /model.
        """
        return [
            "copilot",
            "-p", prompt,
            "--deny-tool", "shell(git*)",
        ]

    def _execute_copilot(
        self,
        cmd: list[str],
        prompt: str,
        repo_path: Path,
        stdout_path: Path,
        stderr_path: Path,
        timeout_s: int,
    ) -> int:
        """Execute copilot CLI in headless mode and capture output.

        Args:
            cmd: Full command list (copilot -p ... --model ... --deny-tool ...)
            prompt: Not used for stdin (prompt is in -p flag), kept for interface parity
            repo_path: Working directory for the subprocess
            stdout_path: Path to write captured stdout
            stderr_path: Path to write captured stderr
            timeout_s: Timeout in seconds

        Returns:
            Process exit code (124 on timeout).
        """
        proc = subprocess.Popen(
            cmd,
            cwd=repo_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout_s)
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
            stderr_path.write_text(f"Copilot timed out after {timeout_s}s\n")
            return 124  # Standard timeout exit code

    def _execute_interactive(
        self,
        cmd: list[str],
        repo_path: Path,
        stdout_path: Path,
        stderr_path: Path,
    ) -> int:
        """Execute copilot CLI in interactive TUI mode.

        Launches the TUI with terminal inherited (no PIPE).
        No timeout — the human controls when to exit.

        Args:
            cmd: The copilot command to run (includes -p with prompt context)
            repo_path: Target repository path
            stdout_path: Path to write stdout marker
            stderr_path: Path to write stderr marker

        Returns:
            Exit code from the copilot process.
        """
        import shlex

        cmd_str = " ".join(shlex.quote(arg) for arg in cmd)

        try:
            original_cwd = os.getcwd()
            os.chdir(repo_path)
            exit_code = os.system(cmd_str)
            if os.WIFEXITED(exit_code):
                exit_code = os.WEXITSTATUS(exit_code)
            else:
                exit_code = 1
        finally:
            os.chdir(original_cwd)
            stdout_path.write_text("(interactive session — no stdout capture)\n")
            stderr_path.write_text("")

        return exit_code
