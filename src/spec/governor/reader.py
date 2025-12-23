"""Governor reader: read specs and AIPs from local-governor.

This module provides read access to the local-governor storage,
allowing Specwright to retrieve specs and AIPs for compilation
and execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import]

if TYPE_CHECKING:
    from typing import Any

    from spec.governor.locator import GovernorPaths


class SpecNotFoundError(Exception):
    """Raised when a spec cannot be found in governor."""

    def __init__(self, slug: str, path: Path) -> None:
        self.slug = slug
        self.path = path
        super().__init__(
            f"Spec '{slug}' not found at {path}\n\n"
            f"Available specs: spec list\n"
            f"Create a new spec: spec create \"{slug}\""
        )


class AIPNotFoundError(Exception):
    """Raised when an AIP cannot be found in governor."""

    def __init__(self, aip_id: str, path: Path) -> None:
        self.aip_id = aip_id
        self.path = path
        super().__init__(
            f"AIP '{aip_id}' not found at {path}\n\n"
            f"Available AIPs: spec aip-list\n"
            f"Compile a spec: spec compile <spec-path>"
        )


class GovernorReader:
    """Reads specs and AIPs from local-governor."""

    def __init__(self, paths: GovernorPaths) -> None:
        """Initialize the reader.

        Args:
            paths: GovernorPaths with all path components
        """
        self._paths = paths

    def read_spec(self, slug: str) -> str:
        """Read a spec file by slug.

        Args:
            slug: The spec slug (filename without extension)

        Returns:
            The spec content as a string

        Raises:
            SpecNotFoundError: If the spec doesn't exist
        """
        spec_path = self._paths.specs / f"{slug}.md"
        if not spec_path.exists():
            raise SpecNotFoundError(slug, spec_path)
        return spec_path.read_text(encoding="utf-8")

    def read_spec_parsed(self, slug: str) -> dict[str, Any]:
        """Read and parse a spec file by slug.

        Args:
            slug: The spec slug (filename without extension)

        Returns:
            Parsed spec as a dictionary (from YAML frontmatter + content)

        Raises:
            SpecNotFoundError: If the spec doesn't exist
        """
        content = self.read_spec(slug)
        return self._parse_spec_content(content)

    def read_aip(self, aip_id: str) -> dict[str, Any]:
        """Read an AIP file by ID.

        Args:
            aip_id: The AIP ID

        Returns:
            The AIP as a dictionary

        Raises:
            AIPNotFoundError: If the AIP doesn't exist
        """
        aip_path = self._paths.aips / f"{aip_id}.yaml"
        if not aip_path.exists():
            raise AIPNotFoundError(aip_id, aip_path)
        with open(aip_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def list_specs(self) -> list[str]:
        """List all spec slugs in governor.

        Returns:
            List of spec slugs (filenames without .md extension)
        """
        if not self._paths.specs.exists():
            return []
        return sorted(
            p.stem for p in self._paths.specs.glob("*.md") if p.is_file()
        )

    def list_aips(self) -> list[str]:
        """List all AIP IDs in governor.

        Returns:
            List of AIP IDs (filenames without .yaml extension)
        """
        if not self._paths.aips.exists():
            return []
        return sorted(
            p.stem for p in self._paths.aips.glob("*.yaml") if p.is_file()
        )

    def spec_exists(self, slug: str) -> bool:
        """Check if a spec exists.

        Args:
            slug: The spec slug

        Returns:
            True if the spec exists
        """
        return (self._paths.specs / f"{slug}.md").exists()

    def aip_exists(self, aip_id: str) -> bool:
        """Check if an AIP exists.

        Args:
            aip_id: The AIP ID

        Returns:
            True if the AIP exists
        """
        return (self._paths.aips / f"{aip_id}.yaml").exists()

    def get_spec_path(self, slug: str) -> Path:
        """Get the path to a spec file.

        Args:
            slug: The spec slug

        Returns:
            Path to the spec file (may not exist)
        """
        return self._paths.specs / f"{slug}.md"

    def get_aip_path(self, aip_id: str) -> Path:
        """Get the path to an AIP file.

        Args:
            aip_id: The AIP ID

        Returns:
            Path to the AIP file (may not exist)
        """
        return self._paths.aips / f"{aip_id}.yaml"

    def _parse_spec_content(self, content: str) -> dict[str, Any]:
        """Parse spec content with YAML frontmatter.

        Args:
            content: Raw spec content

        Returns:
            Dictionary with 'frontmatter' and 'body' keys
        """
        # Split on YAML frontmatter delimiters
        parts = content.split("---", 2)

        if len(parts) >= 3:
            # Has frontmatter
            frontmatter_str = parts[1].strip()
            body = parts[2].strip()
            frontmatter = yaml.safe_load(frontmatter_str) or {}
        else:
            # No frontmatter
            frontmatter = {}
            body = content.strip()

        return {
            "frontmatter": frontmatter,
            "body": body,
        }
