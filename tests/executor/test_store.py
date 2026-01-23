"""
Unit tests for RunStore.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

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
from spec.executor.store import RunStore


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    """Create a RunStore with a temporary root directory."""
    return RunStore(root=tmp_path)


@pytest.fixture
def sample_common() -> Common:
    """Create a sample Common block."""
    return Common(
        repo_path=Path("/workspace/repo"),
        branch="main",
        base_commit="abc123def456",
        timeout_s=300,
        policy_profile="default",
    )


@pytest.fixture
def sample_run_record() -> RunRecord:
    """Create a sample RunRecord."""
    return RunRecord(
        run_id="run-20260122-001",
        job_id="aip-1",
        job_hash="sha256:abc123",
        repo=RepoScope(
            repo_path=Path("/workspace/repo"),
            branch="feat/test",
            base_commit="abc123",
        ),
        policy=Policy(),
        status=RunStatus.pending,
    )


@pytest.fixture
def sample_job_def() -> JobDef:
    """Create a sample JobDef."""
    return JobDef(
        job_id="aip-1",
        version="2.0",
        description="Test job definition",
        steps=[
            StepTemplate(
                step_id="branch.create",
                backend=Backend.cmd,
                payload={"command": "git checkout -b feat/test"},
            ),
            StepTemplate(
                step_id="agent.run_aip",
                backend=Backend.claude_code,
                payload={"aip": "@payload.aip"},
            ),
        ],
    )


@pytest.fixture
def sample_job_instance(sample_common: Common) -> JobInstance:
    """Create a sample JobInstance."""
    return JobInstance(
        job_id="aip-1",
        job_hash="sha256:abc123",
        steps=[
            Step(
                step_n=1,
                step_id="branch.create",
                backend=Backend.cmd,
                common=sample_common,
                payload={"command": "git checkout -b feat/test"},
            ),
            Step(
                step_n=2,
                step_id="agent.run_aip",
                backend=Backend.claude_code,
                common=sample_common,
                payload={"aip": {"title": "Test AIP"}},
            ),
        ],
    )


class TestRunStoreDirectoryStructure:
    """Tests for RunStore directory creation."""

    def test_create_run_creates_directory_structure(self, store: RunStore):
        run_id = "test-run-001"
        run_path = store.create_run(run_id)

        assert run_path.exists()
        assert (run_path / "attempts").is_dir()
        assert (run_path / "steps").is_dir()

    def test_get_run_path(self, store: RunStore, tmp_path: Path):
        assert store.get_run_path("run-001") == tmp_path / "run-001"

    def test_get_step_path(self, store: RunStore, tmp_path: Path):
        assert store.get_step_path("run-001", 1) == tmp_path / "run-001/steps/step-001"
        assert store.get_step_path("run-001", 42) == tmp_path / "run-001/steps/step-042"

    def test_get_attempt_path(self, store: RunStore, tmp_path: Path):
        assert store.get_attempt_path("run-001", 1) == tmp_path / "run-001/attempts/attempt-001.yaml"


class TestRunRecordPersistence:
    """Tests for RunRecord read/write."""

    def test_write_and_read_run_record(self, store: RunStore, sample_run_record: RunRecord):
        run_id = sample_run_record.run_id
        store.create_run(run_id)
        store.write_run_record(run_id, sample_run_record)

        loaded = store.read_run_record(run_id)
        assert loaded.run_id == sample_run_record.run_id
        assert loaded.job_id == sample_run_record.job_id
        assert loaded.status == sample_run_record.status
        assert loaded.repo.branch == sample_run_record.repo.branch


class TestJobDefPersistence:
    """Tests for JobDef read/write."""

    def test_write_and_read_job_def(self, store: RunStore, sample_job_def: JobDef):
        run_id = "test-run"
        store.create_run(run_id)
        store.write_job_def(run_id, sample_job_def)

        loaded = store.read_job_def(run_id)
        assert loaded.job_id == sample_job_def.job_id
        assert len(loaded.steps) == 2
        assert loaded.steps[0].step_id == "branch.create"


class TestJobInstancePersistence:
    """Tests for JobInstance read/write."""

    def test_write_and_read_job_instance(self, store: RunStore, sample_job_instance: JobInstance):
        run_id = "test-run"
        store.create_run(run_id)
        store.write_job_instance(run_id, sample_job_instance)

        loaded = store.read_job_instance(run_id)
        assert loaded.job_id == sample_job_instance.job_id
        assert len(loaded.steps) == 2
        assert loaded.steps[0].step_n == 1


class TestStepManifestPersistence:
    """Tests for StepManifest read/write."""

    def test_write_and_read_step_manifest(self, store: RunStore, sample_common: Common):
        run_id = "test-run"
        store.create_run(run_id)

        manifest = StepManifest(
            step_n=1,
            step_id="agent.run_aip",
            backend=Backend.claude_code,
            common=sample_common,
            payload={"aip": {"title": "Test"}},
        )
        store.write_step_manifest(run_id, 1, manifest)

        loaded = store.read_step_manifest(run_id, 1)
        assert loaded.step_id == manifest.step_id
        assert loaded.backend == Backend.claude_code


class TestStepOutcomePersistence:
    """Tests for StepOutcome read/write."""

    def test_write_and_read_step_outcome(self, store: RunStore):
        run_id = "test-run"
        store.create_run(run_id)

        outcome = StepOutcome(
            step_n=1,
            step_id="test.step",
            outcome=OutcomeStatus.completed,
            duration_ms=5000,
            manifest_ref="steps/step-001/manifest.yaml",
            capture_ref="steps/step-001/capture.yaml",
        )
        store.write_step_outcome(run_id, 1, outcome)

        loaded = store.read_step_outcome(run_id, 1)
        assert loaded.step_id == outcome.step_id
        assert loaded.outcome == OutcomeStatus.completed
        assert loaded.duration_ms == 5000


class TestStepCapturePersistence:
    """Tests for StepCapture read/write."""

    def test_write_and_read_step_capture(self, store: RunStore):
        run_id = "test-run"
        store.create_run(run_id)

        capture = StepCapture(
            step_n=1,
            step_id="agent.run_aip",
            git=GitCapture(
                base_commit="abc123",
                pre_status="",
                post_status="M src/main.py",
                patch_file="steps/step-001/changes.patch",
                changed_files=[{"path": "src/main.py", "before": "abc", "after": "def"}],
            ),
            agent=AgentCapture(
                stdout_file="steps/step-001/stdout.txt",
                stderr_file="steps/step-001/stderr.txt",
                exit_code=0,
            ),
        )
        store.write_step_capture(run_id, 1, capture)

        loaded = store.read_step_capture(run_id, 1)
        assert loaded.step_id == capture.step_id
        assert loaded.git is not None
        assert loaded.git.base_commit == "abc123"
        assert loaded.agent is not None
        assert loaded.agent.exit_code == 0


class TestAttemptPersistence:
    """Tests for AttemptRecord read/write."""

    def test_write_and_read_attempt(self, store: RunStore):
        run_id = "test-run"
        store.create_run(run_id)

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
        store.write_attempt(run_id, attempt)

        loaded = store.read_attempt(run_id, 1)
        assert loaded.attempt_n == 1
        assert loaded.status == AttemptStatus.completed
        assert len(loaded.step_outcomes) == 1


class TestRunStoreListing:
    """Tests for RunStore listing methods."""

    def test_list_runs_empty(self, store: RunStore):
        assert store.list_runs() == []

    def test_list_runs(self, store: RunStore, sample_run_record: RunRecord):
        # Create multiple runs
        for i in range(3):
            run_id = f"run-{i:03d}"
            store.create_run(run_id)
            record = RunRecord(
                run_id=run_id,
                job_id="aip-1",
                job_hash=f"hash-{i}",
                repo=RepoScope(
                    repo_path=Path("/workspace/repo"),
                    branch="main",
                    base_commit="abc",
                ),
            )
            store.write_run_record(run_id, record)

        runs = store.list_runs()
        assert len(runs) == 3
        assert "run-000" in runs
        assert "run-001" in runs
        assert "run-002" in runs

    def test_list_attempts(self, store: RunStore):
        run_id = "test-run"
        store.create_run(run_id)

        for i in range(1, 4):
            attempt = AttemptRecord(
                attempt_n=i,
                started_at=datetime.now(UTC),
            )
            store.write_attempt(run_id, attempt)

        attempts = store.list_attempts(run_id)
        assert attempts == [1, 2, 3]

    def test_list_steps(self, store: RunStore, sample_common: Common):
        run_id = "test-run"
        store.create_run(run_id)

        for step_n in [1, 2, 5]:
            manifest = StepManifest(
                step_n=step_n,
                step_id=f"step-{step_n}",
                backend=Backend.cmd,
                common=sample_common,
                payload={},
            )
            store.write_step_manifest(run_id, step_n, manifest)

        steps = store.list_steps(run_id)
        assert steps == [1, 2, 5]

    def test_run_exists(self, store: RunStore, sample_run_record: RunRecord):
        run_id = sample_run_record.run_id
        assert not store.run_exists(run_id)

        store.create_run(run_id)
        assert not store.run_exists(run_id)  # No run.yaml yet

        store.write_run_record(run_id, sample_run_record)
        assert store.run_exists(run_id)


class TestCompleteWorkflow:
    """Integration test for a complete run workflow."""

    def test_complete_run_workflow(self, store: RunStore, sample_common: Common):
        run_id = "complete-workflow-test"

        # 1. Create run
        store.create_run(run_id)

        # 2. Write run record
        run_record = RunRecord(
            run_id=run_id,
            job_id="aip-1",
            job_hash="sha256:workflow-hash",
            repo=RepoScope(
                repo_path=Path("/workspace/repo"),
                branch="feat/test",
                base_commit="base123",
            ),
            status=RunStatus.running,
        )
        store.write_run_record(run_id, run_record)

        # 3. Write job def
        job_def = JobDef(
            job_id="aip-1",
            steps=[
                StepTemplate(step_id="step.one", backend=Backend.cmd, payload={}),
                StepTemplate(step_id="step.two", backend=Backend.llm, payload={}),
            ],
        )
        store.write_job_def(run_id, job_def)

        # 4. Write job instance
        job_instance = JobInstance(
            job_id="aip-1",
            job_hash="sha256:workflow-hash",
            steps=[
                Step(step_n=1, step_id="step.one", backend=Backend.cmd, common=sample_common, payload={}),
                Step(step_n=2, step_id="step.two", backend=Backend.llm, common=sample_common, payload={}),
            ],
        )
        store.write_job_instance(run_id, job_instance)

        # 5. Write step artifacts for step 1
        manifest1 = StepManifest(
            step_n=1, step_id="step.one", backend=Backend.cmd, common=sample_common, payload={}
        )
        store.write_step_manifest(run_id, 1, manifest1)

        capture1 = StepCapture(
            step_n=1,
            step_id="step.one",
            git=GitCapture(base_commit="base123", pre_status="", post_status=""),
        )
        store.write_step_capture(run_id, 1, capture1)

        outcome1 = StepOutcome(
            step_n=1,
            step_id="step.one",
            outcome=OutcomeStatus.completed,
            duration_ms=100,
            manifest_ref="steps/step-001/manifest.yaml",
            capture_ref="steps/step-001/capture.yaml",
        )
        store.write_step_outcome(run_id, 1, outcome1)

        # 6. Write attempt record
        attempt = AttemptRecord(
            attempt_n=1,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            status=AttemptStatus.completed,
            step_outcomes=[outcome1],
            final_step_n=1,
        )
        store.write_attempt(run_id, attempt)

        # 7. Verify everything can be read back
        assert store.run_exists(run_id)
        assert store.list_runs() == [run_id]
        assert store.list_attempts(run_id) == [1]
        assert store.list_steps(run_id) == [1]

        loaded_record = store.read_run_record(run_id)
        assert loaded_record.status == RunStatus.running

        loaded_instance = store.read_job_instance(run_id)
        assert len(loaded_instance.steps) == 2

        loaded_attempt = store.read_attempt(run_id, 1)
        assert loaded_attempt.status == AttemptStatus.completed
