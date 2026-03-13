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

        Resolution order:
        1. Direct .yaml, .yml, then .md file in project specs/
        2. .index.yaml spec-ref → follow path to canonical location
        3. Prefix-based resolver (searches epics/)

        Args:
            slug: The spec slug (filename without extension), or a prefix.

        Returns:
            The spec content as a string

        Raises:
            SpecNotFoundError: If the spec doesn't exist
        """
        resolved = self._resolve_spec_path(slug)
        if resolved is None:
            raise SpecNotFoundError(slug, self._paths.specs / f"{slug}.yaml")
        return resolved.read_text(encoding="utf-8")

    def _resolve_spec_path(self, slug: str) -> Path | None:
        """Resolve a spec slug to a file path.

        Tries direct .yaml/.yml/.md, then .index.yaml, then epic-prefix resolver.
        """
        # 1. Direct spec in project specs/ (yaml preferred)
        for ext in (".yaml", ".yml", ".md"):
            direct = self._paths.specs / f"{slug}{ext}"
            if direct.exists():
                return direct

        # 2. Index file (.index.yaml) in project specs/
        index = self._paths.specs / f"{slug}.index.yaml"
        if index.exists():
            ref = yaml.safe_load(index.read_text(encoding="utf-8"))
            if ref and ref.get("kind") == "spec-ref" and ref.get("path"):
                canonical = self._paths.root / ref["path"]
                if canonical.exists():
                    return canonical

        # 3. Prefix-based resolver (searches epics by prefix match)
        from spec.governor.resolver import ResolveError, resolve_spec

        try:
            resolved = resolve_spec(slug, self._paths.root)
            return resolved.spec_path
        except ResolveError:
            return None

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

        Includes direct .yaml/.yml/.md files and .index.yaml references.

        Returns:
            List of spec slugs (deduplicated, sorted).
        """
        if not self._paths.specs.exists():
            return []
        slugs: set[str] = set()
        for p in self._paths.specs.iterdir():
            if not p.is_file():
                continue
            if p.suffix in (".md", ".yaml", ".yml"):
                slugs.add(p.stem)
            elif p.name.endswith(".index.yaml"):
                # Strip .index.yaml to get the slug
                slugs.add(p.name.removesuffix(".index.yaml"))
        return sorted(slugs)

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
        """Check if a spec exists (direct, index, or prefix-resolvable).

        Args:
            slug: The spec slug

        Returns:
            True if the spec exists
        """
        return self._resolve_spec_path(slug) is not None

    def aip_exists(self, aip_id: str) -> bool:
        """Check if an AIP exists.

        Args:
            aip_id: The AIP ID

        Returns:
            True if the AIP exists
        """
        return (self._paths.aips / f"{aip_id}.yaml").exists()

    def get_spec_path(self, slug: str) -> Path:
        """Get the resolved path to a spec file.

        Args:
            slug: The spec slug

        Returns:
            Resolved path to the spec file, or the legacy path if unresolvable.
        """
        resolved = self._resolve_spec_path(slug)
        if resolved is not None:
            return resolved
        return self._paths.specs / f"{slug}.yaml"

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
