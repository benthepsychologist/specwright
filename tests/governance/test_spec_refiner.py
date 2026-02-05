"""Tests for spec refiner (LLM-assisted refinement)."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from spec.governance.spec_refiner import (
    REFINEMENT_ALLOWLIST,
    SpecRefiner,
    check_claude_available,
)

SAMPLE_SPEC = """\
---
id: test-spec
title: "Test Feature"
tier: B
owner: testuser
goal: "Implement test feature"
branch: feat/test
status: draft
created: 2024-01-01T00:00:00Z
---

# test-spec: Test Feature

**Epic:** test-epic
**Branch:** `feat/test`
**Tier:** B

## Objective

> Implement test feature

## Problem

1. First problem

## Acceptance Criteria

- [ ] It should work
"""


class TestSpecRefiner:
    """Tests for SpecRefiner class."""

    @pytest.fixture
    def refiner(self, tmp_path):
        """Create a refiner for testing."""
        spec_path = tmp_path / "spec.md"
        spec_path.write_text(SAMPLE_SPEC)

        return SpecRefiner(
            spec_path=spec_path,
            original_content=SAMPLE_SPEC,
            repo_path=tmp_path,
        )

    def test_refinement_allowlist_is_read_only(self):
        """Allowlist contains only read-only tools."""
        # No write tools should be in the allowlist
        write_tools = ["Write", "Edit", "NotebookEdit"]
        for tool in write_tools:
            assert tool not in REFINEMENT_ALLOWLIST

        # Should have common read tools
        assert "Read" in REFINEMENT_ALLOWLIST
        assert "Glob" in REFINEMENT_ALLOWLIST
        assert "Grep" in REFINEMENT_ALLOWLIST

    def test_build_analysis_prompt_includes_spec(self, refiner):
        """Analysis prompt includes the original spec."""
        prompt = refiner._build_analysis_prompt()

        assert "test-spec" in prompt
        assert "Test Feature" in prompt
        assert "First problem" in prompt
        assert "Analysis Tasks" in prompt
        assert "Do NOT output a modified spec" in prompt

    def test_build_refinement_prompt_includes_spec(self, refiner):
        """Refinement prompt includes the original spec."""
        prompt = refiner._build_refinement_prompt()

        assert "test-spec" in prompt
        assert "Test Feature" in prompt
        assert "Preserve User Intent" in prompt
        assert "Output ONLY the spec markdown" in prompt

    def test_context_included_in_prompts(self, tmp_path):
        """Additional context is included in prompts."""
        spec_path = tmp_path / "spec.md"
        spec_path.write_text(SAMPLE_SPEC)

        refiner = SpecRefiner(
            spec_path=spec_path,
            original_content=SAMPLE_SPEC,
            repo_path=tmp_path,
            context="Please focus on the Problem section.",
        )

        analysis_prompt = refiner._build_analysis_prompt()
        refinement_prompt = refiner._build_refinement_prompt()

        assert "Please focus on the Problem section" in analysis_prompt
        assert "Please focus on the Problem section" in refinement_prompt

    def test_no_context_section_when_none(self, refiner):
        """No context section when context is None."""
        prompt = refiner._build_analysis_prompt()
        assert "Additional Context" not in prompt

    @patch("spec.governance.spec_refiner.shutil.which")
    def test_claude_not_found_raises(self, mock_which, refiner):
        """Missing claude CLI raises FileNotFoundError."""
        mock_which.return_value = None

        with pytest.raises(FileNotFoundError) as exc_info:
            refiner._call_claude_code("test prompt")

        assert "claude CLI not found" in str(exc_info.value)

    @patch("spec.governance.spec_refiner.shutil.which")
    @patch("spec.governance.spec_refiner.subprocess.Popen")
    def test_successful_claude_call(self, mock_popen, mock_which, refiner):
        """Successful Claude Code call returns output."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("Analysis output here", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        result = refiner._call_claude_code("test prompt")

        assert result == "Analysis output here"
        mock_proc.communicate.assert_called_once()

    @patch("spec.governance.spec_refiner.shutil.which")
    @patch("spec.governance.spec_refiner.subprocess.Popen")
    def test_claude_failure_raises_runtime_error(
        self, mock_popen, mock_which, refiner
    ):
        """Claude Code failure raises RuntimeError."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "Error: something went wrong")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        with pytest.raises(RuntimeError) as exc_info:
            refiner._call_claude_code("test prompt")

        assert "Claude Code failed" in str(exc_info.value)

    @patch("spec.governance.spec_refiner.shutil.which")
    @patch("spec.governance.spec_refiner.subprocess.Popen")
    @patch("spec.governance.spec_refiner.os.killpg")
    @patch("spec.governance.spec_refiner.os.getpgid")
    def test_timeout_kills_process(
        self, mock_getpgid, mock_killpg, mock_popen, mock_which, tmp_path
    ):
        """Timeout kills the process and raises RuntimeError."""
        spec_path = tmp_path / "spec.md"
        spec_path.write_text(SAMPLE_SPEC)

        refiner = SpecRefiner(
            spec_path=spec_path,
            original_content=SAMPLE_SPEC,
            repo_path=tmp_path,
            timeout_s=1,
        )

        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("claude", 1)
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        mock_getpgid.return_value = 12345

        with pytest.raises(RuntimeError) as exc_info:
            refiner._call_claude_code("test prompt")

        assert "timed out" in str(exc_info.value)
        mock_killpg.assert_called()

    @patch("spec.governance.spec_refiner.shutil.which")
    @patch("spec.governance.spec_refiner.subprocess.Popen")
    def test_analyze_calls_claude_with_analysis_prompt(
        self, mock_popen, mock_which, refiner
    ):
        """analyze() calls Claude with analysis prompt."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("### Summary\nLooks good", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        result = refiner.analyze()

        assert "Looks good" in result

        # Verify prompt contains analysis keywords
        stdin_input = mock_proc.communicate.call_args[1]["input"]
        assert "Analysis Tasks" in stdin_input
        assert "Do NOT output a modified spec" in stdin_input

    @patch("spec.governance.spec_refiner.shutil.which")
    @patch("spec.governance.spec_refiner.subprocess.Popen")
    def test_refine_calls_claude_with_refinement_prompt(
        self, mock_popen, mock_which, refiner
    ):
        """refine() calls Claude with refinement prompt."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        # Return something that starts with --- to be valid spec
        mock_proc.communicate.return_value = ("---\nid: test-spec\n\nRefined content", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        result = refiner.refine()

        assert "---" in result
        assert "test-spec" in result

    @patch("spec.governance.spec_refiner.shutil.which")
    @patch("spec.governance.spec_refiner.subprocess.Popen")
    def test_refine_extracts_spec_from_wrapped_response(
        self, mock_popen, mock_which, refiner
    ):
        """refine() extracts spec when wrapped in other text."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        # Response with spec embedded in explanatory text
        response = """Here is the refined spec:

---
id: test-spec
title: "Refined Test"
---

# Refined content

Some additional text after."""
        mock_proc.communicate.return_value = (response, "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        result = refiner.refine()

        # Should extract just the spec portion
        assert result.startswith("---")
        assert "id: test-spec" in result

    @patch("spec.governance.spec_refiner.shutil.which")
    @patch("spec.governance.spec_refiner.subprocess.Popen")
    def test_refine_uses_model_parameter(self, mock_popen, mock_which, tmp_path):
        """refine() uses specified model."""
        spec_path = tmp_path / "spec.md"
        spec_path.write_text(SAMPLE_SPEC)

        refiner = SpecRefiner(
            spec_path=spec_path,
            original_content=SAMPLE_SPEC,
            repo_path=tmp_path,
            model="claude-opus-4-20250514",
        )

        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("result", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        refiner.refine()

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-opus-4-20250514"

    @patch("spec.governance.spec_refiner.shutil.which")
    @patch("spec.governance.spec_refiner.subprocess.Popen")
    def test_refine_runs_in_repo_directory(self, mock_popen, mock_which, refiner):
        """refine() runs claude in the repo directory."""
        mock_which.return_value = "/usr/bin/claude"
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("result", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        refiner.refine()

        call_args = mock_popen.call_args
        assert call_args[1]["cwd"] == refiner.repo_path


class TestExtractSpecContent:
    """Tests for spec content extraction."""

    @pytest.fixture
    def refiner(self, tmp_path):
        """Create a refiner for testing."""
        spec_path = tmp_path / "spec.md"
        spec_path.write_text(SAMPLE_SPEC)

        return SpecRefiner(
            spec_path=spec_path,
            original_content=SAMPLE_SPEC,
            repo_path=tmp_path,
        )

    def test_extracts_clean_spec(self, refiner):
        """Extracts spec that starts with frontmatter."""
        text = "---\nid: test\ntitle: Test\n---\n\n# Content"
        result = refiner._extract_spec_content(text)
        assert result == text.strip()

    def test_extracts_embedded_spec(self, refiner):
        """Extracts spec embedded in other text."""
        text = """Some explanation here.

---
id: test
title: Test
---

# Content

More text after."""
        result = refiner._extract_spec_content(text)
        assert result.startswith("---")
        assert "id: test" in result

    def test_returns_none_for_no_spec(self, refiner):
        """Returns None when no spec found."""
        text = "Just some regular text without a spec."
        result = refiner._extract_spec_content(text)
        assert result is None


class TestCheckClaudeAvailable:
    """Tests for check_claude_available helper."""

    @patch("spec.governance.spec_refiner.shutil.which")
    def test_claude_available(self, mock_which):
        """Returns True when claude is in PATH."""
        mock_which.return_value = "/usr/bin/claude"
        assert check_claude_available() is True

    @patch("spec.governance.spec_refiner.shutil.which")
    def test_claude_not_available(self, mock_which):
        """Returns False when claude is not in PATH."""
        mock_which.return_value = None
        assert check_claude_available() is False
