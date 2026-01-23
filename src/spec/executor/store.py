"""
Run store: persistence layer for run artifacts.

Layout:
    ~/.local/local-governor/runs/{run_id}/
    ├── run.yaml              # RunRecord
    ├── job_def.yaml          # JobDef (template input)
    ├── job_instance.yaml     # JobInstance (materialized)
    ├── attempts/
    │   └── attempt-001.yaml  # AttemptRecord
    └── steps/
        └── step-001/
            ├── manifest.yaml # StepManifest
            ├── outcome.yaml  # StepOutcome
            └── capture.yaml  # StepCapture (+ artifact files)
"""

from pathlib import Path

import yaml
from pydantic import BaseModel

from spec.executor.schemas.attempt import AttemptRecord
from spec.executor.schemas.capture import StepCapture
from spec.executor.schemas.job_def import JobDef
from spec.executor.schemas.job_instance import JobInstance
from spec.executor.schemas.manifest import StepManifest
from spec.executor.schemas.outcome import StepOutcome
from spec.executor.schemas.run import RunRecord

DEFAULT_ROOT = Path.home() / ".local/local-governor/runs"


def _serialize_model(model: BaseModel) -> str:
    """Serialize a Pydantic model to YAML."""
    data = model.model_dump(mode="json")
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _deserialize_model[T: BaseModel](yaml_str: str, model_class: type[T]) -> T:
    """Deserialize YAML to a Pydantic model."""
    data = yaml.safe_load(yaml_str)
    return model_class.model_validate(data)


class RunStore:
    """
    Persistence layer for run artifacts.

    Provides read/write access to all run-related artifacts.
    """

    def __init__(self, root: Path | None = None) -> None:
        """
        Initialize the run store.

        Args:
            root: Root directory for run storage. Defaults to ~/.local/local-governor/runs
        """
        self.root = root or DEFAULT_ROOT

    def create_run(self, run_id: str) -> Path:
        """
        Create the directory structure for a new run.

        Args:
            run_id: Unique identifier for the run

        Returns:
            Path to the run directory
        """
        run_path = self.get_run_path(run_id)
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / "attempts").mkdir(exist_ok=True)
        (run_path / "steps").mkdir(exist_ok=True)
        return run_path

    def get_run_path(self, run_id: str) -> Path:
        """Get the path to a run directory."""
        return self.root / run_id

    def get_step_path(self, run_id: str, step_n: int) -> Path:
        """Get the path to a step directory."""
        return self.get_run_path(run_id) / "steps" / f"step-{step_n:03d}"

    def get_attempt_path(self, run_id: str, attempt_n: int) -> Path:
        """Get the path to an attempt file."""
        return self.get_run_path(run_id) / "attempts" / f"attempt-{attempt_n:03d}.yaml"

    # --- RunRecord ---

    def write_run_record(self, run_id: str, record: RunRecord) -> None:
        """Write run.yaml."""
        path = self.get_run_path(run_id) / "run.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialize_model(record))

    def read_run_record(self, run_id: str) -> RunRecord:
        """Read run.yaml."""
        path = self.get_run_path(run_id) / "run.yaml"
        return _deserialize_model(path.read_text(), RunRecord)

    # --- JobDef ---

    def write_job_def(self, run_id: str, job_def: JobDef) -> None:
        """Write job_def.yaml."""
        path = self.get_run_path(run_id) / "job_def.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialize_model(job_def))

    def read_job_def(self, run_id: str) -> JobDef:
        """Read job_def.yaml."""
        path = self.get_run_path(run_id) / "job_def.yaml"
        return _deserialize_model(path.read_text(), JobDef)

    # --- JobInstance ---

    def write_job_instance(self, run_id: str, instance: JobInstance) -> None:
        """Write job_instance.yaml."""
        path = self.get_run_path(run_id) / "job_instance.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialize_model(instance))

    def read_job_instance(self, run_id: str) -> JobInstance:
        """Read job_instance.yaml."""
        path = self.get_run_path(run_id) / "job_instance.yaml"
        return _deserialize_model(path.read_text(), JobInstance)

    # --- StepManifest ---

    def write_step_manifest(self, run_id: str, step_n: int, manifest: StepManifest) -> None:
        """Write steps/step-{n}/manifest.yaml."""
        step_path = self.get_step_path(run_id, step_n)
        step_path.mkdir(parents=True, exist_ok=True)
        path = step_path / "manifest.yaml"
        path.write_text(_serialize_model(manifest))

    def read_step_manifest(self, run_id: str, step_n: int) -> StepManifest:
        """Read steps/step-{n}/manifest.yaml."""
        path = self.get_step_path(run_id, step_n) / "manifest.yaml"
        return _deserialize_model(path.read_text(), StepManifest)

    # --- StepOutcome ---

    def write_step_outcome(self, run_id: str, step_n: int, outcome: StepOutcome) -> None:
        """Write steps/step-{n}/outcome.yaml."""
        step_path = self.get_step_path(run_id, step_n)
        step_path.mkdir(parents=True, exist_ok=True)
        path = step_path / "outcome.yaml"
        path.write_text(_serialize_model(outcome))

    def read_step_outcome(self, run_id: str, step_n: int) -> StepOutcome:
        """Read steps/step-{n}/outcome.yaml."""
        path = self.get_step_path(run_id, step_n) / "outcome.yaml"
        return _deserialize_model(path.read_text(), StepOutcome)

    # --- StepCapture ---

    def write_step_capture(self, run_id: str, step_n: int, capture: StepCapture) -> None:
        """Write steps/step-{n}/capture.yaml."""
        step_path = self.get_step_path(run_id, step_n)
        step_path.mkdir(parents=True, exist_ok=True)
        path = step_path / "capture.yaml"
        path.write_text(_serialize_model(capture))

    def read_step_capture(self, run_id: str, step_n: int) -> StepCapture:
        """Read steps/step-{n}/capture.yaml."""
        path = self.get_step_path(run_id, step_n) / "capture.yaml"
        return _deserialize_model(path.read_text(), StepCapture)

    # --- AttemptRecord ---

    def write_attempt(self, run_id: str, attempt: AttemptRecord) -> None:
        """Write attempts/attempt-{n}.yaml."""
        path = self.get_attempt_path(run_id, attempt.attempt_n)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialize_model(attempt))

    def read_attempt(self, run_id: str, attempt_n: int) -> AttemptRecord:
        """Read attempts/attempt-{n}.yaml."""
        path = self.get_attempt_path(run_id, attempt_n)
        return _deserialize_model(path.read_text(), AttemptRecord)

    # --- Listing ---

    def list_runs(self) -> list[str]:
        """List all run_ids."""
        if not self.root.exists():
            return []
        return sorted(
            d.name for d in self.root.iterdir() if d.is_dir() and (d / "run.yaml").exists()
        )

    def list_attempts(self, run_id: str) -> list[int]:
        """List all attempt numbers for a run."""
        attempts_dir = self.get_run_path(run_id) / "attempts"
        if not attempts_dir.exists():
            return []
        return sorted(
            int(f.stem.split("-")[1])
            for f in attempts_dir.glob("attempt-*.yaml")
        )

    def list_steps(self, run_id: str) -> list[int]:
        """List all step numbers for a run."""
        steps_dir = self.get_run_path(run_id) / "steps"
        if not steps_dir.exists():
            return []
        return sorted(
            int(d.name.split("-")[1])
            for d in steps_dir.iterdir()
            if d.is_dir() and d.name.startswith("step-")
        )

    def run_exists(self, run_id: str) -> bool:
        """Check if a run exists."""
        return (self.get_run_path(run_id) / "run.yaml").exists()
