"""Intent parser for spec drafting.

Parses intent from markdown files and epic spec entries into a structured
format suitable for scaffolding specs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from spec.epic.schema import Epic


@dataclass
class ParsedIntent:
    """Structured intent extracted from markdown or epic entry."""

    id: str
    title: str
    goal: str
    tier: str | None = None
    owner: str | None = None
    branch: str | None = None
    epic_id: str | None = None
    repo_id: str | None = None
    expectations: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    raw_content: str = ""


class IntentParser:
    """Parse intent from various sources."""

    def parse_markdown(self, content: str) -> ParsedIntent:
        """Parse markdown intent (YAML frontmatter + body).

        Args:
            content: Raw markdown content with optional YAML frontmatter.

        Returns:
            ParsedIntent with extracted fields.
        """
        fm: dict = {}
        body: str = content

        # Extract frontmatter
        if content.startswith("---\n"):
            end = content.find("\n---\n", 4)
            if end != -1:
                try:
                    fm = yaml.safe_load(content[4:end]) or {}
                except yaml.YAMLError:
                    fm = {}
                body = content[end + 5 :]

        # Extract sections from body
        expectations = self._extract_bullets(body, "Acceptance Criteria")
        constraints = self._extract_bullets(body, "Constraints")

        # Try to extract goal from objective section if not in frontmatter
        goal = fm.get("goal", "")
        if not goal:
            goal = self._extract_quote(body, "Objective")
        if not goal and expectations:
            goal = expectations[0]

        return ParsedIntent(
            id=fm.get("id", ""),
            title=fm.get("title", ""),
            goal=goal,
            tier=fm.get("tier"),
            owner=fm.get("owner"),
            branch=fm.get("branch"),
            expectations=expectations,
            constraints=constraints,
            raw_content=content,
        )

    def parse_markdown_file(self, path: Path) -> ParsedIntent:
        """Parse markdown intent from file path.

        Args:
            path: Path to the markdown file.

        Returns:
            ParsedIntent with extracted fields.

        Raises:
            FileNotFoundError: If file doesn't exist.
        """
        content = path.read_text()
        return self.parse_markdown(content)

    def parse_epic_entry(self, epic: Epic, spec_id: str) -> ParsedIntent:
        """Parse epic spec entry as intent.

        Args:
            epic: Loaded Epic instance.
            spec_id: The spec ID to extract from the epic.

        Returns:
            ParsedIntent with fields from the epic spec entry.

        Raises:
            ValueError: If spec not found in epic.
        """
        spec = epic.get_spec(spec_id)
        if spec is None:
            available = [s.id for s in epic.specs]
            raise ValueError(
                f"Spec '{spec_id}' not found in epic '{epic.id}'. "
                f"Available: {', '.join(available)}"
            )

        return ParsedIntent(
            id=spec.id,
            title=spec.title or spec.id,
            goal=spec.expectations[0] if spec.expectations else "",
            branch=spec.branch,
            epic_id=epic.id,
            repo_id=spec.repo,
            owner=epic.owner,  # Inherit owner from epic
            expectations=list(spec.expectations),
            constraints=list(spec.constraints),
        )

    def _extract_bullets(self, content: str, section: str) -> list[str]:
        """Extract bullet points from a section.

        Args:
            content: Markdown content.
            section: Section header to find (case-insensitive).

        Returns:
            List of bullet point texts (stripped of markers).
        """
        # Find the section header
        header_pattern = rf"^##\s+{re.escape(section)}\s*$"
        lines = content.split("\n")
        in_section = False
        results: list[str] = []

        for line in lines:
            # Check if this is the section header
            if re.match(header_pattern, line, re.IGNORECASE):
                in_section = True
                continue

            # Check if we've hit another section
            if in_section and re.match(r"^##\s+", line):
                break

            # Extract bullet points
            if in_section:
                stripped = line.strip()
                if stripped.startswith("-") or stripped.startswith("*"):
                    # Strip bullet marker
                    text = stripped.lstrip("-* ").strip()
                    # Remove checkbox markers like [ ] or [x]
                    text = re.sub(r"^\[[ xX]?\]\s*", "", text)
                    if text:
                        results.append(text)

        return results

    def _extract_quote(self, content: str, section: str) -> str:
        """Extract blockquote from a section.

        Args:
            content: Markdown content.
            section: Section header to find.

        Returns:
            Text of the first blockquote, or empty string.
        """
        # Find the section header
        header_pattern = rf"^##\s+{re.escape(section)}\s*$"
        lines = content.split("\n")
        in_section = False

        for line in lines:
            # Check if this is the section header
            if re.match(header_pattern, line, re.IGNORECASE):
                in_section = True
                continue

            # Check if we've hit another section
            if in_section and re.match(r"^##\s+", line):
                break

            # Extract blockquote
            if in_section and line.strip().startswith(">"):
                text = line.strip().lstrip("> ").strip()
                if text:
                    return text

        return ""
