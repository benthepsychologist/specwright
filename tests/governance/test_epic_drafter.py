"""Tests for LLM-assisted epic drafting."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spec.governance.epic_drafter import EpicDrafter, check_claude_available


class TestEpicDrafter:
    """Tests for the EpicDrafter class."""

    def test_init_with_defaults(self):
        """Test EpicDrafter initialization with default values."""
        drafter = EpicDrafter(
            title="Test Epic",
            goal="Test the epic drafting",
            owner="testuser",
        )

        assert drafter.title == "Test Epic"
        assert drafter.goal == "Test the epic drafting"
        assert drafter.owner == "testuser"
        assert drafter.repo_path == Path.cwd()
        assert drafter.context is None
        assert drafter.model == "claude-sonnet-4-20250514"
        assert drafter.timeout_s == 600
        assert drafter.max_turns == 50

    def test_init_with_custom_values(self, tmp_path):
        """Test EpicDrafter initialization with custom values."""
        drafter = EpicDrafter(
            title="Custom Epic",
            goal="Custom goal",
            owner="customuser",
            repo_path=tmp_path,
            context="Some context",
            model="claude-opus-4-20250514",
            timeout_s=300,
            max_turns=25,
        )

        assert drafter.title == "Custom Epic"
        assert drafter.repo_path == tmp_path
        assert drafter.context == "Some context"
        assert drafter.model == "claude-opus-4-20250514"
        assert drafter.timeout_s == 300
        assert drafter.max_turns == 25

    def test_build_prompt_basic(self):
        """Test prompt building without context."""
        drafter = EpicDrafter(
            title="Add Caching",
            goal="Implement Redis caching for API responses",
            owner="dev",
        )

        prompt = drafter._build_prompt()

        assert "Add Caching" in prompt
        assert "Implement Redis caching for API responses" in prompt
        assert "dev" in prompt
        assert "patch:" in prompt
        assert "mode: headless" in prompt

    def test_build_prompt_with_context(self):
        """Test prompt building with additional context."""
        drafter = EpicDrafter(
            title="Test",
            goal="Test goal",
            owner="user",
            context="This is additional context about the task.",
        )

        prompt = drafter._build_prompt()

        assert "Additional Context" in prompt
        assert "This is additional context about the task." in prompt

    def test_parse_patch_with_yaml_block(self):
        """Test parsing response with yaml code block."""
        drafter = EpicDrafter(title="T", goal="G", owner="O")

        response = """Here's the patch:

```yaml
patch:
  intent:
    narrative: |
      This is the narrative.
  specs:
    - id: t001-01
      title: First Spec
```

Done."""

        patch = drafter._parse_patch(response)

        assert "intent" in patch
        assert patch["intent"]["narrative"].strip() == "This is the narrative."
        assert len(patch["specs"]) == 1
        assert patch["specs"][0]["id"] == "t001-01"

    def test_parse_patch_direct_yaml(self):
        """Test parsing response with direct YAML (no code block)."""
        drafter = EpicDrafter(title="T", goal="G", owner="O")

        response = """intent:
  narrative: Direct YAML narrative
specs:
  - id: s01
    title: Spec One
"""

        patch = drafter._parse_patch(response)

        assert patch["intent"]["narrative"] == "Direct YAML narrative"
        assert patch["specs"][0]["id"] == "s01"

    def test_parse_patch_with_patch_wrapper(self):
        """Test parsing response with 'patch:' wrapper."""
        drafter = EpicDrafter(title="T", goal="G", owner="O")

        response = """```yaml
patch:
  intent:
    narrative: Wrapped narrative
```"""

        patch = drafter._parse_patch(response)

        assert patch["intent"]["narrative"] == "Wrapped narrative"

    def test_parse_patch_invalid_yaml(self):
        """Test parsing invalid YAML raises RuntimeError."""
        drafter = EpicDrafter(title="T", goal="G", owner="O")

        response = "this is not valid: yaml: content:"

        with pytest.raises(RuntimeError, match="Failed to parse YAML"):
            drafter._parse_patch(response)

    @patch("shutil.which")
    def test_check_claude_available_found(self, mock_which):
        """Test check_claude_available when claude is found."""
        mock_which.return_value = "/usr/local/bin/claude"
        assert check_claude_available() is True

    @patch("shutil.which")
    def test_check_claude_available_not_found(self, mock_which):
        """Test check_claude_available when claude is not found."""
        mock_which.return_value = None
        assert check_claude_available() is False

    @patch("shutil.which")
    def test_call_claude_code_not_found(self, mock_which):
        """Test that _call_claude_code raises when claude not found."""
        mock_which.return_value = None

        drafter = EpicDrafter(title="T", goal="G", owner="O")

        with pytest.raises(FileNotFoundError, match="claude CLI not found"):
            drafter._call_claude_code("test prompt")
