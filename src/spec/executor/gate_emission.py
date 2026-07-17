"""Gated run-record emission — run / run_step / run_report rows through the gate.

Emit-once-at-finalize: after a run completes, the consolidated YAML files in
the local scratch store are mapped to governed objects and submitted through
lorchestra's ``object.create`` job (the sanctioned write path: storacle
``wal.append`` behind the primary_write policy gate). The target dataset is
derived from each kind's registry descriptor (``default_data_domain``) —
never hardcoded here.

Bulk artifacts (stdout/stderr/patches) never become rows: they stay in the
scratch tree, and the rows carry scratch refs in ``metadata``.

There is NO fallback to tree-writing on gate refusal — emission failures
raise ``GateEmissionError`` and must surface to the operator. A silently
degraded run record is worse than a failed run.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RUN_SCHEMA_REF = "iglu:io.lifeos/run/jsonschema/1-0-0"
RUN_STEP_SCHEMA_REF = "iglu:io.lifeos/run_step/jsonschema/1-0-0"
RUN_REPORT_SCHEMA_REF = "iglu:io.lifeos/run_report/jsonschema/1-0-0"

DEFAULT_PROD_DB = Path("~/lifeos/lifeos-cloud-prod.db").expanduser()

#: Runs are execution records produced by specwright's job templates.
JOB_TYPE = "specwright"

# Bulk keys stripped from row payloads (they remain in the scratch files).
_BULK_RUN_KEYS = ("stdout", "stderr", "changes_final")
_BULK_STEP_KEYS = ("stdout", "stderr", "patch")

# Mirrors lorchestra.callable.object_create_prepare._IDENTITY_NAMESPACE —
# parity is asserted by tests/executor/test_gate_emission.py so drift is
# caught, not silently divergent.
_IDENTITY_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "lifeos.object_create")


class GateEmissionError(RuntimeError):
    """Raised when gated emission fails. Never fall back to tree-writing."""


@dataclass
class EmissionResult:
    """Outcome of one run's gated emission, with row-count verification."""

    run_id: str
    run_identity: str
    dataset: str
    table: str
    emitted_names: dict[str, list[str]] = field(default_factory=dict)
    verified_rows: int = 0

    @property
    def total_emitted(self) -> int:
        return sum(len(v) for v in self.emitted_names.values())


def derive_identity(kind: str, name: str) -> str:
    """Deterministic uuid5 identity — same recipe as lorchestra's prepare step."""
    return str(uuid.uuid5(_IDENTITY_NAMESPACE, f"{kind}:{name}"))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise GateEmissionError(f"Expected consolidated file missing: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise GateEmissionError(f"Expected a YAML mapping in {path}")
    return data


def build_run_object_params(run_doc: dict[str, Any], scratch_dir: Path) -> dict[str, Any]:
    """Map a consolidated run.yaml document to run@1-0-0 object params.

    Bulk fields (stdout/stderr/changes_final) are stripped — the row carries
    scratch refs in metadata instead. Identity (run_id) is intentionally NOT
    set: lorchestra's prepare step derives it from kind + name so creation
    stays idempotent.
    """
    slug = run_doc.get("run_id") or run_doc.get("name")
    if not slug:
        raise GateEmissionError("run.yaml has no run_id/name — cannot emit")

    metadata: dict[str, Any] = {
        "source": "specwright",
        "run_slug": slug,
        "epic_id": run_doc.get("epic_id"),
        "spec_id": run_doc.get("spec_id"),
        "job_id": run_doc.get("job_id"),
        "attempts": run_doc.get("attempts") or [],
        "artifacts": _artifact_refs(scratch_dir, _BULK_RUN_KEYS, run_doc),
    }

    params: dict[str, Any] = {
        "name": slug,
        "job_definition_id": run_doc.get("job_id") or "unknown",
        "job_type": JOB_TYPE,
        "status": str(run_doc.get("status") or "unknown"),
        "metadata": metadata,
    }
    for key in ("created_at", "updated_at", "envelope", "policy", "repo", "error"):
        if run_doc.get(key) is not None:
            params[key] = run_doc[key]
    return params


def build_step_object_params(
    step_doc: dict[str, Any], run_slug: str, run_identity: str, scratch_dir: Path
) -> dict[str, Any]:
    """Map a consolidated step-NNN.yaml document to run_step@1-0-0 object params.

    The registered run_step schema only declares identity fields + metadata,
    so all step content (minus bulk) rides in metadata.
    """
    step_n = step_doc.get("step_n")
    if step_n is None:
        raise GateEmissionError(f"Step document for {run_slug} has no step_n")

    metadata = {
        k: v
        for k, v in step_doc.items()
        if k not in ("kind", "artifact_id", "name", "run_id", "step_n", *_BULK_STEP_KEYS)
    }
    metadata["run_slug"] = run_slug
    metadata["artifacts"] = _artifact_refs(scratch_dir, _BULK_STEP_KEYS, step_doc)

    return {
        "name": f"{run_slug}/step-{int(step_n):03d}",
        "run_id": run_identity,
        "step_number": int(step_n),
        "metadata": metadata,
    }


def build_report_object_params(
    report_doc: dict[str, Any], run_slug: str, run_identity: str
) -> dict[str, Any]:
    """Map a consolidated run_report.yaml document to run_report@1-0-0 params."""
    metadata = {
        k: v
        for k, v in report_doc.items()
        if k not in ("kind", "artifact_id", "name", "run_id")
    }
    metadata["run_slug"] = run_slug
    return {
        "name": f"{run_slug}/report",
        "run_id": run_identity,
        "metadata": metadata,
    }


def _artifact_refs(
    scratch_dir: Path, bulk_keys: tuple[str, ...], doc: dict[str, Any]
) -> dict[str, Any]:
    """Record where bulk content lives (scratch tree), for rows that omit it."""
    present = [k for k in bulk_keys if doc.get(k)]
    return {"scratch_dir": str(scratch_dir), "bulk_fields": present}


def _load_descriptor(schema_ref: str) -> dict[str, Any]:
    """Load a kind descriptor from the registry via lorchestra's own loader."""
    from lorchestra.callable.object_creator import _load_schema_by_ref

    return _load_schema_by_ref(schema_ref)


def _resolve_target(schema_ref: str) -> tuple[str, str]:
    """Derive (dataset, table) from the kind descriptor — never hardcoded."""
    descriptor = _load_descriptor(schema_ref)
    dataset = descriptor.get("default_data_domain")
    if not dataset:
        raise GateEmissionError(
            f"Descriptor for {schema_ref} has no default_data_domain — refusing to guess"
        )
    return dataset, f"{dataset}__base"


def _submit_object(schema_ref: str, object_params: dict[str, Any]) -> None:
    """Submit one governed object through lorchestra's object.create job."""
    try:
        import lorchestra
        from lorchestra import execute as lorchestra_execute
    except ImportError as e:  # pragma: no cover - environment-dependent
        raise GateEmissionError(
            "lorchestra is not importable — gated emission requires the "
            "lorchestra library (no fallback to tree-writing). "
            f"Import error: {e}"
        ) from e

    definitions_dir = Path(lorchestra.__file__).parent / "jobs" / "definitions"
    envelope = {
        "job_id": "object.create",
        "payload": {
            "schema_ref": schema_ref,
            "object_params": object_params,
        },
        "definitions_dir": definitions_dir,
    }
    result = lorchestra_execute(envelope)
    if not getattr(result, "success", False):
        detail: str
        failed = getattr(result, "failed_steps", None) or []
        if failed:
            detail = "; ".join(
                str(getattr(s, "error", None) or s) for s in failed
            )
        else:
            detail = str(getattr(result, "error", None) or "unknown error")
        raise GateEmissionError(
            f"Gate refused {schema_ref} object "
            f"'{object_params.get('name')}': {detail}"
        )


def _verify_rows(
    prod_db: Path, table: str, emitted_names: dict[str, list[str]]
) -> int:
    """Count the emitted rows in the target table — the silent-noop guard.

    Never trust a success status without counting rows (lorchestra
    STATUS.md:108 footgun). Also requires every row to carry a non-empty
    policy_stamp (the gate's admission evidence).
    """
    if not prod_db.exists():
        raise GateEmissionError(f"Prod DB not found for verification: {prod_db}")

    verified = 0
    missing: list[str] = []
    unstamped: list[str] = []
    with sqlite3.connect(f"file:{prod_db}?mode=ro", uri=True) as conn:
        for kind, names in emitted_names.items():
            for name in names:
                row = conn.execute(
                    f'SELECT COUNT(*), '  # noqa: S608 - table from descriptor
                    f"SUM(CASE WHEN policy_stamp IS NOT NULL AND policy_stamp != '' "
                    f"AND json_array_length(policy_stamp) > 0 THEN 1 ELSE 0 END) "
                    f'FROM "{table}" '
                    f"WHERE kind LIKE ? AND json_extract(object, '$.name') = ?",
                    (f"{kind}@%", name),
                ).fetchone()
                count = row[0] or 0
                stamped = row[1] or 0
                if count < 1:
                    missing.append(f"{kind}:{name}")
                elif stamped < count:
                    unstamped.append(f"{kind}:{name}")
                else:
                    verified += count
    if missing:
        raise GateEmissionError(
            f"Row-count verification FAILED — emitted but not found in {table}: "
            f"{missing} (silent-noop footgun tripped)"
        )
    if unstamped:
        raise GateEmissionError(
            f"Stamp verification FAILED — rows in {table} without policy_stamp: {unstamped}"
        )
    return verified


def emit_run_records(
    *, store: Any, run_id: str, prod_db: Path | None = None
) -> EmissionResult:
    """Emit one finished run's records through the gate and verify the rows.

    Reads the consolidated YAML files the store wrote to local scratch
    (run.yaml, steps/step-NNN.yaml, run_report.yaml), maps them to the
    registered run / run_step / run_report kinds, submits each through
    lorchestra object.create, then counts the landed rows.
    """
    prod_db = prod_db or DEFAULT_PROD_DB
    run_dir = store.get_run_path(run_id)

    run_doc = _load_yaml(run_dir / "run.yaml")
    slug = run_doc.get("run_id") or run_id
    run_identity = derive_identity("run", slug)

    dataset, table = _resolve_target(RUN_SCHEMA_REF)

    emitted: dict[str, list[str]] = {"run": [], "run_step": [], "run_report": []}

    run_params = build_run_object_params(run_doc, run_dir)
    _submit_object(RUN_SCHEMA_REF, run_params)
    emitted["run"].append(run_params["name"])

    steps_dir = run_dir / "steps"
    step_files = sorted(steps_dir.glob("step-*.yaml")) if steps_dir.exists() else []
    for step_file in step_files:
        step_doc = _load_yaml(step_file)
        step_params = build_step_object_params(step_doc, slug, run_identity, run_dir)
        _submit_object(RUN_STEP_SCHEMA_REF, step_params)
        emitted["run_step"].append(step_params["name"])

    report_path = run_dir / "run_report.yaml"
    if report_path.exists():
        report_doc = _load_yaml(report_path)
        report_params = build_report_object_params(report_doc, slug, run_identity)
        _submit_object(RUN_REPORT_SCHEMA_REF, report_params)
        emitted["run_report"].append(report_params["name"])

    verified = _verify_rows(prod_db, table, emitted)

    return EmissionResult(
        run_id=run_id,
        run_identity=run_identity,
        dataset=dataset,
        table=table,
        emitted_names=emitted,
        verified_rows=verified,
    )
