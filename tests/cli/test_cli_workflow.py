"""Unit tests for CLI workflow commands."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from spec.cli.spec import app

runner = CliRunner()


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory with config."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    # Create minimal config structure
    config_dir = project_dir / "config"
    config_dir.mkdir()
    templates_dir = config_dir / "templates"
    templates_dir.mkdir()

    # Copy templates from real project
    import shutil
    real_templates = Path(__file__).parent.parent.parent / "config" / "templates"
    if real_templates.exists():
        shutil.copytree(real_templates, templates_dir, dirs_exist_ok=True)

    return project_dir


def test_config_discovery_finds_config(tmp_path):
    """Test that find_config walks up directory tree."""
    from spec.cli.spec import find_config

    # Create nested structure
    root = tmp_path / "project"
    root.mkdir()
    nested = root / "src" / "features"
    nested.mkdir(parents=True)

    # Create config at root
    config_path = root / ".specwright.yaml"
    config_data = {"version": "0.1", "paths": {"specs": "specs"}}
    config_path.write_text(yaml.dump(config_data))

    # Test from nested directory
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(nested)
        found_path, found_config = find_config()
        assert found_path == config_path
        assert found_config["version"] == "0.1"
    finally:
        os.chdir(old_cwd)


def test_config_discovery_uses_defaults_when_not_found(tmp_path):
    """Test that find_config returns defaults when no config exists."""
    import os

    from spec.cli.spec import find_config
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        found_path, found_config = find_config()
        assert found_path is None
        # v0.7 format: governor-based config with jobdefs (new default)
        assert found_config["version"] == "0.7"
        assert "governor" in found_config
        assert found_config["governor"]["path"] == "~/.local/local-governor"
        assert "jobdefs" in found_config
        assert "defaults" in found_config
    finally:
        os.chdir(old_cwd)


def test_init_creates_config_file(temp_project):
    """Test spec init creates .specwright.yaml with v0.7 format."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "Created" in result.stdout

        config_path = temp_project / ".specwright.yaml"
        assert config_path.exists()

        config = yaml.safe_load(config_path.read_text())
        # v0.7 format: governor-based with jobdefs and defaults
        assert config["version"] == "0.7"
        assert "governor" in config
        assert "jobdefs" in config
        assert "defaults" in config
    finally:
        os.chdir(old_cwd)


def test_init_prevents_overwrite_without_force(temp_project):
    """Test spec init won't overwrite existing config without --force."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        # Create config
        result1 = runner.invoke(app, ["init"])
        assert result1.exit_code == 0

        # Try to create again without --force should fail
        result2 = runner.invoke(app, ["init"])
        assert result2.exit_code == 1

        # Config file should still exist and be unchanged
        config_path = temp_project / ".specwright.yaml"
        assert config_path.exists()
    finally:
        os.chdir(old_cwd)


def test_init_overwrites_with_force(temp_project):
    """Test spec init --force overwrites existing config."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        # Create config
        runner.invoke(app, ["init"])

        # Modify it
        config_path = temp_project / ".specwright.yaml"
        config_path.write_text("modified: true")

        # Force overwrite
        result = runner.invoke(app, ["init", "--force"])
        assert result.exit_code == 0

        config = yaml.safe_load(config_path.read_text())
        assert "version" in config
        assert "modified" not in config
    finally:
        os.chdir(old_cwd)


def test_init_with_custom_governor_path(temp_project):
    """Test spec init with custom governor path."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        result = runner.invoke(app, ["init", "--governor", "/custom/path"])
        assert result.exit_code == 0

        config_path = temp_project / ".specwright.yaml"
        config = yaml.safe_load(config_path.read_text())
        assert config["governor"]["path"] == "/custom/path"
        assert "/custom/path" in config["jobdefs"]["path"]
    finally:
        os.chdir(old_cwd)


def test_config_displays_loaded_config(temp_project):
    """Test spec config displays configuration."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["config", "--show"])
        assert result.exit_code == 0
        assert "Configuration:" in result.stdout
        assert "version:" in result.stdout
        assert "governor:" in result.stdout
    finally:
        os.chdir(old_cwd)


def test_config_shows_defaults_when_no_config(temp_project):
    """Test spec config shows defaults when no config file exists."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)

        result = runner.invoke(app, ["config", "--show"])
        assert result.exit_code == 0
        # Shows defaults when no config found
        output = result.stdout
        assert "No .specwright.yaml found" in output
        assert "Using defaults:" in output
    finally:
        os.chdir(old_cwd)


def test_validate_build_missing_build_yaml_warns(tmp_path):
    """spec validate build warns (exit 0) when project has no build.yaml."""
    import os

    # Setup: governor with the project we'll query AND a dummy project
    # for the cwd (GovernorLocator resolves project from cwd name)
    governor_dir = tmp_path / "local-governor"

    # Create the project we want to validate (no build.yaml)
    no_build = governor_dir / "projects" / "no-build-project"
    (no_build / "specs").mkdir(parents=True)
    # Deliberately NOT creating no-build-project.build.yaml

    # Create a "workspace" directory to use as cwd so GovernorLocator
    # can resolve it as a project name
    workspace = tmp_path / "no-build-project"
    workspace.mkdir()

    old_cwd = os.getcwd()
    old_env = os.environ.get("SPECWRIGHT_GOVERNOR_ROOT")
    try:
        os.chdir(workspace)
        os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = str(governor_dir)

        result = runner.invoke(app, ["validate", "build", "no-build-project"])

        assert result.exit_code == 0, f"Expected exit 0 (warn), got {result.exit_code}: {result.output}"
        assert "warning" in result.output.lower() or "Warning" in result.output
    finally:
        os.chdir(old_cwd)
        if old_env is not None:
            os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = old_env
        else:
            os.environ.pop("SPECWRIGHT_GOVERNOR_ROOT", None)
