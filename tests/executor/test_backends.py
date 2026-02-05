"""
Tests for execution backends.
"""

import subprocess
from unittest.mock import patch

import pytest

from spec.executor.backends import (
    BackendBase,
    BackendError,
    UnknownBackendError,
    get_backend,
    list_backends,
    register_backend,
)
from spec.executor.backends.claude_code import ClaudeCodeBackend
from spec.executor.backends.cmd import CmdBackend
from spec.executor.backends.codex import CodexBackend
from spec.executor.backends.llm import LlmBackend
from spec.executor.backends.registry import disable_backend, enable_backend
from spec.executor.schemas import (
    Backend,
    Common,
    Policy,
    StepCapture,
    StepManifest,
)

# =============================================================================
# Registry Tests
# =============================================================================


class TestBackendRegistry:
    """Tests for backend registry."""

    def test_list_backends(self):
        """All four backends should be registered."""
        backends = list_backends()
        assert "cmd" in backends
        assert "llm" in backends
        assert "claude-code" in backends
        assert "codex" in backends

    def test_get_backend_cmd(self):
        """get_backend returns CmdBackend for 'cmd'."""
        backend = get_backend("cmd")
        assert isinstance(backend, CmdBackend)
        assert backend.name == "cmd"

    def test_get_backend_llm(self):
        """get_backend returns LlmBackend for 'llm'."""
        backend = get_backend("llm")
        assert isinstance(backend, LlmBackend)
        assert backend.name == "llm"

    def test_get_backend_claude_code(self):
        """get_backend returns ClaudeCodeBackend for 'claude-code'."""
        backend = get_backend("claude-code")
        assert isinstance(backend, ClaudeCodeBackend)
        assert backend.name == "claude-code"

    def test_get_backend_codex(self):
        """get_backend returns CodexBackend for 'codex'."""
        backend = get_backend("codex")
        assert isinstance(backend, CodexBackend)
        assert backend.name == "codex"

    def test_get_backend_unknown(self):
        """get_backend raises UnknownBackendError for unknown backend."""
        with pytest.raises(UnknownBackendError) as exc_info:
            get_backend("nonexistent")
        assert "nonexistent" in str(exc_info.value)

    def test_get_backend_case_insensitive(self):
        """Backend lookup is case-insensitive."""
        backend1 = get_backend("CMD")
        backend2 = get_backend("Cmd")
        backend3 = get_backend("cmd")
        assert all(isinstance(b, CmdBackend) for b in [backend1, backend2, backend3])

    def test_disable_enable_backend(self):
        """Backends can be disabled and re-enabled."""
        # Disable
        disable_backend("codex")
        with pytest.raises(UnknownBackendError):
            get_backend("codex")

        # Re-enable
        enable_backend("codex")
        backend = get_backend("codex")
        assert isinstance(backend, CodexBackend)

    def test_register_custom_backend(self):
        """Custom backends can be registered."""

        class CustomBackend(BackendBase):
            @property
            def name(self) -> str:
                return "custom"

            def dispatch(self, manifest, artifacts_dir, policy):
                pass

        register_backend("custom", CustomBackend)
        backend = get_backend("custom")
        assert isinstance(backend, CustomBackend)


# =============================================================================
# CmdBackend Tests
# =============================================================================


class TestCmdBackend:
    """Tests for cmd backend."""

    @pytest.fixture
    def backend(self):
        return CmdBackend()

    @pytest.fixture
    def manifest(self, tmp_path):
        """Create a basic manifest for testing."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        # Initialize git repo
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

        # Get commit sha
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        commit = result.stdout.strip()

        # Get branch name
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        branch = result.stdout.strip() or "master"

        return StepManifest(
            step_n=1,
            step_id="test.cmd",
            backend=Backend.cmd,
            common=Common(
                repo_path=repo_path,
                branch=branch,
                base_commit=commit,
                timeout_s=30,
            ),
            payload={"command": "echo hello"},
        )

    @pytest.fixture
    def policy(self):
        return Policy()

    def test_dispatch_success(self, backend, manifest, policy, tmp_path):
        """Successful command execution."""
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert isinstance(capture, StepCapture)
        assert capture.step_n == 1
        assert capture.step_id == "test.cmd"
        assert capture.agent is not None
        assert capture.agent.exit_code == 0

        # Check stdout was captured (relative path in capture, resolve against artifacts_dir)
        stdout_path = artifacts_dir / capture.agent.stdout_file
        assert stdout_path.exists()
        assert "hello" in stdout_path.read_text()

    def test_dispatch_command_fails(self, backend, manifest, policy, tmp_path):
        """Failed command returns non-zero exit code."""
        manifest.payload["command"] = "exit 42"
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 42

    def test_dispatch_policy_violation(self, backend, manifest, policy, tmp_path):
        """Policy violation returns exit code 126."""
        manifest.payload["command"] = "git push origin main"
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 126
        stderr_path = artifacts_dir / capture.agent.stderr_file
        assert "Policy violation" in stderr_path.read_text()

    def test_dispatch_timeout(self, backend, manifest, policy, tmp_path):
        """Timeout returns exit code 124."""
        manifest.payload["command"] = "sleep 10"
        manifest.common = Common(
            repo_path=manifest.common.repo_path,
            branch=manifest.common.branch,
            base_commit=manifest.common.base_commit,
            timeout_s=1,  # 1 second timeout
        )
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 124
        stderr_path = artifacts_dir / capture.agent.stderr_file
        assert "timed out" in stderr_path.read_text()

    def test_dispatch_captures_git_state(self, backend, manifest, policy, tmp_path):
        """Git state is captured after command."""
        # Modify a file
        manifest.payload["command"] = "echo modified > test.txt"
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.git is not None
        assert capture.git.working_tree_dirty is True

    def test_dispatch_no_command_raises(self, backend, manifest, policy, tmp_path):
        """Missing command raises BackendError."""
        manifest.payload = {}
        artifacts_dir = tmp_path / "artifacts"

        with pytest.raises(BackendError) as exc_info:
            backend.dispatch(manifest, artifacts_dir, policy)
        assert "command" in str(exc_info.value)


# =============================================================================
# LlmBackend Tests
# =============================================================================


class TestLlmBackend:
    """Tests for llm backend."""

    @pytest.fixture
    def backend(self):
        return LlmBackend()

    @pytest.fixture
    def manifest(self, tmp_path):
        return StepManifest(
            step_n=1,
            step_id="test.llm",
            backend=Backend.llm,
            common=Common(
                repo_path=tmp_path,
                branch="main",
                base_commit="abc123",
                timeout_s=30,
            ),
            payload={"prompt": "Say hello"},
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

    @patch("spec.executor.backends.llm.LlmBackend._call_llm")
    def test_dispatch_success(self, mock_call, backend, manifest, policy, tmp_path):
        """Successful LLM call."""
        mock_call.return_value = "Hello!"
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 0
        stdout_path = artifacts_dir / capture.agent.stdout_file
        assert "Hello!" in stdout_path.read_text()

    @patch("spec.executor.backends.llm.LlmBackend._call_llm")
    def test_dispatch_api_error(self, mock_call, backend, manifest, policy, tmp_path):
        """LLM error returns exit code 1."""
        mock_call.side_effect = Exception("API rate limit")
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 1
        stderr_path = artifacts_dir / capture.agent.stderr_file
        assert "API rate limit" in stderr_path.read_text()

    def test_verify_network_preflight_disabled_by_default(self, backend, monkeypatch):
        """verify() should not make a network prompt unless explicitly enabled."""
        monkeypatch.delenv("SPECWRIGHT_LLM_NETWORK_PREFLIGHT", raising=False)

        import sys
        from types import ModuleType

        class DummyModel:
            needs_key = None

            def prompt(self, _prompt):  # pragma: no cover
                raise AssertionError("network preflight should not run")

        dummy_llm = ModuleType("llm")
        dummy_llm.get_model = lambda _name: DummyModel()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "llm", dummy_llm)

        backend.verify()

    def test_verify_network_preflight_enabled(self, backend, monkeypatch):
        """verify() performs a tiny real-prompt call when enabled (mocked here)."""
        monkeypatch.setenv("SPECWRIGHT_LLM_NETWORK_PREFLIGHT", "1")

        import sys
        from types import ModuleType

        class DummyResp:
            def text(self):
                return "OK"

        class DummyModel:
            needs_key = None

            def prompt(self, _prompt):
                return DummyResp()

        dummy_llm = ModuleType("llm")
        dummy_llm.get_model = lambda _name: DummyModel()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "llm", dummy_llm)

        backend.verify()


# =============================================================================
# ClaudeCodeBackend Tests
# =============================================================================


class TestClaudeCodeBackend:
    """Tests for claude-code backend."""

    @pytest.fixture
    def backend(self):
        return ClaudeCodeBackend()

    @pytest.fixture
    def manifest(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        # Initialize git repo
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
            step_id="test.claude",
            backend=Backend.claude_code,
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

    def test_no_prompt_or_aip_raises(self, backend, manifest, policy, tmp_path):
        """Missing prompt and aip_path raises BackendError."""
        manifest.payload = {}
        artifacts_dir = tmp_path / "artifacts"

        with pytest.raises(BackendError) as exc_info:
            backend.dispatch(manifest, artifacts_dir, policy)
        assert "prompt" in str(exc_info.value) or "aip" in str(exc_info.value)

    def test_build_default_tools(self, backend, policy):
        """Default tools are built based on policy."""
        tools = backend._build_default_tools(policy)
        assert "Read" in tools
        assert "Edit" in tools
        assert "Bash(git status:*)" in tools

        # Commit is allowed by default
        assert "Bash(git add:*)" in tools
        assert "Bash(git commit:*)" in tools

    def test_build_default_tools_no_commit(self, backend):
        """Commit tools excluded when not allowed."""
        policy = Policy(allow_commit=False)
        tools = backend._build_default_tools(policy)
        assert "Bash(git add:*)" not in tools
        assert "Bash(git commit:*)" not in tools

    @patch("shutil.which")
    def test_verify_missing_claude(self, mock_which, backend):
        """verify raises when claude not found."""
        mock_which.return_value = None
        with pytest.raises(BackendError) as exc_info:
            backend.verify()
        assert "claude" in str(exc_info.value)

    def test_build_interactive_command_basic(self, backend):
        """Interactive command has prompt as positional argument after --."""
        cmd = backend._build_interactive_command(prompt="Do the task")
        assert cmd == ["claude", "--", "Do the task"]

    def test_build_interactive_command_resume(self, backend):
        """Interactive command with resume."""
        cmd = backend._build_interactive_command(prompt="Do the task", resume=True)
        assert cmd == ["claude", "--resume", "--", "Do the task"]

    def test_build_interactive_command_model(self, backend):
        """Interactive command with model."""
        cmd = backend._build_interactive_command(prompt="Do the task", model="opus-4")
        assert cmd == ["claude", "--model", "opus-4", "--", "Do the task"]

    def test_build_interactive_command_resume_and_model(self, backend):
        """Interactive command with both resume and model."""
        cmd = backend._build_interactive_command(prompt="Do the task", model="opus-4", resume=True)
        assert "--dangerously-skip-permissions" not in cmd
        assert "--resume" in cmd
        assert "--model" in cmd
        assert "opus-4" in cmd
        assert "--" in cmd
        assert "Do the task" in cmd

    def test_build_interactive_command_no_print(self, backend):
        """Interactive command must NOT have --print (it's interactive, not headless)."""
        cmd = backend._build_interactive_command(prompt="Do the task")
        assert "--print" not in cmd
        # But it DOES NOT have --dangerously-skip-permissions since we want human control
        assert "--dangerously-skip-permissions" not in cmd

    def test_write_task_md(self, backend, tmp_path):
        """_write_task_md writes content to .claude/TASK.md."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        task_path = backend._write_task_md(repo_path, "# My Spec\nDo the thing.")

        assert task_path == repo_path / ".claude" / "TASK.md"
        assert task_path.exists()
        assert "# My Spec" in task_path.read_text()
        assert "Do the thing." in task_path.read_text()

    def test_write_task_md_creates_claude_dir(self, backend, tmp_path):
        """_write_task_md creates .claude/ if it doesn't exist."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        backend._write_task_md(repo_path, "content")

        assert (repo_path / ".claude").is_dir()

    def test_write_task_md_overwrites_existing(self, backend, tmp_path):
        """_write_task_md overwrites existing TASK.md."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        (repo_path / ".claude").mkdir()
        (repo_path / ".claude" / "TASK.md").write_text("old content")

        backend._write_task_md(repo_path, "new content")

        assert (repo_path / ".claude" / "TASK.md").read_text() == "new content"


# =============================================================================
# CodexBackend Tests
# =============================================================================


class TestCodexBackend:
    """Tests for codex backend."""

    @pytest.fixture
    def backend(self):
        return CodexBackend()

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
            step_id="test.codex",
            backend=Backend.codex,
            common=Common(
                repo_path=repo_path,
                branch=branch,
                base_commit=commit,
                timeout_s=30,
            ),
            payload={"prompt": "Write a function"},
        )

    @pytest.fixture
    def policy(self):
        return Policy()

    @patch("shutil.which")
    def test_dispatch_codex_not_found(self, mock_which, backend, manifest, policy, tmp_path):
        """Codex not found returns exit 127."""
        mock_which.return_value = None
        artifacts_dir = tmp_path / "artifacts"

        capture = backend.dispatch(manifest, artifacts_dir, policy)

        assert capture.agent.exit_code == 127
        stderr_path = artifacts_dir / capture.agent.stderr_file
        assert "codex CLI not found" in stderr_path.read_text()

    @patch("shutil.which")
    def test_verify_missing_codex(self, mock_which, backend):
        """verify raises when codex not found."""
        mock_which.return_value = None
        with pytest.raises(BackendError) as exc_info:
            backend.verify()
        assert "codex" in str(exc_info.value)
