"""Tests for spec refine CLI command."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from spec.cli.spec import app

runner = CliRunner()


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


class TestSpecRefineHelp:
    """Tests for spec refine --help."""

    def test_refine_help_shows_usage(self):
        """spec refine --help shows usage information."""
        result = runner.invoke(app, ["refine", "--help"])
        assert result.exit_code == 0
        assert "Refine an existing spec" in result.output
        assert "--context" in result.output
        assert "--dry-run" in result.output
        assert "--apply" in result.output
        assert "--model" in result.output


class TestSpecRefineValidation:
    """Tests for argument validation."""

    def test_spec_file_must_exist(self, tmp_path):
        """Missing spec file fails with error."""
        result = runner.invoke(app, ["refine", str(tmp_path / "nonexistent.md")])
        assert result.exit_code != 0

    def test_dry_run_and_apply_mutually_exclusive(self, tmp_path):
        """Cannot use --dry-run and --apply together."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(SAMPLE_SPEC)

        result = runner.invoke(
            app, ["refine", str(spec_file), "--dry-run", "--apply"]
        )
        assert result.exit_code == 1
        assert "Cannot use --dry-run and --apply together" in result.output

    def test_context_file_must_exist(self, tmp_path):
        """Missing context file fails with error."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(SAMPLE_SPEC)

        result = runner.invoke(
            app,
            ["refine", str(spec_file), "--context", str(tmp_path / "nonexistent.md")],
        )
        assert result.exit_code == 1
        assert "Context file not found" in result.output


class TestSpecRefineDryRun:
    """Tests for --dry-run mode."""

    @patch("spec.governance.spec_refiner.SpecRefiner")
    def test_dry_run_shows_suggestions(self, mock_refiner_class, tmp_path):
        """--dry-run shows analysis suggestions without modifying file."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(SAMPLE_SPEC)

        mock_refiner = MagicMock()
        mock_refiner.analyze.return_value = "### Summary\nSpec needs more detail."
        mock_refiner_class.return_value = mock_refiner

        result = runner.invoke(app, ["refine", str(spec_file), "--dry-run"])
        assert result.exit_code == 0
        assert "Suggested Improvements" in result.output
        mock_refiner.analyze.assert_called_once()
        mock_refiner.refine.assert_not_called()

        # File should be unchanged
        assert spec_file.read_text() == SAMPLE_SPEC


class TestSpecRefineApply:
    """Tests for --apply mode."""

    @patch("spec.governance.spec_refiner.SpecRefiner")
    def test_apply_modifies_file(self, mock_refiner_class, tmp_path):
        """--apply writes refined content to file."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(SAMPLE_SPEC)

        refined_content = SAMPLE_SPEC.replace("First problem", "First problem (refined)")
        mock_refiner = MagicMock()
        mock_refiner.refine.return_value = refined_content
        mock_refiner_class.return_value = mock_refiner

        result = runner.invoke(app, ["refine", str(spec_file), "--apply"])
        assert result.exit_code == 0
        assert "Applied refinements" in result.output
        mock_refiner.refine.assert_called_once()

        # File should be updated
        assert "(refined)" in spec_file.read_text()


class TestSpecRefineDiff:
    """Tests for default diff mode."""

    @patch("spec.governance.spec_refiner.SpecRefiner")
    def test_default_shows_diff(self, mock_refiner_class, tmp_path):
        """Default mode shows diff of proposed changes."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(SAMPLE_SPEC)

        refined_content = SAMPLE_SPEC.replace("First problem", "Improved problem description")
        mock_refiner = MagicMock()
        mock_refiner.refine.return_value = refined_content
        mock_refiner_class.return_value = mock_refiner

        result = runner.invoke(app, ["refine", str(spec_file)])
        assert result.exit_code == 0
        assert "Proposed Changes" in result.output
        mock_refiner.refine.assert_called_once()

        # File should be unchanged
        assert spec_file.read_text() == SAMPLE_SPEC

    @patch("spec.governance.spec_refiner.SpecRefiner")
    def test_no_changes_shows_message(self, mock_refiner_class, tmp_path):
        """Shows message when no changes are suggested."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(SAMPLE_SPEC)

        # Return same content
        mock_refiner = MagicMock()
        mock_refiner.refine.return_value = SAMPLE_SPEC
        mock_refiner_class.return_value = mock_refiner

        result = runner.invoke(app, ["refine", str(spec_file)])
        assert result.exit_code == 0
        assert "No changes suggested" in result.output


class TestSpecRefineContext:
    """Tests for --context flag."""

    @patch("spec.governance.spec_refiner.SpecRefiner")
    def test_context_passed_to_refiner(self, mock_refiner_class, tmp_path):
        """--context file content is passed to refiner."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(SAMPLE_SPEC)

        context_file = tmp_path / "feedback.md"
        context_file.write_text("Please add more detail to the Problem section.")

        mock_refiner = MagicMock()
        mock_refiner.refine.return_value = SAMPLE_SPEC
        mock_refiner_class.return_value = mock_refiner

        result = runner.invoke(
            app, ["refine", str(spec_file), "--context", str(context_file)]
        )
        assert result.exit_code == 0

        # Verify context was passed to refiner
        call_kwargs = mock_refiner_class.call_args[1]
        assert "Please add more detail" in call_kwargs["context"]


class TestSpecRefineErrors:
    """Tests for error handling."""

    @patch("spec.governance.spec_refiner.SpecRefiner")
    def test_claude_not_found_error(self, mock_refiner_class, tmp_path):
        """Shows error when claude CLI not found."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(SAMPLE_SPEC)

        mock_refiner = MagicMock()
        mock_refiner.refine.side_effect = FileNotFoundError("claude CLI not found")
        mock_refiner_class.return_value = mock_refiner

        result = runner.invoke(app, ["refine", str(spec_file)])
        assert result.exit_code == 1
        assert "claude CLI" in result.output

    @patch("spec.governance.spec_refiner.SpecRefiner")
    def test_runtime_error_shown(self, mock_refiner_class, tmp_path):
        """Shows error on runtime failures."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(SAMPLE_SPEC)

        mock_refiner = MagicMock()
        mock_refiner.refine.side_effect = RuntimeError("Claude Code timed out")
        mock_refiner_class.return_value = mock_refiner

        result = runner.invoke(app, ["refine", str(spec_file)])
        assert result.exit_code == 1
        assert "timed out" in result.output
