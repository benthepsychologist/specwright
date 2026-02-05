"""Epic updater: round-trip YAML updates to epic.yaml files.

Provides surgical edits to epic.yaml (set spec status, update timestamps,
add build_delta) using ruamel.yaml to preserve comments and formatting.

Separate from epic/loader.py which reads into typed dataclasses via dacite.
This module writes back via ruamel round-trip — different concerns.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from spec.core.exceptions import SpecwrightError


class EpicUpdateError(SpecwrightError):
    """Failed to update epic.yaml."""

    exit_code = 3


class EpicUpdater:
    """Round-trip update of epic.yaml fields.

    Usage::

        updater = EpicUpdater(epic_yaml_path)
        updater.set_spec_status("t004-01", "done")
        updater.set_updated()
        updater.save()
    """

    def __init__(self, epic_yaml_path: Path) -> None:
        self.path = epic_yaml_path
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._data: Any = None
        self._load()

    def _load(self) -> None:
        """Load epic.yaml with ruamel round-trip."""
        with self.path.open() as f:
            self._data = self._yaml.load(f)
        if self._data is None:
            raise EpicUpdateError(f"Epic file is empty: {self.path}")

    def _find_spec(self, spec_id: str) -> Any:
        """Find a spec entry by ID in the YAML data.

        Returns the raw ruamel CommentedMap for the spec.
        Raises EpicUpdateError if not found.
        """
        specs = self._data.get("specs", [])
        for spec in specs:
            if spec.get("id") == spec_id:
                return spec
        available = [s.get("id", "?") for s in specs]
        raise EpicUpdateError(
            f"Spec '{spec_id}' not found in epic. Available: {available}"
        )

    def get_spec_entry(self, spec_id: str) -> Any:
        """Get the raw spec entry (CommentedMap) by ID.

        Returns the live reference into the YAML data — mutations
        will be reflected when save() is called.
        """
        return self._find_spec(spec_id)

    def get_target(self, target_id: str) -> Any | None:
        """Get a target entry by ID, or None if not found."""
        for t in self._data.get("targets", []):
            if t.get("id") == target_id:
                return t
        return None

    def get_spec_status(self, spec_id: str) -> str:
        """Get the current status of a spec."""
        spec = self._find_spec(spec_id)
        return spec.get("status", "planned")

    def set_spec_status(self, spec_id: str, status: str) -> None:
        """Update a spec's status field in-place."""
        spec = self._find_spec(spec_id)
        spec["status"] = status

    def set_updated(self, timestamp: str | None = None) -> None:
        """Update the epic's updated timestamp.

        If no timestamp given, uses current UTC time in ISO format.
        """
        if timestamp is None:
            timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._data["updated"] = timestamp

    def add_build_delta(self, spec_id: str, delta: dict) -> None:
        """Add a build_delta to a spec that doesn't have one.

        Raises EpicUpdateError if the spec already has a build_delta.
        """
        spec = self._find_spec(spec_id)
        if spec.get("build_delta"):
            raise EpicUpdateError(
                f"Spec '{spec_id}' already has a build_delta"
            )
        spec["build_delta"] = delta

    def save(self) -> None:
        """Write back atomically.

        Writes to a temp file then os.replace() to swap.
        """
        tmp_fd = None
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=".epic_update_",
                suffix=".tmp",
            )
            os.close(tmp_fd)
            tmp_fd = None

            with open(tmp_path, "w") as f:
                self._yaml.dump(self._data, f)

            os.replace(tmp_path, self.path)
            tmp_path = None
        except Exception as e:
            raise EpicUpdateError(f"Failed to write epic.yaml: {e}") from e
        finally:
            if tmp_fd is not None:
                try:
                    os.close(tmp_fd)
                except OSError:
                    pass
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
