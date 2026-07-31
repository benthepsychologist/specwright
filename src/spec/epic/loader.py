"""Epic loader: load and validate epics from YAML.

This module provides functions for loading epics from the governor
filesystem and validating their structure.
"""

from __future__ import annotations

import os
import re
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

# Category mapping: prefix letter -> directory name
CATEGORY_MAP = {
    "a": "a-architecture",
    "e": "e-epics",
    "t": "t-tooling",
    "h": "h-hotfix",
    "s": "s-security",
}


class EpicNotFoundError(SpecwrightError):
    """Epic not found in governor."""

    exit_code = 2


class EpicValidationError(SpecwrightError):
    """Epic validation failed."""

    exit_code = 3


def get_category_from_id(epic_id: str) -> str | None:
    """Extract category prefix from epic ID.

    Args:
        epic_id: Epic identifier like 't004-specwright-governance'.

    Returns:
        Single-letter category prefix (e.g., 't'), or None if not recognized.
    """
    match = re.match(r"^([aehst])\d{3}-", epic_id)
    return match.group(1) if match else None


def get_category_dir(category: str) -> str | None:
    """Get category directory name from prefix.

    Args:
        category: Single-letter category prefix.

    Returns:
        Directory name (e.g., 't-tooling'), or None if unknown.
    """
    return CATEGORY_MAP.get(category)


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

    t018-04: checks the new canon/initiatives/<initiative>/epics/<epic_id>/
    root first (most epics moved there) via a real existence scan, then
    falls back to the old epics/ root's existing resolution:
    - t004-foo -> epics/t-tooling/t004-foo/
    - e012-bar -> epics/e-epics/e012-bar/
    - unknown  -> epics/unknown/ (fallback for legacy/uncategorized)

    Args:
        epic_id: The epic identifier.

    Returns:
        Path to the epic directory within governor.
    """
    root = get_governor_root()

    # New root first (t018-04): most epics now live under
    # canon/initiatives/<initiative>/epics/<epic_id>/. Unlike the old
    # root's category guess below, this is a real existence scan -- no
    # initiative name is known here, so the path can't be guessed.
    initiatives_root = root / "canon" / "initiatives"
    if initiatives_root.exists():
        for epic_yaml in initiatives_root.rglob("epic.yaml"):
            if epic_yaml.parent.name == epic_id:
                return epic_yaml.parent

    # Old root fallback (unassigned epics, e.g. e007/e009) — unchanged.
    epics_root = root / "epics"

    # Try to extract category from ID prefix
    category = get_category_from_id(epic_id)
    if category:
        category_dir = get_category_dir(category)
        if category_dir:
            return epics_root / category_dir / epic_id

    # Fallback: check if epic exists in any category subdir (for loading)
    for epic_yaml in epics_root.rglob("epic.yaml"):
        if epic_yaml.parent.name == epic_id:
            return epic_yaml.parent

    # Final fallback: flat structure (legacy)
    return epics_root / epic_id


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

    Supports multiple layouts:
    - New (t018-04): canon/initiatives/<initiative>/epics/t004-foo/epic.yaml
    - Flat: epics/t004-foo/epic.yaml
    - Category-grouped: epics/t-tooling/t004-foo/epic.yaml

    Returns:
        List of epic IDs (directory names containing epic.yaml).
    """
    root = get_governor_root()
    search_roots = [root / "canon" / "initiatives", root / "epics"]

    epic_ids: list[str] = []
    seen: set[str] = set()

    for search_root in search_roots:
        if not search_root.exists():
            continue
        for epic_yaml in search_root.rglob("epic.yaml"):
            epic_id = epic_yaml.parent.name
            if epic_id not in seen:
                seen.add(epic_id)
                epic_ids.append(epic_id)

    return sorted(epic_ids)
