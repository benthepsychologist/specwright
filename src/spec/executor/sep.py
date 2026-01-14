"""
Step Execution Plan (SEP)

Schema and utilities for Step Execution Plans - the detailed plan
of what an agent will do before execution begins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


class SepError(Exception):
    """Base exception for SEP-related failures."""


class SepLoadError(SepError):
    """Raised when a SEP cannot be loaded (IO/YAML/structure)."""


class SepValidationError(SepError):
    """Raised when a loaded SEP fails schema validation."""


@dataclass
class FileChange:
    """Describes a planned file modification."""

    path: str  # relative path in repo
    action: str  # create, modify, delete
    description: str  # what will change
    estimated_lines: int | None = None  # rough estimate


@dataclass
class VerificationStep:
    """Describes a verification step to validate the changes."""

    command: str  # command to run
    expected_outcome: str  # what success looks like
    required: bool = True  # fail step if this fails


@dataclass
class SEPProvenance:
    """Provenance information for SEP generation.

    Records how the SEP was generated (deterministic vs LLM).
    """

    generator: str  # "deterministic" or "llm"
    model: str | None = None  # LLM model alias, only set when generator="llm"


@dataclass
class StepExecutionPlan:
    """
    Complete execution plan for a single step.

    This is created by the agent before implementation begins,
    allowing for review and validation of the planned approach.
    """

    # Identity
    aip_id: str
    step_id: str
    step_index: int
    created_at: str = ""

    # What the step will do
    objective: str = ""  # from AIP step prompt, summarized
    files_to_touch: list[FileChange] = field(default_factory=list)
    verification_steps: list[VerificationStep] = field(default_factory=list)

    # Scope
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)

    # Metadata
    estimated_complexity: str = "medium"  # low, medium, high
    requires_human_review: bool = False  # true if touching sensitive paths

    # Provenance
    provenance: SEPProvenance | None = None  # how the SEP was generated

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


def save_sep(sep: StepExecutionPlan, path: Path) -> None:
    """
    Save a StepExecutionPlan to a YAML file.

    Uses deterministic serialization (sorted keys where appropriate).
    """
    # Convert FileChange objects to dicts
    files_to_touch: list[dict[str, Any]] = []
    for fc in sep.files_to_touch:
        fc_dict: dict[str, Any] = {
            "path": fc.path,
            "action": fc.action,
            "description": fc.description,
        }
        if fc.estimated_lines is not None:
            fc_dict["estimated_lines"] = fc.estimated_lines
        files_to_touch.append(fc_dict)

    # Convert VerificationStep objects to dicts
    verification_steps: list[dict[str, Any]] = []
    for vs in sep.verification_steps:
        vs_dict: dict[str, Any] = {
            "command": vs.command,
            "expected_outcome": vs.expected_outcome,
        }
        if not vs.required:
            vs_dict["required"] = vs.required
        verification_steps.append(vs_dict)

    data: dict[str, Any] = {
        "aip_id": sep.aip_id,
        "step_id": sep.step_id,
        "step_index": sep.step_index,
        "created_at": sep.created_at,
        "objective": sep.objective,
        "files_to_touch": files_to_touch,
        "verification_steps": verification_steps,
        "allowed_paths": sorted(sep.allowed_paths),
        "forbidden_paths": sorted(sep.forbidden_paths),
        "estimated_complexity": sep.estimated_complexity,
        "requires_human_review": sep.requires_human_review,
    }

    # Add provenance if present
    if sep.provenance is not None:
        provenance_dict: dict[str, Any] = {"generator": sep.provenance.generator}
        if sep.provenance.model is not None:
            provenance_dict["model"] = sep.provenance.model
        data["provenance"] = provenance_dict

    yaml_content = _serialize_canonical_sep(data)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_content, encoding="utf-8")


def load_sep_from_aip(aip: dict, step_idx: int) -> StepExecutionPlan:
    """
    Load a StepExecutionPlan from an AIP step (AIP v2.0 embedded SEP).

    AIP v2.0 embeds SEP fields directly in each step:
    - objective
    - files_to_touch
    - verification_steps
    """
    aip_id = aip.get("aip_id", "unknown")
    plan = aip.get("plan", [])

    if step_idx < 0 or step_idx >= len(plan):
        raise SepLoadError(f"Step index {step_idx} out of range (0-{len(plan) - 1})")

    step = plan[step_idx]
    step_id = step.get("step_id", f"step-{step_idx + 1:03d}")

    # Convert files_to_touch dicts to FileChange objects
    files_to_touch: list[FileChange] = []
    for fc_dict in step.get("files_to_touch", []):
        if isinstance(fc_dict, dict):
            files_to_touch.append(
                FileChange(
                    path=fc_dict.get("path", ""),
                    action=fc_dict.get("action", "modify"),
                    description=fc_dict.get("description", ""),
                    estimated_lines=fc_dict.get("estimated_lines"),
                )
            )

    # Convert verification_steps dicts to VerificationStep objects
    verification_steps: list[VerificationStep] = []
    for vs_dict in step.get("verification_steps", []):
        if isinstance(vs_dict, dict):
            verification_steps.append(
                VerificationStep(
                    command=vs_dict.get("command", ""),
                    expected_outcome=vs_dict.get("expected_outcome", ""),
                    required=vs_dict.get("required", True),
                )
            )

    # Load provenance if present
    provenance: SEPProvenance | None = None
    provenance_data = step.get("provenance")
    if provenance_data is not None and isinstance(provenance_data, dict):
        provenance = SEPProvenance(
            generator=provenance_data.get("generator", "deterministic"),
            model=provenance_data.get("model"),
        )

    return StepExecutionPlan(
        aip_id=aip_id,
        step_id=step_id,
        step_index=step_idx + 1,  # 1-based for display
        created_at=datetime.now(UTC).isoformat(),
        objective=step.get("objective", step.get("description", "")),
        files_to_touch=files_to_touch,
        verification_steps=verification_steps,
        allowed_paths=step.get("allowed_paths", []),
        forbidden_paths=step.get("forbidden_paths", []),
        estimated_complexity=step.get("estimated_complexity", "medium"),
        requires_human_review=step.get("requires_human_review", False),
        provenance=provenance,
    )


def load_sep(path: Path) -> StepExecutionPlan:
    """
    Load a StepExecutionPlan from a YAML file.
    """

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SepLoadError(f"Failed to read SEP file: {path}: {e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise SepLoadError(f"Invalid YAML in SEP file: {path}: {e}") from e

    if data is None:
        raise SepLoadError(f"SEP file is empty: {path}")

    if not isinstance(data, dict):
        raise SepLoadError(
            f"SEP file must contain a YAML mapping at top-level, got {type(data).__name__}: {path}"
        )

    _validate_sep_mapping(data)

    # Convert dicts back to FileChange objects
    files_to_touch: list[FileChange] = []
    for fc_dict in data.get("files_to_touch", []):
        if not isinstance(fc_dict, dict):
            raise SepValidationError(
                "Invalid files_to_touch entry: expected mapping, "
                f"got {type(fc_dict).__name__}"
            )
        files_to_touch.append(
            FileChange(
                path=fc_dict["path"],
                action=fc_dict["action"],
                description=fc_dict["description"],
                estimated_lines=fc_dict.get("estimated_lines"),
            )
        )

    # Convert dicts back to VerificationStep objects
    verification_steps: list[VerificationStep] = []
    for vs_dict in data.get("verification_steps", []):
        if not isinstance(vs_dict, dict):
            raise SepValidationError(
                "Invalid verification_steps entry: expected mapping, "
                f"got {type(vs_dict).__name__}"
            )
        verification_steps.append(
            VerificationStep(
                command=vs_dict["command"],
                expected_outcome=vs_dict["expected_outcome"],
                required=vs_dict.get("required", True),
            )
        )

    created_at = data.get("created_at", "")
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()

    objective = data.get("objective", "")
    if objective is None:
        objective = ""

    # Load provenance if present
    provenance: SEPProvenance | None = None
    provenance_data = data.get("provenance")
    if provenance_data is not None and isinstance(provenance_data, dict):
        provenance = SEPProvenance(
            generator=provenance_data.get("generator", "deterministic"),
            model=provenance_data.get("model"),
        )

    return StepExecutionPlan(
        aip_id=data["aip_id"],
        step_id=data["step_id"],
        step_index=data["step_index"],
        created_at=created_at,
        objective=objective,
        files_to_touch=files_to_touch,
        verification_steps=verification_steps,
        allowed_paths=data.get("allowed_paths", []),
        forbidden_paths=data.get("forbidden_paths", []),
        estimated_complexity=data.get("estimated_complexity", "medium"),
        requires_human_review=data.get("requires_human_review", False),
        provenance=provenance,
    )


def _serialize_canonical_sep(data: dict[str, Any]) -> str:
    """Serialize SEP data to YAML deterministically and safely.

    - Disables anchors/aliases
    - Uses block style YAML
    - Preserves our explicit key order (sort_keys=False)
    - Strips trailing whitespace and ensures a trailing newline
    """

    class CanonicalDumper(yaml.SafeDumper):
        def ignore_aliases(self, _data: Any) -> bool:  # noqa: ANN401
            return True

    def represent_none(self, _value: None):
        return self.represent_scalar("tag:yaml.org,2002:null", "null")

    CanonicalDumper.add_representer(type(None), represent_none)

    yaml_str = yaml.dump(
        data,
        Dumper=CanonicalDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )

    lines = [line.rstrip() for line in yaml_str.split("\n")]
    return "\n".join(lines).rstrip("\n") + "\n"


def _validate_sep_mapping(data: dict[str, Any]) -> None:
    required_keys = ["aip_id", "step_id", "step_index"]
    for key in required_keys:
        if key not in data:
            raise SepValidationError(f"Missing required key: {key}")

    _require_str(data, "aip_id")
    _require_str(data, "step_id")
    _require_int(data, "step_index")

    if data.get("step_index") < 1:
        raise SepValidationError("Invalid step_index: expected 1-based step number (>= 1)")

    _optional_str_or_datetime(data, "created_at")
    _optional_str_or_none(data, "objective")
    _optional_str_or_none(data, "estimated_complexity")
    _optional_bool(data, "requires_human_review")

    _optional_list_of_str(data, "allowed_paths")
    _optional_list_of_str(data, "forbidden_paths")

    _optional_list_of_mappings(data, "files_to_touch")
    for idx, item in enumerate(data.get("files_to_touch", []) or []):
        _require_str(item, "path", prefix=f"files_to_touch[{idx}].")
        _require_str(item, "action", prefix=f"files_to_touch[{idx}].")
        _require_str(item, "description", prefix=f"files_to_touch[{idx}].")
        _optional_int_or_none(item, "estimated_lines", prefix=f"files_to_touch[{idx}].")

    _optional_list_of_mappings(data, "verification_steps")
    for idx, item in enumerate(data.get("verification_steps", []) or []):
        _require_str(item, "command", prefix=f"verification_steps[{idx}].")
        _require_str(item, "expected_outcome", prefix=f"verification_steps[{idx}].")
        _optional_bool(item, "required", prefix=f"verification_steps[{idx}].")


def _require_str(data: dict[str, Any], key: str, *, prefix: str = "") -> None:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SepValidationError(
            f"Invalid {prefix}{key}: expected non-empty string, got {type(value).__name__}"
        )


def _require_int(data: dict[str, Any], key: str, *, prefix: str = "") -> None:
    value = data.get(key)
    if not isinstance(value, int):
        raise SepValidationError(
            f"Invalid {prefix}{key}: expected int, got {type(value).__name__}"
        )


def _optional_bool(data: dict[str, Any], key: str, *, prefix: str = "") -> None:
    if key not in data:
        return
    value = data.get(key)
    if not isinstance(value, bool):
        raise SepValidationError(
            f"Invalid {prefix}{key}: expected bool, got {type(value).__name__}"
        )


def _optional_int_or_none(data: dict[str, Any], key: str, *, prefix: str = "") -> None:
    if key not in data:
        return
    value = data.get(key)
    if value is None:
        return
    if not isinstance(value, int):
        raise SepValidationError(
            f"Invalid {prefix}{key}: expected int|null, got {type(value).__name__}"
        )


def _optional_str_or_none(data: dict[str, Any], key: str) -> None:
    if key not in data:
        return
    value = data.get(key)
    if value is None:
        return
    if not isinstance(value, str):
        raise SepValidationError(
            f"Invalid {key}: expected string|null, got {type(value).__name__}"
        )


def _optional_str_or_datetime(data: dict[str, Any], key: str) -> None:
    if key not in data:
        return
    value = data.get(key)
    if value is None:
        return
    if not isinstance(value, (str, datetime)):
        raise SepValidationError(
            f"Invalid {key}: expected string|datetime|null, got {type(value).__name__}"
        )


def _optional_list_of_str(data: dict[str, Any], key: str) -> None:
    if key not in data:
        return
    value = data.get(key)
    if value is None:
        return
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SepValidationError(
            f"Invalid {key}: expected list[str], got {type(value).__name__}"
        )


def _optional_list_of_mappings(data: dict[str, Any], key: str) -> None:
    if key not in data:
        return
    value = data.get(key)
    if value is None:
        return
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SepValidationError(
            f"Invalid {key}: expected list[mapping], got {type(value).__name__}"
        )
