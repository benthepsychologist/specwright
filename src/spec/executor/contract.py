"""
Step Contract Builder

Builds machine-readable contracts for autonomous step execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Safe defaults - always included unless explicitly overridden
SAFE_ALLOWED_DEFAULTS = ["src/**", "tests/**"]

# Forbidden defaults - always included
FORBIDDEN_DEFAULTS = [".git/**", "*.lock", ".env*", "secrets/**"]

# Codex allowed commands
CODEX_ALLOWED_COMMANDS = [
    "cat",
    "ls",
    "find",
    "grep",
    "head",
    "tail",
    "wc",
    "diff",
    "echo",
    "python",
    "pytest",
    "ruff",
    "mypy",
]

# Codex forbidden commands
CODEX_FORBIDDEN_COMMANDS = [
    "rm -rf",
    "sudo",
    "chmod 777",
    "curl",
    "wget",
    "ssh",
    "scp",
    "git push",
    "git commit",
]


class EscalationRequired(Exception):
    """Raised when human intervention is required.

    Used in contract building when allowed_paths resolves to empty.
    For adapter-related escalations (e.g., command violations), use
    spec.executor.adapters.EscalationRequired which inherits from AdapterError.
    """

    def __init__(self, reason: str, violations: list[str] | None = None):
        self.reason = reason
        self.violations = violations or []
        super().__init__(reason)


@dataclass
class CodexConfig:
    """Configuration for the Codex agent adapter."""

    sandbox_mode: str = "read-only"
    output_schema_path: str = ""
    allowed_commands: list[str] = field(default_factory=lambda: CODEX_ALLOWED_COMMANDS.copy())
    forbidden_commands: list[str] = field(default_factory=lambda: CODEX_FORBIDDEN_COMMANDS.copy())


@dataclass
class StepContract:
    """
    Machine-readable contract for a single step execution.

    This contract defines all constraints and configuration needed
    for autonomous execution of an AIP step.
    """

    # Identity
    aip_id: str
    step_id: str
    step_index: int

    # Scope constraints
    allowed_paths: list[str]
    forbidden_paths: list[str]

    # Verification
    verification_commands: list[str] = field(
        default_factory=lambda: ["ruff check .", "mypy .", "pytest"]
    )
    verification_timeout: int = 300

    # Codex configuration
    codex_config: CodexConfig = field(default_factory=CodexConfig)

    # Retry configuration
    max_iterations: int = 3

    # Metadata
    created_at: str = ""
    baseline_commit: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


def _derive_paths_from_outputs(outputs: list[str]) -> list[str]:
    """
    Derive allowed path patterns from step output files.

    For each output file, extract the top-level directory and create a glob pattern.
    """
    dirs = set()
    for output in outputs:
        parts = output.split("/")
        if len(parts) > 1:
            # Use top-level directory as glob pattern
            dirs.add(f"{parts[0]}/**")
        else:
            # Root-level file - allow the specific file
            dirs.add(output)
    return sorted(dirs)


def _merge_with_safe_defaults(paths: list[str]) -> list[str]:
    """Merge given paths with safe defaults, avoiding duplicates."""
    result = list(paths)
    for default in SAFE_ALLOWED_DEFAULTS:
        if default not in result:
            result.append(default)
    return sorted(result)


def build_contract(
    aip: dict[str, Any],
    step_idx: int,
    autogov_policy: dict[str, Any] | None = None,
) -> StepContract:
    """
    Build a StepContract from an AIP definition and step index.

    Args:
        aip: Parsed AIP dictionary
        step_idx: Zero-based index of the step in the plan
        autogov_policy: Optional autogov policy for forbidden paths

    Returns:
        StepContract with all constraints resolved

    Raises:
        EscalationRequired: If allowed_paths resolves to empty after all rules
        IndexError: If step_idx is out of range
    """
    plan = aip.get("plan", [])
    if step_idx < 0 or step_idx >= len(plan):
        raise IndexError(f"Step index {step_idx} out of range (plan has {len(plan)} steps)")

    step = plan[step_idx]
    aip_id = aip.get("aip_id", "unknown")
    step_id = step.get("step_id", f"step-{step_idx:03d}")

    # === Derive allowed_paths using priority rules ===

    # Priority 1: Explicit step declaration
    if "allowed_paths" in step and step["allowed_paths"]:
        allowed_paths = step["allowed_paths"]

    # Priority 2: Step outputs + safe defaults
    elif "outputs" in step and step["outputs"]:
        derived = _derive_paths_from_outputs(step["outputs"])
        allowed_paths = _merge_with_safe_defaults(derived)

    # Priority 3: Spec repo.paths + safe defaults
    elif "repo" in aip and "paths" in aip["repo"] and aip["repo"]["paths"]:
        allowed_paths = _merge_with_safe_defaults(aip["repo"]["paths"])

    # Priority 4: Fallback to safe defaults
    else:
        allowed_paths = SAFE_ALLOWED_DEFAULTS.copy()

    # === Derive forbidden_paths ===

    forbidden_paths = FORBIDDEN_DEFAULTS.copy()

    # Add spec-level forbidden paths
    if "context" in aip and "constraints" in aip["context"]:
        for constraint in aip["context"]["constraints"]:
            if isinstance(constraint, str) and constraint.startswith("No changes to "):
                # Parse constraints like "No changes to src/spec/compiler/"
                path = constraint.replace("No changes to ", "").strip()
                if not path.endswith("**"):
                    path = f"{path.rstrip('/')}/**"
                if path not in forbidden_paths:
                    forbidden_paths.append(path)

    # Add autogov policy forbidden paths
    if autogov_policy:
        protected = autogov_policy.get("protected_paths", [])
        for path in protected:
            if path not in forbidden_paths:
                forbidden_paths.append(path)

    # === Validate: escalate if allowed_paths is empty ===

    if not allowed_paths:
        raise EscalationRequired(
            "allowed_paths resolved to empty after all derivation rules. "
            "Human must explicitly define allowed paths for this step."
        )

    # === Build verification commands ===

    verification_commands = step.get("verification_commands", ["ruff check .", "mypy .", "pytest"])

    # === Build codex config ===

    codex_config = CodexConfig(
        sandbox_mode="read-only",
        output_schema_path="artifacts/schemas/codex_output.schema.json",
    )

    return StepContract(
        aip_id=aip_id,
        step_id=step_id,
        step_index=step_idx,
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
        verification_commands=verification_commands,
        codex_config=codex_config,
        max_iterations=aip.get("max_iterations", 3),
    )


def save_contract(contract: StepContract, path: Path) -> None:
    """
    Save a StepContract to a YAML file.

    Uses deterministic serialization (sorted keys).
    """
    data = {
        "aip_id": contract.aip_id,
        "step_id": contract.step_id,
        "step_index": contract.step_index,
        "allowed_paths": sorted(contract.allowed_paths),
        "forbidden_paths": sorted(contract.forbidden_paths),
        "verification_commands": contract.verification_commands,
        "verification_timeout": contract.verification_timeout,
        "codex_config": {
            "sandbox_mode": contract.codex_config.sandbox_mode,
            "output_schema_path": contract.codex_config.output_schema_path,
            "allowed_commands": sorted(contract.codex_config.allowed_commands),
            "forbidden_commands": sorted(contract.codex_config.forbidden_commands),
        },
        "max_iterations": contract.max_iterations,
        "created_at": contract.created_at,
        "baseline_commit": contract.baseline_commit,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=True)


def load_contract(path: Path) -> StepContract:
    """Load a StepContract from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    codex_config = CodexConfig(
        sandbox_mode=data.get("codex_config", {}).get("sandbox_mode", "read-only"),
        output_schema_path=data.get("codex_config", {}).get("output_schema_path", ""),
        allowed_commands=data.get("codex_config", {}).get(
            "allowed_commands", CODEX_ALLOWED_COMMANDS.copy()
        ),
        forbidden_commands=data.get("codex_config", {}).get(
            "forbidden_commands", CODEX_FORBIDDEN_COMMANDS.copy()
        ),
    )

    return StepContract(
        aip_id=data["aip_id"],
        step_id=data["step_id"],
        step_index=data["step_index"],
        allowed_paths=data["allowed_paths"],
        forbidden_paths=data["forbidden_paths"],
        verification_commands=data.get(
            "verification_commands", ["ruff check .", "mypy .", "pytest"]
        ),
        verification_timeout=data.get("verification_timeout", 300),
        codex_config=codex_config,
        max_iterations=data.get("max_iterations", 3),
        created_at=data.get("created_at", ""),
        baseline_commit=data.get("baseline_commit", ""),
    )
