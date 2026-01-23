"""AIP v3 Compiler - compile epic specs into AIP context packets.

This module provides the compiler that reads a spec entry from an epic
and produces an AIP v3 skeleton. This replaces the old spec.md → AIP flow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from spec.aip.models import (
    AIPExecution,
    AIPMetadata,
    AIPv3,
    AIPWorkspace,
    WorkspaceMode,
)
from spec.autogov.exceptions import SpecwrightError
from spec.epic.loader import get_governor_root, load_epic

if TYPE_CHECKING:
    from spec.epic.schema import Epic, SpecRef


class CompileError(SpecwrightError):
    """Error during AIP compilation."""

    exit_code = 3


class SpecNotFoundError(SpecwrightError):
    """Spec not found in epic."""

    exit_code = 2


def compile_from_epic(epic_id: str, spec_id: str) -> AIPv3:
    """Compile an AIP v3 context packet from an epic spec.

    Args:
        epic_id: The epic identifier
        spec_id: The spec identifier within the epic

    Returns:
        Compiled AIPv3 instance

    Raises:
        SpecNotFoundError: If the spec is not found in the epic
        CompileError: If compilation fails
    """
    # Load the epic
    epic = load_epic(epic_id)

    # Find the spec
    spec_ref = epic.get_spec(spec_id)
    if spec_ref is None:
        available = [s.id for s in epic.specs]
        raise SpecNotFoundError(
            f"Spec '{spec_id}' not found in epic '{epic_id}'. "
            f"Available specs: {', '.join(available) or '(none)'}"
        )

    # Resolve target repo
    target = epic.get_target(spec_ref.repo)
    if target is None:
        raise CompileError(
            f"Target '{spec_ref.repo}' referenced by spec '{spec_id}' not found in epic"
        )

    # Build the AIP
    return _build_aip(epic, spec_ref, target.repo_path)


def _build_aip(epic: Epic, spec_ref: SpecRef, repo_path: str) -> AIPv3:
    """Build an AIPv3 from epic and spec data.

    Args:
        epic: The parent epic
        spec_ref: The spec reference
        repo_path: Path to the target repository

    Returns:
        Built AIPv3 instance
    """
    now = datetime.now(UTC).isoformat()

    # Build metadata
    metadata = AIPMetadata(
        epic_id=epic.id,
        spec_id=spec_ref.id,
        owner=epic.owner,
        created=now,
    )

    # Build workspace
    workspace = AIPWorkspace(
        mode=WorkspaceMode.SINGLE_REPO,
        repo_path=repo_path,
        branch=spec_ref.branch,
        base_branch=_get_base_branch(epic, spec_ref),
    )

    # Build goal from epic intent and spec expectations
    goal = _build_goal(epic, spec_ref)

    # Build AIP
    return AIPv3(
        version="3.0",
        kind="context-packet",
        metadata=metadata,
        workspace=workspace,
        goal=goal,
        expectations=list(spec_ref.expectations),
        constraints=list(spec_ref.constraints),
        checks=list(spec_ref.checks),
        execution=AIPExecution(),
    )


def _get_base_branch(epic: Epic, spec_ref: SpecRef) -> str:
    """Get the base branch for a spec.

    Args:
        epic: The parent epic
        spec_ref: The spec reference

    Returns:
        Base branch name
    """
    target = epic.get_target(spec_ref.repo)
    if target:
        return target.default_branch
    return "main"


def _build_goal(epic: Epic, spec_ref: SpecRef) -> str:
    """Build goal text from epic and spec.

    Args:
        epic: The parent epic
        spec_ref: The spec reference

    Returns:
        Goal text
    """
    # Use epic intent goal if available
    if epic.intent and epic.intent.goal:
        return epic.intent.goal

    # Fall back to spec id-based description
    return f"Implement {spec_ref.id}"


def get_aip_storage_path(epic_id: str, spec_id: str) -> Path:
    """Get the storage path for a compiled AIP.

    Args:
        epic_id: The epic identifier
        spec_id: The spec identifier

    Returns:
        Path where the AIP should be stored
    """
    governor_root = get_governor_root()
    return governor_root / "projects" / "specwright" / "aips" / epic_id / spec_id / "aip.yaml"


def save_compiled_aip(aip: AIPv3, epic_id: str, spec_id: str) -> Path:
    """Save a compiled AIP to the standard location.

    Args:
        aip: The compiled AIP
        epic_id: The epic identifier
        spec_id: The spec identifier

    Returns:
        Path where the AIP was saved
    """
    path = get_aip_storage_path(epic_id, spec_id)
    aip.save(path)
    return path


def load_compiled_aip(epic_id: str, spec_id: str) -> AIPv3:
    """Load a previously compiled AIP.

    Args:
        epic_id: The epic identifier
        spec_id: The spec identifier

    Returns:
        Loaded AIPv3 instance

    Raises:
        SpecNotFoundError: If the AIP file doesn't exist
    """
    path = get_aip_storage_path(epic_id, spec_id)
    if not path.exists():
        raise SpecNotFoundError(
            f"Compiled AIP not found for {epic_id}/{spec_id}. "
            f"Run 'spec compile {spec_id}' first."
        )
    return AIPv3.load(path)


def compile_from_aip_file(aip_path: Path) -> AIPv3:
    """Load an existing AIP v3 file.

    This is useful for loading hand-authored AIP files that don't come
    from an epic (e.g., the AIP file for this very spec).

    Args:
        aip_path: Path to the AIP YAML file

    Returns:
        Loaded AIPv3 instance

    Raises:
        CompileError: If loading fails
    """
    if not aip_path.exists():
        raise CompileError(f"AIP file not found: {aip_path}")

    try:
        return AIPv3.load(aip_path)
    except Exception as e:
        raise CompileError(f"Failed to load AIP: {e}")
