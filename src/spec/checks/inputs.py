"""Input gathering for check execution.

This module handles gathering all inputs defined for a check,
dispatching to type-specific handlers for each input type.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spec.core.exceptions import SpecwrightError

if TYPE_CHECKING:
    from spec.epic.schema import Check, CheckInput, Epic, Target


class InputGatherError(SpecwrightError):
    """Failed to gather input for a check."""

    exit_code = 1


@dataclass
class GatheredInput:
    """A gathered input for check execution."""

    type: str  # epic, spec, file, git_diff, cli_output, governance_pack
    source: str  # path, command, or description
    content: str  # the actual content


def gather_inputs(
    check: Check,
    epic: Epic,
    epic_path: Path,
) -> list[GatheredInput]:
    """Gather all inputs defined for a check.

    Iterates through check.inputs and gathers each one.

    Args:
        check: The check definition with inputs list.
        epic: The epic containing targets and run context.
        epic_path: Path to the epic directory.

    Returns:
        List of gathered inputs.

    Raises:
        InputGatherError: If any input fails to gather.
    """
    gathered: list[GatheredInput] = []

    for input_def in check.inputs:
        gathered_input = _gather_single(input_def, epic, epic_path)
        gathered.append(gathered_input)

    return gathered


def _gather_single(
    input_def: CheckInput,
    epic: Epic,
    epic_path: Path,
) -> GatheredInput:
    """Gather a single input based on its type.

    Args:
        input_def: The input definition.
        epic: The epic containing targets and run context.
        epic_path: Path to the epic directory.

    Returns:
        The gathered input.

    Raises:
        InputGatherError: If the input cannot be gathered.
    """
    input_type = input_def.type

    if input_type == "epic":
        return _gather_epic(epic_path)
    elif input_type == "spec":
        return _gather_spec(input_def, epic)
    elif input_type == "file":
        return _gather_file(input_def, epic)
    elif input_type == "git_diff":
        return _gather_git_diff(input_def, epic)
    elif input_type == "cli_output":
        return _gather_cli_output(input_def, epic)
    elif input_type == "governance_pack":
        return _gather_governance_pack(input_def, epic)
    else:
        raise InputGatherError(f"Unknown input type: {input_type}")


def _resolve_target(input_def: CheckInput, epic: Epic) -> Target:
    """Resolve the target for an input.

    Uses input_def.target if specified, otherwise uses the first target.

    Args:
        input_def: The input definition.
        epic: The epic containing targets.

    Returns:
        The resolved target.

    Raises:
        InputGatherError: If no target can be resolved.
    """
    if input_def.target:
        target = epic.get_target(input_def.target)
        if target is None:
            raise InputGatherError(
                f"Target '{input_def.target}' not found in epic"
            )
        return target

    if not epic.targets:
        raise InputGatherError("No targets defined in epic")

    return epic.targets[0]


def _gather_epic(epic_path: Path) -> GatheredInput:
    """Gather epic.yaml content.

    Args:
        epic_path: Path to the epic directory.

    Returns:
        GatheredInput with epic.yaml content.

    Raises:
        InputGatherError: If epic.yaml cannot be read.
    """
    epic_yaml_path = epic_path / "epic.yaml"

    if not epic_yaml_path.exists():
        raise InputGatherError(f"epic.yaml not found at {epic_yaml_path}")

    try:
        content = epic_yaml_path.read_text(encoding="utf-8")
    except OSError as e:
        raise InputGatherError(f"Failed to read epic.yaml: {e}") from e

    return GatheredInput(
        type="epic",
        source=str(epic_yaml_path),
        content=content,
    )


def _gather_spec(input_def: CheckInput, epic: Epic) -> GatheredInput:
    """Gather spec file content from governor.

    Args:
        input_def: Input definition with path relative to governor root.
        epic: The epic with run_context.

    Returns:
        GatheredInput with spec file content.

    Raises:
        InputGatherError: If spec cannot be read.
    """
    if not input_def.path:
        raise InputGatherError("Spec input requires 'path' field")

    if not epic.run_context:
        raise InputGatherError("Epic requires run_context for spec input")

    governor_root = Path(epic.run_context.governor_root)
    spec_path = governor_root / input_def.path

    if not spec_path.exists():
        raise InputGatherError(f"Spec file not found: {spec_path}")

    try:
        content = spec_path.read_text(encoding="utf-8")
    except OSError as e:
        raise InputGatherError(f"Failed to read spec file: {e}") from e

    return GatheredInput(
        type="spec",
        source=str(spec_path),
        content=content,
    )


def _gather_file(input_def: CheckInput, epic: Epic) -> GatheredInput:
    """Gather file content from target repository.

    Args:
        input_def: Input definition with path and optional target.
        epic: The epic with targets.

    Returns:
        GatheredInput with file content.

    Raises:
        InputGatherError: If file cannot be read.
    """
    if not input_def.path:
        raise InputGatherError("File input requires 'path' field")

    target = _resolve_target(input_def, epic)
    file_path = Path(target.repo_path) / input_def.path

    if not file_path.exists():
        raise InputGatherError(f"File not found: {file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as e:
        raise InputGatherError(f"Failed to read file: {e}") from e

    return GatheredInput(
        type="file",
        source=str(file_path),
        content=content,
    )


def _gather_git_diff(input_def: CheckInput, epic: Epic) -> GatheredInput:
    """Gather git diff output from target repository.

    Args:
        input_def: Input definition with optional range and target.
        epic: The epic with targets.

    Returns:
        GatheredInput with git diff output.

    Raises:
        InputGatherError: If git diff fails.
    """
    target = _resolve_target(input_def, epic)
    repo_path = Path(target.repo_path)

    # Default range if not specified
    diff_range = input_def.range or "HEAD~1..HEAD"

    try:
        result = subprocess.run(
            ["git", "diff", diff_range],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as e:
        raise InputGatherError(
            f"git diff timed out in {repo_path}"
        ) from e
    except OSError as e:
        raise InputGatherError(f"Failed to run git diff: {e}") from e

    if result.returncode != 0:
        raise InputGatherError(
            f"git diff failed: {result.stderr.strip()}"
        )

    return GatheredInput(
        type="git_diff",
        source=f"git diff {diff_range} in {repo_path}",
        content=result.stdout,
    )


def _gather_cli_output(input_def: CheckInput, epic: Epic) -> GatheredInput:
    """Gather CLI command output.

    Args:
        input_def: Input definition with args list.
        epic: The epic with run_context and targets.

    Returns:
        GatheredInput with command output.

    Raises:
        InputGatherError: If command fails.
    """
    if not input_def.args:
        raise InputGatherError("cli_output input requires 'args' field")

    if not epic.run_context:
        raise InputGatherError("Epic requires run_context for cli_output input")

    # Build argv
    argv = [epic.run_context.cli_bin] + list(input_def.args)

    # Determine cwd based on cwd_policy
    if epic.run_context.cwd_policy == "governor":
        cwd = Path(epic.run_context.governor_root)
    else:
        # Default to repo policy
        target = _resolve_target(input_def, epic)
        cwd = Path(target.repo_path)

    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
    except subprocess.TimeoutExpired as e:
        raise InputGatherError(
            f"Command timed out: {' '.join(argv)}"
        ) from e
    except OSError as e:
        raise InputGatherError(
            f"Failed to run command: {e}"
        ) from e

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        raise InputGatherError(
            f"Command failed (exit {result.returncode}): {' '.join(argv)}\n{stderr}".strip()
        )

    # Combine stdout and stderr
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"

    command_str = " ".join(argv)
    return GatheredInput(
        type="cli_output",
        source=command_str,
        content=output,
    )


def _gather_governance_pack(input_def: CheckInput, epic: Epic) -> GatheredInput:
    """Gather governance context (currently dormant)."""
    return GatheredInput(
        type="governance_pack",
        source="governance (dormant)",
        content="[Governance pack not available — autogov is dormant]",
    )
