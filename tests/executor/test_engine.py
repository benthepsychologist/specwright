"""
Tests for the executor engine.
"""

import subprocess

import pytest

from spec.executor.engine import (
    CompileError,
    ExecutorError,
    VariableError,
    _evaluate_condition,
    compile_job,
    execute,
    generate_run_id,
    has_unresolved_run_refs,
    resolve_variables,
)
from spec.executor.engine import _generate_run_report
from spec.executor.jobdefs import (
    JobDefNotFoundError,
    list_job_defs,
    load_job_def,
)
from spec.executor.schemas import (
    Backend,
    JobDef,
    JobInstance,
    OutcomeStatus,
    RunStatus,
    StepTemplate,
)
from spec.executor.schemas.attempt import AttemptRecord, AttemptStatus
from spec.executor.schemas.capture import AgentCapture, StepCapture
from spec.executor.schemas.outcome import StepOutcome
from spec.executor.schemas.run import Policy, RepoScope, RunRecord
from spec.executor.store import RunStore

# =============================================================================
# Variable Resolution Tests
# =============================================================================


class TestVariableResolution:
    """Tests for variable resolution."""

    def test_resolve_simple_ctx_ref(self):
        """Resolve @ctx.key reference."""
        ctx = {"name": "test"}
        result = resolve_variables("@ctx.name", ctx, {})
        assert result == "test"

    def test_resolve_simple_payload_ref(self):
        """Resolve @payload.key reference."""
        payload = {"value": 42}
        result = resolve_variables("@payload.value", {}, payload)
        assert result == 42

    def test_resolve_nested_ref(self):
        """Resolve @ctx.nested.key reference."""
        ctx = {"nested": {"key": "deep"}}
        result = resolve_variables("@ctx.nested.key", ctx, {})
        assert result == "deep"

    def test_resolve_string_interpolation(self):
        """Resolve references embedded in a string."""
        ctx = {"name": "test"}
        payload = {"version": "1.0"}
        result = resolve_variables("Project @ctx.name version @payload.version", ctx, payload)
        assert result == "Project test version 1.0"

    def test_resolve_dict(self):
        """Resolve references in a dict."""
        ctx = {"name": "test"}
        data = {"project": "@ctx.name", "static": "value"}
        result = resolve_variables(data, ctx, {})
        assert result == {"project": "test", "static": "value"}

    def test_resolve_list(self):
        """Resolve references in a list."""
        ctx = {"item": "resolved"}
        data = ["@ctx.item", "static", "@ctx.item"]
        result = resolve_variables(data, ctx, {})
        assert result == ["resolved", "static", "resolved"]

    def test_resolve_run_ref(self):
        """Resolve @run.* reference during execution."""
        run = {"run_id": "run-123", "repo_path": "/workspace"}
        result = resolve_variables("@run.run_id", {}, {}, run=run)
        assert result == "run-123"

    def test_resolve_run_ref_not_allowed(self):
        """@run.* raises error when not allowed."""
        run = {"run_id": "run-123"}
        with pytest.raises(VariableError) as exc_info:
            resolve_variables("@run.run_id", {}, {}, run=run, allow_run=False)
        assert "@run.*" in str(exc_info.value)

    def test_resolve_run_ref_unavailable(self):
        """@run.* raises error when run context not available."""
        with pytest.raises(VariableError) as exc_info:
            resolve_variables("@run.run_id", {}, {}, run=None, allow_run=True)
        assert "not available" in str(exc_info.value)

    def test_unresolved_variable_raises(self):
        """Unresolved variable raises VariableError."""
        with pytest.raises(VariableError) as exc_info:
            resolve_variables("@ctx.nonexistent", {}, {})
        assert "Unresolved" in str(exc_info.value)

    def test_preserve_primitives(self):
        """Non-string primitives are preserved."""
        assert resolve_variables(42, {}, {}) == 42
        assert resolve_variables(3.14, {}, {}) == 3.14
        assert resolve_variables(True, {}, {}) is True
        assert resolve_variables(None, {}, {}) is None

    def test_bracket_notation(self):
        """Resolve @ctx['key'] bracket notation."""
        ctx = {"my-key": "value"}
        result = resolve_variables("@ctx['my-key']", ctx, {})
        assert result == "value"

    def test_passthrough_spec_md(self):
        """spec_md key is not resolved (contains user content with @-refs)."""
        ctx = {"name": "test"}
        data = {
            "spec_md": "# Spec\n@run.read.items should NOT be resolved",
            "other_key": "@ctx.name",
        }
        result = resolve_variables(data, ctx, {})
        # spec_md should be passed through unchanged
        assert result["spec_md"] == "# Spec\n@run.read.items should NOT be resolved"
        # other_key should be resolved
        assert result["other_key"] == "test"

    def test_passthrough_epic_spec(self):
        """epic_spec key is not resolved."""
        data = {
            "epic_spec": {"pipeline": "@run.read.items"},
            "normal": "@ctx.val",
        }
        ctx = {"val": "resolved"}
        result = resolve_variables(data, ctx, {})
        assert result["epic_spec"] == {"pipeline": "@run.read.items"}
        assert result["normal"] == "resolved"

    def test_passthrough_prompt(self):
        """prompt key is not resolved."""
        data = {
            "prompt": "Execute @run.pipeline with items",
            "repo_path": "@ctx.path",
        }
        ctx = {"path": "/workspace"}
        result = resolve_variables(data, ctx, {})
        assert result["prompt"] == "Execute @run.pipeline with items"
        assert result["repo_path"] == "/workspace"


class TestHasUnresolvedRunRefs:
    """Tests for has_unresolved_run_refs."""

    def test_no_refs(self):
        """String without @run.* returns False."""
        assert not has_unresolved_run_refs("plain string")

    def test_has_run_ref(self):
        """String with @run.* returns True."""
        assert has_unresolved_run_refs("@run.run_id")

    def test_has_run_ref_in_dict(self):
        """Dict with @run.* in value returns True."""
        assert has_unresolved_run_refs({"key": "@run.path"})

    def test_has_run_ref_in_list(self):
        """List with @run.* in element returns True."""
        assert has_unresolved_run_refs(["@run.id", "static"])

    def test_nested_run_ref(self):
        """Nested @run.* returns True."""
        assert has_unresolved_run_refs({"outer": {"inner": "@run.value"}})


# =============================================================================
# Condition Evaluation Tests
# =============================================================================


class TestConditionEvaluation:
    """Tests for condition evaluation."""

    def test_equals_true(self):
        """Condition with == that evaluates to true."""
        ctx = {"tier": "A"}
        assert _evaluate_condition("@ctx.tier == 'A'", ctx, {}) is True

    def test_equals_false(self):
        """Condition with == that evaluates to false."""
        ctx = {"tier": "B"}
        assert _evaluate_condition("@ctx.tier == 'A'", ctx, {}) is False

    def test_not_equals_true(self):
        """Condition with != that evaluates to true."""
        ctx = {"tier": "B"}
        assert _evaluate_condition("@ctx.tier != 'A'", ctx, {}) is True

    def test_not_equals_false(self):
        """Condition with != that evaluates to false."""
        ctx = {"tier": "A"}
        assert _evaluate_condition("@ctx.tier != 'A'", ctx, {}) is False

    def test_truthy_check_true(self):
        """Truthy check on true value."""
        ctx = {"enabled": True}
        assert _evaluate_condition("@ctx.enabled", ctx, {}) is True

    def test_truthy_check_false(self):
        """Truthy check on false value."""
        ctx = {"enabled": False}
        assert _evaluate_condition("@ctx.enabled", ctx, {}) is False

    def test_missing_key_false(self):
        """Missing key evaluates to false."""
        assert _evaluate_condition("@ctx.nonexistent", {}, {}) is False


# =============================================================================
# Compilation Tests
# =============================================================================


class TestCompileJob:
    """Tests for job compilation."""

    @pytest.fixture
    def simple_job_def(self):
        """Create a simple JobDef for testing."""
        return JobDef(
            job_id="test-job",
            steps=[
                StepTemplate(
                    step_id="step1",
                    backend=Backend.cmd,
                    payload={"command": "echo @payload.message"},
                ),
                StepTemplate(
                    step_id="step2",
                    backend=Backend.cmd,
                    payload={"command": "echo done"},
                ),
            ],
        )

    @pytest.fixture
    def conditional_job_def(self):
        """Create a JobDef with conditional steps."""
        return JobDef(
            job_id="conditional-job",
            steps=[
                StepTemplate(
                    step_id="always",
                    backend=Backend.cmd,
                    payload={"command": "echo always"},
                ),
                StepTemplate(
                    step_id="only-tier-a",
                    backend=Backend.cmd,
                    condition="@ctx.tier == 'A'",
                    payload={"command": "echo tier A"},
                ),
                StepTemplate(
                    step_id="only-tier-b",
                    backend=Backend.cmd,
                    condition="@ctx.tier == 'B'",
                    payload={"command": "echo tier B"},
                ),
            ],
        )

    def test_compile_simple_job(self, simple_job_def):
        """Compile a simple job."""
        envelope = {
            "payload": {
                "message": "hello",
                "repo_path": "/workspace/test",
                "feature_branch": "feat/test",
            }
        }
        result = compile_job(simple_job_def, envelope)

        assert isinstance(result, JobInstance)
        assert result.job_id == "test-job"
        assert len(result.steps) == 2
        assert result.steps[0].step_n == 1
        assert result.steps[0].step_id == "step1"
        assert result.steps[0].payload["command"] == "echo hello"


def test_generate_run_report_reads_llm_stdout(tmp_path, monkeypatch):
    """Run report generation reads LlmBackend response from StepCapture.agent stdout.

    Regression test for: AttributeError: 'StepCapture' object has no attribute 'llm'.
    """

    # Create a minimal run directory via RunStore
    store = RunStore(root=tmp_path / "runs")
    run_id = "run-test-report"
    run_dir = store.create_run(run_id)

    # Minimal RunRecord / AttemptRecord
    run_record = RunRecord(
        run_id=run_id,
        job_id="interactive-1",
        job_hash="sha256:deadbeefdeadbeef",
        repo=RepoScope(repo_path=tmp_path / "repo", branch="feat/x", base_commit="HEAD"),
        policy=Policy(),
        status=RunStatus.completed,
    )

    from datetime import datetime

    attempt = AttemptRecord(
        attempt_n=1,
        started_at=datetime(2025, 1, 1),
        ended_at=datetime(2025, 1, 1),
        status=AttemptStatus.completed,
        step_outcomes=[
            StepOutcome(
                step_n=1,
                step_id="dummy",
                outcome=OutcomeStatus.completed,
                duration_ms=1,
                manifest_ref="steps/step-001/manifest.yaml",
                capture_ref="steps/step-001/capture.yaml",
            )
        ],
    )

    # Monkeypatch LlmBackend to avoid real provider calls
    import spec.executor.backends.llm as llm_mod

    class DummyLlmBackend:
        def dispatch(self, manifest, artifacts_dir, policy, capture_patch=False):  # noqa: ARG002
            (artifacts_dir / "stdout.txt").write_text("REPORT BODY\n")
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

    monkeypatch.setattr(llm_mod, "LlmBackend", DummyLlmBackend)

    _generate_run_report(run_record, attempt, store, run_dir, use_llm=True)

    report_path = run_dir / "run_report.md"
    assert report_path.exists()
    assert "REPORT BODY" in report_path.read_text()

    def test_compile_resolves_payload_refs(self, simple_job_def):
        """Compile resolves @payload.* references."""
        envelope = {
            "payload": {
                "message": "world",
                "repo_path": "/workspace/test",
            }
        }
        result = compile_job(simple_job_def, envelope)

        assert result.steps[0].payload["command"] == "echo world"

    def test_compile_condition_includes_step(self, conditional_job_def):
        """Compile includes step when condition is true."""
        envelope = {
            "ctx": {"tier": "A"},
            "payload": {"repo_path": "/workspace/test"},
        }
        result = compile_job(conditional_job_def, envelope)

        step_ids = [s.step_id for s in result.steps]
        assert "always" in step_ids
        assert "only-tier-a" in step_ids
        assert "only-tier-b" not in step_ids

    def test_compile_condition_excludes_step(self, conditional_job_def):
        """Compile excludes step when condition is false."""
        envelope = {
            "ctx": {"tier": "B"},
            "payload": {"repo_path": "/workspace/test"},
        }
        result = compile_job(conditional_job_def, envelope)

        step_ids = [s.step_id for s in result.steps]
        assert "always" in step_ids
        assert "only-tier-a" not in step_ids
        assert "only-tier-b" in step_ids

    def test_compile_forbids_run_refs_in_condition(self):
        """Compile raises error for @run.* in condition."""
        job_def = JobDef(
            job_id="bad-job",
            steps=[
                StepTemplate(
                    step_id="bad-step",
                    backend=Backend.cmd,
                    condition="@run.status == 'ok'",
                    payload={"command": "echo bad"},
                ),
            ],
        )
        envelope = {"payload": {"repo_path": "/workspace"}}

        with pytest.raises(CompileError) as exc_info:
            compile_job(job_def, envelope)
        assert "@run.*" in str(exc_info.value)

    def test_compile_no_steps_raises(self):
        """Compile raises if all steps are excluded."""
        job_def = JobDef(
            job_id="empty-job",
            steps=[
                StepTemplate(
                    step_id="never",
                    backend=Backend.cmd,
                    condition="@ctx.impossible == 'true'",
                    payload={"command": "echo never"},
                ),
            ],
        )
        envelope = {"ctx": {}, "payload": {"repo_path": "/workspace"}}

        with pytest.raises(CompileError) as exc_info:
            compile_job(job_def, envelope)
        assert "No steps" in str(exc_info.value)

    def test_compile_step_numbering(self, conditional_job_def):
        """Compile assigns correct step numbers after filtering."""
        envelope = {
            "ctx": {"tier": "A"},
            "payload": {"repo_path": "/workspace/test"},
        }
        result = compile_job(conditional_job_def, envelope)

        # Should have 2 steps (always + only-tier-a)
        assert len(result.steps) == 2
        assert result.steps[0].step_n == 1
        assert result.steps[1].step_n == 2

    def test_compile_generates_job_hash(self, simple_job_def):
        """Compile generates a job_hash."""
        envelope = {"payload": {"message": "test", "repo_path": "/workspace"}}
        result = compile_job(simple_job_def, envelope)

        assert result.job_hash.startswith("sha256:")
        assert len(result.job_hash) > 10

    def test_compile_hash_deterministic(self, simple_job_def):
        """Same input produces same hash."""
        envelope = {"payload": {"message": "test", "repo_path": "/workspace"}}

        result1 = compile_job(simple_job_def, envelope)
        result2 = compile_job(simple_job_def, envelope)

        assert result1.job_hash == result2.job_hash

    def test_compile_propagates_interactive_flag(self):
        """Interactive flag is propagated from StepTemplate to Step."""
        job_def = JobDef(
            job_id="interactive-compile-test",
            steps=[
                StepTemplate(
                    step_id="headless",
                    backend=Backend.cmd,
                    payload={"command": "echo headless"},
                ),
                StepTemplate(
                    step_id="interactive",
                    backend=Backend.cmd,
                    payload={"command": "echo interactive"},
                    interactive=True,
                ),
            ],
        )
        envelope = {"payload": {"repo_path": "/workspace"}}
        result = compile_job(job_def, envelope)

        assert result.steps[0].interactive is False
        assert result.steps[1].interactive is True


# =============================================================================
# JobDef Registry Tests
# =============================================================================


class TestJobDefLoader:
    """Tests for JobDef loading from YAML files."""

    @pytest.fixture
    def jobdefs_dir(self, tmp_path):
        """Set up test jobdefs directory with default jobdefs."""
        from spec.executor.jobdefs import install_default_jobdefs

        gov_path = tmp_path / "local-governor"
        install_default_jobdefs(gov_path)
        return gov_path

    def test_aip1_available(self, jobdefs_dir):
        """aip-1 can be loaded from jobdefs directory."""
        assert "aip-1" in list_job_defs(jobdefs_dir)

    def test_load_aip1(self, jobdefs_dir):
        """Can load aip-1 JobDef."""
        job_def = load_job_def("aip-1", jobdefs_dir)
        assert job_def.job_id == "aip-1"
        assert len(job_def.steps) == 10  # 3-pass model with commits

    def test_aip1_step_ids(self, jobdefs_dir):
        """aip-1 has correct step IDs for 3-pass model."""
        job_def = load_job_def("aip-1", jobdefs_dir)
        step_ids = [s.step_id for s in job_def.steps]
        assert step_ids == [
            "branch.create",
            "agent.run_spec",
            "commit.run1",
            "agent.drift_fix",
            "commit.run2",
            "agent.drift_verify",
            "commit.run3",
            "capture.bundle",
            "assess.acceptance",
            "finalize.run",
        ]

    def test_aip1_on_failure_skip_to(self, jobdefs_dir):
        """agent.run_spec has on_failure_skip_to set to capture.bundle."""
        job_def = load_job_def("aip-1", jobdefs_dir)
        run_aip = next(s for s in job_def.steps if s.step_id == "agent.run_spec")
        assert run_aip.on_failure_skip_to == "capture.bundle"

    def test_load_unknown_raises(self, jobdefs_dir):
        """Loading unknown job_id raises JobDefNotFoundError."""
        with pytest.raises(JobDefNotFoundError) as exc_info:
            load_job_def("nonexistent", jobdefs_dir)
        assert "nonexistent" in str(exc_info.value)

    def test_interactive1_available(self, jobdefs_dir):
        """interactive-1 can be loaded from jobdefs directory."""
        assert "interactive-1" in list_job_defs(jobdefs_dir)

    def test_load_interactive1(self, jobdefs_dir):
        """Can load interactive-1 JobDef."""
        job_def = load_job_def("interactive-1", jobdefs_dir)
        assert job_def.job_id == "interactive-1"
        assert len(job_def.steps) == 5

    def test_interactive1_step_ids(self, jobdefs_dir):
        """interactive-1 has correct step IDs."""
        job_def = load_job_def("interactive-1", jobdefs_dir)
        step_ids = [s.step_id for s in job_def.steps]
        assert step_ids == [
            "branch.create",
            "agent.interactive",
            "commit.interactive",
            "capture.bundle",
            "finalize.run",
        ]

    def test_interactive1_agent_step_is_interactive(self, jobdefs_dir):
        """agent.interactive step has interactive=True."""
        job_def = load_job_def("interactive-1", jobdefs_dir)
        agent_step = next(s for s in job_def.steps if s.step_id == "agent.interactive")
        assert agent_step.interactive is True

    def test_interactive1_agent_payload_has_interactive(self, jobdefs_dir):
        """agent.interactive payload includes interactive=True."""
        job_def = load_job_def("interactive-1", jobdefs_dir)
        agent_step = next(s for s in job_def.steps if s.step_id == "agent.interactive")
        assert agent_step.payload.get("interactive") is True

    def test_interactive1_non_agent_steps_not_interactive(self, jobdefs_dir):
        """Non-agent steps in interactive-1 are not interactive."""
        job_def = load_job_def("interactive-1", jobdefs_dir)
        for step in job_def.steps:
            if step.step_id != "agent.interactive":
                assert step.interactive is False

    def test_aip1_steps_not_interactive(self, jobdefs_dir):
        """All aip-1 steps have interactive=False (default)."""
        job_def = load_job_def("aip-1", jobdefs_dir)
        for step in job_def.steps:
            assert step.interactive is False


# =============================================================================
# Run ID Generation Tests
# =============================================================================


class TestRunIdGeneration:
    """Tests for run ID generation."""

    def test_generate_run_id_format(self):
        """Run ID has correct format."""
        run_id = generate_run_id()
        assert run_id.startswith("run-")
        # Format: run-YYYYMMDD-HHMMSS-XXXXXX
        parts = run_id.split("-")
        assert len(parts) == 4

    def test_generate_run_id_unique(self):
        """Generated run IDs are unique."""
        ids = [generate_run_id() for _ in range(10)]
        assert len(set(ids)) == 10


# =============================================================================
# Execute Integration Tests
# =============================================================================


class TestExecute:
    """Integration tests for execute()."""

    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a test git repository."""
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

        return repo_path

    @pytest.fixture
    def store(self, tmp_path):
        """Create a test store."""
        return RunStore(root=tmp_path / "runs")

    @pytest.fixture
    def simple_job(self):
        """Create a simple test job."""
        return JobDef(
            job_id="simple-test",
            steps=[
                StepTemplate(
                    step_id="echo",
                    backend=Backend.cmd,
                    payload={"command": "echo hello", "capture_git": False},
                ),
            ],
        )

    def test_execute_creates_run_directory(self, git_repo, store, simple_job):
        """Execute creates run directory structure."""
        envelope = {
            "job_def": simple_job.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        run_path = store.get_run_path(result.run_id)
        assert run_path.exists()
        assert (run_path / "run.yaml").exists()
        assert (run_path / "job_def.yaml").exists()
        assert (run_path / "job_instance.yaml").exists()
        assert (run_path / "attempts").exists()
        assert (run_path / "steps").exists()

    def test_execute_writes_run_record(self, git_repo, store, simple_job):
        """Execute writes RunRecord to run.yaml."""
        envelope = {
            "job_def": simple_job.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        run_record = store.read_run_record(result.run_id)
        assert run_record.job_id == "simple-test"
        assert run_record.status in [RunStatus.completed, RunStatus.failed]

    def test_execute_writes_step_artifacts(self, git_repo, store, simple_job):
        """Execute writes step manifest, outcome, capture."""
        envelope = {
            "job_def": simple_job.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        step_path = store.get_step_path(result.run_id, 1)
        assert (step_path / "manifest.yaml").exists()
        assert (step_path / "outcome.yaml").exists()
        assert (step_path / "capture.yaml").exists()

    def test_execute_writes_attempt(self, git_repo, store, simple_job):
        """Execute writes AttemptRecord."""
        envelope = {
            "job_def": simple_job.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        attempt = store.read_attempt(result.run_id, 1)
        assert attempt.attempt_n == 1
        assert attempt.ended_at is not None
        assert len(attempt.step_outcomes) == 1

    def test_execute_success_status(self, git_repo, store, simple_job):
        """Successful execution returns completed status."""
        envelope = {
            "job_def": simple_job.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        assert result.status == RunStatus.completed

    def test_execute_failed_step_status(self, git_repo, store):
        """Failed step returns failed status."""
        # Register a failing job
        job_def = JobDef(
            job_id="failing-test",
            steps=[
                StepTemplate(
                    step_id="fail",
                    backend=Backend.cmd,
                    payload={"command": "exit 1", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        assert result.status == RunStatus.failed

    def test_execute_missing_job_def(self, store):
        """Missing job_def raises ExecutorError."""
        envelope = {"payload": {"repo_path": "/workspace"}}

        with pytest.raises(ExecutorError) as exc_info:
            execute(envelope, store=store)
        assert "job_def" in str(exc_info.value)

    def test_execute_custom_run_id(self, git_repo, store, simple_job):
        """Can specify custom run_id."""
        envelope = {
            "job_def": simple_job.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store, run_id="custom-run-123")

        assert result.run_id == "custom-run-123"

    def test_execute_preserves_envelope(self, git_repo, store, simple_job):
        """Execute preserves envelope in RunRecord."""
        envelope = {
            "job_def": simple_job.model_dump(),
            "ctx": {"custom": "value"},
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        assert result.envelope["ctx"]["custom"] == "value"

    def test_execute_multi_step(self, git_repo, store):
        """Execute runs multiple steps in order."""
        job_def = JobDef(
            job_id="multi-step-test",
            steps=[
                StepTemplate(
                    step_id="step1",
                    backend=Backend.cmd,
                    payload={"command": "echo step1", "capture_git": False},
                ),
                StepTemplate(
                    step_id="step2",
                    backend=Backend.cmd,
                    payload={"command": "echo step2", "capture_git": False},
                ),
                StepTemplate(
                    step_id="step3",
                    backend=Backend.cmd,
                    payload={"command": "echo step3", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        assert result.status == RunStatus.completed

        # Check all steps executed
        for step_n in [1, 2, 3]:
            outcome = store.read_step_outcome(result.run_id, step_n)
            assert outcome.outcome == OutcomeStatus.completed

    def test_execute_aborts_on_failure(self, git_repo, store):
        """Execute aborts after first failure."""
        job_def = JobDef(
            job_id="abort-test",
            steps=[
                StepTemplate(
                    step_id="success",
                    backend=Backend.cmd,
                    payload={"command": "echo ok", "capture_git": False},
                ),
                StepTemplate(
                    step_id="fail",
                    backend=Backend.cmd,
                    payload={"command": "exit 1", "capture_git": False},
                ),
                StepTemplate(
                    step_id="never",
                    backend=Backend.cmd,
                    payload={"command": "echo never", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        assert result.status == RunStatus.failed

        # Check step 3 was never executed
        step3_path = store.get_step_path(result.run_id, 3) / "outcome.yaml"
        assert not step3_path.exists()

    def test_execute_llm_network_preflight_hard_fails_before_steps(self, git_repo, store, monkeypatch):
        """For LLM jobs, network preflight aborts the run before step 1."""
        monkeypatch.delenv("SPECWRIGHT_LLM_NETWORK_PREFLIGHT", raising=False)

        import spec.executor.backends.llm as llm_mod

        def boom(self):  # noqa: ARG001
            raise Exception("no network")

        monkeypatch.setattr(llm_mod.LlmBackend, "verify", boom)

        llm_job = JobDef(
            job_id="preflight-llm",
            steps=[
                StepTemplate(
                    step_id="llm",
                    backend=Backend.llm,
                    payload={"prompt": "hello", "capture_git": False},
                )
            ],
        )

        envelope = {
            "job_def": llm_job.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store, run_id="preflight-fail")
        assert result.status == RunStatus.failed

        # No step artifacts should exist because we abort before dispatch loop.
        step1 = store.get_step_path(result.run_id, 1)
        assert not (step1 / "manifest.yaml").exists()
        assert not (step1 / "outcome.yaml").exists()
        assert not (step1 / "capture.yaml").exists()


class TestExecuteVariableResolution:
    """Tests for variable resolution during execution."""

    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a test git repository."""
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

        return repo_path

    @pytest.fixture
    def store(self, tmp_path):
        """Create a test store."""
        return RunStore(root=tmp_path / "runs")

    def test_run_refs_resolved_at_dispatch(self, git_repo, store):
        """@run.* refs are resolved at step dispatch time."""
        job_def = JobDef(
            job_id="run-ref-test",
            steps=[
                StepTemplate(
                    step_id="use-run-id",
                    backend=Backend.cmd,
                    # This would fail at compile time if @run.* wasn't allowed in payload
                    payload={"command": "echo @run.run_id", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store, run_id="test-run-abc")

        # The run_id should be resolved in the manifest
        manifest = store.read_step_manifest(result.run_id, 1)
        assert manifest.payload["command"] == "echo test-run-abc"


# =============================================================================
# Continue on Failure Tests
# =============================================================================


class TestContinueOnFailure:
    """Tests for continue_on_failure behavior."""

    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a test git repository."""
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

        return repo_path

    @pytest.fixture
    def store(self, tmp_path):
        """Create a test store."""
        return RunStore(root=tmp_path / "runs")

    def test_continue_on_failure_runs_subsequent_steps(self, git_repo, store):
        """When continue_on_failure=True, subsequent steps still run."""
        job_def = JobDef(
            job_id="continue-test",
            steps=[
                StepTemplate(
                    step_id="step1",
                    backend=Backend.cmd,
                    payload={"command": "echo step1", "capture_git": False},
                ),
                StepTemplate(
                    step_id="step2",
                    backend=Backend.cmd,
                    continue_on_failure=True,  # KEY
                    payload={"command": "exit 1", "capture_git": False},  # FAILS
                ),
                StepTemplate(
                    step_id="step3",
                    backend=Backend.cmd,
                    payload={"command": "echo step3 ran", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        # All three steps should have run
        assert store.read_step_outcome(result.run_id, 1).outcome == OutcomeStatus.completed
        assert store.read_step_outcome(result.run_id, 2).outcome == OutcomeStatus.failed
        assert store.read_step_outcome(result.run_id, 3).outcome == OutcomeStatus.completed

        # Final status should be completed_with_errors
        assert result.status == RunStatus.completed_with_errors

    def test_fail_fast_without_continue_flag(self, git_repo, store):
        """Without continue_on_failure, failure aborts."""
        job_def = JobDef(
            job_id="failfast-test",
            steps=[
                StepTemplate(
                    step_id="step1",
                    backend=Backend.cmd,
                    payload={"command": "echo step1", "capture_git": False},
                ),
                StepTemplate(
                    step_id="step2",
                    backend=Backend.cmd,
                    continue_on_failure=False,  # DEFAULT - fail fast
                    payload={"command": "exit 1", "capture_git": False},  # FAILS
                ),
                StepTemplate(
                    step_id="step3",
                    backend=Backend.cmd,
                    payload={"command": "echo should not run", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        # Step 3 should NOT have run
        step3_outcome_path = store.get_step_path(result.run_id, 3) / "outcome.yaml"
        assert not step3_outcome_path.exists()

        # Final status should be failed
        assert result.status == RunStatus.failed

    def test_multiple_failures_with_continue(self, git_repo, store):
        """Multiple steps can fail with continue_on_failure."""
        job_def = JobDef(
            job_id="multi-fail-test",
            steps=[
                StepTemplate(
                    step_id="step1",
                    backend=Backend.cmd,
                    payload={"command": "echo ok", "capture_git": False},
                ),
                StepTemplate(
                    step_id="step2",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "exit 1", "capture_git": False},
                ),
                StepTemplate(
                    step_id="step3",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "exit 2", "capture_git": False},
                ),
                StepTemplate(
                    step_id="step4",
                    backend=Backend.cmd,
                    payload={"command": "echo final", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        # All four steps should have run
        assert store.read_step_outcome(result.run_id, 1).outcome == OutcomeStatus.completed
        assert store.read_step_outcome(result.run_id, 2).outcome == OutcomeStatus.failed
        assert store.read_step_outcome(result.run_id, 3).outcome == OutcomeStatus.failed
        assert store.read_step_outcome(result.run_id, 4).outcome == OutcomeStatus.completed

        # Final status should be completed_with_errors
        assert result.status == RunStatus.completed_with_errors

    def test_aip1_style_captures_on_agent_failure(self, git_repo, store):
        """Even if agent step fails, capture/assess/finalize still run."""
        job_def = JobDef(
            job_id="aip1-style-test",
            steps=[
                # Step 1: Setup (must succeed)
                StepTemplate(
                    step_id="setup",
                    backend=Backend.cmd,
                    continue_on_failure=False,
                    payload={"command": "echo setup", "capture_git": False},
                ),
                # Step 2: Agent work (continue on failure)
                StepTemplate(
                    step_id="agent.work",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "echo partial work && exit 1", "capture_git": False},
                ),
                # Step 3: Capture (best effort)
                StepTemplate(
                    step_id="capture",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "echo capturing", "capture_git": False},
                ),
                # Step 4: Assess (best effort)
                StepTemplate(
                    step_id="assess",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "echo assessing", "capture_git": False},
                ),
                # Step 5: Finalize (always try)
                StepTemplate(
                    step_id="finalize",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "echo finalized", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        # All 5 steps should have artifacts
        for step_n in range(1, 6):
            step_path = store.get_step_path(result.run_id, step_n)
            assert (step_path / "manifest.yaml").exists()
            assert (step_path / "outcome.yaml").exists()
            assert (step_path / "capture.yaml").exists()

        # Verify outcomes
        assert store.read_step_outcome(result.run_id, 1).outcome == OutcomeStatus.completed
        assert store.read_step_outcome(result.run_id, 2).outcome == OutcomeStatus.failed  # Agent failed
        assert store.read_step_outcome(result.run_id, 3).outcome == OutcomeStatus.completed
        assert store.read_step_outcome(result.run_id, 4).outcome == OutcomeStatus.completed
        assert store.read_step_outcome(result.run_id, 5).outcome == OutcomeStatus.completed

        # Final status
        assert result.status == RunStatus.completed_with_errors

    def test_all_steps_succeed_returns_completed(self, git_repo, store):
        """When all steps succeed, status is completed (not completed_with_errors)."""
        job_def = JobDef(
            job_id="all-success-test",
            steps=[
                StepTemplate(
                    step_id="step1",
                    backend=Backend.cmd,
                    continue_on_failure=True,  # Flag doesn't matter when successful
                    payload={"command": "echo ok", "capture_git": False},
                ),
                StepTemplate(
                    step_id="step2",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "echo ok", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        # Should be completed (not completed_with_errors)
        assert result.status == RunStatus.completed

    def test_on_failure_skip_to_skips_intermediate_steps(self, git_repo, store):
        """When on_failure_skip_to is set, intermediate steps are skipped."""
        job_def = JobDef(
            job_id="skip-to-test",
            steps=[
                StepTemplate(
                    step_id="setup",
                    backend=Backend.cmd,
                    payload={"command": "echo setup", "capture_git": False},
                ),
                StepTemplate(
                    step_id="agent",
                    backend=Backend.cmd,
                    on_failure_skip_to="capture",  # Skip to capture on failure
                    payload={"command": "exit 1", "capture_git": False},  # FAILS
                ),
                StepTemplate(
                    step_id="commit1",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "echo commit1", "capture_git": False},
                ),
                StepTemplate(
                    step_id="drift-fix",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "echo drift-fix", "capture_git": False},
                ),
                StepTemplate(
                    step_id="capture",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "echo capture", "capture_git": False},
                ),
                StepTemplate(
                    step_id="finalize",
                    backend=Backend.cmd,
                    continue_on_failure=True,
                    payload={"command": "echo finalize", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)

        # Should complete with errors (agent failed, some skipped)
        assert result.status == RunStatus.completed_with_errors

        # Load outcomes and check what happened
        attempt = store.read_attempt(result.run_id, 1)
        step_ids = [o.step_id for o in attempt.step_outcomes]
        outcomes = {o.step_id: o.outcome for o in attempt.step_outcomes}

        # All 6 steps should have outcomes
        assert len(step_ids) == 6

        # Setup should complete
        assert outcomes["setup"] == OutcomeStatus.completed

        # Agent should fail
        assert outcomes["agent"] == OutcomeStatus.failed

        # commit1 and drift-fix should be skipped
        assert outcomes["commit1"] == OutcomeStatus.skipped
        assert outcomes["drift-fix"] == OutcomeStatus.skipped

        # capture and finalize should complete
        assert outcomes["capture"] == OutcomeStatus.completed
        assert outcomes["finalize"] == OutcomeStatus.completed


# =============================================================================
# Interactive Exit Code Policy Tests
# =============================================================================


class TestInteractiveExitCodePolicy:
    """Tests for interactive step exit code handling.

    Interactive steps (interactive=True) always complete regardless of
    exit code — the human was present and controls the session.
    Headless steps keep strict exit code handling.
    """

    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a test git repository."""
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

        return repo_path

    @pytest.fixture
    def store(self, tmp_path):
        """Create a test store."""
        return RunStore(root=tmp_path / "runs")

    def test_interactive_exit_130_is_completed(self, git_repo, store):
        """Interactive step with exit 130 (SIGINT) → completed."""
        job_def = JobDef(
            job_id="interactive-130-test",
            steps=[
                StepTemplate(
                    step_id="interactive_step",
                    backend=Backend.cmd,
                    interactive=True,
                    payload={"command": "exit 130", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)
        outcome = store.read_step_outcome(result.run_id, 1)
        assert outcome.outcome == OutcomeStatus.completed
        assert result.status == RunStatus.completed

    def test_interactive_exit_143_is_completed(self, git_repo, store):
        """Interactive step with exit 143 (SIGTERM) → completed."""
        job_def = JobDef(
            job_id="interactive-143-test",
            steps=[
                StepTemplate(
                    step_id="interactive_step",
                    backend=Backend.cmd,
                    interactive=True,
                    payload={"command": "exit 143", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)
        outcome = store.read_step_outcome(result.run_id, 1)
        assert outcome.outcome == OutcomeStatus.completed
        assert result.status == RunStatus.completed

    def test_interactive_exit_0_is_completed(self, git_repo, store):
        """Interactive step with exit 0 → completed (no regression)."""
        job_def = JobDef(
            job_id="interactive-0-test",
            steps=[
                StepTemplate(
                    step_id="interactive_step",
                    backend=Backend.cmd,
                    interactive=True,
                    payload={"command": "exit 0", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)
        outcome = store.read_step_outcome(result.run_id, 1)
        assert outcome.outcome == OutcomeStatus.completed

    def test_headless_exit_130_is_failed(self, git_repo, store):
        """Headless step with exit 130 → failed (no regression)."""
        job_def = JobDef(
            job_id="headless-130-test",
            steps=[
                StepTemplate(
                    step_id="headless_step",
                    backend=Backend.cmd,
                    interactive=False,  # default
                    payload={"command": "exit 130", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)
        assert result.status == RunStatus.failed

    def test_headless_exit_0_is_completed(self, git_repo, store):
        """Headless step with exit 0 → completed (no regression)."""
        job_def = JobDef(
            job_id="headless-0-test",
            steps=[
                StepTemplate(
                    step_id="headless_step",
                    backend=Backend.cmd,
                    interactive=False,
                    payload={"command": "exit 0", "capture_git": False},
                ),
            ],
        )

        envelope = {
            "job_def": job_def.model_dump(),
            "payload": {"repo_path": str(git_repo)},
        }

        result = execute(envelope, store=store)
        outcome = store.read_step_outcome(result.run_id, 1)
        assert outcome.outcome == OutcomeStatus.completed
        assert result.status == RunStatus.completed
