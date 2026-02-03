"""Epic loader: load and validate epics from YAML.

This module provides functions for loading epics from the governor
filesystem and validating their structure.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import dacite
from ruamel.yaml import YAML

from spec.core.exceptions import SpecwrightError
from spec.epic.schema import (
    Actor,
    CheckScope,
    Epic,
    EventType,
    SpecStatus,
)


class EpicNotFoundError(SpecwrightError):
    """Epic not found in governor."""

    exit_code = 2


class EpicValidationError(SpecwrightError):
    """Epic validation failed."""

    exit_code = 3


def _disable_implicit_timestamps(yaml: YAML) -> None:
    """Disable YAML 1.1 implicit timestamp parsing.

    Without this, values like 2026-01-16T00:00:00Z may be parsed as datetime
    objects by the YAML loader, which makes downstream validation and
    round-tripping less predictable.
    """
    try:
        resolvers = yaml.Resolver.yaml_implicit_resolvers
    except Exception:
        return

    for key, mappings in list(resolvers.items()):
        resolvers[key] = [
            m for m in mappings if not m or m[0] != "tag:yaml.org,2002:timestamp"
        ]


def get_governor_root() -> Path:
    """Get the governor root directory.

    Checks SPECWRIGHT_GOVERNOR_ROOT env var first, else uses
    ~/.local/local-governor.

    Returns:
        Resolved absolute path to governor root.
    """
    env_root = os.environ.get("SPECWRIGHT_GOVERNOR_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path("~/.local/local-governor").expanduser().resolve()


def get_epic_path(epic_id: str) -> Path:
    """Get the path to an epic directory.

    Args:
        epic_id: The epic identifier.

    Returns:
        Path to the epic directory within governor.
    """
    return get_governor_root() / "epics" / epic_id


def load_epic(epic_id: str) -> Epic:
    """Load an epic from governor by ID.

    Args:
        epic_id: The epic identifier.

    Returns:
        Loaded and validated Epic instance.

    Raises:
        EpicNotFoundError: If the epic does not exist.
        EpicValidationError: If the epic fails validation.
    """
    epic_dir = get_epic_path(epic_id)
    epic_file = epic_dir / "epic.yaml"

    if not epic_file.exists():
        raise EpicNotFoundError(f"Epic not found: {epic_id}")

    return load_epic_from_path(epic_file)


def load_epic_from_path(path: Path) -> Epic:
    """Load and validate an epic from a YAML file.

    Args:
        path: Path to the epic.yaml file.

    Returns:
        Loaded and validated Epic instance.

    Raises:
        EpicNotFoundError: If the file does not exist.
        EpicValidationError: If loading or validation fails.
    """
    if not path.exists():
        raise EpicNotFoundError(f"Epic file not found: {path}")

    yaml = YAML()
    _disable_implicit_timestamps(yaml)
    yaml.preserve_quotes = True

    try:
        with open(path) as f:
            data = yaml.load(f)
    except Exception as e:
        raise EpicValidationError(f"Failed to parse epic YAML: {e}")

    if data is None:
        raise EpicValidationError(f"Epic file is empty: {path}")

    return _parse_epic(data, path)


def _parse_epic(data: dict[str, Any], source_path: Path) -> Epic:
    """Parse epic data into an Epic instance.

    Args:
        data: Raw YAML data dictionary.
        source_path: Path to source file for error messages.

    Returns:
        Validated Epic instance.

    Raises:
        EpicValidationError: If parsing or validation fails.
    """
    try:
        # Configure dacite for enum and datetime conversion
        config = dacite.Config(
            cast=[SpecStatus, EventType, Actor, CheckScope],
            type_hooks={
                datetime: _parse_datetime,
            },
        )

        epic = dacite.from_dict(data_class=Epic, data=data, config=config)

    except dacite.DaciteError as e:
        raise EpicValidationError(f"Failed to parse epic structure: {e}")
    except Exception as e:
        raise EpicValidationError(f"Unexpected error parsing epic: {e}")

    # Run validation
    errors = epic.validate()
    if errors:
        error_list = "\n  - ".join(errors)
        raise EpicValidationError(f"Epic validation failed:\n  - {error_list}")

    return epic


def _parse_datetime(value: Any) -> datetime:
    """Parse datetime from various formats.

    Handles ISO 8601 format including trailing 'Z' for UTC.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Handle Z suffix (UTC) - Python's fromisoformat doesn't accept it
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        # Try ISO format first
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
        # Try common formats
        for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
        raise ValueError(f"Cannot parse datetime: {value}")
    raise ValueError(f"Expected datetime or string, got {type(value)}")


def list_epics() -> list[str]:
    """List all epic IDs in the governor.

    Returns:
        List of epic IDs (directory names under governor/epics/).
    """
    epics_dir = get_governor_root() / "epics"
    if not epics_dir.exists():
        return []

    epic_ids: list[str] = []
    for item in epics_dir.iterdir():
        if item.is_dir() and (item / "epic.yaml").exists():
            epic_ids.append(item.name)

    return sorted(epic_ids)
