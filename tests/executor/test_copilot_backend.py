"""
Tests for the Copilot CLI execution backend.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from spec.executor.backends import BackendError, get_backend, list_backends
from spec.executor.backends.copilot import DEFAULT_MODEL, CopilotBackend
from spec.executor.schemas import (
    Backend,
    Common,
    Policy,
    StepCapture,
    StepManifest,
)

# =============================================================================
# Registry Integration
# =============================================================================


class TestCopilotRegistry:
    """Copilot backend is registered and discoverable."""

    def test_copilot_in_list(self):
        backends = list_backends()
        assert "copilot" in backends

    def test_get_backend_returns_copilot(self):
        backend = get_backend("copilot")
        assert isinstance(backend, CopilotBackend)
        assert backend.name == "copilot"


# =============================================================================
# Verify Tests
# =============================================================================


class TestCopilotVerify:
    """Tests for CopilotBackend.verify()."""

    @pytest.fixture
    def backend(self):
        return CopilotBackend()

    @patch("pathlib.Path.exists", return_value=False)
    @patch("shutil.which")
    def test_verify_missing_cli(self, mock_which, mock_path_exists, backend):
        """verify raises when copilot CLI not found."""
        mock_which.return_value = None
        with pytest.raises(BackendError) as exc_info:
            backend.verify()
        assert "Copilot CLI not found" in str(exc_info.value)
        assert "copilot-cli" in str(exc_info.value)

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/copilot")
    def test_verify_deny_tool_supported_stdout(self, mock_which, mock_run, backend):
        """verify succeeds when --deny-tool is in stdout."""
        mock_run.return_value = MagicMock(
            stdout="Usage: copilot [options]\n  --deny-tool  Deny a tool\n",
            stderr="",
            returncode=0,
        )
        backend.verify()  # Should not raise

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/copilot")
    def test_verify_deny_tool_supported_stderr(self, mock_which, mock_run, backend):
        """verify succeeds when --deny-tool is in stderr (some CLIs output help there)."""
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Usage: copilot [options]\n  --deny-tool  Deny a tool\n",
            returncode=0,
        )
        backend.verify()  # Should not raise

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/copilot")
    def test_verify_deny_tool_missing(self, mock_which, mock_run, backend):
        """verify raises when --deny-tool not in stdout or stderr."""
        mock_run.return_value = MagicMock(
            stdout="Usage: copilot [options]\n  --model  Select model\n",
            stderr="",
            returncode=0,
        )
        with pytest.raises(BackendError) as exc_info:
            backend.verify()
        assert "--deny-tool" in str(exc_info.value)
        assert "Upgrade" in str(exc_info.value)

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/copilot")
    def test_verify_help_timeout(self, mock_which, mock_run, backend):
        """verify raises on --help timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="copilot", timeout=10)
        with pytest.raises(BackendError) as exc_info:
            backend.verify()
        assert "timed out" in str(exc_info.value)

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/copilot")
    def test_verify_help_file_not_found(self, mock_which, mock_run, backend):
        """verify raises when subprocess can't find binary (race condition)."""
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(BackendError) as exc_info:
            backend.verify()
        assert "not found" in str(exc_info.value)


# =============================================================================
# Command Building Tests
# =============================================================================


class TestCopilotCommands:
    """Tests for command building methods."""

    @pytest.fixture
    def backend(self):
        return CopilotBackend()

    def test_build_command_headless(self, backend):
        """Headless command includes -p, --model, --allow-all-tools, and --deny-tool."""
        cmd = backend._build_command(prompt="Do the task", model="gpt-5.2")
        assert cmd == [
            "copilot",
            "-p", "Do the task",
            "--model", "gpt-5.2",
            "--allow-all-tools",
            "--deny-tool", "shell(git*)",
        ]

    def test_build_command_default_model(self, backend):
        """Default model is used when no model specified."""
        cmd = backend._build_command(prompt="Do the task", model=DEFAULT_MODEL)
        assert "--model" in cmd
        assert DEFAULT_MODEL in cmd

    def test_build_interactive_command(self, backend):
        """Interactive command has -p with prompt and --deny-tool."""
        prompt = "Here is the spec context"
        cmd = backend._build_interactive_command(prompt=prompt)
        assert cmd == [
            "copilot",
            "-p", prompt,
            "--deny-tool", "shell(git*)",
        ]

    def test_deny_tool_always_present(self, backend):
        """--deny-tool 'shell(git*)' is always present in commands."""
        headless = backend._build_command(prompt="test", model="gpt-5.2")
        interactive = backend._build_interactive_command(prompt="test context")

        for cmd in [headless, interactive]:
            assert "--deny-tool" in cmd
            idx = cmd.index("--deny-tool")
            assert cmd[idx + 1] == "shell(git*)"


# =============================================================================
# Dispatch Tests
# =============================================================================


class TestCopilotDispatch:
    """Tests for CopilotBackend.dispatch()."""

    @pytest.fixture
    def backend(self):
        return CopilotBackend()

    @pytest.fixture
    def manifest(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        (repo_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        commit = result.stdout.strip()

        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        branch = result.stdout.strip() or "master"

        return StepManifest(
            step_n=1,
            step_id="test.copilot",
            backend=Backend.copilot,
            common=Common(
                repo_path=repo_path,
                branch=branch,
                base_commit=commit,
                timeout_s=30,
            ),
            payload={"prompt": "Create a hello.py file"},
        )

    @pytest.fixture
    def policy(self):
        return Policy()

    def test_dispatch_no_prompt_raises(self, backend, manifest, policy, tmp_path):
        """Missing prompt raises BackendError."""
        manifest.payload = {}
        artifacts_dir = tmp_path / "artifacts"

        with pytest.raises(BackendError) as exc_info:
            backend.dispatch(manifest, artifacts_dir, policy)
        assert "prompt" in str(exc_info.value)

    @patch("spec.executor.backends.copilot.CopilotBackend._execute_copilot")
    def test_dispatch_success_first_model(self, mock_exec, backend, manifest, policy, tmp_path):
        """Successful dispatch with first model."""
        mock_exec.return_value = 0
        manifest.payload["models"] = ["gpt-5.2", "claude-sonnet-4.5"]
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert isinstance(capture, StepCapture)
        assert capture.step_n == 1
        assert capture.step_id == "test.copilot"
        assert capture.agent is not None
        assert capture.agent.exit_code == 0
        # Should have been called only once (first model succeeded)
        assert mock_exec.call_count == 1

    @patch("spec.executor.backends.copilot.CopilotBackend._execute_copilot")
    def test_dispatch_fallback_to_second_model(self, mock_exec, backend, manifest, policy, tmp_path):
        """Falls back to second model when first returns model error."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        def side_effect(*, cmd, prompt, repo_path, stdout_path, stderr_path, timeout_s):
            if "gpt-5.2" in cmd:
                stderr_path.write_text("unknown model: gpt-5.2")
                return 1
            # Second model succeeds
            stdout_path.write_text("done")
            stderr_path.write_text("")
            return 0

        mock_exec.side_effect = side_effect
        manifest.payload["models"] = ["gpt-5.2", "claude-sonnet-4.5"]

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 0
        assert mock_exec.call_count == 2

    @patch("spec.executor.backends.copilot.CopilotBackend._execute_copilot")
    def test_dispatch_all_models_fail(self, mock_exec, backend, manifest, policy, tmp_path):
        """All models failing results in step failure."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        def side_effect(*, cmd, prompt, repo_path, stdout_path, stderr_path, timeout_s):
            stderr_path.write_text("unknown model")
            return 1

        mock_exec.side_effect = side_effect
        manifest.payload["models"] = ["model-a", "model-b"]

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 1
        stderr_path = artifacts_dir / capture.agent.stderr_file
        content = stderr_path.read_text()
        assert "No models available" in content

    @patch("spec.executor.backends.copilot.CopilotBackend._execute_copilot")
    def test_dispatch_default_model_used(self, mock_exec, backend, manifest, policy, tmp_path):
        """Default model used when models not specified."""
        mock_exec.return_value = 0
        # No models in payload
        manifest.payload = {"prompt": "Do something"}
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 0
        # Check the command included default model
        call_args = mock_exec.call_args
        cmd = call_args.kwargs.get("cmd") or call_args[0][0]
        assert DEFAULT_MODEL in cmd

    @patch("spec.executor.backends.copilot.CopilotBackend._execute_copilot")
    def test_dispatch_non_model_error_stops_trying(
        self, mock_exec, backend, manifest, policy, tmp_path
    ):
        """Non-model error (auth failure, etc.) stops trying further models."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        def side_effect(*, cmd, prompt, repo_path, stdout_path, stderr_path, timeout_s):
            stderr_path.write_text("authentication failed: invalid token")
            return 1

        mock_exec.side_effect = side_effect
        manifest.payload["models"] = ["gpt-5.2", "claude-sonnet-4.5"]

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        # Should stop after first non-model error
        assert mock_exec.call_count == 1
        assert capture.agent.exit_code == 1

    @patch("spec.executor.backends.copilot.CopilotBackend._execute_copilot")
    def test_dispatch_captures_git_state(self, mock_exec, backend, manifest, policy, tmp_path):
        """Git state is captured before and after execution."""
        mock_exec.return_value = 0
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.git is not None

    @patch("spec.executor.backends.copilot.CopilotBackend._execute_copilot")
    def test_dispatch_no_git_capture(self, mock_exec, backend, manifest, policy, tmp_path):
        """Git capture can be disabled."""
        mock_exec.return_value = 0
        manifest.payload["capture_git"] = False
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.git is None

    @patch("spec.executor.backends.copilot.CopilotBackend._execute_copilot")
    def test_dispatch_timeout(self, mock_exec, backend, manifest, policy, tmp_path):
        """Timeout returns exit code 124."""

        def side_effect(*, cmd, prompt, repo_path, stdout_path, stderr_path, timeout_s):
            stdout_path.write_text("")
            stderr_path.write_text(f"Copilot timed out after {timeout_s}s\n")
            return 124

        mock_exec.side_effect = side_effect
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 124
        stderr_path = artifacts_dir / capture.agent.stderr_file
        assert "timed out" in stderr_path.read_text()

    @patch("spec.executor.backends.copilot.CopilotBackend._execute_copilot")
    def test_dispatch_exception_in_execution(
        self, mock_exec, backend, manifest, policy, tmp_path
    ):
        """Exception during all models results in failure."""
        mock_exec.side_effect = RuntimeError("Unexpected crash")
        manifest.payload["models"] = ["gpt-5.2"]
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 1
        stderr_path = artifacts_dir / capture.agent.stderr_file
        assert "No models available" in stderr_path.read_text()


# =============================================================================
# Execution Method Tests
# =============================================================================


class TestCopilotExecution:
    """Tests for low-level execution methods."""

    @pytest.fixture
    def backend(self):
        return CopilotBackend()

    @patch("subprocess.Popen")
    def test_execute_copilot_success(self, mock_popen, backend, tmp_path):
        """Headless execution captures stdout/stderr."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("output text", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        stdout_path = tmp_path / "stdout.txt"
        stderr_path = tmp_path / "stderr.txt"

        exit_code = backend._execute_copilot(
            cmd=["copilot", "-p", "test", "--model", "gpt-5.2"],
            prompt="test",
            repo_path=tmp_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_s=30,
        )

        assert exit_code == 0
        assert stdout_path.read_text() == "output text"
        assert stderr_path.read_text() == ""

    @patch("subprocess.Popen")
    def test_execute_copilot_timeout(self, mock_popen, backend, tmp_path):
        """Timeout kills process group and returns 124."""
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="copilot", timeout=5)
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        stdout_path = tmp_path / "stdout.txt"
        stderr_path = tmp_path / "stderr.txt"

        with patch("os.killpg"), patch("os.getpgid", return_value=12345):
            exit_code = backend._execute_copilot(
                cmd=["copilot", "-p", "test"],
                prompt="test",
                repo_path=tmp_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_s=5,
            )

        assert exit_code == 124
        assert "timed out" in stderr_path.read_text()

    @patch("subprocess.Popen")
    def test_execute_copilot_stdin_devnull(self, mock_popen, backend, tmp_path):
        """Copilot backend uses DEVNULL for stdin (prompt is in -p flag, not stdin)."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("out", "err")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        stdout_path = tmp_path / "stdout.txt"
        stderr_path = tmp_path / "stderr.txt"

        backend._execute_copilot(
            cmd=["copilot", "-p", "hello"],
            prompt="hello",
            repo_path=tmp_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_s=30,
        )

        # Popen must use DEVNULL for stdin to prevent hanging on auth prompts
        call_kwargs = mock_popen.call_args.kwargs
        assert call_kwargs.get("stdin") == subprocess.DEVNULL
