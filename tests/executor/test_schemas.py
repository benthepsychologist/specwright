"""
Unit tests for executor v2 schemas.
"""

from datetime import datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from spec.executor.schemas import (
    AgentCapture,
    AttemptRecord,
    Backend,
    Common,
    GitCapture,
    JobDef,
    JobInstance,
    OutcomeStatus,
    Policy,
    RepoScope,
    RunRecord,
    RunStatus,
    Step,
    StepCapture,
    StepManifest,
    StepOutcome,
    StepTemplate,
)
from spec.executor.schemas.attempt import AttemptStatus


class TestBackendEnum:
    """Tests for Backend enum."""

    def test_backend_values(self):
        assert Backend.cmd.value == "cmd"
        assert Backend.llm.value == "llm"
        assert Backend.claude_code.value == "claude-code"
        assert Backend.codex.value == "codex"


class TestRunStatus:
    """Tests for RunStatus enum."""

    def test_run_status_values(self):
        assert RunStatus.pending.value == "pending"
        assert RunStatus.running.value == "running"
        assert RunStatus.completed.value == "completed"
        assert RunStatus.failed.value == "failed"
        assert RunStatus.cancelled.value == "cancelled"


class TestOutcomeStatus:
    """Tests for OutcomeStatus enum."""

    def test_outcome_status_values(self):
        assert OutcomeStatus.completed.value == "completed"
        assert OutcomeStatus.failed.value == "failed"
        assert OutcomeStatus.timeout.value == "timeout"
        assert OutcomeStatus.cancelled.value == "cancelled"


class TestRepoScope:
    """Tests for RepoScope model."""

    def test_valid_repo_scope(self):
        scope = RepoScope(
            repo_path=Path("/workspace/myrepo"),
            branch="main",
            base_commit="abc123def456",
        )
        assert scope.repo_path == Path("/workspace/myrepo")
        assert scope.branch == "main"
        assert scope.base_commit == "abc123def456"

    def test_repo_scope_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            RepoScope(
                repo_path=Path("/workspace/myrepo"),
                branch="main",
                base_commit="abc123",
                extra_field="not allowed",
            )


class TestPolicy:
    """Tests for Policy model."""

    def test_default_policy(self):
        policy = Policy()
        assert policy.profile == "default"
        assert "git push" in policy.blocked_commands
        assert "git merge" in policy.blocked_commands
        assert policy.allow_commit is True
        assert policy.allow_push is False
        assert policy.allow_merge is False

    def test_custom_policy(self):
        policy = Policy(
            profile="strict",
            blocked_commands=["git push", "git merge", "rm -rf"],
            allow_commit=False,
            allow_push=False,
            allow_merge=False,
        )
        assert policy.profile == "strict"
        assert len(policy.blocked_commands) == 3
        assert policy.allow_commit is False


class TestRunRecord:
    """Tests for RunRecord model."""

    def test_valid_run_record(self):
        record = RunRecord(
            run_id="run-20260122-001",
            job_id="aip-1",
            job_hash="sha256:abc123",
            repo=RepoScope(
                repo_path=Path("/workspace/myrepo"),
                branch="feat/test",
                base_commit="abc123",
            ),
        )
        assert record.run_id == "run-20260122-001"
        assert record.status == RunStatus.pending
        assert record.error is None

    def test_run_record_yaml_roundtrip(self):
        record = RunRecord(
            run_id="run-test",
            job_id="aip-1",
            job_hash="sha256:abc",
            repo=RepoScope(
                repo_path=Path("/workspace/repo"),
                branch="main",
                base_commit="def456",
            ),
            status=RunStatus.running,
        )
        data = record.model_dump(mode="json")
        yaml_str = yaml.dump(data)
        loaded = yaml.safe_load(yaml_str)
        restored = RunRecord.model_validate(loaded)
        assert restored.run_id == record.run_id
        assert restored.status == record.status


class TestStepTemplate:
    """Tests for StepTemplate model."""

    def test_valid_step_template(self):
        template = StepTemplate(
            step_id="branch.create",
            backend=Backend.cmd,
            description="Create feature branch",
            payload={"command": "git checkout -b @payload.branch"},
        )
        assert template.step_id == "branch.create"
        assert template.backend == Backend.cmd
        assert template.condition is None

    def test_step_template_with_condition(self):
        template = StepTemplate(
            step_id="optional.step",
            backend=Backend.llm,
            condition="@ctx.run_llm == true",
            payload={"prompt": "Do something"},
        )
        assert template.condition == "@ctx.run_llm == true"


class TestJobDef:
    """Tests for JobDef model."""

    def test_valid_job_def(self):
        job_def = JobDef(
            job_id="aip-1",
            version="2.0",
            description="AIP executor template",
            steps=[
                StepTemplate(
                    step_id="branch.create",
                    backend=Backend.cmd,
                    payload={"command": "git checkout -b feat/test"},
                ),
                StepTemplate(
                    step_id="agent.run_spec",
                    backend=Backend.claude_code,
                    payload={"spec_md": "@payload.spec_md"},
                ),
            ],
        )
        assert job_def.job_id == "aip-1"
        assert len(job_def.steps) == 2

    def test_job_def_requires_steps(self):
        with pytest.raises(ValidationError):
            JobDef(job_id="empty", steps=None)


class TestCommon:
    """Tests for Common model."""

    def test_valid_common(self):
        common = Common(
            repo_path=Path("/workspace/repo"),
            branch="main",
            base_commit="abc123",
            timeout_s=600,
            policy_profile="strict",
        )
        assert common.timeout_s == 600
        assert common.policy_profile == "strict"

    def test_common_defaults(self):
        common = Common(
            repo_path=Path("/workspace/repo"),
            branch="main",
            base_commit="abc123",
        )
        assert common.timeout_s == 300
        assert common.policy_profile == "default"


class TestStep:
    """Tests for Step model."""

    def test_valid_step(self):
        step = Step(
            step_n=1,
            step_id="branch.create",
            backend=Backend.cmd,
            common=Common(
                repo_path=Path("/workspace/repo"),
                branch="main",
                base_commit="abc123",
            ),
            payload={"command": "git checkout -b feat/test"},
        )
        assert step.step_n == 1

    def test_step_requires_positive_step_n(self):
        with pytest.raises(ValidationError):
            Step(
                step_n=0,
                step_id="test",
                backend=Backend.cmd,
                common=Common(
                    repo_path=Path("/workspace/repo"),
                    branch="main",
                    base_commit="abc123",
                ),
            )


class TestJobInstance:
    """Tests for JobInstance model."""

    def test_valid_job_instance(self):
        instance = JobInstance(
            job_id="aip-1",
            job_hash="sha256:abc123",
            steps=[
                Step(
                    step_n=1,
                    step_id="branch.create",
                    backend=Backend.cmd,
                    common=Common(
                        repo_path=Path("/workspace/repo"),
                        branch="main",
                        base_commit="abc123",
                    ),
                    payload={"command": "git checkout -b feat/test"},
                ),
            ],
        )
        assert instance.job_id == "aip-1"
        assert len(instance.steps) == 1

    def test_job_instance_yaml_roundtrip(self):
        instance = JobInstance(
            job_id="aip-1",
            job_hash="sha256:abc123",
            steps=[
                Step(
                    step_n=1,
                    step_id="test.step",
                    backend=Backend.cmd,
                    common=Common(
                        repo_path=Path("/workspace/repo"),
                        branch="main",
                        base_commit="abc123",
                    ),
                    payload={"key": "value"},
                ),
            ],
        )
        data = instance.model_dump(mode="json")
        yaml_str = yaml.dump(data)
        loaded = yaml.safe_load(yaml_str)
        restored = JobInstance.model_validate(loaded)
        assert restored.job_id == instance.job_id
        assert len(restored.steps) == 1


class TestStepManifest:
    """Tests for StepManifest model."""

    def test_valid_step_manifest(self):
        manifest = StepManifest(
            step_n=1,
            step_id="agent.run_spec",
            backend=Backend.claude_code,
            common=Common(
                repo_path=Path("/workspace/repo"),
                branch="main",
                base_commit="abc123",
            ),
            payload={"spec_md": "# Test Spec\n\nContent here"},
        )
        assert manifest.step_n == 1
        assert manifest.backend == Backend.claude_code


class TestStepOutcome:
    """Tests for StepOutcome model."""

    def test_valid_step_outcome(self):
        outcome = StepOutcome(
            step_n=1,
            step_id="test.step",
            outcome=OutcomeStatus.completed,
            duration_ms=5000,
            manifest_ref="steps/step-001/manifest.yaml",
            capture_ref="steps/step-001/capture.yaml",
        )
        assert outcome.outcome == OutcomeStatus.completed
        assert outcome.duration_ms == 5000
        assert outcome.error is None

    def test_step_outcome_with_error(self):
        outcome = StepOutcome(
            step_n=2,
            step_id="failing.step",
            outcome=OutcomeStatus.failed,
            duration_ms=1000,
            manifest_ref="steps/step-002/manifest.yaml",
            capture_ref="steps/step-002/capture.yaml",
            error="Command failed with exit code 1",
        )
        assert outcome.outcome == OutcomeStatus.failed
        assert outcome.error is not None

    def test_step_outcome_requires_non_negative_duration(self):
        with pytest.raises(ValidationError):
            StepOutcome(
                step_n=1,
                step_id="test",
                outcome=OutcomeStatus.completed,
                duration_ms=-1,
                manifest_ref="ref",
                capture_ref="ref",
            )


class TestGitCapture:
    """Tests for GitCapture model."""

    def test_valid_git_capture(self):
        capture = GitCapture(
            base_commit="abc123",
            pre_status="",
            post_status="M src/main.py",
            patch_file="steps/step-001/changes.patch",
            changed_files=[
                {"path": "src/main.py", "before": "abc", "after": "def"},
            ],
        )
        assert capture.base_commit == "abc123"
        assert len(capture.changed_files) == 1

    def test_git_capture_with_commit(self):
        capture = GitCapture(
            base_commit="abc123",
            pre_status="",
            post_status="",
            commit_sha="def456",
        )
        assert capture.commit_sha == "def456"


class TestAgentCapture:
    """Tests for AgentCapture model."""

    def test_valid_agent_capture(self):
        capture = AgentCapture(
            stdout_file="steps/step-001/stdout.txt",
            stderr_file="steps/step-001/stderr.txt",
            exit_code=0,
        )
        assert capture.exit_code == 0
        assert capture.transcript_file is None

    def test_agent_capture_with_transcript(self):
        capture = AgentCapture(
            stdout_file="steps/step-001/stdout.txt",
            stderr_file="steps/step-001/stderr.txt",
            exit_code=0,
            transcript_file="steps/step-001/transcript.jsonl",
        )
        assert capture.transcript_file is not None


class TestStepCapture:
    """Tests for StepCapture model."""

    def test_minimal_step_capture(self):
        capture = StepCapture(step_n=1, step_id="test.step")
        assert capture.git is None
        assert capture.agent is None
        assert capture.assessments == []
        assert capture.traces == []

    def test_full_step_capture(self):
        capture = StepCapture(
            step_n=1,
            step_id="agent.run_spec",
            git=GitCapture(
                base_commit="abc123",
                pre_status="",
                post_status="M src/main.py",
            ),
            agent=AgentCapture(
                stdout_file="steps/step-001/stdout.txt",
                stderr_file="steps/step-001/stderr.txt",
                exit_code=0,
            ),
            assessments=[{"criterion": "tests pass", "verdict": True}],
            traces=["steps/step-001/trace.jsonl"],
        )
        assert capture.git is not None
        assert capture.agent is not None
        assert len(capture.assessments) == 1
        assert len(capture.traces) == 1


class TestAttemptRecord:
    """Tests for AttemptRecord model."""

    def test_valid_attempt_record(self):
        attempt = AttemptRecord(
            attempt_n=1,
            started_at=datetime(2026, 1, 22, 10, 0, 0),
        )
        assert attempt.attempt_n == 1
        assert attempt.status == AttemptStatus.running
        assert attempt.ended_at is None
        assert attempt.step_outcomes == []

    def test_completed_attempt_record(self):
        attempt = AttemptRecord(
            attempt_n=1,
            started_at=datetime(2026, 1, 22, 10, 0, 0),
            ended_at=datetime(2026, 1, 22, 10, 5, 0),
            status=AttemptStatus.completed,
            step_outcomes=[
                StepOutcome(
                    step_n=1,
                    step_id="test",
                    outcome=OutcomeStatus.completed,
                    duration_ms=1000,
                    manifest_ref="steps/step-001/manifest.yaml",
                    capture_ref="steps/step-001/capture.yaml",
                ),
            ],
            final_step_n=1,
        )
        assert attempt.status == AttemptStatus.completed
        assert len(attempt.step_outcomes) == 1

    def test_attempt_yaml_roundtrip(self):
        attempt = AttemptRecord(
            attempt_n=1,
            started_at=datetime(2026, 1, 22, 10, 0, 0),
            ended_at=datetime(2026, 1, 22, 10, 5, 0),
            status=AttemptStatus.completed,
            step_outcomes=[],
            final_step_n=5,
        )
        data = attempt.model_dump(mode="json")
        yaml_str = yaml.dump(data)
        loaded = yaml.safe_load(yaml_str)
        restored = AttemptRecord.model_validate(loaded)
        assert restored.attempt_n == attempt.attempt_n
        assert restored.status == attempt.status
