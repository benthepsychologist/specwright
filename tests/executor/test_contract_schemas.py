"""
Tests for autonomous step execution contract schemas.
"""

import json
from pathlib import Path

import pytest
import yaml

from spec.executor.schemas import (
    AgentResponse,
    AgentStatus,
    CodexConfig,
    CommandResult,
    FailedCommand,
    FailureContext,
    RepoState,
    ScopeResult,
    ScopeViolation,
    StepContract,
    StepResult,
    TerminationReason,
    VerificationResult,
)


# =============================================================================
# TerminationReason Tests
# =============================================================================


class TestTerminationReason:
    """Tests for TerminationReason enum."""

    def test_all_values_defined(self):
        """All expected termination reasons exist."""
        expected = {
            "PASS",
            "FAIL_VERIFY_RETRYABLE",
            "FAIL_SCOPE",
            "FAIL_PATCH_APPLY",
            "FAIL_ADAPTER_PROTOCOL",
            "FAIL_DIRTY_WORKTREE",
            "ESCALATE_NEEDS_HUMAN",
            "ESCALATE_AMBIGUOUS",
            "GATE_REJECTED",
            "GATE_DEFERRED",
        }
        actual = {r.value for r in TerminationReason}
        assert actual == expected

    def test_is_retryable(self):
        """Only FAIL_VERIFY_RETRYABLE is retryable."""
        retryable = [r for r in TerminationReason if r.is_retryable()]
        assert retryable == [TerminationReason.FAIL_VERIFY_RETRYABLE]

    def test_is_success(self):
        """Only PASS is success."""
        success = [r for r in TerminationReason if r.is_success()]
        assert success == [TerminationReason.PASS]

    def test_requires_human(self):
        """Correct reasons require human intervention."""
        human_required = {r for r in TerminationReason if r.requires_human()}
        expected = {
            TerminationReason.ESCALATE_NEEDS_HUMAN,
            TerminationReason.ESCALATE_AMBIGUOUS,
            TerminationReason.GATE_REJECTED,
            TerminationReason.GATE_DEFERRED,
        }
        assert human_required == expected


# =============================================================================
# CodexConfig Tests
# =============================================================================


class TestCodexConfig:
    """Tests for CodexConfig schema."""

    def test_default_values(self):
        """Defaults are set correctly."""
        config = CodexConfig()
        assert config.sandbox == "read-only"
        assert config.emit_json_events is True
        assert config.output_schema is None

    def test_custom_values(self):
        """Custom values override defaults."""
        config = CodexConfig(
            sandbox="workspace-write",
            emit_json_events=False,
            output_schema="/path/to/schema.json",
        )
        assert config.sandbox == "workspace-write"
        assert config.emit_json_events is False
        assert config.output_schema == "/path/to/schema.json"

    def test_rejects_extra_fields(self):
        """Extra fields are rejected."""
        with pytest.raises(ValueError):
            CodexConfig(sandbox="read-only", extra_field="not allowed")


# =============================================================================
# StepContract Tests
# =============================================================================


class TestStepContract:
    """Tests for StepContract schema."""

    def test_minimal_contract(self, tmp_path):
        """Minimal contract with required fields."""
        contract = StepContract(
            step_id="step-001",
            aip_id="AIP-test-2024-01-01-001",
            repo_root=tmp_path,
        )
        assert contract.step_id == "step-001"
        assert contract.aip_id == "AIP-test-2024-01-01-001"
        assert contract.repo_root == tmp_path
        # Check defaults
        assert contract.allowed_paths == ["src/**", "tests/**"]
        assert contract.forbidden_paths == []
        assert contract.allowed_ops == ["read", "write", "test"]
        assert contract.max_iterations == 3
        assert isinstance(contract.codex, CodexConfig)

    def test_full_contract(self, tmp_path):
        """Full contract with all fields."""
        contract = StepContract(
            step_id="step-003",
            aip_id="AIP-myproject-2024-12-13-001",
            repo_root=tmp_path,
            allowed_paths=["src/**", "tests/**", "docs/**"],
            forbidden_paths=["**/*.lock", "pyproject.toml", ".env*"],
            allowed_ops=["read", "write", "test", "lint"],
            max_iterations=5,
            codex=CodexConfig(sandbox="workspace-write"),
        )
        assert "docs/**" in contract.allowed_paths
        assert "**/*.lock" in contract.forbidden_paths
        assert "lint" in contract.allowed_ops
        assert contract.max_iterations == 5
        assert contract.codex.sandbox == "workspace-write"

    def test_max_iterations_bounds(self, tmp_path):
        """max_iterations must be between 1 and 10."""
        # Valid bounds
        StepContract(step_id="s", aip_id="a", repo_root=tmp_path, max_iterations=1)
        StepContract(step_id="s", aip_id="a", repo_root=tmp_path, max_iterations=10)

        # Invalid bounds
        with pytest.raises(ValueError):
            StepContract(step_id="s", aip_id="a", repo_root=tmp_path, max_iterations=0)
        with pytest.raises(ValueError):
            StepContract(step_id="s", aip_id="a", repo_root=tmp_path, max_iterations=11)

    def test_yaml_roundtrip(self, tmp_path):
        """Contract can be serialized to YAML and back."""
        contract = StepContract(
            step_id="step-001",
            aip_id="AIP-test",
            repo_root=tmp_path,
            allowed_paths=["src/**"],
            forbidden_paths=["*.lock"],
        )
        yaml_str = yaml.dump(contract.model_dump(mode="json"), default_flow_style=False)
        loaded = yaml.safe_load(yaml_str)
        restored = StepContract.model_validate(loaded)
        assert restored.step_id == contract.step_id
        assert restored.allowed_paths == contract.allowed_paths


# =============================================================================
# RepoState Tests
# =============================================================================


class TestRepoState:
    """Tests for RepoState schema."""

    def test_valid_repo_state(self):
        """Valid repo state."""
        state = RepoState(
            commit="abc123def456",
            branch="feat/my-feature",
            dirty=False,
            baseline="abc123def456",
        )
        assert state.commit == "abc123def456"
        assert state.branch == "feat/my-feature"
        assert state.dirty is False
        assert state.baseline == "abc123def456"

    def test_dirty_state(self):
        """Dirty repo state."""
        state = RepoState(
            commit="abc123",
            branch="main",
            dirty=True,
            baseline="abc123",
        )
        assert state.dirty is True

    def test_json_roundtrip(self):
        """RepoState can be serialized to JSON and back."""
        state = RepoState(
            commit="abc123",
            branch="main",
            dirty=False,
            baseline="abc123",
        )
        json_str = json.dumps(state.model_dump())
        loaded = json.loads(json_str)
        restored = RepoState.model_validate(loaded)
        assert restored == state


# =============================================================================
# FailureContext Tests
# =============================================================================


class TestFailureContext:
    """Tests for FailureContext schema."""

    def test_minimal_failure_context(self):
        """Minimal failure context."""
        ctx = FailureContext(
            iteration=1,
            failure_category="verify_fail",
        )
        assert ctx.iteration == 1
        assert ctx.failure_category == "verify_fail"
        assert ctx.failed_commands == []
        assert ctx.previous_patch_path is None

    def test_full_failure_context(self):
        """Full failure context with failed commands."""
        ctx = FailureContext(
            iteration=2,
            failure_category="verify_fail",
            failed_commands=[
                FailedCommand(
                    command="pytest -q",
                    exit_code=1,
                    stderr_tail="FAILED test_x - AssertionError",
                ),
            ],
            previous_patch_path="iter-1/patch.diff",
            previous_verification_report_path="iter-1/verification_report.json",
        )
        assert ctx.iteration == 2
        assert len(ctx.failed_commands) == 1
        assert ctx.failed_commands[0].exit_code == 1

    def test_iteration_must_be_non_negative(self):
        """iteration must be >= 0."""
        with pytest.raises(ValueError):
            FailureContext(iteration=-1, failure_category="verify_fail")


# =============================================================================
# AgentResponse Tests
# =============================================================================


class TestAgentResponse:
    """Tests for AgentResponse schema."""

    def test_success_response(self):
        """Success response."""
        response = AgentResponse(
            status=AgentStatus.success,
            needs_human=False,
            notes="Implemented feature; tests pass.",
        )
        assert response.status == AgentStatus.success
        assert response.needs_human is False
        assert "tests pass" in response.notes

    def test_needs_human_response(self):
        """Response requesting human intervention."""
        response = AgentResponse(
            status=AgentStatus.needs_human,
            needs_human=True,
            notes="Cannot determine correct behavior from spec.",
        )
        assert response.status == AgentStatus.needs_human
        assert response.needs_human is True

    def test_failure_response(self):
        """Failure response."""
        response = AgentResponse(
            status=AgentStatus.failure,
            needs_human=False,
            notes="Could not fix all test failures.",
        )
        assert response.status == AgentStatus.failure


# =============================================================================
# ScopeResult Tests
# =============================================================================


class TestScopeResult:
    """Tests for ScopeResult schema."""

    def test_passed_result(self):
        """Scope check passed."""
        result = ScopeResult(
            passed=True,
            violations=[],
            touched_files=["src/main.py", "tests/test_main.py"],
        )
        assert result.passed is True
        assert result.violations == []
        assert len(result.touched_files) == 2

    def test_failed_result(self):
        """Scope check failed with violations."""
        result = ScopeResult(
            passed=False,
            violations=[
                ScopeViolation(
                    file_path="pyproject.toml",
                    violation_type="forbidden",
                    matched_pattern="pyproject.toml",
                ),
                ScopeViolation(
                    file_path="README.md",
                    violation_type="not_allowed",
                    matched_pattern=None,
                ),
            ],
            touched_files=["src/main.py", "pyproject.toml", "README.md"],
        )
        assert result.passed is False
        assert len(result.violations) == 2


# =============================================================================
# VerificationResult Tests
# =============================================================================


class TestVerificationResult:
    """Tests for VerificationResult schema."""

    def test_passed_result(self):
        """Verification passed."""
        result = VerificationResult(
            passed=True,
            commands=[
                CommandResult(
                    command="pytest -q",
                    exit_code=0,
                    stdout="5 passed",
                    stderr="",
                    duration_ms=1500,
                    timed_out=False,
                ),
            ],
        )
        assert result.passed is True
        assert result.failure_category is None

    def test_failed_result(self):
        """Verification failed."""
        result = VerificationResult(
            passed=False,
            commands=[
                CommandResult(
                    command="pytest -q",
                    exit_code=1,
                    stdout="",
                    stderr="FAILED test_x",
                    duration_ms=1500,
                    timed_out=False,
                ),
            ],
            failure_category="test_fail",
        )
        assert result.passed is False
        assert result.failure_category == "test_fail"

    def test_timeout_result(self):
        """Command timed out."""
        result = VerificationResult(
            passed=False,
            commands=[
                CommandResult(
                    command="pytest tests/",
                    exit_code=124,
                    stdout="",
                    stderr="",
                    duration_ms=300000,
                    timed_out=True,
                ),
            ],
            failure_category="timeout",
        )
        assert result.commands[0].timed_out is True


# =============================================================================
# StepResult Tests
# =============================================================================


class TestStepResult:
    """Tests for StepResult schema."""

    def test_success_result(self, tmp_path):
        """Successful step result."""
        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test",
            termination_reason=TerminationReason.PASS,
            iterations_used=1,
            final_patch_path="iter-0/patch.diff",
            touched_files=["src/main.py"],
            verification_passed=True,
            scope_passed=True,
            gate_package_path="gate.md",
            artifacts_dir=tmp_path,
        )
        assert result.termination_reason == TerminationReason.PASS
        assert result.termination_reason.is_success()
        assert result.verification_passed is True

    def test_failed_result(self, tmp_path):
        """Failed step result."""
        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test",
            termination_reason=TerminationReason.FAIL_SCOPE,
            iterations_used=1,
            scope_passed=False,
            error="Modified forbidden file: pyproject.toml",
            artifacts_dir=tmp_path,
        )
        assert result.termination_reason == TerminationReason.FAIL_SCOPE
        assert not result.termination_reason.is_retryable()
        assert result.error is not None

    def test_escalation_result(self, tmp_path):
        """Step requiring human intervention."""
        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test",
            termination_reason=TerminationReason.ESCALATE_NEEDS_HUMAN,
            iterations_used=2,
            verification_passed=True,
            scope_passed=True,
            artifacts_dir=tmp_path,
            metadata={"agent_notes": "Cannot determine correct behavior"},
        )
        assert result.termination_reason.requires_human()
        assert "agent_notes" in result.metadata
