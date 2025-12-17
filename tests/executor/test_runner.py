"""Tests for Step Execution Runner."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from spec.executor.adapters import EscalationRequired, ProtocolError, ToolNotFoundError
from spec.executor.runner import (
    IterationResult,
    RepoState,
    StepResult,
    StepRunner,
    TerminationReason,
    render_gate_package,
)


@pytest.fixture
def mock_repo(tmp_path: Path) -> Path:
    """Create a mock git repository."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    # Create initial commit
    (repo / "README.md").write_text("# Test Repo")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    return repo


@pytest.fixture
def sample_aip() -> dict[str, Any]:
    """Sample AIP document for testing."""
    return {
        "aip_id": "AIP-test-2024-12-13-001",
        "spec_version": "1.0.0",
        "goal": "Test goal",
        "plan": [
            {
                "id": "step-001",
                "prompt": "Implement feature X",
                "outputs": ["src/feature.py"],
                "verification_commands": ["python -c 'print(1)'"],
            },
            {
                "id": "step-002",
                "prompt": "Add tests",
                "outputs": ["tests/test_feature.py"],
            },
        ],
    }


@pytest.fixture
def mock_adapter() -> Any:
    """Create a mock adapter for testing."""
    from unittest.mock import MagicMock

    adapter = MagicMock()
    adapter.name.return_value = "mock"
    return adapter


class TestTerminationReason:
    """Tests for TerminationReason enum."""

    def test_pass_reason(self) -> None:
        """Test PASS termination reason."""
        assert TerminationReason.PASS.value == "PASS"

    def test_fail_reasons(self) -> None:
        """Test failure termination reasons."""
        assert TerminationReason.FAIL_VERIFY_RETRYABLE.value == "FAIL_VERIFY_RETRYABLE"
        assert TerminationReason.FAIL_SCOPE.value == "FAIL_SCOPE"
        assert TerminationReason.FAIL_PATCH_APPLY.value == "FAIL_PATCH_APPLY"
        assert TerminationReason.FAIL_ADAPTER_PROTOCOL.value == "FAIL_ADAPTER_PROTOCOL"
        assert TerminationReason.FAIL_DIRTY_WORKTREE.value == "FAIL_DIRTY_WORKTREE"

    def test_escalation_reasons(self) -> None:
        """Test escalation termination reasons."""
        assert TerminationReason.ESCALATE_NEEDS_HUMAN.value == "ESCALATE_NEEDS_HUMAN"
        assert TerminationReason.ESCALATE_AMBIGUOUS.value == "ESCALATE_AMBIGUOUS"

    def test_gate_reasons(self) -> None:
        """Test gate decision reasons."""
        assert TerminationReason.GATE_REJECTED.value == "GATE_REJECTED"
        assert TerminationReason.GATE_DEFERRED.value == "GATE_DEFERRED"


class TestRepoState:
    """Tests for RepoState dataclass."""

    def test_repo_state_fields(self) -> None:
        """Test RepoState has all required fields."""
        state = RepoState(
            commit="abc123",
            branch="main",
            dirty=False,
            baseline="abc123",
        )
        assert state.commit == "abc123"
        assert state.branch == "main"
        assert state.dirty is False
        assert state.baseline == "abc123"


class TestIterationResult:
    """Tests for IterationResult dataclass."""

    def test_iteration_result_defaults(self) -> None:
        """Test IterationResult default values."""
        result = IterationResult(iteration=0)
        assert result.iteration == 0
        assert result.patch_applied is False
        assert result.patch_path is None
        assert result.scope_result is None
        assert result.verification_result is None
        assert result.agent_json is None
        assert result.cmdlog_path is None
        assert result.error is None
        assert result.termination_reason is None


class TestStepResult:
    """Tests for StepResult dataclass."""

    def test_step_result_required_fields(self) -> None:
        """Test StepResult required fields."""
        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test",
            termination_reason=TerminationReason.PASS,
        )
        assert result.step_id == "step-001"
        assert result.aip_id == "AIP-test"
        assert result.termination_reason == TerminationReason.PASS
        assert result.iterations == []
        assert result.touched_files == []
        assert result.dry_run is False


class TestStepRunnerInit:
    """Tests for StepRunner initialization."""

    def test_init_with_defaults(self, mock_repo: Path) -> None:
        """Test StepRunner initialization with defaults."""
        runner = StepRunner(repo_root=mock_repo)
        assert runner.repo_root == mock_repo
        assert runner.runs_dir == mock_repo / "runs"
        assert runner.adapter_name == "claude"

    def test_init_with_custom_runs_dir(self, mock_repo: Path, tmp_path: Path) -> None:
        """Test StepRunner with custom runs directory."""
        runs_dir = tmp_path / "custom_runs"
        runner = StepRunner(repo_root=mock_repo, runs_dir=runs_dir)
        assert runner.runs_dir == runs_dir


class TestStepRunnerDryRun:
    """Tests for dry run execution."""

    def test_dry_run_creates_input_bundle(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test dry run creates input bundle and returns command."""
        runner = StepRunner(repo_root=mock_repo)

        result = runner.run_step(sample_aip, step_idx=0, dry_run=True)

        assert result.dry_run is True
        assert result.termination_reason == TerminationReason.PASS
        assert result.dry_run_command is not None
        assert "claude" in result.dry_run_command
        assert "--input" in result.dry_run_command

    def test_dry_run_writes_contract(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test dry run writes contract.yaml."""
        runner = StepRunner(repo_root=mock_repo)

        runner.run_step(sample_aip, step_idx=0, dry_run=True)

        # Find the input directory
        runs_dir = mock_repo / "runs"
        aip_dir = runs_dir / sample_aip["aip_id"]
        assert aip_dir.exists()

        # Check contract was written
        run_dirs = list(aip_dir.iterdir())
        assert len(run_dirs) == 1
        step_dir = run_dirs[0] / "step-001"
        assert (step_dir / "input" / "contract.yaml").exists()

    def test_dry_run_writes_prompt(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test dry run writes prompt.md."""
        runner = StepRunner(repo_root=mock_repo)

        runner.run_step(sample_aip, step_idx=0, dry_run=True)

        # Find the input directory
        runs_dir = mock_repo / "runs"
        aip_dir = runs_dir / sample_aip["aip_id"]
        run_dirs = list(aip_dir.iterdir())
        step_dir = run_dirs[0] / "step-001"

        prompt_path = step_dir / "input" / "prompt.md"
        assert prompt_path.exists()
        prompt_content = prompt_path.read_text()
        assert "step-001" in prompt_content
        assert "Implement feature X" in prompt_content

    def test_dry_run_writes_repo_state(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test dry run writes repo_state.json."""
        runner = StepRunner(repo_root=mock_repo)

        runner.run_step(sample_aip, step_idx=0, dry_run=True)

        # Find the input directory
        runs_dir = mock_repo / "runs"
        aip_dir = runs_dir / sample_aip["aip_id"]
        run_dirs = list(aip_dir.iterdir())
        step_dir = run_dirs[0] / "step-001"

        repo_state_path = step_dir / "input" / "repo_state.json"
        assert repo_state_path.exists()
        repo_state = json.loads(repo_state_path.read_text())
        assert "commit" in repo_state
        assert "branch" in repo_state
        assert repo_state["dirty"] is False


class TestStepRunnerDirtyWorktree:
    """Tests for dirty worktree handling."""

    def test_dirty_worktree_fails(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test execution fails with dirty worktree."""
        # Make repo dirty
        (mock_repo / "dirty.txt").write_text("dirty")

        runner = StepRunner(repo_root=mock_repo)
        result = runner.run_step(sample_aip, step_idx=0)

        assert result.termination_reason == TerminationReason.FAIL_DIRTY_WORKTREE
        assert "dirty" in result.error.lower()

    def test_allow_dirty_flag(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test --allow-dirty bypasses dirty check."""
        # Make repo dirty
        (mock_repo / "dirty.txt").write_text("dirty")

        runner = StepRunner(repo_root=mock_repo)
        result = runner.run_step(sample_aip, step_idx=0, dry_run=True, allow_dirty=True)

        # Should proceed to dry run
        assert result.termination_reason == TerminationReason.PASS
        assert result.dry_run is True


class TestStepRunnerInvalidStep:
    """Tests for invalid step index handling."""

    def test_step_index_out_of_range(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test invalid step index returns error."""
        runner = StepRunner(repo_root=mock_repo)

        result = runner.run_step(sample_aip, step_idx=99)

        assert result.termination_reason == TerminationReason.FAIL_ADAPTER_PROTOCOL
        assert "out of range" in result.error

    def test_negative_step_index(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test negative step index returns error."""
        runner = StepRunner(repo_root=mock_repo)

        result = runner.run_step(sample_aip, step_idx=-1)

        assert result.termination_reason == TerminationReason.FAIL_ADAPTER_PROTOCOL


class TestStepRunnerExecution:
    """Tests for step execution with mocked adapter."""

    def test_successful_execution(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test successful step execution."""
        runner = StepRunner(repo_root=mock_repo)

        # Mock adapter execute
        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            # Write required outputs
            (output_dir / "patch.diff").write_text("")  # Empty patch
            (output_dir / "agent.json").write_text(
                json.dumps(
                    {"status": "success", "needs_human": False, "notes": "Done"}
                )
            )
            (output_dir / "cmdlog.txt").write_text("")

        runner._adapter.execute = mock_execute

        result = runner.run_step(sample_aip, step_idx=0)

        assert result.termination_reason == TerminationReason.PASS
        assert len(result.iterations) == 1
        assert result.iterations[0].termination_reason == TerminationReason.PASS

    def test_adapter_tool_not_found(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test adapter tool not found error."""
        runner = StepRunner(repo_root=mock_repo)

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            raise ToolNotFoundError("claude")

        runner._adapter.execute = mock_execute

        result = runner.run_step(sample_aip, step_idx=0)

        assert result.termination_reason == TerminationReason.FAIL_ADAPTER_PROTOCOL
        assert len(result.iterations) == 1

    def test_adapter_protocol_error(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test adapter protocol error."""
        runner = StepRunner(repo_root=mock_repo)

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            raise ProtocolError("Invalid output")

        runner._adapter.execute = mock_execute

        result = runner.run_step(sample_aip, step_idx=0)

        assert result.termination_reason == TerminationReason.FAIL_ADAPTER_PROTOCOL

    def test_adapter_escalation_required(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test adapter escalation required."""
        runner = StepRunner(repo_root=mock_repo)

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            raise EscalationRequired("Human review needed", violations=["test"])

        runner._adapter.execute = mock_execute

        result = runner.run_step(sample_aip, step_idx=0)

        assert result.termination_reason == TerminationReason.ESCALATE_NEEDS_HUMAN

    def test_agent_needs_human(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test agent requesting human review via agent.json."""
        runner = StepRunner(repo_root=mock_repo)

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            (output_dir / "patch.diff").write_text("")
            (output_dir / "agent.json").write_text(
                json.dumps(
                    {"status": "needs_human", "needs_human": True, "notes": "Help!"}
                )
            )
            (output_dir / "cmdlog.txt").write_text("")

        runner._adapter.execute = mock_execute

        result = runner.run_step(sample_aip, step_idx=0)

        assert result.termination_reason == TerminationReason.ESCALATE_NEEDS_HUMAN

    def test_missing_patch_diff(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test missing patch.diff output."""
        runner = StepRunner(repo_root=mock_repo)

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            # Don't write patch.diff
            (output_dir / "agent.json").write_text(json.dumps({"status": "success"}))

        runner._adapter.execute = mock_execute

        result = runner.run_step(sample_aip, step_idx=0)

        assert result.termination_reason == TerminationReason.FAIL_ADAPTER_PROTOCOL
        assert "patch.diff" in result.error

    def test_missing_agent_json(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test missing agent.json output."""
        runner = StepRunner(repo_root=mock_repo)

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            (output_dir / "patch.diff").write_text("")
            # Don't write agent.json

        runner._adapter.execute = mock_execute

        result = runner.run_step(sample_aip, step_idx=0)

        assert result.termination_reason == TerminationReason.FAIL_ADAPTER_PROTOCOL
        assert "agent.json" in result.error


class TestStepRunnerScopeViolation:
    """Tests for scope violation handling."""

    def test_scope_violation_no_retry(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test scope violation causes immediate failure (no retry)."""
        runner = StepRunner(repo_root=mock_repo)

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            # Write empty patch (no changes via patch)
            (output_dir / "patch.diff").write_text("")
            (output_dir / "agent.json").write_text(
                json.dumps({"status": "success", "needs_human": False, "notes": ""})
            )
            (output_dir / "cmdlog.txt").write_text("")

            # Create a forbidden file directly (simulating scope violation)
            # This file will show up in git diff but violates scope
            (repo_root / ".env").write_text("SECRET=bad")
            # Track this file so git diff shows it
            subprocess.run(["git", "add", ".env"], cwd=repo_root, capture_output=True)

        runner._adapter.execute = mock_execute

        result = runner.run_step(sample_aip, step_idx=0, max_iterations=3)

        assert result.termination_reason == TerminationReason.FAIL_SCOPE
        # Should NOT retry on scope violation
        assert len(result.iterations) == 1


class TestStepRunnerRetry:
    """Tests for retry behavior."""

    def test_retry_on_verification_failure(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test retry on verification failure."""
        runner = StepRunner(repo_root=mock_repo)

        call_count = 0

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            nonlocal call_count
            call_count += 1
            (output_dir / "patch.diff").write_text("")
            (output_dir / "agent.json").write_text(
                json.dumps({"status": "success", "needs_human": False, "notes": ""})
            )
            (output_dir / "cmdlog.txt").write_text("")

        runner._adapter.execute = mock_execute

        # Use a failing verification command
        sample_aip["plan"][0]["verification_commands"] = ["false"]

        result = runner.run_step(sample_aip, step_idx=0, max_iterations=3)

        assert result.termination_reason == TerminationReason.FAIL_VERIFY_RETRYABLE
        assert len(result.iterations) == 3
        assert call_count == 3

    def test_max_iterations_respected(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test max iterations is respected."""
        runner = StepRunner(repo_root=mock_repo)

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            (output_dir / "patch.diff").write_text("")
            (output_dir / "agent.json").write_text(
                json.dumps({"status": "success", "needs_human": False, "notes": ""})
            )
            (output_dir / "cmdlog.txt").write_text("")

        runner._adapter.execute = mock_execute

        sample_aip["plan"][0]["verification_commands"] = ["false"]

        result = runner.run_step(sample_aip, step_idx=0, max_iterations=5)

        assert len(result.iterations) == 5

    def test_failure_context_written_on_retry(
        self, mock_repo: Path, sample_aip: dict[str, Any]
    ) -> None:
        """Test failure_context.json written on retry iterations."""
        runner = StepRunner(repo_root=mock_repo)

        failure_contexts = []

        def mock_execute(input_dir: Path, output_dir: Path, repo_root: Path) -> None:
            # Check if failure_context.json exists
            fc_path = input_dir / "failure_context.json"
            if fc_path.exists():
                failure_contexts.append(json.loads(fc_path.read_text()))

            (output_dir / "patch.diff").write_text("")
            (output_dir / "agent.json").write_text(
                json.dumps({"status": "success", "needs_human": False, "notes": ""})
            )
            (output_dir / "cmdlog.txt").write_text("")

        runner._adapter.execute = mock_execute

        sample_aip["plan"][0]["verification_commands"] = ["false"]

        runner.run_step(sample_aip, step_idx=0, max_iterations=3)

        # First iteration has no failure context, subsequent ones do
        assert len(failure_contexts) == 2  # iterations 1 and 2
        assert failure_contexts[0]["iteration"] == 1
        assert failure_contexts[1]["iteration"] == 2


class TestRenderGatePackage:
    """Tests for gate package rendering."""

    def test_render_pass_result(self) -> None:
        """Test rendering a passing result."""
        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test",
            termination_reason=TerminationReason.PASS,
            touched_files=["src/main.py"],
        )

        markdown = render_gate_package(result, Path("/tmp"))

        assert "step-001" in markdown
        assert "AIP-test" in markdown
        assert "PASS" in markdown
        assert "src/main.py" in markdown

    def test_render_error_result(self) -> None:
        """Test rendering an error result."""
        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test",
            termination_reason=TerminationReason.FAIL_SCOPE,
            error="Touched forbidden file .env",
        )

        markdown = render_gate_package(result, Path("/tmp"))

        assert "FAIL_SCOPE" in markdown
        assert "Error" in markdown
        assert ".env" in markdown

    def test_render_dry_run_result(self) -> None:
        """Test rendering a dry run result."""
        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test",
            termination_reason=TerminationReason.PASS,
            dry_run=True,
            dry_run_command="claude --input /tmp/input --output /tmp/output",
        )

        markdown = render_gate_package(result, Path("/tmp"))

        assert "Dry Run" in markdown
        assert "claude --input" in markdown


class TestArtifactTreeCompleteness:
    """Tests asserting artifact tree completeness for each termination path."""

    def _find_run_dir(self, runs_dir: Path) -> Path:
        """Find the first run directory."""
        # Structure: runs/<aip_id>/<timestamp>/<step_id>
        for aip_dir in runs_dir.iterdir():
            for timestamp_dir in aip_dir.iterdir():
                for step_dir in timestamp_dir.iterdir():
                    return step_dir
        raise ValueError("No run directory found")

    def _assert_step_root_artifacts(self, run_dir: Path) -> None:
        """Assert required artifacts exist at step root."""
        # Required at step root (always)
        assert (run_dir / "result.json").exists(), "result.json missing"
        assert (run_dir / "gate.md").exists(), "gate.md missing"

    def _assert_input_bundle(self, run_dir: Path) -> None:
        """Assert input bundle was written."""
        input_dir = run_dir / "input"
        assert input_dir.exists(), "input/ directory missing"
        assert (input_dir / "contract.yaml").exists(), "contract.yaml missing"
        assert (input_dir / "prompt.md").exists(), "prompt.md missing"
        assert (input_dir / "repo_state.json").exists(), "repo_state.json missing"

    def _assert_iteration_artifacts(self, iter_dir: Path, ran_to_completion: bool) -> None:
        """Assert required iteration artifacts exist."""
        # Always required
        output_dir = iter_dir / "output"
        assert output_dir.exists(), f"{iter_dir.name}/output/ missing"
        assert (output_dir / "patch.diff").exists(), f"{iter_dir.name}/output/patch.diff missing"
        assert (output_dir / "agent.json").exists(), f"{iter_dir.name}/output/agent.json missing"

        # Only if ran to scope check
        if ran_to_completion:
            assert (iter_dir / "policy_report.json").exists(), f"{iter_dir.name}/policy_report.json missing"

    def test_pass_path_artifacts(
        self, mock_repo: Path, mock_adapter: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test artifact completeness on PASS path."""
        # Setup mock adapter to produce valid outputs
        def mock_execute(
            input_dir: Path, output_dir: Path, repo_root: Path
        ) -> None:
            (output_dir / "patch.diff").write_text("")
            (output_dir / "agent.json").write_text(
                json.dumps({"status": "success", "needs_human": False, "notes": "ok"})
            )
            (output_dir / "cmdlog.txt").write_text("")

        mock_adapter.execute = mock_execute

        monkeypatch.setattr(
            "spec.executor.runner.get_adapter",
            lambda name: mock_adapter,
        )

        runs_dir = mock_repo / "runs"
        runner = StepRunner(mock_repo, runs_dir=runs_dir)

        aip = {
            "aip_id": "AIP-test",
            "plan": [
                {
                    "id": "step-001",
                    "prompt": "Do something",
                    "verification_commands": ["true"],
                }
            ],
        }

        result = runner.run_step(aip, step_idx=0)

        assert result.termination_reason == TerminationReason.PASS

        run_dir = self._find_run_dir(runs_dir)
        self._assert_step_root_artifacts(run_dir)
        self._assert_input_bundle(run_dir)

        # Check iteration artifacts
        iter_dir = run_dir / "iter-0"
        self._assert_iteration_artifacts(iter_dir, ran_to_completion=True)

        # Verify result.json has required fields
        result_json = json.loads((run_dir / "result.json").read_text())
        assert result_json["aip_id"] == "AIP-test"
        assert result_json["step_id"] == "step-001"
        assert result_json["step_idx"] == 0
        assert result_json["termination_reason"] == "PASS"
        assert result_json["adapter_name"] == "claude"
        assert result_json["baseline_sha"] is not None

    def test_fail_adapter_protocol_artifacts(
        self, mock_repo: Path, mock_adapter: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test artifact completeness on FAIL_ADAPTER_PROTOCOL path."""
        mock_adapter.execute.side_effect = ProtocolError("Invalid JSON", failure_category="parse_error")

        monkeypatch.setattr(
            "spec.executor.runner.get_adapter",
            lambda name: mock_adapter,
        )

        runs_dir = mock_repo / "runs"
        runner = StepRunner(mock_repo, runs_dir=runs_dir)

        aip = {
            "aip_id": "AIP-test",
            "plan": [{"id": "step-001", "prompt": "Do something"}],
        }

        result = runner.run_step(aip, step_idx=0)

        assert result.termination_reason == TerminationReason.FAIL_ADAPTER_PROTOCOL

        run_dir = self._find_run_dir(runs_dir)
        self._assert_step_root_artifacts(run_dir)
        self._assert_input_bundle(run_dir)

        # Iteration should have stub artifacts
        iter_dir = run_dir / "iter-0"
        assert (iter_dir / "output" / "patch.diff").exists()
        assert (iter_dir / "output" / "agent.json").exists()

        # Stub agent.json should indicate failure
        stub = json.loads((iter_dir / "output" / "agent.json").read_text())
        assert stub["status"] == "failure"

    def test_fail_scope_artifacts(
        self, mock_repo: Path, mock_adapter: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test artifact completeness on FAIL_SCOPE path."""
        # Adapter produces patch that modifies a forbidden file.
        # Create a valid patch that modifies pyproject.toml (which we'll forbid).
        def mock_execute(
            input_dir: Path, output_dir: Path, repo_root: Path
        ) -> None:
            # Create pyproject.toml first (add to repo if it doesn't exist)
            pyproject = repo_root / "pyproject.toml"
            if not pyproject.exists():
                pyproject.write_text("[project]\nname = 'test'\n")
                subprocess.run(["git", "add", "pyproject.toml"], cwd=repo_root, check=True)
                subprocess.run(["git", "commit", "-m", "add pyproject"], cwd=repo_root, check=True)

            # Create patch that modifies pyproject.toml
            patch = """--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,2 +1,3 @@
 [project]
 name = 'test'
+version = '1.0.0'
"""
            (output_dir / "patch.diff").write_text(patch)
            (output_dir / "agent.json").write_text(
                json.dumps({"status": "success", "needs_human": False, "notes": "ok"})
            )

        mock_adapter.execute = mock_execute

        monkeypatch.setattr(
            "spec.executor.runner.get_adapter",
            lambda name: mock_adapter,
        )

        runs_dir = mock_repo / "runs"
        runner = StepRunner(mock_repo, runs_dir=runs_dir)

        aip = {
            "aip_id": "AIP-test",
            "plan": [
                {
                    "id": "step-001",
                    "prompt": "Do something",
                    "forbidden_paths": ["pyproject.toml"],
                }
            ],
        }

        result = runner.run_step(aip, step_idx=0)

        assert result.termination_reason == TerminationReason.FAIL_SCOPE

        run_dir = self._find_run_dir(runs_dir)
        self._assert_step_root_artifacts(run_dir)
        self._assert_input_bundle(run_dir)

        # Policy report should exist
        assert (run_dir / "policy_report.json").exists()

    def test_escalate_needs_human_artifacts(
        self, mock_repo: Path, mock_adapter: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test artifact completeness on ESCALATE_NEEDS_HUMAN path."""
        mock_adapter.execute.side_effect = EscalationRequired("Needs review", violations=["compound_operator"])

        monkeypatch.setattr(
            "spec.executor.runner.get_adapter",
            lambda name: mock_adapter,
        )

        runs_dir = mock_repo / "runs"
        runner = StepRunner(mock_repo, runs_dir=runs_dir)

        aip = {
            "aip_id": "AIP-test",
            "plan": [{"id": "step-001", "prompt": "Do something"}],
        }

        result = runner.run_step(aip, step_idx=0)

        assert result.termination_reason == TerminationReason.ESCALATE_NEEDS_HUMAN

        run_dir = self._find_run_dir(runs_dir)
        self._assert_step_root_artifacts(run_dir)
        self._assert_input_bundle(run_dir)

        # Iteration should have stub artifacts
        iter_dir = run_dir / "iter-0"
        assert (iter_dir / "output" / "patch.diff").exists()
        assert (iter_dir / "output" / "agent.json").exists()

    def test_max_iterations_artifacts(
        self, mock_repo: Path, mock_adapter: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test artifact completeness when max iterations exhausted."""
        call_count = 0

        def mock_execute(
            input_dir: Path, output_dir: Path, repo_root: Path
        ) -> None:
            nonlocal call_count
            call_count += 1
            (output_dir / "patch.diff").write_text("")
            (output_dir / "agent.json").write_text(
                json.dumps({"status": "success", "needs_human": False, "notes": "ok"})
            )

        mock_adapter.execute = mock_execute

        monkeypatch.setattr(
            "spec.executor.runner.get_adapter",
            lambda name: mock_adapter,
        )

        runs_dir = mock_repo / "runs"
        runner = StepRunner(mock_repo, runs_dir=runs_dir)

        aip = {
            "aip_id": "AIP-test",
            "plan": [
                {
                    "id": "step-001",
                    "prompt": "Do something",
                    "verification_commands": ["false"],  # Always fails
                }
            ],
        }

        result = runner.run_step(aip, step_idx=0, max_iterations=3)

        assert result.termination_reason == TerminationReason.FAIL_VERIFY_RETRYABLE
        assert call_count == 3

        run_dir = self._find_run_dir(runs_dir)
        self._assert_step_root_artifacts(run_dir)
        self._assert_input_bundle(run_dir)

        # All iteration directories should exist
        for i in range(3):
            iter_dir = run_dir / f"iter-{i}"
            assert iter_dir.exists(), f"iter-{i} missing"
            self._assert_iteration_artifacts(iter_dir, ran_to_completion=True)

            # Iterations > 0 should have failure_context.json in input
            if i > 0:
                assert (iter_dir / "input" / "failure_context.json").exists()

    def test_dirty_worktree_artifacts(
        self, mock_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test artifacts are written even on dirty worktree failure."""
        # Make worktree dirty
        (mock_repo / "dirty.txt").write_text("uncommitted")

        runs_dir = mock_repo / "runs"
        runner = StepRunner(mock_repo, runs_dir=runs_dir)

        aip = {
            "aip_id": "AIP-test",
            "plan": [{"id": "step-001", "prompt": "Do something"}],
        }

        result = runner.run_step(aip, step_idx=0)

        assert result.termination_reason == TerminationReason.FAIL_DIRTY_WORKTREE

        run_dir = self._find_run_dir(runs_dir)
        # Even early failures should produce result.json and gate.md
        self._assert_step_root_artifacts(run_dir)
