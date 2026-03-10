"""Tests for consolidated YAML run writer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from spec.executor.run_writers import ConsolidatedRunWriter
from spec.executor.schemas import (
    AgentCapture,
    AttemptRecord,
    Backend,
    Common,
    GitCapture,
    OutcomeStatus,
    Policy,
    RepoScope,
    RunRecord,
    RunStatus,
    StepCapture,
    StepManifest,
    StepOutcome,
)
from spec.executor.schemas.attempt import AttemptStatus


def _sample_common(tmp_path: Path) -> Common:
    return Common(
        repo_path=tmp_path / "repo",
        branch="feat/test",
        base_commit="abc123",
        timeout_s=300,
    )


def test_step_write_then_append_creates_valid_step_yaml(tmp_path: Path) -> None:
    writer = ConsolidatedRunWriter(root=tmp_path / "runs" / "e101")
    run_id = "run-e101-test-0001"
    writer.create_run(run_id)

    manifest = StepManifest(
        step_n=1,
        step_id="agent.run_spec",
        backend=Backend.cmd,
        common=_sample_common(tmp_path),
        payload={"command": "echo hello"},
    )
    writer.write_step_manifest(run_id, 1, manifest)

    step_yaml = writer.get_run_path(run_id) / "steps" / "step-001.yaml"
    raw_start = yaml.safe_load(step_yaml.read_text(encoding="utf-8"))
    assert raw_start["kind"] == "run_step"
    assert raw_start["step_n"] == 1
    assert raw_start["step_id"] == "agent.run_spec"
    assert raw_start["backend"] == "cmd"
    assert "outcome" not in raw_start

    step_dir = writer.get_step_path(run_id, 1)
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "stdout.txt").write_text("stdout line\n", encoding="utf-8")
    (step_dir / "stderr.txt").write_text("stderr line\n", encoding="utf-8")
    (step_dir / "changes.patch").write_text("--- a/test\n+++ b/test\n", encoding="utf-8")

    capture = StepCapture(
        step_n=1,
        step_id="agent.run_spec",
        git=GitCapture(
            base_commit="abc123",
            pre_status="",
            post_status="",
            patch_file="changes.patch",
        ),
        agent=AgentCapture(
            stdout_file="stdout.txt",
            stderr_file="stderr.txt",
            exit_code=0,
        ),
    )
    writer.write_step_capture(run_id, 1, capture)
    writer.write_step_outcome(
        run_id,
        1,
        StepOutcome(
            step_n=1,
            step_id="agent.run_spec",
            outcome=OutcomeStatus.completed,
            duration_ms=1234,
            manifest_ref="steps/step-001.yaml",
            capture_ref="steps/step-001.yaml",
        ),
    )

    raw_end = yaml.safe_load(step_yaml.read_text(encoding="utf-8"))
    assert raw_end["outcome"] == "completed"
    assert raw_end["duration_ms"] == 1234
    assert raw_end["capture"]["step_id"] == "agent.run_spec"
    assert "stdout line" in raw_end["stdout"]
    assert "stderr line" in raw_end["stderr"]
    assert "--- a/test" in raw_end["patch"]


def test_run_yaml_embeds_attempts_and_blob_fields(tmp_path: Path) -> None:
    writer = ConsolidatedRunWriter(root=tmp_path / "runs" / "e101")
    run_id = "run-e101-test-0002"
    run_path = writer.create_run(run_id)

    (run_path / "stdout.txt").write_text("run stdout\n", encoding="utf-8")
    (run_path / "stderr.txt").write_text("run stderr\n", encoding="utf-8")
    (run_path / "changes_final.patch").write_text("diff --git a/x b/x\n", encoding="utf-8")

    writer.write_attempt(
        run_id,
        AttemptRecord(
            attempt_n=1,
            started_at=datetime(2026, 3, 1, tzinfo=UTC),
            ended_at=datetime(2026, 3, 1, 0, 1, tzinfo=UTC),
            status=AttemptStatus.completed,
            final_step_n=2,
        ),
    )

    record = RunRecord(
        run_id=run_id,
        job_id="aip-1",
        job_hash="sha256:123",
        repo=RepoScope(repo_path=tmp_path / "repo", branch="feat/test", base_commit="abc123"),
        policy=Policy(profile="default"),
        status=RunStatus.completed,
        envelope={"payload": {"epic_id": "e101", "spec_id": "e101-04d"}},
    )
    writer.write_run_record(run_id, record)

    raw = yaml.safe_load((run_path / "run.yaml").read_text(encoding="utf-8"))
    assert raw["kind"] == "run"
    assert raw["run_id"] == run_id
    assert raw["epic_id"] == "e101"
    assert raw["spec_id"] == "e101-04d"
    assert len(raw["attempts"]) == 1
    assert "run stdout" in raw["stdout"]
    assert "run stderr" in raw["stderr"]
    assert "diff --git" in raw["changes_final"]


def test_run_report_written_as_yaml(tmp_path: Path) -> None:
    writer = ConsolidatedRunWriter(root=tmp_path / "runs" / "e101")
    run_id = "run-e101-test-0003"
    run_path = writer.create_run(run_id)

    writer.write_run_report(
        run_id,
        report_data={
            "run_id": run_id,
            "generated_at": "2026-03-01T00:00:00Z",
            "status": "completed",
            "job_id": "aip-1",
            "summary": "Done",
            "assessment": "Looks good",
            "issues": [{"description": "none", "severity": "warning"}],
            "recommendation": "Merge",
        },
        markdown_content="# ignored for consolidated",
    )

    report_path = run_path / "run_report.yaml"
    raw = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert raw["kind"] == "run_report"
    assert raw["name"] == f"{run_id}/report"
    assert raw["run_id"] == run_id
    assert raw["summary"] == "Done"
