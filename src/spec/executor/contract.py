"""
Step Contract Builder for autonomous step execution.

Builds StepContract from AIP/spec data, deriving allowed_paths and forbidden_paths
according to the v1 priority rules:

1. If step explicitly declares allowed_paths: use it (plus policy forbiddens merged)
2. Else if step declares outputs: derive from output directories AND add safe defaults
3. Else if spec has repo.paths: use them + safe defaults
4. Else: use safe defaults (src/**, tests/**, docs/**)

Raises EscalationRequired only if allowed_paths resolves to empty after all rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from spec.executor.schemas.contract import CodexConfig, StepContract


class EscalationRequired(Exception):
    """Raised when contract cannot be built without human intervention."""

    def __init__(self, reason: str, *, step_id: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.step_id = step_id


class ContractBuildError(Exception):
    """Raised when contract building fails due to invalid input."""

    def __init__(self, message: str, *, step_id: str | None = None):
        super().__init__(message)
        self.step_id = step_id


# Safe default paths that are always allowed unless explicitly forbidden
SAFE_DEFAULTS = ["src/**", "tests/**"]

# Extended safe defaults when no explicit paths specified
EXTENDED_DEFAULTS = ["src/**", "tests/**", "docs/**"]


def build_contract(
    aip: dict[str, Any],
    step_idx: int,
    *,
    autogov_policy: dict[str, Any] | None = None,
    repo_root: Path | None = None,
) -> StepContract:
    """
    Build a StepContract from AIP data and step index.

    Args:
        aip: The AIP (Agentic Implementation Plan) dict, parsed from YAML/JSON
        step_idx: 0-based index of the step in the plan
        autogov_policy: Optional autogov policy dict with path-level constraints
        repo_root: Repository root path (required)

    Returns:
        StepContract configured for the step

    Raises:
        ContractBuildError: If AIP structure is invalid
        EscalationRequired: If allowed_paths cannot be derived (empty after all rules)
    """
    if repo_root is None:
        raise ContractBuildError("repo_root is required")

    # Extract AIP identity
    aip_id = aip.get("aip_id") or aip.get("id") or "unknown"

    # Get the plan/steps section
    plan = aip.get("plan", aip.get("steps", []))
    if isinstance(plan, dict):
        # Plan might be nested under a key
        plan = plan.get("steps", [])

    if not isinstance(plan, list):
        raise ContractBuildError(f"AIP plan must be a list, got {type(plan).__name__}")

    if step_idx < 0 or step_idx >= len(plan):
        raise ContractBuildError(
            f"step_idx {step_idx} out of range (plan has {len(plan)} steps)"
        )

    step = plan[step_idx]
    if not isinstance(step, dict):
        raise ContractBuildError(f"Step must be a dict, got {type(step).__name__}")

    step_id = step.get("step_id") or step.get("id") or f"step-{step_idx + 1:03d}"

    # Derive allowed_paths using priority rules
    allowed_paths = _derive_allowed_paths(step, aip)

    # Derive forbidden_paths from spec + autogov
    forbidden_paths = _derive_forbidden_paths(step, aip, autogov_policy)

    # Validate: allowed_paths must not be empty
    if not allowed_paths:
        raise EscalationRequired(
            "Cannot derive allowed_paths: no explicit paths, outputs, or repo.paths defined",
            step_id=step_id,
        )

    # Extract allowed operations
    allowed_ops = _derive_allowed_ops(step, aip)

    # Extract iteration limit
    max_iterations = step.get("max_iterations", aip.get("max_iterations", 3))
    max_iterations = max(1, min(10, max_iterations))  # Clamp to valid range

    # Build Codex config
    codex_config = _build_codex_config(step, aip)

    return StepContract(
        step_id=step_id,
        aip_id=aip_id,
        repo_root=repo_root,
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
        allowed_ops=allowed_ops,
        max_iterations=max_iterations,
        codex=codex_config,
    )


def _derive_allowed_paths(step: dict[str, Any], aip: dict[str, Any]) -> list[str]:
    """
    Derive allowed_paths using v1 priority rules.

    Priority:
    1. Step explicit allowed_paths
    2. Step outputs -> derive directories + safe defaults
    3. Spec repo.paths + safe defaults
    4. Extended safe defaults (src/**, tests/**, docs/**)
    """
    # Rule 1: Explicit step declaration
    if "allowed_paths" in step:
        paths = step["allowed_paths"]
        if isinstance(paths, list) and paths:
            return list(paths)

    # Rule 2: Derive from step outputs
    outputs = step.get("outputs", [])
    if outputs:
        derived = set(SAFE_DEFAULTS)
        for output in outputs:
            if isinstance(output, str):
                # Extract parent directory pattern
                parent = _path_to_glob_pattern(output)
                if parent:
                    derived.add(parent)
            elif isinstance(output, dict) and "path" in output:
                parent = _path_to_glob_pattern(output["path"])
                if parent:
                    derived.add(parent)
        if derived:
            return sorted(derived)

    # Rule 3: Spec-level repo.paths
    repo_config = aip.get("repo", {})
    if isinstance(repo_config, dict):
        repo_paths = repo_config.get("paths", [])
        if isinstance(repo_paths, list) and repo_paths:
            combined = set(SAFE_DEFAULTS)
            combined.update(repo_paths)
            return sorted(combined)

    # Rule 4: Fallback to extended safe defaults
    return list(EXTENDED_DEFAULTS)


def _path_to_glob_pattern(path: str) -> str | None:
    """Convert a file path to a glob pattern for its parent directory."""
    if not path:
        return None

    # Handle already-glob patterns
    if "**" in path or "*" in path:
        return path

    # Get parent directory
    p = Path(path)
    parts = p.parts

    if len(parts) == 0:
        return None
    elif len(parts) == 1:
        # Root-level file: allow files in root
        return "*"
    else:
        # Has parent: create pattern for parent/**
        parent = parts[0]
        return f"{parent}/**"


def _derive_forbidden_paths(
    step: dict[str, Any],
    aip: dict[str, Any],
    autogov_policy: dict[str, Any] | None,
) -> list[str]:
    """
    Derive forbidden_paths from spec and autogov policy.

    Sources merged:
    1. Step-level forbidden_paths
    2. Spec-level forbidden_paths
    3. Autogov policy forbidden_paths
    """
    forbidden = set()

    # Step-level
    step_forbidden = step.get("forbidden_paths", [])
    if isinstance(step_forbidden, list):
        forbidden.update(step_forbidden)

    # Spec-level (in frontmatter or repo section)
    spec_forbidden = aip.get("forbidden_paths", [])
    if isinstance(spec_forbidden, list):
        forbidden.update(spec_forbidden)

    repo_config = aip.get("repo", {})
    if isinstance(repo_config, dict):
        repo_forbidden = repo_config.get("forbidden_paths", [])
        if isinstance(repo_forbidden, list):
            forbidden.update(repo_forbidden)

    # Autogov policy
    if autogov_policy:
        policy_forbidden = autogov_policy.get("forbidden_paths", [])
        if isinstance(policy_forbidden, list):
            forbidden.update(policy_forbidden)

        # Also check path_constraints
        path_constraints = autogov_policy.get("path_constraints", {})
        if isinstance(path_constraints, dict):
            for constraint in path_constraints.get("forbidden", []):
                if isinstance(constraint, str):
                    forbidden.add(constraint)
                elif isinstance(constraint, dict) and "pattern" in constraint:
                    forbidden.add(constraint["pattern"])

    return sorted(forbidden)


def _derive_allowed_ops(step: dict[str, Any], aip: dict[str, Any]) -> list[str]:
    """Derive allowed operations from step and spec."""
    # Step-level override
    if "allowed_ops" in step:
        ops = step["allowed_ops"]
        if isinstance(ops, list) and ops:
            return list(ops)

    # Spec-level
    if "allowed_ops" in aip:
        ops = aip["allowed_ops"]
        if isinstance(ops, list) and ops:
            return list(ops)

    # Default operations
    return ["read", "write", "test"]


def _build_codex_config(step: dict[str, Any], aip: dict[str, Any]) -> CodexConfig:
    """Build CodexConfig from step and spec settings."""
    # Check for codex section in step or spec
    codex_step = step.get("codex", {})
    codex_spec = aip.get("codex", {})

    # Merge with step taking precedence
    codex_merged = {**codex_spec, **codex_step}

    return CodexConfig(
        sandbox=codex_merged.get("sandbox", "read-only"),
        emit_json_events=codex_merged.get("emit_json_events", True),
        output_schema=codex_merged.get("output_schema"),
    )


def save_contract(contract: StepContract, path: Path) -> None:
    """
    Save a StepContract to a YAML file.

    Args:
        contract: The contract to save
        path: Path to write to (should end in .yaml)
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict with JSON-serializable types
    data = contract.model_dump(mode="json")

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_contract(path: Path) -> StepContract:
    """
    Load a StepContract from a YAML file.

    Args:
        path: Path to the contract file

    Returns:
        Parsed StepContract

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is invalid
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    return StepContract.model_validate(data)


def save_contract_json(contract: StepContract, path: Path) -> None:
    """Save a StepContract to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = contract.model_dump(mode="json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_contract_json(path: Path) -> StepContract:
    """Load a StepContract from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    return StepContract.model_validate(data)
