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
        assert "paths" in found_config
        assert found_config["paths"]["specs"] == "specs"
    finally:
        os.chdir(old_cwd)


def test_init_creates_config_file(temp_project):
    """Test spec init creates .specwright.yaml."""
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
        assert config["version"] == "0.1"
        assert "paths" in config
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


def test_config_displays_loaded_config(temp_project):
    """Test spec config displays configuration."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "Config loaded from:" in result.stdout
        assert "version:" in result.stdout
    finally:
        os.chdir(old_cwd)


def test_config_shows_defaults_when_no_config(temp_project):
    """Test spec config shows defaults when no config file exists."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)

        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "No .specwright.yaml found" in result.stdout
        assert "version:" in result.stdout
    finally:
        os.chdir(old_cwd)


def test_create_generates_markdown_by_default(temp_project):
    """Test spec create generates Markdown by default."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        result = runner.invoke(app, [
            "create",
            "--tier", "C",
            "--title", "Test Feature",
            "--owner", "alice",
            "--goal", "Test MD generation"
        ])

        assert result.exit_code == 0
        assert "Created Tier C spec at specs/test-feature.md" in result.stdout

        spec_path = temp_project / "specs" / "test-feature.md"
        assert spec_path.exists()

        content = spec_path.read_text()
        assert "tier: C" in content
        assert "title: Test Feature" in content
        assert "owner: alice" in content
        assert "goal: Test MD generation" in content
    finally:
        os.chdir(old_cwd)


def test_create_with_yaml_flag_generates_yaml(temp_project):
    """Test spec create --yaml generates YAML directly."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        result = runner.invoke(app, [
            "create",
            "--tier", "C",
            "--title", "Legacy Test",
            "--owner", "bob",
            "--goal", "Test YAML generation",
            "--yaml"
        ])

        assert result.exit_code == 0
        assert "Created Tier C AIP at aips/legacy-test.yaml" in result.stdout

        aip_path = temp_project / "aips" / "legacy-test.yaml"
        assert aip_path.exists()

        aip = yaml.safe_load(aip_path.read_text())
        assert aip["tier"] == "C"
        assert aip["title"] == "Legacy Test"
        assert aip["meta"]["created_by"] == "bob"
    finally:
        os.chdir(old_cwd)


def test_compile_converts_md_to_yaml(temp_project):
    """Test spec compile converts Markdown to YAML."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        # Create MD spec
        runner.invoke(app, [
            "create",
            "--tier", "C",
            "--title", "Compile Test",
            "--owner", "charlie",
            "--goal", "Test compilation"
        ])

        # Compile it
        result = runner.invoke(app, ["compile", "specs/compile-test.md"])

        assert result.exit_code == 0
        assert "Compiled specs/compile-test.md → aips/compile-test.yaml" in result.stdout

        yaml_path = temp_project / "aips" / "compile-test.yaml"
        assert yaml_path.exists()

        aip = yaml.safe_load(yaml_path.read_text())
        assert "meta" in aip
        assert aip["meta"]["goal"] == "Test compilation"
    finally:
        os.chdir(old_cwd)


def test_compile_creates_output_directory(temp_project):
    """Test spec compile creates output directory if it doesn't exist."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        # Create MD spec
        runner.invoke(app, [
            "create",
            "--tier", "C",
            "--title", "Dir Test",
            "--owner", "dave",
            "--goal", "Test dir creation"
        ])

        # Ensure aips/ doesn't exist
        aips_dir = temp_project / "aips"
        if aips_dir.exists():
            import shutil
            shutil.rmtree(aips_dir)

        # Compile should create the directory
        result = runner.invoke(app, ["compile", "specs/dir-test.md"])

        assert result.exit_code == 0
        assert (temp_project / "aips" / "dir-test.yaml").exists()
    finally:
        os.chdir(old_cwd)
