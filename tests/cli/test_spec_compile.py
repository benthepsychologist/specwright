"""Tests for `spec spec-compile` command output location and emitted step metadata.

Note: In v2, the v1 spec compile command was renamed to `spec spec-compile`
to make room for the v2 executor `spec compile` command.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from spec.cli.spec import app

runner = CliRunner()


@pytest.fixture
def temp_project_v06(tmp_path: Path) -> Path:
    """Create a temp project with v0.6 config and repo-local .specwright dirs."""
    config_path = tmp_path / ".specwright.yaml"
    config_path.write_text(
        "\n".join(
            [
                "version: '0.6'",
                "governor:",
                "  path: ~/.local/local-governor",
                "project_slug: testproj",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (tmp_path / ".specwright" / "specs").mkdir(parents=True)
    (tmp_path / ".specwright" / "aips").mkdir(parents=True)

    return tmp_path


def test_compile_repo_local_spec_defaults_to_repo_aips(temp_project_v06: Path) -> None:
    """Compiling a spec under .specwright/specs should write to .specwright/aips (even in v0.6)."""
    original_dir = Path.cwd()
    os.chdir(temp_project_v06)
    try:
        spec_path = Path(".specwright/specs/test-spec.md")
        spec_path.write_text(
            "\n".join(
                [
                    "---",
                    "title: Test Spec",
                    "tier: B",
                    "owner: test",
                    "goal: Test compile output paths",
                    "---",
                    "",
                    "# Test Spec",
                    "",
                    "## Plan",
                    "",
                    "### Step 1: Example",
                    "",
                    "**Prompt:**",
                    "",
                    "Do a thing.",
                    "",
                    "**Suggested Paths:** `src/**`, `pyproject.toml`",
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        # Note: v1 spec compile renamed to spec-compile in v2
        result = runner.invoke(app, ["spec-compile", str(spec_path), "--overwrite"])
        assert result.exit_code == 0, result.output

        output_path = Path(".specwright/aips/test-spec.yaml")
        assert output_path.exists(), "Expected repo-local AIP to be written"

        aip = yaml.safe_load(output_path.read_text(encoding="utf-8"))
        step1 = next(s for s in aip["plan"] if s["step_id"] == "step-001")

        # suggested_paths provides soft guidance (not enforced)
        assert "suggested_paths" in step1
        assert "src/**" in step1["suggested_paths"]
        assert "pyproject.toml" in step1["suggested_paths"]
    finally:
        os.chdir(original_dir)
