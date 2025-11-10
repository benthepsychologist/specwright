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
        assert found_config["paths"]["specs"] == ".specwright/specs"
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

        result = runner.invoke(app, ["config", "--show"])
        assert result.exit_code == 0
        assert "Current configuration:" in result.stdout
        assert "version:" in result.stdout
        assert "user:" in result.stdout
        assert "default_owner:" in result.stdout
    finally:
        os.chdir(old_cwd)


def test_config_shows_defaults_when_no_config(temp_project):
    """Test spec config shows error when no config file exists."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)

        result = runner.invoke(app, ["config", "--show"])
        assert result.exit_code == 1
        # Error messages go to stderr, but typer.testing combines them into output
        output = result.stdout + result.stderr if hasattr(result, 'stderr') else result.output
        assert "No .specwright.yaml found" in output
        assert "spec init" in output
    finally:
        os.chdir(old_cwd)


def test_config_set_user(temp_project):
    """Test spec config user sets default owner."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        result = runner.invoke(app, ["config", "user", "testuser"])
        assert result.exit_code == 0
        assert "Set user: testuser" in result.stdout

        # Verify it's in the config
        result = runner.invoke(app, ["config", "--show"])
        assert "default_owner: testuser" in result.stdout
    finally:
        os.chdir(old_cwd)


def test_create_without_owner_uses_default(temp_project):
    """Test spec create uses default owner from config."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])
        runner.invoke(app, ["config", "user", "defaultuser"])

        # Create without --owner flag
        result = runner.invoke(app, [
            "create",
            "Test Feature",
            "--tier", "C",
            "--goal", "Test default owner"
        ])
        assert result.exit_code == 0
        assert "Using default owner: defaultuser" in result.stdout

        # Verify owner is set in the created file
        spec_path = temp_project / ".specwright/specs/test-feature.md"
        assert spec_path.exists()
        content = spec_path.read_text()
        assert "owner: defaultuser" in content
    finally:
        os.chdir(old_cwd)


def test_create_without_owner_fails_when_no_default(temp_project):
    """Test spec create fails when no owner provided and no default set."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        # Try to create without --owner and no default
        result = runner.invoke(app, [
            "create",
            "Test Feature",
            "--tier", "C",
            "--goal", "Test error handling"
        
])
        assert result.exit_code == 1
        # Error messages go to stderr, but typer.testing combines them into output
        output = result.stdout + result.stderr if hasattr(result, 'stderr') else result.output
        assert "No owner specified" in output
        assert "spec config user" in output
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
            "Test Feature",
            "--tier", "C",
            "--owner", "alice",
            "--goal", "Test MD generation"
        
])

        assert result.exit_code == 0
        assert "Created Tier C spec at .specwright/specs/test-feature.md" in result.stdout

        spec_path = temp_project / ".specwright" / "specs" / "test-feature.md"
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
            "Legacy Test",
            "--tier", "C",
            "--owner", "bob",
            "--goal", "Test YAML generation",
            
"--yaml"
        ])

        assert result.exit_code == 0
        assert "Created Tier C AIP at .specwright/aips/legacy-test.yaml" in result.stdout

        aip_path = temp_project / ".specwright" / "aips" / "legacy-test.yaml"
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
            "Compile Test",
            "--tier", "C",
            "--owner", "charlie",
            "--goal", "Test compilation"
        
])

        # Compile it - should now succeed with fixed templates
        result = runner.invoke(app, ["compile", ".specwright/specs/compile-test.md"])

        # Compilation and validation should both succeed
        assert result.exit_code == 0
        assert "Compiled .specwright/specs/compile-test.md" in result.stdout
        assert "Validation passed" in result.stdout

        # File should still be created
        yaml_path = temp_project / ".specwright" / "aips" / "compile-test.yaml"
        assert yaml_path.exists()

        # Check content is correct (new schema-compliant structure)
        aip = yaml.safe_load(yaml_path.read_text())
        assert "meta" in aip
        assert "objective" in aip
        assert aip["objective"]["goal"] == "Test compilation"
        assert aip["meta"]["created_by"] == "charlie"
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
            "Dir Test",
            "--tier", "C",
            "--owner", "dave",
            "--goal", "Test dir creation"
        
])

        # Ensure .specwright/aips/ doesn't exist
        aips_dir = temp_project / ".specwright" / "aips"
        if aips_dir.exists():
            import shutil
            shutil.rmtree(aips_dir)

        # Compile should create the directory and succeed
        result = runner.invoke(app, ["compile", ".specwright/specs/dir-test.md"])

        # Should succeed and create directory
        assert result.exit_code == 0
        assert (temp_project / ".specwright" / "aips" / "dir-test.yaml").exists()
        assert (temp_project / ".specwright" / "aips").exists()
    finally:
        os.chdir(old_cwd)


def test_validate_md_spec(temp_project):
    """Test spec validate works on .md files."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        # Create MD spec
        runner.invoke(app, [
            "create",
            "Validate Test",
            "--tier", "C",
            "--owner", "eve",
            "--goal", "Test validation"
        
])

        # Validate MD file directly
        result = runner.invoke(app, ["validate", ".specwright/specs/validate-test.md"])

        assert result.exit_code == 0
        assert "is valid" in result.stdout or "✓" in result.stdout
    finally:
        os.chdir(old_cwd)


def test_validate_yaml_aip(temp_project):
    """Test spec validate works on compiled .yaml AIPs."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        # Create and compile
        runner.invoke(app, [
            "create",
            "YAML Validate",
            "--tier", "C",
            "--owner", "frank",
            "--goal", "Test YAML validation"
        
])
        runner.invoke(app, ["compile", ".specwright/specs/yaml-validate.md"])

        # Validate compiled YAML
        result = runner.invoke(app, ["validate", ".specwright/aips/yaml-validate.yaml"])

        assert result.exit_code == 0
        assert "is valid" in result.stdout or "✓" in result.stdout
    finally:
        os.chdir(old_cwd)


def test_validate_uses_current_spec(temp_project):
    """Test spec validate uses current spec when no arg provided."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        # Create spec and set as current
        runner.invoke(app, [
            "create",
            "Current Validate",
            "--tier", "C",
            "--owner", "grace",
            "--goal", "Test current validation"
        
])
        runner.invoke(app, ["config", "current.spec", ".specwright/specs/current-validate.md"])

        # Validate without arguments
        result = runner.invoke(app, ["validate"])

        assert result.exit_code == 0
        assert "Using current spec" in result.stdout or "is valid" in result.stdout
    finally:
        os.chdir(old_cwd)


def test_validate_fails_on_invalid_spec(temp_project):
    """Test spec validate fails on invalid spec."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        # Create an invalid spec with missing required fields
        invalid_spec = temp_project / ".specwright" / "specs" / "invalid.md"
        invalid_spec.parent.mkdir(parents=True, exist_ok=True)
        invalid_spec.write_text("""---
tier: C
title: Invalid Spec
---

# Invalid Spec

Missing owner and goal fields.
""")

        # Validate should fail
        result = runner.invoke(app, ["validate", str(invalid_spec)])

        assert result.exit_code == 1
        output = result.stdout + result.stderr if hasattr(result, 'stderr') else result.output
        # The error output contains "Validating" and "failed"
        assert "failed" in output.lower() or "missing" in output.lower()
    finally:
        os.chdir(old_cwd)


def test_run_fails_without_aip(temp_project):
    """Test spec run fails when no AIP is set or provided."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        runner.invoke(app, ["init"])

        # Try to run without any AIP
        result = runner.invoke(app, ["run"])

        assert result.exit_code == 1
        output = result.stdout + result.stderr if hasattr(result, 'stderr') else result.output
        assert "No AIP" in output or "not found" in output.lower()
    finally:
        os.chdir(old_cwd)
