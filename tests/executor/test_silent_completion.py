"""
Integration tests for hf-03-01-silent-completion-detection.

Exercises the real engine.execute() -> _run_steps() -> outcome_status
computation path (AC2), and the real _generate_run_report() path (AC3),
using an on-disk git repo and the cmd backend -- no mocking of the status
computation or report generation itself.

Mirrors the real aip-1 shape: a non-patch-capturing setup step (standing in
for governance/sync_refs.py's unconditional CLAUDE.md marker append) runs
before a capture_patch=True step that either does nothing real (silent
completion) or makes a real change.
"""

import subprocess

import yaml

from spec.executor.engine import execute
from spec.executor.run_writers import ConsolidatedRunWriter
from spec.executor.schemas import Backend, JobDef, OutcomeStatus, RunStatus, StepTemplate

SYNC_BLOCK_APPEND = (
    "printf '\\n<!-- BEGIN SYNCED: proj -->\\n"
    "## Current Spec: proj\\n(No acceptance criteria section found in spec)\\n"
    "<!-- END SYNCED: proj -->\\n' >> CLAUDE.md"
)


def _git_repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, check=True, capture_output=True)
    (repo_path / "CLAUDE.md").write_text("# CLAUDE.md\n\nexisting content\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_path, check=True, capture_output=True)
    return repo_path


def _job_def(job_id: str, agent_command: str) -> JobDef:
    return JobDef(
        job_id=job_id,
        steps=[
            StepTemplate(
                step_id="refs.sync",
                backend=Backend.cmd,
                payload={"command": SYNC_BLOCK_APPEND, "capture_git": True},
                capture_patch=False,
                continue_on_failure=True,
            ),
            StepTemplate(
                step_id="agent.run_spec",
                backend=Backend.cmd,
                payload={"command": agent_command, "capture_git": True},
                capture_patch=True,
                continue_on_failure=True,
            ),
        ],
    )


class TestSilentCompletionStatus:
    """AC2: OutcomeStatus/RunStatus reflect a substantively-empty agent step."""

    def test_no_op_agent_step_is_not_completed(self, tmp_path):
        repo_path = _git_repo(tmp_path)
        # Agent step does nothing beyond what refs.sync already dirtied.
        job_def = _job_def("silent-test", "true")
        store = ConsolidatedRunWriter(root=tmp_path / "runs")

        envelope = {"job_def": job_def.model_dump(mode="json"), "payload": {"repo_path": str(repo_path)}}
        result = execute(envelope, store=store)

        agent_outcome = store.read_step_outcome(result.run_id, 2)
        assert agent_outcome.outcome == OutcomeStatus.no_change
        assert agent_outcome.outcome != OutcomeStatus.completed
        assert agent_outcome.error is not None
        assert "no substantive change" in agent_outcome.error

        assert result.status != RunStatus.completed
        assert result.status == RunStatus.completed_with_errors

    def test_real_change_agent_step_is_completed(self, tmp_path):
        repo_path = _git_repo(tmp_path)
        # Agent step makes a real code change beyond the sync block.
        job_def = _job_def("real-change-test", "echo 'def f(): pass' > real_code.py && git add real_code.py")
        store = ConsolidatedRunWriter(root=tmp_path / "runs")

        envelope = {"job_def": job_def.model_dump(mode="json"), "payload": {"repo_path": str(repo_path)}}
        result = execute(envelope, store=store)

        agent_outcome = store.read_step_outcome(result.run_id, 2)
        assert agent_outcome.outcome == OutcomeStatus.completed
        assert agent_outcome.error is None

        assert result.status == RunStatus.completed


class TestSilentCompletionReportCascade:
    """AC3: run_report issues/recommendation reflect the no_change outcome."""

    def test_no_op_run_produces_populated_issues_and_recommendation(self, tmp_path):
        repo_path = _git_repo(tmp_path)
        job_def = _job_def("silent-report-test", "true")
        store = ConsolidatedRunWriter(root=tmp_path / "runs")

        envelope = {"job_def": job_def.model_dump(mode="json"), "payload": {"repo_path": str(repo_path)}}
        result = execute(envelope, store=store)

        report_path = store.get_run_path(result.run_id) / "run_report.yaml"
        assert report_path.exists()
        report = yaml.safe_load(report_path.read_text())

        assert report["status"] == "completed_with_errors"

        assert report["issues"], "expected at least one issue for the no-op agent step"
        issue_text = " ".join(i.get("description", "") for i in report["issues"])
        assert "agent.run_spec" in issue_text
        assert "no_change" in issue_text or "no change" in issue_text.lower()

        assert report["recommendation"] != "Proceed with normal review and merge process."
        assert "review" in report["recommendation"].lower()

    def test_real_change_run_keeps_plain_success_recommendation(self, tmp_path):
        repo_path = _git_repo(tmp_path)
        job_def = _job_def(
            "real-change-report-test",
            "echo 'def f(): pass' > real_code.py && git add real_code.py",
        )
        store = ConsolidatedRunWriter(root=tmp_path / "runs")

        envelope = {"job_def": job_def.model_dump(mode="json"), "payload": {"repo_path": str(repo_path)}}
        result = execute(envelope, store=store)

        report_path = store.get_run_path(result.run_id) / "run_report.yaml"
        report = yaml.safe_load(report_path.read_text())

        assert report["status"] == "completed"
        assert report["issues"] == []
        assert report["recommendation"] == "Proceed with normal review and merge process."
