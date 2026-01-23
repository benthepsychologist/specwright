"""Tests for background runner."""

from unittest.mock import MagicMock, patch

import pytest

from spec.aip.models import (
    AIPExecution,
    AIPMetadata,
    AIPv3,
    AIPWorkspace,
    WorkspaceMode,
)
from spec.runner.background import (
    RunnerError,
    RunResult,
    find_claude_binary,
    run_background,
)


@pytest.fixture
def sample_aip(tmp_path):
    """Create a sample AIP for testing."""
    return AIPv3(
        version="3.0",
        kind="context-packet",
        metadata=AIPMetadata(
            epic_id="test-epic",
            spec_id="test-spec",
            owner="tester",
            created="2026-01-16T00:00:00+00:00",
        ),
        workspace=AIPWorkspace(
            mode=WorkspaceMode.SINGLE_REPO,
            repo_path=str(tmp_path),
            branch="feat/test",
            base_branch="main",
        ),
        goal="Test goal",
        execution=AIPExecution(timeout_seconds=60),
    )


class TestFindClaudeBinary:
    """Tests for find_claude_binary function."""

    @patch("shutil.which")
    def test_finds_claude_in_path(self, mock_which):
        """Test finding claude in PATH."""
        mock_which.return_value = "/usr/local/bin/claude"

        result = find_claude_binary()

        assert result == "/usr/local/bin/claude"

    @patch("shutil.which")
    def test_raises_when_not_found(self, mock_which):
        """Test that RunnerError is raised when claude not found."""
        mock_which.return_value = None

        with pytest.raises(RunnerError) as exc_info:
            find_claude_binary()

        assert "not found" in str(exc_info.value).lower()


class TestRunResult:
    """Tests for RunResult dataclass."""

    def test_creates_with_defaults(self):
        """Test creating RunResult with minimal args."""
        result = RunResult(exit_code=0, duration_seconds=10.5)

        assert result.exit_code == 0
        assert result.duration_seconds == 10.5
        assert result.timeout_reached is False
        assert result.started_at != ""

    def test_timeout_flag(self):
        """Test timeout_reached flag."""
        result = RunResult(
            exit_code=1,
            duration_seconds=60.0,
            timeout_reached=True,
        )

        assert result.timeout_reached is True


class TestRunBackground:
    """Tests for run_background function."""

    @patch("spec.runner.background.find_claude_binary")
    @patch("spec.runner.background.write_task_md")
    def test_run_creates_transcript(
        self, mock_write_task, mock_find_claude, sample_aip, tmp_path
    ):
        """Test that run creates transcript file."""
        mock_find_claude.return_value = "/usr/bin/claude"

        class MockStdout:
            def __init__(self):
                self._fd = 10

            def fileno(self):
                return self._fd

        class MockProcess:
            def __init__(self):
                self._poll_calls = 0
                self.returncode = 0
                self.stdout = MockStdout()

            def poll(self):
                self._poll_calls += 1
                if self._poll_calls >= 2:
                    return 0
                return None

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return None

            def kill(self):
                return None

        mock_process = MockProcess()

        popen_calls: dict[str, object] = {}

        def _fake_popen(cmd, **kwargs):
            popen_calls["cmd"] = cmd
            popen_calls["kwargs"] = kwargs
            return mock_process

        with patch("spec.runner.background.subprocess.Popen", side_effect=_fake_popen):
            # selectors.DefaultSelector() will try to register/monitor a real fd.
            # Mock it so we can deterministically drive output readiness.
            class _FakeSelector:
                def __init__(self):
                    self._registered = None
                    self._select_calls = 0

                def register(self, fileobj, _events):
                    self._registered = fileobj

                def select(self, timeout=None):
                    self._select_calls += 1
                    # First call: report readiness so os.read emits bytes.
                    if self._select_calls == 1:
                        return [(type("K", (), {"fileobj": self._registered})(), 1)]
                    return []

                def close(self):
                    return None

            with patch("spec.runner.background.selectors.DefaultSelector", return_value=_FakeSelector()):
                reads = [b'{"type": "message"}\n', b"", b""]

                def _fake_os_read(_fd, _n):
                    return reads.pop(0) if reads else b""

                with patch("spec.runner.background.os.read", side_effect=_fake_os_read):
                    transcript_path = tmp_path / "transcript.jsonl"
                    result = run_background(sample_aip, transcript_path=transcript_path)

        # Check transcript was created with content
        assert transcript_path.exists()
        content = transcript_path.read_text()
        assert '{"type": "message"}' in content
        assert result.transcript_path == transcript_path
        assert result.exit_code == 0
        # Ensure we provided a prompt to Claude via prompt argument
        assert isinstance(popen_calls.get("cmd"), list)
        assert str(popen_calls["cmd"][-1]).startswith("# Task:")

    @patch("spec.runner.background.find_claude_binary")
    @patch("spec.runner.background.subprocess.Popen")
    @patch("spec.runner.background.write_task_md")
    def test_run_respects_timeout(
        self, mock_write_task, mock_popen, mock_find_claude, sample_aip, tmp_path
    ):
        """Test that run respects timeout setting."""
        mock_find_claude.return_value = "/usr/bin/claude"

        # Mock process that runs longer than timeout.
        mock_process = MagicMock()
        mock_process.stdout.fileno.return_value = 11
        mock_process.poll.return_value = None  # Never completes naturally
        mock_popen.return_value = mock_process

        # selectors.DefaultSelector() expects file descriptor; avoid it here.
        with patch("spec.runner.background.selectors.DefaultSelector") as mock_sel_cls:
            mock_sel = MagicMock()
            mock_sel.select.return_value = []
            mock_sel_cls.return_value = mock_sel

            # Use very short timeout
            sample_aip.execution = AIPExecution(timeout_seconds=0)

            transcript_path = tmp_path / "transcript.jsonl"

            # Make time deterministic: force the first loop iteration to exceed the timeout.
            # Also prevent any accidental reads on a fake fd.
            with patch("spec.runner.background.time.time", side_effect=[0.0, 1.0, 1.0, 1.0]):
                with patch("spec.runner.background.os.read", return_value=b""):
                    result = run_background(sample_aip, timeout=0, transcript_path=transcript_path)

        assert result.timeout_reached is True
        mock_process.terminate.assert_called_once()

    @patch("spec.runner.background.find_claude_binary")
    @patch("spec.runner.background.write_task_md")
    def test_run_handles_file_not_found(
        self, mock_write_task, mock_find_claude, sample_aip, tmp_path
    ):
        """Test that run handles FileNotFoundError gracefully."""
        mock_find_claude.return_value = "/nonexistent/claude"

        with patch("spec.runner.background.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("claude not found")

            transcript_path = tmp_path / "transcript.jsonl"
            result = run_background(sample_aip, transcript_path=transcript_path)

            assert result.exit_code == 127
            assert result.error is not None
            assert "not found" in result.error.lower()
