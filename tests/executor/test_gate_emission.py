"""Tests for gated run-record emission (e040-07d D2)."""

from pathlib import Path

import pytest
import yaml

from spec.executor import gate_emission
from spec.executor.gate_emission import (
    GateEmissionError,
    build_report_object_params,
    build_run_object_params,
    build_step_object_params,
    derive_identity,
    emit_run_records,
)

# ---------------------------------------------------------------------------
# Identity parity
# ---------------------------------------------------------------------------


def test_derive_identity_matches_lorchestra():
    """Our identity recipe must match lorchestra's prepare step exactly —
    step/report rows reference the run row's derived run_id."""
    lorchestra_prepare = pytest.importorskip(
        "lorchestra.callable.object_create_prepare"
    )
    name = "run-e040-test-20260717-000000-abc123"
    assert derive_identity("run", name) == lorchestra_prepare._derive_identity(
        "run", name, "iglu:io.lifeos/run/jsonschema/1-0-0"
    )


# ---------------------------------------------------------------------------
# Object param builders
# ---------------------------------------------------------------------------


RUN_DOC = {
    "kind": "run",
    "artifact_id": "some-uuid",
    "name": "run-e040-test-20260717-000000-abc123",
    "run_id": "run-e040-test-20260717-000000-abc123",
    "job_id": "aip-1",
    "status": "completed",
    "epic_id": "e040",
    "spec_id": "e040-07d",
    "repo": {"repo_path": "/workspace/foo", "branch": "main", "base_commit": "abc"},
    "policy": {"profile": "standard", "allow_commit": True, "allow_push": False},
    "created_at": "2026-07-17T00:00:00Z",
    "updated_at": "2026-07-17T00:10:00Z",
    "envelope": {"job_def": {"job_id": "aip-1"}, "payload": {"x": 1}},
    "attempts": [{"attempt_n": 1, "status": "completed"}],
    "stdout": "BULK-STDOUT",
    "stderr": "BULK-STDERR",
    "changes_final": "BULK-PATCH",
}

STEP_DOC = {
    "kind": "run_step",
    "artifact_id": "step-uuid",
    "name": "run-e040-test-20260717-000000-abc123/step-003",
    "run_id": "run-e040-test-20260717-000000-abc123",
    "step_n": 3,
    "step_id": "agent.run_spec",
    "backend": "copilot",
    "started_at": "2026-07-17T00:01:00Z",
    "payload": {"a": 1},
    "outcome": "completed",
    "duration_ms": 1234,
    "ended_at": "2026-07-17T00:03:00Z",
    "error": None,
    "capture": {"git": {"base_commit": "abc"}},
    "stdout": "BULK-STDOUT",
    "stderr": "BULK-STDERR",
    "patch": "BULK-PATCH",
}

REPORT_DOC = {
    "kind": "run_report",
    "artifact_id": "report-uuid",
    "name": "run-e040-test-20260717-000000-abc123/report",
    "run_id": "run-e040-test-20260717-000000-abc123",
    "generated_at": "2026-07-17T00:11:00Z",
    "status": "completed",
    "job_id": "aip-1",
    "summary": "It worked.",
    "assessment": "Good.",
    "issues": [],
    "recommendation": "Ship it.",
}

# Properties declared by the registered run@1-0-0 schema
# (unevaluatedProperties: false — anything else is a gate refusal).
RUN_SCHEMA_PROPERTIES = {
    "kind", "name", "run_id", "job_type", "status", "created_at",
    "updated_at", "job_hash", "metadata", "schema_ref", "job_definition_id",
    "schema_version", "job_request_id", "envelope", "policy", "repo",
    "steps", "error",
}
RUN_STEP_SCHEMA_PROPERTIES = {
    "kind", "run_step_id", "name", "run_id", "step_number",
    "schema_version", "metadata",
}
RUN_REPORT_SCHEMA_PROPERTIES = {
    "kind", "run_report_id", "name", "run_id", "schema_version", "metadata",
}


def test_run_params_shape_and_bulk_stripped(tmp_path):
    params = build_run_object_params(RUN_DOC, tmp_path)

    assert set(params) <= RUN_SCHEMA_PROPERTIES
    assert params["name"] == RUN_DOC["run_id"]
    assert params["job_definition_id"] == "aip-1"
    assert params["job_type"] == "specwright"
    assert params["status"] == "completed"
    assert params["envelope"] == RUN_DOC["envelope"]
    # Identity derivation is lorchestra's job — never pre-set.
    assert "run_id" not in params
    # Bulk never becomes row content.
    flat = str(params)
    assert "BULK-STDOUT" not in flat
    assert "BULK-STDERR" not in flat
    assert "BULK-PATCH" not in flat
    # Scratch refs recorded instead.
    assert params["metadata"]["artifacts"]["scratch_dir"] == str(tmp_path)
    assert set(params["metadata"]["artifacts"]["bulk_fields"]) == {
        "stdout", "stderr", "changes_final",
    }
    # Non-schema run.yaml keys ride in metadata.
    assert params["metadata"]["epic_id"] == "e040"
    assert params["metadata"]["spec_id"] == "e040-07d"
    assert params["metadata"]["attempts"] == RUN_DOC["attempts"]


def test_step_params_shape_and_bulk_stripped(tmp_path):
    run_identity = derive_identity("run", RUN_DOC["run_id"])
    params = build_step_object_params(STEP_DOC, RUN_DOC["run_id"], run_identity, tmp_path)

    assert set(params) <= RUN_STEP_SCHEMA_PROPERTIES
    assert params["name"] == f"{RUN_DOC['run_id']}/step-003"
    assert params["run_id"] == run_identity
    assert params["step_number"] == 3
    md = params["metadata"]
    assert md["step_id"] == "agent.run_spec"
    assert md["backend"] == "copilot"
    assert md["outcome"] == "completed"
    flat = str(params)
    assert "BULK-STDOUT" not in flat
    assert "BULK-PATCH" not in flat
    assert set(md["artifacts"]["bulk_fields"]) == {"stdout", "stderr", "patch"}


def test_report_params_shape(tmp_path):
    run_identity = derive_identity("run", RUN_DOC["run_id"])
    params = build_report_object_params(REPORT_DOC, RUN_DOC["run_id"], run_identity)

    assert set(params) <= RUN_REPORT_SCHEMA_PROPERTIES
    assert params["name"] == f"{RUN_DOC['run_id']}/report"
    assert params["run_id"] == run_identity
    md = params["metadata"]
    assert md["summary"] == "It worked."
    assert md["issues"] == []


# ---------------------------------------------------------------------------
# Emission wiring (faked gate + faked verification)
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, run_dir: Path):
        self._run_dir = run_dir

    def get_run_path(self, run_id: str) -> Path:
        return self._run_dir


@pytest.fixture
def consolidated_run(tmp_path):
    """A consolidated scratch run tree on disk."""
    run_dir = tmp_path / RUN_DOC["run_id"]
    (run_dir / "steps").mkdir(parents=True)
    (run_dir / "run.yaml").write_text(yaml.dump(RUN_DOC))
    (run_dir / "steps" / "step-003.yaml").write_text(yaml.dump(STEP_DOC))
    (run_dir / "run_report.yaml").write_text(yaml.dump(REPORT_DOC))
    return run_dir


def test_emit_run_records_submits_all_and_verifies(consolidated_run, monkeypatch):
    submitted: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        gate_emission, "_submit_object",
        lambda ref, params: submitted.append((ref, params)),
    )
    monkeypatch.setattr(
        gate_emission, "_resolve_target", lambda ref: ("ops", "ops__base")
    )
    monkeypatch.setattr(
        gate_emission, "_verify_rows", lambda db, table, names: 3
    )

    store = _FakeStore(consolidated_run)
    result = emit_run_records(
        store=store, run_id=RUN_DOC["run_id"], prod_db=Path("/nonexistent")
    )

    refs = [r for r, _ in submitted]
    assert refs == [
        gate_emission.RUN_SCHEMA_REF,
        gate_emission.RUN_STEP_SCHEMA_REF,
        gate_emission.RUN_REPORT_SCHEMA_REF,
    ]
    assert result.dataset == "ops"
    assert result.table == "ops__base"
    assert result.total_emitted == 3
    assert result.verified_rows == 3
    assert result.run_identity == derive_identity("run", RUN_DOC["run_id"])


def test_emit_run_records_gate_refusal_raises(consolidated_run, monkeypatch):
    """Gate refusal surfaces as GateEmissionError — never swallowed."""

    def _refuse(ref, params):
        raise GateEmissionError("severity=error: unknown_kind")

    monkeypatch.setattr(gate_emission, "_submit_object", _refuse)
    monkeypatch.setattr(
        gate_emission, "_resolve_target", lambda ref: ("ops", "ops__base")
    )

    with pytest.raises(GateEmissionError, match="severity=error"):
        emit_run_records(
            store=_FakeStore(consolidated_run),
            run_id=RUN_DOC["run_id"],
            prod_db=Path("/nonexistent"),
        )


def test_emit_run_records_missing_run_yaml_raises(tmp_path):
    empty_dir = tmp_path / "empty-run"
    empty_dir.mkdir()
    with pytest.raises(GateEmissionError, match="run.yaml"):
        emit_run_records(
            store=_FakeStore(empty_dir),
            run_id="run-x",
            prod_db=Path("/nonexistent"),
        )


# ---------------------------------------------------------------------------
# Row-count verification (silent-noop guard) against a real sqlite file
# ---------------------------------------------------------------------------


def _make_ops_db(tmp_path, rows):
    import json
    import sqlite3

    db = tmp_path / "prod.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE ops__base (kind TEXT, object TEXT, policy_stamp TEXT)"
        )
        for kind, name, stamp in rows:
            conn.execute(
                "INSERT INTO ops__base VALUES (?, ?, ?)",
                (kind, json.dumps({"name": name}), stamp),
            )
    return db


def test_verify_rows_counts_stamped_rows(tmp_path):
    db = _make_ops_db(
        tmp_path,
        [
            ("run@1.0.0", "run-x", '[{"gate": "primary_write"}]'),
            ("run_step@1.0.0", "run-x/step-001", '[{"gate": "primary_write"}]'),
        ],
    )
    verified = gate_emission._verify_rows(
        db, "ops__base",
        {"run": ["run-x"], "run_step": ["run-x/step-001"], "run_report": []},
    )
    assert verified == 2


def test_verify_rows_missing_row_trips_noop_guard(tmp_path):
    db = _make_ops_db(
        tmp_path, [("run@1.0.0", "run-x", '[{"gate": "primary_write"}]')]
    )
    with pytest.raises(GateEmissionError, match="silent-noop"):
        gate_emission._verify_rows(
            db, "ops__base",
            {"run": ["run-x"], "run_step": ["run-x/step-001"]},
        )


def test_verify_rows_unstamped_row_fails(tmp_path):
    db = _make_ops_db(tmp_path, [("run@1.0.0", "run-x", "[]")])
    with pytest.raises(GateEmissionError, match="[Ss]tamp"):
        gate_emission._verify_rows(db, "ops__base", {"run": ["run-x"]})
