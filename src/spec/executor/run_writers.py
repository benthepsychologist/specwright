"""Run output writers.

Legacy writer behavior remains in RunStore (`spec.executor.store.RunStore`).
This module adds a consolidated YAML writer for registrar ingestion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import yaml

from spec.executor.schemas.attempt import AttemptRecord
from spec.executor.schemas.capture import StepCapture
from spec.executor.schemas.job_def import JobDef
from spec.executor.schemas.job_instance import JobInstance
from spec.executor.schemas.manifest import StepManifest
from spec.executor.schemas.outcome import OutcomeStatus, StepOutcome
from spec.executor.schemas.run import Policy, RepoScope, RunRecord, RunStatus


class _LiteralStr(str):
    """Marker type for forcing YAML literal block scalars."""


def _literal_str_representer(dumper: yaml.Dumper, data: _LiteralStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


yaml.SafeDumper.add_representer(_LiteralStr, _literal_str_representer)

_UUID_NAMESPACE = UUID("9f31e4e2-7728-4ebf-a6df-0f95c0bde2cc")


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _artifact_uuid(kind: str, name: str) -> str:
    return str(uuid5(_UUID_NAMESPACE, f"{kind}:{name}"))


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _to_yaml(data: dict[str, Any]) -> str:
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str) and ("\n" in value):
            normalized[key] = _LiteralStr(value)
        else:
            normalized[key] = value
    return yaml.safe_dump(
        normalized,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


class ConsolidatedRunWriter:
    """Write run artifacts in consolidated registrar-friendly YAML layout."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._job_defs: dict[str, JobDef] = {}
        self._job_instances: dict[str, JobInstance] = {}
        self._attempts: dict[str, list[AttemptRecord]] = {}
        self._step_manifests: dict[tuple[str, int], StepManifest] = {}
        self._step_captures: dict[tuple[str, int], StepCapture] = {}
        self._step_started_at: dict[tuple[str, int], datetime] = {}

    def create_run(self, run_id: str) -> Path:
        run_path = self.get_run_path(run_id)
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / "steps").mkdir(parents=True, exist_ok=True)
        self._attempts.setdefault(run_id, [])
        return run_path

    def get_run_path(self, run_id: str) -> Path:
        return self.root / run_id

    def get_step_path(self, run_id: str, step_n: int) -> Path:
        # Step artifact files (stdout/stderr/changes.patch) still live in per-step dirs.
        return self.get_run_path(run_id) / "steps" / f"step-{step_n:03d}"

    def _get_step_yaml_path(self, run_id: str, step_n: int) -> Path:
        return self.get_run_path(run_id) / "steps" / f"step-{step_n:03d}.yaml"

    def _step_name(self, run_id: str, step_n: int) -> str:
        return f"{run_id}/step-{step_n:03d}"

    def _attempts_payload(self, run_id: str) -> list[dict[str, Any]]:
        attempts = sorted(self._attempts.get(run_id, []), key=lambda a: a.attempt_n)
        payload: list[dict[str, Any]] = []
        for attempt in attempts:
            payload.append(
                {
                    "attempt_n": attempt.attempt_n,
                    "started_at": _iso_utc(attempt.started_at),
                    "ended_at": _iso_utc(attempt.ended_at) if attempt.ended_at else None,
                    "status": attempt.status.value,
                    "final_step_n": attempt.final_step_n,
                    "error": attempt.error,
                }
            )
        return payload

    def write_run_record(self, run_id: str, record: RunRecord) -> None:
        run_path = self.get_run_path(run_id)
        run_path.mkdir(parents=True, exist_ok=True)

        payload = (record.envelope or {}).get("payload", {})
        epic_id = payload.get("epic_id") or "adhoc"
        spec_id = payload.get("spec_id") or ""

        envelope = dict(record.envelope or {})
        if "job_def" not in envelope and run_id in self._job_defs:
            envelope["job_def"] = self._job_defs[run_id].model_dump(mode="json")

        data: dict[str, Any] = {
            "kind": "run",
            "artifact_id": _artifact_uuid("run", record.run_id),
            "name": record.run_id,
            "run_id": record.run_id,
            "job_id": record.job_id,
            "status": record.status.value,
            "epic_id": epic_id,
            "spec_id": spec_id,
            "repo": record.repo.model_dump(mode="json"),
            "policy": record.policy.model_dump(mode="json"),
            "created_at": _iso_utc(record.created_at),
            "updated_at": _iso_utc(record.updated_at),
            "envelope": envelope,
            "attempts": self._attempts_payload(run_id),
            "stdout": _read_text(run_path / "stdout.txt"),
            "stderr": _read_text(run_path / "stderr.txt"),
            "changes_final": _read_text(run_path / "changes_final.patch"),
        }
        if record.error:
            data["error"] = record.error

        (run_path / "run.yaml").write_text(_to_yaml(data), encoding="utf-8")

    def read_run_record(self, run_id: str) -> RunRecord:
        path = self.get_run_path(run_id) / "run.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid run.yaml at {path}")
        return RunRecord(
            run_id=str(raw.get("run_id", run_id)),
            job_id=str(raw.get("job_id", "")),
            job_hash=str(raw.get("job_hash", "")),
            repo=RepoScope.model_validate(raw.get("repo", {})),
            policy=Policy.model_validate(raw.get("policy", {})),
            status=RunStatus(str(raw.get("status", RunStatus.pending.value))),
            created_at=raw.get("created_at", datetime.now(UTC)),
            updated_at=raw.get("updated_at", datetime.now(UTC)),
            envelope=raw.get("envelope", {}),
            error=raw.get("error"),
        )

    def write_job_def(self, run_id: str, job_def: JobDef) -> None:
        self._job_defs[run_id] = job_def

    def read_job_def(self, run_id: str) -> JobDef:
        if run_id not in self._job_defs:
            raise FileNotFoundError(f"JobDef not found for run {run_id}")
        return self._job_defs[run_id]

    def write_job_instance(self, run_id: str, instance: JobInstance) -> None:
        self._job_instances[run_id] = instance

    def read_job_instance(self, run_id: str) -> JobInstance:
        if run_id not in self._job_instances:
            raise FileNotFoundError(f"JobInstance not found for run {run_id}")
        return self._job_instances[run_id]

    def write_step_manifest(self, run_id: str, step_n: int, manifest: StepManifest) -> None:
        key = (run_id, step_n)
        started_at = datetime.now(UTC)
        self._step_manifests[key] = manifest
        self._step_started_at[key] = started_at

        data = {
            "kind": "run_step",
            "artifact_id": _artifact_uuid("run_step", self._step_name(run_id, step_n)),
            "name": self._step_name(run_id, step_n),
            "run_id": run_id,
            "step_n": step_n,
            "step_id": manifest.step_id,
            "backend": manifest.backend.value,
            "started_at": _iso_utc(started_at),
            "payload": manifest.payload,
        }
        path = self._get_step_yaml_path(run_id, step_n)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_to_yaml(data), encoding="utf-8")

    def read_step_manifest(self, run_id: str, step_n: int) -> StepManifest:
        key = (run_id, step_n)
        if key not in self._step_manifests:
            raise FileNotFoundError(f"StepManifest not found for run={run_id} step={step_n}")
        return self._step_manifests[key]

    def write_step_capture(self, run_id: str, step_n: int, capture: StepCapture) -> None:
        self._step_captures[(run_id, step_n)] = capture

    def _resolve_patch_text(self, run_id: str, step_n: int, capture: StepCapture | None) -> str:
        if capture and capture.git and capture.git.patch_file:
            patch_path = Path(capture.git.patch_file)
            if patch_path.is_absolute():
                return _read_text(patch_path)
            if patch_path.parts and patch_path.parts[0] == "steps":
                return _read_text(self.get_run_path(run_id) / patch_path)
            step_dir = self.get_step_path(run_id, step_n)
            return _read_text(step_dir / patch_path)
        return _read_text(self.get_step_path(run_id, step_n) / "changes.patch")

    def write_step_outcome(self, run_id: str, step_n: int, outcome: StepOutcome) -> None:
        key = (run_id, step_n)
        step_path = self._get_step_yaml_path(run_id, step_n)
        existing_raw = (
            yaml.safe_load(step_path.read_text(encoding="utf-8"))
            if step_path.exists()
            else {}
        )
        if not isinstance(existing_raw, dict):
            existing_raw = {}

        capture = self._step_captures.get(key)
        started_at = self._step_started_at.get(key, datetime.now(UTC))
        ended_at = datetime.now(UTC)

        existing_raw.update(
            {
                "kind": "run_step",
                "artifact_id": _artifact_uuid("run_step", self._step_name(run_id, step_n)),
                "name": self._step_name(run_id, step_n),
                "run_id": run_id,
                "step_n": step_n,
                "step_id": outcome.step_id,
                "backend": existing_raw.get("backend", "unknown"),
                "started_at": existing_raw.get("started_at", _iso_utc(started_at)),
                "outcome": outcome.outcome.value,
                "duration_ms": outcome.duration_ms,
                "ended_at": _iso_utc(ended_at),
                "error": outcome.error,
                "capture": (
                    capture.model_dump(mode="json", exclude_none=True) if capture else None
                ),
                "stdout": _read_text(self.get_step_path(run_id, step_n) / "stdout.txt"),
                "stderr": _read_text(self.get_step_path(run_id, step_n) / "stderr.txt"),
                "patch": self._resolve_patch_text(run_id, step_n, capture),
            }
        )

        step_path.parent.mkdir(parents=True, exist_ok=True)
        step_path.write_text(_to_yaml(existing_raw), encoding="utf-8")

    def read_step_outcome(self, run_id: str, step_n: int) -> StepOutcome:
        step_yaml = self._get_step_yaml_path(run_id, step_n)
        raw = yaml.safe_load(step_yaml.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid step yaml at {step_yaml}")
        return StepOutcome(
            step_n=int(raw.get("step_n", step_n)),
            step_id=str(raw.get("step_id", "")),
            outcome=OutcomeStatus(str(raw.get("outcome", OutcomeStatus.failed.value))),
            duration_ms=int(raw.get("duration_ms", 0)),
            manifest_ref=f"steps/step-{step_n:03d}.yaml",
            capture_ref=f"steps/step-{step_n:03d}.yaml",
            error=raw.get("error"),
        )

    def read_step_capture(self, run_id: str, step_n: int) -> StepCapture:
        key = (run_id, step_n)
        if key not in self._step_captures:
            raise FileNotFoundError(f"StepCapture not found for run={run_id} step={step_n}")
        return self._step_captures[key]

    def write_attempt(self, run_id: str, attempt: AttemptRecord) -> None:
        attempts = self._attempts.setdefault(run_id, [])
        attempts = [a for a in attempts if a.attempt_n != attempt.attempt_n]
        attempts.append(attempt)
        self._attempts[run_id] = sorted(attempts, key=lambda a: a.attempt_n)

    def read_attempt(self, run_id: str, attempt_n: int) -> AttemptRecord:
        for attempt in self._attempts.get(run_id, []):
            if attempt.attempt_n == attempt_n:
                return attempt
        raise FileNotFoundError(f"Attempt {attempt_n} not found for run {run_id}")

    def list_runs(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(
            d.name
            for d in self.root.iterdir()
            if d.is_dir() and (d / "run.yaml").exists()
        )

    def list_attempts(self, run_id: str) -> list[int]:
        return sorted(a.attempt_n for a in self._attempts.get(run_id, []))

    def list_steps(self, run_id: str) -> list[int]:
        steps_dir = self.get_run_path(run_id) / "steps"
        if not steps_dir.exists():
            return []
        return sorted(
            int(path.stem.split("-")[1])
            for path in steps_dir.glob("step-*.yaml")
            if path.is_file()
        )

    def run_exists(self, run_id: str) -> bool:
        return (self.get_run_path(run_id) / "run.yaml").exists()

    def write_run_report(
        self,
        run_id: str,
        report_data: dict[str, Any],
        markdown_content: str,
    ) -> None:
        _ = markdown_content  # legacy-only artifact; not used in consolidated output
        run_id_for_name = report_data.get("run_id", run_id)
        final = {
            "kind": "run_report",
            "artifact_id": _artifact_uuid("run_report", f"{run_id_for_name}/report"),
            "name": f"{run_id_for_name}/report",
            "run_id": run_id_for_name,
            "generated_at": report_data.get("generated_at", _iso_utc(datetime.now(UTC))),
            "status": report_data.get("status", "unknown"),
            "job_id": report_data.get("job_id", ""),
            "summary": report_data.get("summary", ""),
            "assessment": report_data.get("assessment", ""),
            "issues": report_data.get("issues", []),
            "recommendation": report_data.get("recommendation", ""),
        }
        path = self.get_run_path(run_id) / "run_report.yaml"
        path.write_text(_to_yaml(final), encoding="utf-8")
