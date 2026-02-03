"""Build delta applicator: apply build_delta changes to build.yaml files.

Applies adds/modifies/removes from a build_delta dict to a target
build.yaml file using ruamel.yaml for round-trip preservation.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from spec.core.exceptions import SpecwrightError


class DeltaConflictError(SpecwrightError):
    """A build_delta conflicts with the current build.yaml state."""

    exit_code = 3


class DeltaApplicationError(SpecwrightError):
    """Failed to apply a build_delta."""

    exit_code = 3


# Map delta section keys to (yaml_path, key_field) tuples.
# yaml_path is a list of keys to traverse into the YAML doc.
# key_field is the field used to match entries within the section list.
_SECTION_MAP: dict[str, tuple[list[str], str | None]] = {
    "layout": (["layout"], "path"),
    "modules": (["modules"], "name"),
    "boundaries": (["boundaries"], "name"),
    "decisions": (["decisions"], "id"),
    "slots": (["slots"], "name"),
    "frozen": (["frozen"], "path"),
    "contracts": (["contracts"], "name"),
    "kernel_surfaces": (["kernel", "surfaces"], "name"),
    "kernel_invariants": (["kernel", "invariants"], None),  # plain string list
}


class BuildDeltaApplicator:
    """Apply a build_delta to a build.yaml file using ruamel round-trip editing.

    Usage::

        applicator = BuildDeltaApplicator(build_path, delta)
        preview = applicator.preview()   # human-readable summary
        applicator.validate()            # check for conflicts
        applicator.apply()               # write atomically
    """

    def __init__(self, build_path: Path, delta: dict[str, Any]) -> None:
        self.build_path = build_path
        self.delta = delta
        self._yaml = YAML()
        self._yaml.preserve_quotes = True

    def _load(self) -> Any:
        """Load the build.yaml with ruamel round-trip."""
        with self.build_path.open() as f:
            return self._yaml.load(f)

    def _resolve_section(
        self, rt_data: Any, yaml_path: list[str]
    ) -> tuple[Any, str, list | None]:
        """Navigate into nested YAML and return (parent, key, section_list).

        Creates intermediate dicts/lists if they don't exist.
        Returns the parent container, the final key, and the current list
        (or None if the key doesn't exist yet).
        """
        parent = rt_data
        for key in yaml_path[:-1]:
            if key not in parent:
                parent[key] = {}
            parent = parent[key]

        final_key = yaml_path[-1]
        section = parent.get(final_key)
        return parent, final_key, section

    def preview(self) -> str:
        """Return a human-readable summary of what would change."""
        lines: list[str] = []

        adds = self.delta.get("adds", {})
        modifies = self.delta.get("modifies", {})
        removes = self.delta.get("removes", {})

        for section_key, entries in adds.items():
            if not entries:
                continue
            mapping = _SECTION_MAP.get(section_key)
            if not mapping:
                lines.append(f"  add to {section_key}: (unknown section)")
                continue
            _, key_field = mapping
            for entry in entries:
                if key_field and isinstance(entry, dict):
                    label = entry.get(key_field, "?")
                    lines.append(f"  add {section_key}: {label}")
                else:
                    lines.append(f"  add {section_key}: {entry}")

        for section_key, entries in modifies.items():
            if not entries:
                continue
            mapping = _SECTION_MAP.get(section_key)
            if not mapping:
                lines.append(f"  modify {section_key}: (unknown section)")
                continue
            _, key_field = mapping
            for entry in entries:
                if key_field and isinstance(entry, dict):
                    label = entry.get(key_field, "?")
                    lines.append(f"  modify {section_key}: {label}")
                else:
                    lines.append(f"  modify {section_key}: {entry}")

        for section_key, entries in removes.items():
            if not entries:
                continue
            mapping = _SECTION_MAP.get(section_key)
            if not mapping:
                lines.append(f"  remove from {section_key}: (unknown section)")
                continue
            _, key_field = mapping
            for entry in entries:
                if key_field and isinstance(entry, dict):
                    label = entry.get(key_field, "?")
                    lines.append(f"  remove {section_key}: {label}")
                else:
                    lines.append(f"  remove {section_key}: {entry}")

        if not lines:
            return "  (no changes)"

        summary = self.delta.get("summary", "")
        header = f"  summary: {summary}\n" if summary else ""
        return header + "\n".join(lines)

    def validate(self) -> list[str]:
        """Check for conflicts without modifying anything.

        Returns a list of conflict descriptions. Empty list means safe to apply.
        """
        rt_data = self._load()
        conflicts: list[str] = []

        adds = self.delta.get("adds", {})
        removes = self.delta.get("removes", {})
        modifies = self.delta.get("modifies", {})

        # Check adds don't already exist
        for section_key, entries in adds.items():
            if not entries:
                continue
            mapping = _SECTION_MAP.get(section_key)
            if not mapping:
                conflicts.append(f"Unknown section in adds: {section_key}")
                continue
            yaml_path, key_field = mapping
            _, _, section = self._resolve_section(rt_data, yaml_path)
            if section is None:
                continue
            if key_field is None:
                # String-list section: check for duplicate values
                existing_values = set(section)
                for entry in entries:
                    if entry in existing_values:
                        conflicts.append(
                            f"adds.{section_key}: '{entry}' already exists"
                        )
                continue
            existing_keys = {
                e.get(key_field) for e in section if isinstance(e, dict)
            }
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_key = entry.get(key_field)
                if entry_key and entry_key in existing_keys:
                    conflicts.append(
                        f"adds.{section_key}: '{entry_key}' already exists"
                    )

        # Check modifies reference existing entries
        for section_key, entries in modifies.items():
            if not entries:
                continue
            mapping = _SECTION_MAP.get(section_key)
            if not mapping:
                conflicts.append(f"Unknown section in modifies: {section_key}")
                continue
            yaml_path, key_field = mapping
            if key_field is None:
                # String-list sections can't be modified — only added/removed
                conflicts.append(
                    f"modifies.{section_key}: cannot modify a plain-value list "
                    f"(use adds/removes instead)"
                )
                continue
            _, _, section = self._resolve_section(rt_data, yaml_path)
            if section is None:
                conflicts.append(
                    f"modifies.{section_key}: section does not exist"
                )
                continue
            existing_keys = {
                e.get(key_field) for e in section if isinstance(e, dict)
            }
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_key = entry.get(key_field)
                if entry_key and entry_key not in existing_keys:
                    conflicts.append(
                        f"modifies.{section_key}: '{entry_key}' does not exist"
                    )

        # Check removes reference existing entries
        for section_key, entries in removes.items():
            if not entries:
                continue
            mapping = _SECTION_MAP.get(section_key)
            if not mapping:
                conflicts.append(f"Unknown section in removes: {section_key}")
                continue
            yaml_path, key_field = mapping
            _, _, section = self._resolve_section(rt_data, yaml_path)
            if section is None:
                conflicts.append(
                    f"removes.{section_key}: section does not exist"
                )
                continue
            if key_field is None:
                # String-list section: check values exist
                existing_values = set(section)
                for entry in entries:
                    if entry not in existing_values:
                        conflicts.append(
                            f"removes.{section_key}: '{entry}' does not exist"
                        )
                continue
            existing_keys = {
                e.get(key_field) for e in section if isinstance(e, dict)
            }
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_key = entry.get(key_field)
                if entry_key and entry_key not in existing_keys:
                    conflicts.append(
                        f"removes.{section_key}: '{entry_key}' does not exist"
                    )

        return conflicts

    def apply(self) -> None:
        """Apply the delta atomically.

        Loads build.yaml, applies all mutations in memory, writes to a
        temp file, then os.replace() to swap atomically. On any failure
        the original file is untouched.

        Raises:
            DeltaConflictError: If the delta conflicts with current state.
            DeltaApplicationError: If the application fails.
        """
        conflicts = self.validate()
        if conflicts:
            msg = "Build delta conflicts:\n  " + "\n  ".join(conflicts)
            raise DeltaConflictError(msg)

        rt_data = self._load()

        try:
            self._apply_adds(rt_data, self.delta.get("adds", {}))
            self._apply_modifies(rt_data, self.delta.get("modifies", {}))
            self._apply_removes(rt_data, self.delta.get("removes", {}))
        except Exception as e:
            raise DeltaApplicationError(f"Failed to apply delta: {e}") from e

        # Write to temp file, then atomic swap
        tmp_fd = None
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=self.build_path.parent,
                prefix=".build_delta_",
                suffix=".tmp",
            )
            os.close(tmp_fd)
            tmp_fd = None

            with open(tmp_path, "w") as f:
                self._yaml.dump(rt_data, f)

            os.replace(tmp_path, self.build_path)
            tmp_path = None  # swap succeeded, don't clean up
        except Exception as e:
            raise DeltaApplicationError(
                f"Failed to write build.yaml: {e}"
            ) from e
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

    def _apply_adds(self, rt_data: Any, adds: dict[str, Any]) -> None:
        """Append new entries to build.yaml sections."""
        for section_key, entries in adds.items():
            if not entries:
                continue
            mapping = _SECTION_MAP.get(section_key)
            if not mapping:
                raise DeltaApplicationError(
                    f"Unknown section in adds: {section_key}"
                )
            yaml_path, _ = mapping
            parent, final_key, section = self._resolve_section(rt_data, yaml_path)
            if section is None:
                section = []
                parent[final_key] = section
            for entry in entries:
                section.append(entry)

    def _apply_modifies(self, rt_data: Any, modifies: dict[str, Any]) -> None:
        """Update existing entries in build.yaml sections.

        Scalar fields overwrite. Array fields append new items.
        """
        for section_key, entries in modifies.items():
            if not entries:
                continue
            mapping = _SECTION_MAP.get(section_key)
            if not mapping:
                raise DeltaApplicationError(
                    f"Unknown section in modifies: {section_key}"
                )
            yaml_path, key_field = mapping
            _, _, section = self._resolve_section(rt_data, yaml_path)
            if section is None:
                raise DeltaApplicationError(
                    f"Cannot modify {section_key}: section does not exist"
                )

            if key_field is None:
                # String-list sections can't be modified — should be
                # caught by validate(), but guard here too.
                raise DeltaApplicationError(
                    f"Cannot modify {section_key}: plain-value lists "
                    f"only support adds/removes"
                )

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_key = entry.get(key_field)
                if entry_key is None:
                    continue

                # Find the matching existing entry
                target = None
                for existing in section:
                    if isinstance(existing, dict) and existing.get(key_field) == entry_key:
                        target = existing
                        break

                if target is None:
                    raise DeltaApplicationError(
                        f"Cannot modify {section_key}/{entry_key}: not found"
                    )

                # Merge: scalars overwrite, arrays append
                for field_name, value in entry.items():
                    if field_name == key_field:
                        continue  # don't overwrite the key itself
                    if isinstance(value, list) and isinstance(
                        target.get(field_name), list
                    ):
                        # Append new items to existing list
                        existing_list = target[field_name]
                        for item in value:
                            if item not in existing_list:
                                existing_list.append(item)
                    else:
                        target[field_name] = value

    def _apply_removes(self, rt_data: Any, removes: dict[str, Any]) -> None:
        """Remove entries from build.yaml sections."""
        for section_key, entries in removes.items():
            if not entries:
                continue
            mapping = _SECTION_MAP.get(section_key)
            if not mapping:
                raise DeltaApplicationError(
                    f"Unknown section in removes: {section_key}"
                )
            yaml_path, key_field = mapping
            _, _, section = self._resolve_section(rt_data, yaml_path)
            if section is None:
                raise DeltaApplicationError(
                    f"Cannot remove from {section_key}: section does not exist"
                )

            if key_field is None:
                # String-list section: remove by value
                for entry in entries:
                    try:
                        section.remove(entry)
                    except ValueError:
                        raise DeltaApplicationError(
                            f"Cannot remove from {section_key}: "
                            f"'{entry}' not found"
                        )
                continue

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_key = entry.get(key_field)
                if entry_key is None:
                    continue

                # Find and remove by index (reverse to preserve indices)
                to_remove = [
                    i
                    for i, existing in enumerate(section)
                    if isinstance(existing, dict)
                    and existing.get(key_field) == entry_key
                ]
                for i in reversed(to_remove):
                    del section[i]
