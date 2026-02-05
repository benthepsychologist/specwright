"""Tests for the python backend with governance callables."""

from pathlib import Path

import pytest

from spec.executor.backends.python import (
    PythonBackend,
    get_callable,
    list_callables,
    register_callable,
)


class TestCallableRegistry:
    def test_governance_callables_registered(self) -> None:
        """Governance callables should be auto-registered."""
        # Force registration
        from spec.executor.backends.registry import _auto_register
        _auto_register()

        names = list_callables()
        assert "governance.validate_build" in names
        assert "governance.validate_epic" in names
        assert "governance.validate_contracts" in names

    def test_get_callable(self) -> None:
        fn = get_callable("governance.validate_build")
        assert fn is not None
        assert callable(fn)


class TestPythonBackendDispatch:
    def test_dispatch_success(self, tmp_path: Path) -> None:
        """Test backend dispatch with a passing callable."""
        def my_func(*, payload, repo_path):
            return {
                "passed": True,
                "data": {"result": "ok", "count": payload.get("count", 0)},
                "summary": "All good",
            }

        register_callable("test.pass", my_func)

        backend = PythonBackend()
        from spec.executor.schemas import Common, StepManifest

        manifest = StepManifest(
            step_n=1,
            step_id="test.step",
            backend="python",
            payload={"callable": "test.pass", "count": 42},
            common=Common(
                repo_path=str(tmp_path),
                branch="main",
                base_commit="abc123",
                timeout_s=60,
            ),
        )

        artifacts = tmp_path / "artifacts"
        from spec.executor.schemas import Policy
        policy = Policy()

        capture = backend.dispatch(manifest, artifacts, policy)
        assert capture.agent.exit_code == 0
        assert len(capture.assessments) == 1
        assert capture.assessments[0]["result"] == "ok"
        assert capture.assessments[0]["count"] == 42

    def test_dispatch_failure(self, tmp_path: Path) -> None:
        """Test backend dispatch with a failing callable."""
        def my_func(*, payload, repo_path):
            return {
                "passed": False,
                "data": {"error": "bad thing"},
                "summary": "FAILED",
            }

        register_callable("test.fail", my_func)

        backend = PythonBackend()
        from spec.executor.schemas import Common, Policy, StepManifest

        manifest = StepManifest(
            step_n=1,
            step_id="test.step",
            backend="python",
            payload={"callable": "test.fail"},
            common=Common(
                repo_path=str(tmp_path),
                branch="main",
                base_commit="abc123",
                timeout_s=60,
            ),
        )

        capture = backend.dispatch(manifest, tmp_path / "artifacts", Policy())
        assert capture.agent.exit_code == 1
        assert capture.assessments[0]["error"] == "bad thing"

    def test_dispatch_exception(self, tmp_path: Path) -> None:
        """Test backend handles callable exceptions gracefully."""
        def my_func(*, payload, repo_path):
            raise ValueError("boom")

        register_callable("test.boom", my_func)

        backend = PythonBackend()
        from spec.executor.schemas import Common, Policy, StepManifest

        manifest = StepManifest(
            step_n=1,
            step_id="test.step",
            backend="python",
            payload={"callable": "test.boom"},
            common=Common(
                repo_path=str(tmp_path),
                branch="main",
                base_commit="abc123",
                timeout_s=60,
            ),
        )

        capture = backend.dispatch(manifest, tmp_path / "artifacts", Policy())
        assert capture.agent.exit_code == 1
        # stderr should contain the traceback
        stderr = (tmp_path / "artifacts" / "stderr.txt").read_text()
        assert "boom" in stderr

    def test_dispatch_unknown_callable(self, tmp_path: Path) -> None:
        """Test backend rejects unknown callables."""
        backend = PythonBackend()
        from spec.executor.backends.base import BackendError
        from spec.executor.schemas import Common, Policy, StepManifest

        manifest = StepManifest(
            step_n=1,
            step_id="test.step",
            backend="python",
            payload={"callable": "does.not.exist"},
            common=Common(
                repo_path=str(tmp_path),
                branch="main",
                base_commit="abc123",
                timeout_s=60,
            ),
        )

        with pytest.raises(BackendError, match="Unknown callable"):
            backend.dispatch(manifest, tmp_path / "artifacts", Policy())


class TestGovernanceCallablesIntegration:
    """Test governance callables return proper structured data."""

    def test_validate_build_returns_report(self, tmp_path: Path) -> None:
        """validate_build should return a structured ValidationReport dict."""
        from spec.governance.callables import validate_build

        # Create a minimal repo with a matching build.yaml
        (tmp_path / "src").mkdir()
        result = validate_build(
            payload={"project": "nonexistent_project_xyz"},
            repo_path=tmp_path,
        )
        assert result["passed"] is False
        assert "error" in result["data"]
