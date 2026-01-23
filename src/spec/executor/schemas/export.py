"""
JSON Schema export for executor schemas.
"""

import json
from pathlib import Path

from spec.executor.schemas.attempt import AttemptRecord
from spec.executor.schemas.capture import StepCapture
from spec.executor.schemas.job_def import JobDef
from spec.executor.schemas.job_instance import JobInstance
from spec.executor.schemas.manifest import StepManifest
from spec.executor.schemas.outcome import StepOutcome
from spec.executor.schemas.run import RunRecord

SCHEMAS = {
    "run-record": RunRecord,
    "job-def": JobDef,
    "job-instance": JobInstance,
    "step-manifest": StepManifest,
    "step-outcome": StepOutcome,
    "step-capture": StepCapture,
    "attempt-record": AttemptRecord,
}


def export_schema(model_class: type, output_path: Path) -> None:
    """Export a Pydantic model's JSON schema to a file."""
    schema = model_class.model_json_schema()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2) + "\n")


def export_all_schemas(output_dir: Path) -> None:
    """Export all executor schemas to the given directory."""
    for name, model_class in SCHEMAS.items():
        output_path = output_dir / f"{name}.schema.json"
        export_schema(model_class, output_path)


if __name__ == "__main__":
    # Default export location
    output_dir = Path(__file__).parents[4] / "config/schemas/executor"
    export_all_schemas(output_dir)
    print(f"Exported {len(SCHEMAS)} schemas to {output_dir}")
