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

import os
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
    # The registered run@1-0-0 schema declares a top-level `envelope`
    # property, but storacle's policy input flattens object fields, and a
    # top-level `envelope` collides with the WAL row's envelope-piece
    # semantics in check_schema_adherence ("no exact envelope schema_ref"
    # refusal). Until the primitives distinguish object-envelope from
    # row-envelope, the specwright job envelope rides in metadata.
    if run_doc.get("envelope") is not None:
        metadata["envelope"] = run_doc["envelope"]

    params: dict[str, Any] = {
        "name": slug,
        "job_definition_id": run_doc.get("job_id") or "unknown",
        "job_type": JOB_TYPE,
        "status": str(run_doc.get("status") or "unknown"),
        "metadata": metadata,
    }
    for key in ("created_at", "updated_at", "policy", "repo", "error"):
        if run_doc.get(key) is not None:
            params[key] = run_doc[key]
    return params


def build_step_object_params(
    step_doc: dict[str, Any],
    run_slug: str,
    run_identity: str,
    scratch_dir: Path,
    job_id: str,
) -> dict[str, Any]:
    """Map a consolidated step-NNN.yaml document to run_step@1-0-0 object params.

    run_step is a schema subtype of run (registry nesting = inheritance),
    so the resolved schema also requires job_definition_id / job_type /
    status. Step content (minus bulk) rides in metadata.
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
        "job_definition_id": job_id or "unknown",
        "job_type": JOB_TYPE,
        "status": str(step_doc.get("outcome") or "unknown"),
        "metadata": metadata,
    }


def build_report_object_params(
    report_doc: dict[str, Any], run_slug: str, run_identity: str, job_id: str
) -> dict[str, Any]:
    """Map a consolidated run_report.yaml document to run_report@1-0-0 params.

    run_report is a schema subtype of run (see build_step_object_params).
    """
    metadata = {
        k: v
        for k, v in report_doc.items()
        if k not in ("kind", "artifact_id", "name", "run_id")
    }
    metadata["run_slug"] = run_slug
    return {
        "name": f"{run_slug}/report",
        "run_id": run_identity,
        "job_definition_id": job_id or "unknown",
        "job_type": JOB_TYPE,
        "status": str(report_doc.get("status") or "unknown"),
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


#: Mirrors storacle config.py's required_vars — the gate cannot stamp
#: without these; checked BEFORE submit so a mis-resolved .env fails with
#: a diagnosis instead of a bare missing-variables refusal mid-emission.
_REQUIRED_STORACLE_VARS = (
    "STORACLE_NAMESPACE_SALT",
    "STORACLE_PROJECT",
    "STORACLE_WAL_DATASET",
    "STORACLE_WAL_TABLE",
    "STORACLE_OPS_DATASET",
    "STORACLE_ALLOWED_WAL_DATASETS",
)


def _load_lorchestra_env(lorchestra_pkg: Any) -> Path:
    """Source lorchestra's .env as defaults for storacle configuration.

    Mirrors life-cli's convention (it dotenv-loads its own .env before
    calling lorchestra in-process). Pre-set environment variables win —
    this only fills gaps, so operators can still override per-invocation.

    Returns the resolved .env path so callers can name it in errors.
    """
    env_path = Path(lorchestra_pkg.__file__).resolve().parent.parent / ".env"
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv ships with the venv
        return env_path
    if env_path.exists():
        load_dotenv(env_path, override=False)
    return env_path


def _require_storacle_env(env_path: Path, lorchestra_pkg: Any) -> None:
    """Refuse loudly, pre-submit, when the storacle gate would starve.

    2026-07-20 incident: lorchestra got installed NON-editable into this
    venv, so ``lorchestra.__file__`` resolved into site-packages, the
    ``.env`` lookup silently missed ``/workspace/lorchestra/.env``, and two
    runs' emissions died mid-submit on a bare missing-variables refusal.
    This check turns that silent skip into a diagnosis.
    """
    missing = [
        v for v in _REQUIRED_STORACLE_VARS if not (os.environ.get(v) or "").strip()
    ]
    if not missing:
        return
    if env_path.exists():
        hint = f"loaded {env_path} but these vars are not in it"
    else:
        hint = (
            f"{env_path} DOES NOT EXIST — is lorchestra installed "
            f"non-editable? (lorchestra.__file__={lorchestra_pkg.__file__!r}; "
            "fix: uv pip install --no-deps -e /workspace/lorchestra)"
        )
    raise GateEmissionError(
        f"storacle environment incomplete before submit — missing "
        f"{', '.join(missing)}; {hint}"
    )


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

    env_path = _load_lorchestra_env(lorchestra)
    _require_storacle_env(env_path, lorchestra)

    definitions_dir = Path(lorchestra.__file__).parent / "jobs" / "definitions"
    envelope = {
        "job_id": "object.create",
        "payload": {
            # "kind" must be present (None is fine): the object.create job
            # resolves @payload.kind strictly at compile time.
            "kind": None,
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


def _row_exists(prod_db: Path, table: str, kind: str, name: str) -> bool:
    """True if a row of this kind+name already landed (idempotent resume).

    Emission is append-once: a retry after a partial emission must not
    re-submit rows that already exist (name-uniqueness would refuse them).
    A missing DB reports False — submission then proceeds and verification
    fails loudly instead.
    """
    if not prod_db.exists():
        return False
    with sqlite3.connect(f"file:{prod_db}?mode=ro", uri=True) as conn:
        row = conn.execute(
            f'SELECT COUNT(*) FROM "{table}" '  # noqa: S608 - table from descriptor
            f"WHERE kind LIKE ? AND json_extract(object, '$.name') = ?",
            (f"{kind}@%", name),
        ).fetchone()
    return bool(row and row[0])


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

    job_id = str(run_doc.get("job_id") or "unknown")
    emitted: dict[str, list[str]] = {"run": [], "run_step": [], "run_report": []}

    def _submit_once(kind: str, schema_ref: str, params: dict[str, Any]) -> None:
        if not _row_exists(prod_db, table, kind, params["name"]):
            _submit_object(schema_ref, params)
        emitted[kind].append(params["name"])

    run_params = build_run_object_params(run_doc, run_dir)
    _submit_once("run", RUN_SCHEMA_REF, run_params)

    steps_dir = run_dir / "steps"
    step_files = sorted(steps_dir.glob("step-*.yaml")) if steps_dir.exists() else []
    for step_file in step_files:
        step_doc = _load_yaml(step_file)
        step_params = build_step_object_params(step_doc, slug, run_identity, run_dir, job_id)
        _submit_once("run_step", RUN_STEP_SCHEMA_REF, step_params)

    report_path = run_dir / "run_report.yaml"
    if report_path.exists():
        report_doc = _load_yaml(report_path)
        report_params = build_report_object_params(report_doc, slug, run_identity, job_id)
        _submit_once("run_report", RUN_REPORT_SCHEMA_REF, report_params)

    verified = _verify_rows(prod_db, table, emitted)

    return EmissionResult(
        run_id=run_id,
        run_identity=run_identity,
        dataset=dataset,
        table=table,
        emitted_names=emitted,
        verified_rows=verified,
    )
