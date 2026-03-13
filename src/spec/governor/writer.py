"""Governor writer: write specs, AIPs, errors, and provenance.

This module provides write access to the local-governor storage,
using atomic writes (temp file + rename) to prevent corruption.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import]

if TYPE_CHECKING:
    from typing import Any

    from spec.governor.errors import ErrorRecord
    from spec.governor.locator import GovernorPaths
    from spec.governor.provenance import ProvenanceSnapshot


class GovernorWriter:
    """Writes specs, AIPs, errors, and provenance to local-governor."""

    def __init__(self, paths: GovernorPaths) -> None:
        """Initialize the writer.

        Args:
            paths: GovernorPaths with all path components
        """
        self._paths = paths

    def write_spec(self, slug: str, content: str) -> Path:
        """Write a spec file.

        Args:
            slug: The spec slug (filename without extension)
            content: The spec content (YAML or Markdown)

        Returns:
            Path to the written file
        """
        spec_path = self._paths.specs / f"{slug}.yaml"
        self._atomic_write(spec_path, content)
        return spec_path

    def write_aip(self, aip_id: str, aip: dict[str, Any]) -> Path:
        """Write an AIP file.

        Args:
            aip_id: The AIP ID
            aip: The AIP dictionary

        Returns:
            Path to the written file
        """
        aip_path = self._paths.aips / f"{aip_id}.yaml"
        content = yaml.dump(aip, sort_keys=False, default_flow_style=False)
        self._atomic_write(aip_path, content)
        return aip_path

    def write_error(self, error: ErrorRecord) -> Path:
        """Write an error record.

        Args:
            error: The error record to write

        Returns:
            Path to the written file
        """
        # Index by repo/date/error_id
        date_str = datetime.now().strftime("%Y-%m-%d")
        error_dir = self._paths.errors / error.repo / date_str
        error_dir.mkdir(parents=True, exist_ok=True)

        error_path = error_dir / f"{error.error_id}.yaml"
        content = yaml.dump(
            error.to_dict(), sort_keys=False, default_flow_style=False
        )
        self._atomic_write(error_path, content)
        return error_path

    def write_provenance(self, snapshot: ProvenanceSnapshot) -> Path:
        """Write a provenance snapshot.

        Args:
            snapshot: The provenance snapshot to write

        Returns:
            Path to the written file
        """
        # Index by repo/date/run_id
        date_str = datetime.now().strftime("%Y-%m-%d")
        run_dir = self._paths.runs / snapshot.repo / date_str
        run_dir.mkdir(parents=True, exist_ok=True)

        run_path = run_dir / f"{snapshot.run_id}.yaml"
        content = yaml.dump(
            snapshot.to_dict(), sort_keys=False, default_flow_style=False
        )
        self._atomic_write(run_path, content)
        return run_path

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content atomically using temp file + rename.

        Args:
            path: Target file path
            content: Content to write
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file in same directory for atomic rename
        fd, temp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
            # Atomic rename
            Path(temp_path).rename(path)
        except Exception:
            # Clean up temp file on failure
            Path(temp_path).unlink(missing_ok=True)
            raise

    def delete_spec(self, slug: str) -> bool:
        """Delete a spec file.

        Args:
            slug: The spec slug

        Returns:
            True if deleted, False if didn't exist
        """
        for ext in (".yaml", ".md"):
            spec_path = self._paths.specs / f"{slug}{ext}"
            if spec_path.exists():
                spec_path.unlink()
                return True
        return False

    def delete_aip(self, aip_id: str) -> bool:
        """Delete an AIP file.

        Args:
            aip_id: The AIP ID

        Returns:
            True if deleted, False if didn't exist
        """
        aip_path = self._paths.aips / f"{aip_id}.yaml"
        if aip_path.exists():
            aip_path.unlink()
            return True
        return False
