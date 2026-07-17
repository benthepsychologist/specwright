"""Tests for `spec run chat-1 --free-range` (free-range chat harness).

These tests verify the plumbing only — they never launch a real interactive
Claude TUI. The claude-code backend is stubbed so the run exercises the
free-range bypass, jobdef compilation without a spec, and routing to the
sessions store.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from spec.cli import exec_commands
from spec.cli.spec import app
from spec.executor.backends.base import BackendBase
from spec.executor.jobdefs import install_default_jobdefs
from spec.executor.store import RunStore

runner = CliRunner()


@pytest.fixture
def jobdefs_installed(tmp_path, monkeypatch):
    """Install default jobdefs (incl. chat-1) to a temp dir and patch loader."""
    gov_path = tmp_path / "local-governor"
    install_default_jobdefs(gov_path)

    import spec.executor.jobdefs as jobdefs_module

    original_get_jobdefs_dir = jobdefs_module.get_jobdefs_dir

    def patched_get_jobdefs_dir(governor_path=None):
        if governor_path is None:
            governor_path = gov_path
        return original_get_jobdefs_dir(governor_path)

    monkeypatch.setattr(jobdefs_module, "get_jobdefs_dir", patched_get_jobdefs_dir)
    return gov_path


def test_free_range_dry_run_compiles_without_spec(jobdefs_installed):
    """--free-range --dry-run compiles chat-1 with NO spec and no error."""
    result = runner.invoke(app, ["run", "chat-1", "--free-range", "--dry-run"])
    assert result.exit_code == 0, result.stdout
    assert "Dry run" in result.stdout
    assert "job_id: chat-1" in result.stdout
    # No complaint about a missing spec.
    assert "Must provide" not in result.stdout
    assert "Spec file not found" not in result.stdout


def test_free_range_dry_run_no_aip_refs(jobdefs_installed):
    """The compiled instance must not carry any @aip.* references."""
    result = runner.invoke(app, ["run", "chat-1", "--free-range", "--dry-run"])
    assert result.exit_code == 0, result.stdout
    assert "@aip." not in result.stdout


def test_free_range_routes_to_sessions_store(jobdefs_installed, tmp_path, monkeypatch):
    """A real (stubbed) free-range run lands under the sessions store."""
    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(exec_commands, "SESSIONS_ROOT", sessions_root)

    # Avoid backend.verify() network/CLI checks.
    monkeypatch.setenv("SPECWRIGHT_SKIP_BACKEND_PREFLIGHT", "1")
    monkeypatch.setenv("SPECWRIGHT_SKIP_LLM_PREFLIGHT", "1")

    # Stub the claude-code backend so no real TUI launches.
    from spec.executor.backends import registry
    from spec.executor.schemas import AgentCapture, StepCapture

    class StubInteractiveBackend(BackendBase):
        @property
        def name(self) -> str:
            return "claude-code"

        def verify(self) -> None:
            return None

        def dispatch(self, manifest, artifacts_dir, policy, capture_patch=False):
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            (artifacts_dir / "stdout.txt").write_text("(stub interactive)\n")
            (artifacts_dir / "stderr.txt").write_text("")
            return StepCapture(
                step_n=manifest.step_n,
                step_id=manifest.step_id,
                agent=AgentCapture(
                    stdout_file="stdout.txt",
                    stderr_file="stderr.txt",
                    exit_code=0,
                ),
            )

    original = registry._BACKENDS.get("claude-code")
    registry.register_backend("claude-code", StubInteractiveBackend)
    try:
        result = runner.invoke(
            app,
            ["run", "chat-1", "--free-range", "--repo", str(tmp_path), "--run-id", "run-chat-test-1"],
        )
    finally:
        if original is not None:
            registry.register_backend("claude-code", original)

    assert result.exit_code in (0, 2), result.stdout  # 2 = completed_with_errors

    # Run record landed in the sessions store, not the default runs root.
    store = RunStore(root=sessions_root)
    assert store.run_exists("run-chat-test-1")
    run_dir = store.get_run_path("run-chat-test-1")
    assert (run_dir / "run.yaml").exists()


def test_free_range_unknown_job_still_errors(jobdefs_installed):
    """Free-range mode does not bypass the unknown-job check."""
    result = runner.invoke(app, ["run", "no-such-job", "--free-range", "--dry-run"])
    assert result.exit_code == 1
    # The error itself goes to stderr; the available-jobs hint (incl. chat-1)
    # confirms we reached the unknown-job branch, not the spec gate.
    assert "Available job IDs" in result.stdout
    assert "chat-1" in result.stdout
