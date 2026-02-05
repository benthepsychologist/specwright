"""Tests for LLM-assisted spec entry drafting."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from spec.epic.schema import Epic, Intent, SpecRef, SpecStatus, Target
from spec.governance.spec_entry_drafter import SpecEntryDrafter, check_claude_available


def make_epic(
    with_targets: bool = True,
    with_specs: bool = False,
) -> Epic:
    """Create a test epic."""
    targets = []
    if with_targets:
        targets = [
            Target(
                id="myrepo",
                repo_path="/workspace/myrepo",
                default_branch="main",
            )
        ]

    specs = []
    if with_specs:
        specs = [
            SpecRef(
                id="t001-01",
                repo="myrepo",
                branch="feat/auth",
                title="Auth Spec",
                status=SpecStatus.PLANNED,
                depends_on=[],
            ),
            SpecRef(
                id="t001-02",
                repo="myrepo",
                branch="feat/tokens",
                title="Tokens Spec",
                status=SpecStatus.PLANNED,
                depends_on=["t001-01"],
            ),
        ]

    return Epic(
        version="0.2",
        kind="epic",
        id="t001-test",
        title="Test Epic",
        owner="testuser",
        created=datetime.now(UTC),
        updated=datetime.now(UTC),
        intent=Intent(goal="Test the thing", narrative="Some narrative."),
        targets=targets,
        specs=specs,
    )


class TestSpecEntryDrafter:
    """Tests for the SpecEntryDrafter class."""

    def test_init_basic(self):
        """Test basic initialization."""
        epic = make_epic()
        drafter = SpecEntryDrafter(
            epic=epic,
            description="Add caching layer",
        )

        assert drafter.epic == epic
        assert drafter.description == "Add caching layer"
        assert drafter.target_id is None
        assert drafter.context is None

    def test_init_with_options(self):
        """Test initialization with all options."""
        epic = make_epic()
        drafter = SpecEntryDrafter(
            epic=epic,
            description="Add caching",
            target_id="myrepo",
            context="Extra context",
            model="claude-opus-4-20250514",
            timeout_s=300,
            max_turns=25,
        )

        assert drafter.target_id == "myrepo"
        assert drafter.context == "Extra context"
        assert drafter.model == "claude-opus-4-20250514"

    def test_get_repo_path_with_target_id(self, tmp_path):
        """Test _get_repo_path with explicit target_id."""
        epic = make_epic()
        epic.targets[0].repo_path = str(tmp_path)

        drafter = SpecEntryDrafter(
            epic=epic,
            description="test",
            target_id="myrepo",
        )

        assert drafter._get_repo_path() == tmp_path

    def test_get_repo_path_missing_target(self):
        """Test _get_repo_path raises for missing target."""
        epic = make_epic()
        drafter = SpecEntryDrafter(
            epic=epic,
            description="test",
            target_id="nonexistent",
        )

        with pytest.raises(ValueError, match="Target 'nonexistent' not found"):
            drafter._get_repo_path()

    def test_get_repo_path_first_target(self, tmp_path):
        """Test _get_repo_path uses first target when no target_id."""
        epic = make_epic()
        epic.targets[0].repo_path = str(tmp_path)

        drafter = SpecEntryDrafter(epic=epic, description="test")

        assert drafter._get_repo_path() == tmp_path

    def test_get_repo_path_no_targets(self):
        """Test _get_repo_path falls back to cwd when no targets."""
        epic = make_epic(with_targets=False)
        drafter = SpecEntryDrafter(epic=epic, description="test")

        from pathlib import Path
        assert drafter._get_repo_path() == Path.cwd()

    def test_infer_spec_id_pattern_no_specs(self):
        """Test pattern inference with no existing specs."""
        epic = make_epic()
        drafter = SpecEntryDrafter(epic=epic, description="test")

        pattern = drafter._infer_spec_id_pattern()

        assert "t001" in pattern  # Epic prefix

    def test_infer_spec_id_pattern_with_specs(self):
        """Test pattern inference with existing specs."""
        epic = make_epic(with_specs=True)
        drafter = SpecEntryDrafter(epic=epic, description="test")

        pattern = drafter._infer_spec_id_pattern()

        assert "t001-03" in pattern or "03" in pattern

    def test_build_prompt_includes_epic_context(self):
        """Test prompt includes epic information."""
        epic = make_epic(with_specs=True)
        drafter = SpecEntryDrafter(
            epic=epic,
            description="Add logging functionality",
        )

        prompt = drafter._build_prompt()

        assert "t001-test" in prompt
        assert "Test the thing" in prompt
        assert "t001-01" in prompt  # Existing spec
        assert "Add logging functionality" in prompt
        assert "mode: headless" in prompt

    def test_build_prompt_includes_context(self):
        """Test prompt includes additional context."""
        epic = make_epic()
        drafter = SpecEntryDrafter(
            epic=epic,
            description="test",
            context="Consider using the existing Logger class.",
        )

        prompt = drafter._build_prompt()

        assert "Consider using the existing Logger class." in prompt

    def test_parse_specs_basic(self):
        """Test parsing specs from response."""
        epic = make_epic()
        drafter = SpecEntryDrafter(epic=epic, description="test")

        response = """```yaml
specs:
  - id: t001-03
    title: Logging Spec
    repo: myrepo
    branch: feat/logging
    path: specs/t001-03.md
    mode: headless
    expectations:
      - Add structured logging
    constraints:
      - Use existing logger interface
```"""

        specs = drafter._parse_specs(response)

        assert len(specs) == 1
        assert specs[0]["id"] == "t001-03"
        assert specs[0]["title"] == "Logging Spec"
        assert specs[0]["mode"] == "headless"
        assert len(specs[0]["expectations"]) == 1

    def test_parse_specs_multiple(self):
        """Test parsing multiple specs."""
        epic = make_epic()
        drafter = SpecEntryDrafter(epic=epic, description="test")

        response = """```yaml
specs:
  - id: s01
    title: First
    repo: r1
    branch: b1
  - id: s02
    title: Second
    repo: r1
    branch: b2
    depends_on: [s01]
```"""

        specs = drafter._parse_specs(response)

        assert len(specs) == 2
        assert specs[0]["id"] == "s01"
        assert specs[1]["id"] == "s02"
        assert specs[1]["depends_on"] == ["s01"]

    def test_parse_specs_invalid_yaml(self):
        """Test parsing invalid YAML raises."""
        epic = make_epic()
        drafter = SpecEntryDrafter(epic=epic, description="test")

        with pytest.raises(RuntimeError, match="Failed to parse YAML"):
            drafter._parse_specs("not: valid: yaml:")

    def test_parse_specs_missing_specs_key(self):
        """Test parsing response without specs key."""
        epic = make_epic()
        drafter = SpecEntryDrafter(epic=epic, description="test")

        response = "something_else: value"
        specs = drafter._parse_specs(response)

        assert specs == []

    @patch("shutil.which")
    def test_check_claude_available(self, mock_which):
        """Test check_claude_available function."""
        mock_which.return_value = "/usr/bin/claude"
        assert check_claude_available() is True

        mock_which.return_value = None
        assert check_claude_available() is False
