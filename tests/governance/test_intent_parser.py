"""Tests for intent parser."""

import pytest

from spec.governance.intent_parser import IntentParser, ParsedIntent


class TestIntentParser:
    """Tests for IntentParser class."""

    def test_parse_markdown_with_frontmatter(self):
        """Parse markdown with YAML frontmatter extracts all fields."""
        content = """---
id: t005-03-workstation-containers
title: "Workstation containers: life + dev"
tier: B
owner: benthepsychologist
goal: "life container starts reliably"
branch: feat/t005-03-workstation-containers
---

# t005-03: Workstation containers

## Objective

> life container starts reliably

## Acceptance Criteria

- life container starts reliably
- dev container starts reliably

## Constraints

- Maintain trust gradient: agent < life < dev
"""
        parser = IntentParser()
        intent = parser.parse_markdown(content)

        assert intent.id == "t005-03-workstation-containers"
        assert intent.title == "Workstation containers: life + dev"
        assert intent.tier == "B"
        assert intent.owner == "benthepsychologist"
        assert intent.goal == "life container starts reliably"
        assert intent.branch == "feat/t005-03-workstation-containers"
        assert intent.expectations == [
            "life container starts reliably",
            "dev container starts reliably",
        ]
        assert intent.constraints == ["Maintain trust gradient: agent < life < dev"]

    def test_parse_markdown_without_frontmatter(self):
        """Parse markdown without frontmatter extracts from body."""
        content = """# Feature: Add dark mode

## Objective

> Enable users to switch to dark theme

## Acceptance Criteria

- [ ] Toggle button appears in settings
- [x] Theme persists across sessions
- Dark mode applies to all components

## Constraints

- Must use CSS variables for theming
"""
        parser = IntentParser()
        intent = parser.parse_markdown(content)

        assert intent.id == ""
        assert intent.title == ""
        assert intent.goal == "Enable users to switch to dark theme"
        assert intent.expectations == [
            "Toggle button appears in settings",
            "Theme persists across sessions",
            "Dark mode applies to all components",
        ]
        assert intent.constraints == ["Must use CSS variables for theming"]

    def test_parse_markdown_goal_from_expectations(self):
        """If no goal in frontmatter or objective, use first expectation."""
        content = """---
id: test-spec
title: Test Spec
---

## Acceptance Criteria

- First thing must work
- Second thing too
"""
        parser = IntentParser()
        intent = parser.parse_markdown(content)

        assert intent.goal == "First thing must work"

    def test_parse_markdown_empty_content(self):
        """Empty content returns empty ParsedIntent."""
        parser = IntentParser()
        intent = parser.parse_markdown("")

        assert intent.id == ""
        assert intent.title == ""
        assert intent.goal == ""
        assert intent.expectations == []
        assert intent.constraints == []

    def test_parse_markdown_preserves_raw_content(self):
        """Raw content is preserved in ParsedIntent."""
        content = "# Some content\n\nWith body text."
        parser = IntentParser()
        intent = parser.parse_markdown(content)

        assert intent.raw_content == content

    def test_parse_markdown_invalid_frontmatter(self):
        """Invalid YAML frontmatter is handled gracefully."""
        content = """---
invalid: yaml: content:
---

## Acceptance Criteria

- Still parses body
"""
        parser = IntentParser()
        intent = parser.parse_markdown(content)

        # Should still parse body even with invalid frontmatter
        assert intent.expectations == ["Still parses body"]

    def test_extract_bullets_with_asterisks(self):
        """Bullet extraction works with asterisk markers."""
        content = """## Acceptance Criteria

* First item
* Second item
"""
        parser = IntentParser()
        bullets = parser._extract_bullets(content, "Acceptance Criteria")

        assert bullets == ["First item", "Second item"]

    def test_extract_bullets_case_insensitive(self):
        """Section header matching is case-insensitive."""
        content = """## ACCEPTANCE CRITERIA

- Item one
"""
        parser = IntentParser()
        bullets = parser._extract_bullets(content, "acceptance criteria")

        assert bullets == ["Item one"]


class TestIntentParserEpicEntry:
    """Tests for parsing epic entries."""

    def test_parse_epic_entry_extracts_fields(self):
        """Parse epic spec entry extracts all SpecRef fields."""
        from datetime import datetime

        from spec.epic.schema import Epic, Intent, SpecRef, SpecStatus, Target

        epic = Epic(
            version="1.0",
            kind="epic",
            id="t005-vmctl-docker-isolation",
            title="VMctl Docker isolation",
            owner="benthepsychologist",
            created=datetime.now(),
            updated=datetime.now(),
            intent=Intent(goal="Isolate containers"),
            targets=[
                Target(
                    id="vm-workstation-manager",
                    repo_path="/workspace/vm-workstation-manager",
                    default_branch="main",
                )
            ],
            specs=[
                SpecRef(
                    id="t005-03-workstation-containers",
                    repo="vm-workstation-manager",
                    branch="feat/t005-03",
                    title="Workstation containers: life + dev",
                    status=SpecStatus.PLANNED,
                    expectations=[
                        "life container starts reliably",
                        "dev container starts reliably",
                    ],
                    constraints=["Maintain trust gradient: agent < life < dev"],
                )
            ],
        )

        parser = IntentParser()
        intent = parser.parse_epic_entry(epic, "t005-03-workstation-containers")

        assert intent.id == "t005-03-workstation-containers"
        assert intent.title == "Workstation containers: life + dev"
        assert intent.goal == "life container starts reliably"
        assert intent.branch == "feat/t005-03"
        assert intent.epic_id == "t005-vmctl-docker-isolation"
        assert intent.repo_id == "vm-workstation-manager"
        assert intent.owner == "benthepsychologist"  # Inherited from epic
        assert intent.expectations == [
            "life container starts reliably",
            "dev container starts reliably",
        ]
        assert intent.constraints == ["Maintain trust gradient: agent < life < dev"]

    def test_parse_epic_entry_not_found_raises(self):
        """Missing spec raises ValueError with available specs."""
        from datetime import datetime

        from spec.epic.schema import Epic, Intent, SpecRef, Target

        epic = Epic(
            version="1.0",
            kind="epic",
            id="t005",
            title="Test Epic",
            owner="test",
            created=datetime.now(),
            updated=datetime.now(),
            intent=Intent(goal="Test"),
            targets=[Target(id="repo", repo_path="/", default_branch="main")],
            specs=[
                SpecRef(id="spec-a", repo="repo", branch="main"),
                SpecRef(id="spec-b", repo="repo", branch="main"),
            ],
        )

        parser = IntentParser()
        with pytest.raises(ValueError) as exc_info:
            parser.parse_epic_entry(epic, "spec-missing")

        assert "spec-missing" in str(exc_info.value)
        assert "spec-a" in str(exc_info.value)
        assert "spec-b" in str(exc_info.value)

    def test_parse_epic_entry_uses_id_as_title_fallback(self):
        """If spec has no title, use id as title."""
        from datetime import datetime

        from spec.epic.schema import Epic, Intent, SpecRef, Target

        epic = Epic(
            version="1.0",
            kind="epic",
            id="t005",
            title="Test Epic",
            owner="test",
            created=datetime.now(),
            updated=datetime.now(),
            intent=Intent(goal="Test"),
            targets=[Target(id="repo", repo_path="/", default_branch="main")],
            specs=[
                SpecRef(
                    id="spec-without-title",
                    repo="repo",
                    branch="main",
                    title=None,  # No title
                )
            ],
        )

        parser = IntentParser()
        intent = parser.parse_epic_entry(epic, "spec-without-title")

        assert intent.title == "spec-without-title"
