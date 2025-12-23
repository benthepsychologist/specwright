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
        # v0.6 format: governor-based config (new default)
        assert found_config["version"] == "0.6"
        assert "governor" in found_config
        assert found_config["governor"]["path"] == "~/.local/local-governor"
    finally:
        os.chdir(old_cwd)


def test_init_creates_config_file(temp_project):
    """Test spec init creates .specwright.yaml with v0.6 format."""
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
        # v0.6 format: governor-based (new default)
        assert config["version"] == "0.6"
        assert "governor" in config
    finally:
        os.chdir(old_cwd)


def test_init_legacy_mode_creates_v01_config(temp_project):
    """Test spec init --legacy-mode creates v0.1 config."""
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(temp_project)
        result = runner.invoke(app, ["init", "--legacy-mode"])
        assert result.exit_code == 0
        assert "Created" in result.stdout

        config_path = temp_project / ".specwright.yaml"
        assert config_path.exists()

        config = yaml.safe_load(config_path.read_text())
        # Legacy v0.1 format: repo-local paths
        assert config["version"] == "0.1"
        assert "paths" in config
    finally:
        os.chdir(old_cwd)


def test_create_with_v06_governor_config(tmp_path):
    """Test spec create with v0.6 governor config writes to governor path."""
    import os

    # Setup: create mock governor directory with project structure
    governor_dir = tmp_path / "local-governor"
    project_specs = governor_dir / "projects" / "test-project" / "specs"
    project_aips = governor_dir / "projects" / "test-project" / "aips"
    project_specs.mkdir(parents=True)
    project_aips.mkdir(parents=True)

    # Setup: create project directory with v0.6 config
    # Note: autogov.enabled: false so we don't need --autogov flag or build files
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    config_path = project_dir / ".specwright.yaml"
    config = {
        "version": "0.6",
        "governor": {
            "path": str(governor_dir)
        },
        "project_slug": "test-project",
        "autogov": {
            "enabled": False
        }
    }
    config_path.write_text(yaml.dump(config))

    old_cwd = os.getcwd()
    try:
        os.chdir(project_dir)

        # Create a spec - should write to governor/projects/{project}/specs/
        result = runner.invoke(app, [
            "create",
            "Governor Feature",
            "--tier", "C",
            "--owner", "alice",
            "--goal", "Test governor path"
        ])

        assert result.exit_code == 0
        assert "Created Tier C spec" in result.stdout
        assert "governor-feature.md" in result.stdout

        # Verify spec was written to governor project path
        spec_path = project_specs / "governor-feature.md"
        assert spec_path.exists(), f"Expected spec at {spec_path}"

        content = spec_path.read_text()
        assert "tier: C" in content
        assert "owner: alice" in content

        # Verify NOT written to repo-local path
        local_spec_path = project_dir / ".specwright" / "specs" / "governor-feature.md"
        assert not local_spec_path.exists(), "Spec should NOT be in repo-local path"
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
        runner.invoke(app, ["init", "--legacy-mode"])

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
        runner.invoke(app, ["init", "--legacy-mode"])
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
        runner.invoke(app, ["init", "--legacy-mode"])

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
        runner.invoke(app, ["init", "--legacy-mode"])

        result = runner.invoke(app, [
            "create",
            "Test Feature",
            "--tier", "C",
            "--owner", "alice",
            "--goal", "Test MD generation"
        ])

        assert result.exit_code == 0
        # Check for key parts of success message (path may be absolute or relative)
        assert "Created Tier C spec" in result.stdout
        assert "test-feature.md" in result.stdout

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
        runner.invoke(app, ["init", "--legacy-mode"])

        result = runner.invoke(app, [
            "create",
            "Legacy Test",
            "--tier", "C",
            "--owner", "bob",
            "--goal", "Test YAML generation",
            "--yaml"
        ])

        assert result.exit_code == 0
        # Check for key parts of success message (path may be absolute or relative)
        assert "Created Tier C AIP" in result.stdout
        assert "legacy-test.yaml" in result.stdout

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
        runner.invoke(app, ["init", "--legacy-mode"])

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
        runner.invoke(app, ["init", "--legacy-mode"])

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
        runner.invoke(app, ["init", "--legacy-mode"])

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
        runner.invoke(app, ["init", "--legacy-mode"])

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
        runner.invoke(app, ["init", "--legacy-mode"])

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
        runner.invoke(app, ["init", "--legacy-mode"])

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
        runner.invoke(app, ["init", "--legacy-mode"])

        # Try to run without any AIP
        result = runner.invoke(app, ["run"])

        assert result.exit_code == 1
        output = result.stdout + result.stderr if hasattr(result, 'stderr') else result.output
        assert "No AIP" in output or "not found" in output.lower()
    finally:
        os.chdir(old_cwd)


# ============================================================================
# Tests for `spec run --step N` autonomous mode and exit codes
# ============================================================================


@pytest.fixture
def aip_with_plan(tmp_path):
    """Create a valid AIP with plan steps for autonomous mode testing."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    # Create config
    config = {
        "version": "0.1",
        "paths": {"specs": ".specwright/specs", "aips": ".specwright/aips"},
        "user": {"default_owner": "testuser"},
    }
    config_path = project_dir / ".specwright.yaml"
    config_path.write_text(yaml.dump(config))

    # Create a valid AIP with plan steps
    aip = {
        "aip_id": "AIP-test-2024-01-01-001",
        "title": "Test AIP",
        "tier": "C",
        "project_slug": "test-project",
        "objective": {
            "goal": "Test autonomous step execution",
            "acceptance_criteria": ["Step executes", "Exit codes correct"],
        },
        "repo": {
            "url": "git@github.com:test/project.git",
            "default_branch": "main",
            "working_branch": "feat/test",
        },
        "orchestrator_contract": {
            "artifacts_dir": ".aip_artifacts/AIP-test-2024-01-01-001",
        },
        "plan": [
            {
                "step_id": "step-001",
                "role": "agentic",
                "description": "Test step one",
                "scope": {
                    "allowed_paths": ["src/**"],
                    "forbidden_paths": [".git/**"],
                    "verification_commands": ["echo 'ok'"],
                },
            },
            {
                "step_id": "step-002",
                "role": "agentic",
                "description": "Test step two",
                "scope": {
                    "allowed_paths": ["tests/**"],
                    "forbidden_paths": [".git/**"],
                    "verification_commands": ["echo 'ok'"],
                },
            },
        ],
        "pull_request": {
            "title": "Test PR",
            "target_branch": "main",
        },
        "meta": {
            "created_by": "testuser",
            "created_at": "2024-01-01T00:00:00Z",
        },
    }

    aip_path = project_dir / "test-aip.yaml"
    aip_path.write_text(yaml.dump(aip))

    return project_dir, aip_path


class TestAutonomousModeDispatch:
    """Tests that verify spec run dispatches correctly between HITL and autonomous mode."""

    def test_run_without_step_does_not_call_autonomous_runner(self, aip_with_plan, monkeypatch):
        """Test that `spec run` without --step uses HITL mode (interactive prompts)."""
        import os

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        # Track if _run_autonomous_step was called
        autonomous_called = False

        def mock_autonomous_step(*args, **kwargs):
            nonlocal autonomous_called
            autonomous_called = True
            raise Exception("Should not be called in HITL mode")

        monkeypatch.setattr("spec.cli.spec._run_autonomous_step", mock_autonomous_step)

        try:
            os.chdir(project_dir)
            # Run without --step flag - will fail because HITL mode needs interactive input
            # but we verify autonomous runner was NOT called
            runner.invoke(app, ["run", str(aip_path)])

            # The key assertion: autonomous mode should NOT have been invoked
            assert not autonomous_called, "Autonomous runner should not be called without --step"
        finally:
            os.chdir(old_cwd)

    def test_run_with_step_calls_autonomous_runner(self, aip_with_plan, monkeypatch):
        """Test that `spec run --step N` dispatches to autonomous runner."""
        import os

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        # Track if _run_autonomous_step was called and with what args
        captured_args = {}

        def mock_autonomous_step(
            aip_path, step_num, dry_run, allow_dirty, max_iterations, adapter,
            governance_bundle=None, autogov_project=None, autogov_source=None
        ):
            captured_args["step_num"] = step_num
            captured_args["dry_run"] = dry_run
            captured_args["adapter"] = adapter
            # Simulate successful execution by raising Exit(0)
            raise SystemExit(0)

        monkeypatch.setattr("spec.cli.spec._run_autonomous_step", mock_autonomous_step)

        try:
            os.chdir(project_dir)
            runner.invoke(app, ["run", str(aip_path), "--step", "1"])

            # Verify autonomous mode was called with correct args
            assert "step_num" in captured_args, "Autonomous runner should be called with --step"
            assert captured_args["step_num"] == 1
            assert captured_args["dry_run"] is False
            assert captured_args["adapter"] == "claude"
        finally:
            os.chdir(old_cwd)

    def test_run_with_step_passes_all_flags(self, aip_with_plan, monkeypatch):
        """Test that autonomous mode flags are correctly passed."""
        import os

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        captured_args = {}

        def mock_autonomous_step(
            aip_path, step_num, dry_run, allow_dirty, max_iterations, adapter,
            governance_bundle=None, autogov_project=None, autogov_source=None
        ):
            captured_args.update({
                "step_num": step_num,
                "dry_run": dry_run,
                "allow_dirty": allow_dirty,
                "max_iterations": max_iterations,
                "adapter": adapter,
            })
            raise SystemExit(0)

        monkeypatch.setattr("spec.cli.spec._run_autonomous_step", mock_autonomous_step)

        try:
            os.chdir(project_dir)
            runner.invoke(app, [
                "run", str(aip_path),
                "--step", "2",
                "--dry-run",
                "--allow-dirty",
                "--max-iterations", "5",
                "--adapter", "mock"
            ])

            assert captured_args["step_num"] == 2
            assert captured_args["dry_run"] is True
            assert captured_args["allow_dirty"] is True
            assert captured_args["max_iterations"] == 5
            assert captured_args["adapter"] == "mock"
        finally:
            os.chdir(old_cwd)


class TestExitCodeMapping:
    """Tests that verify exit codes map correctly to termination reasons."""

    def test_exit_code_pass_is_zero(self, aip_with_plan, monkeypatch):
        """Test PASS termination reason returns exit code 0."""
        import os

        from spec.executor import TerminationReason
        from spec.executor.runner import StepResult

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        # Mock StepRunner to return PASS
        def mock_run_step(*args, **kwargs):
            return StepResult(
                step_id="step-001",
                aip_id="AIP-test",
                termination_reason=TerminationReason.PASS,
                iterations=[],
            )

        monkeypatch.setattr("spec.executor.StepRunner.run_step", mock_run_step)

        try:
            os.chdir(project_dir)
            result = runner.invoke(app, ["run", str(aip_path), "--step", "1"])
            assert result.exit_code == 0, f"PASS should exit with code 0, got {result.exit_code}"
        finally:
            os.chdir(old_cwd)

    def test_exit_code_fail_scope_is_one(self, aip_with_plan, monkeypatch):
        """Test FAIL_SCOPE termination reason returns exit code 1."""
        import os

        from spec.executor import TerminationReason
        from spec.executor.runner import StepResult

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        def mock_run_step(*args, **kwargs):
            return StepResult(
                step_id="step-001",
                aip_id="AIP-test",
                termination_reason=TerminationReason.FAIL_SCOPE,
                error="Touched forbidden path",
                iterations=[],
            )

        monkeypatch.setattr("spec.executor.StepRunner.run_step", mock_run_step)

        try:
            os.chdir(project_dir)
            result = runner.invoke(app, ["run", str(aip_path), "--step", "1"])
            assert result.exit_code == 1, f"FAIL_SCOPE should exit with code 1, got {result.exit_code}"
        finally:
            os.chdir(old_cwd)

    def test_exit_code_fail_adapter_protocol_is_one(self, aip_with_plan, monkeypatch):
        """Test FAIL_ADAPTER_PROTOCOL termination reason returns exit code 1."""
        import os

        from spec.executor import TerminationReason
        from spec.executor.runner import StepResult

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        def mock_run_step(*args, **kwargs):
            return StepResult(
                step_id="step-001",
                aip_id="AIP-test",
                termination_reason=TerminationReason.FAIL_ADAPTER_PROTOCOL,
                error="Invalid output schema",
                iterations=[],
            )

        monkeypatch.setattr("spec.executor.StepRunner.run_step", mock_run_step)

        try:
            os.chdir(project_dir)
            result = runner.invoke(app, ["run", str(aip_path), "--step", "1"])
            assert result.exit_code == 1, f"FAIL_ADAPTER_PROTOCOL should exit with code 1, got {result.exit_code}"
        finally:
            os.chdir(old_cwd)

    def test_exit_code_fail_dirty_worktree_is_one(self, aip_with_plan, monkeypatch):
        """Test FAIL_DIRTY_WORKTREE termination reason returns exit code 1."""
        import os

        from spec.executor import TerminationReason
        from spec.executor.runner import StepResult

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        def mock_run_step(*args, **kwargs):
            return StepResult(
                step_id="step-001",
                aip_id="AIP-test",
                termination_reason=TerminationReason.FAIL_DIRTY_WORKTREE,
                error="Dirty worktree",
                iterations=[],
            )

        monkeypatch.setattr("spec.executor.StepRunner.run_step", mock_run_step)

        try:
            os.chdir(project_dir)
            result = runner.invoke(app, ["run", str(aip_path), "--step", "1"])
            assert result.exit_code == 1, f"FAIL_DIRTY_WORKTREE should exit with code 1, got {result.exit_code}"
        finally:
            os.chdir(old_cwd)

    def test_exit_code_escalate_needs_human_is_two(self, aip_with_plan, monkeypatch):
        """Test ESCALATE_NEEDS_HUMAN termination reason returns exit code 2."""
        import os

        from spec.executor import TerminationReason
        from spec.executor.runner import StepResult

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        def mock_run_step(*args, **kwargs):
            return StepResult(
                step_id="step-001",
                aip_id="AIP-test",
                termination_reason=TerminationReason.ESCALATE_NEEDS_HUMAN,
                error="Compound shell operator detected",
                iterations=[],
            )

        monkeypatch.setattr("spec.executor.StepRunner.run_step", mock_run_step)

        try:
            os.chdir(project_dir)
            result = runner.invoke(app, ["run", str(aip_path), "--step", "1"])
            assert result.exit_code == 2, f"ESCALATE_NEEDS_HUMAN should exit with code 2, got {result.exit_code}"
        finally:
            os.chdir(old_cwd)

    def test_exit_code_escalate_ambiguous_is_two(self, aip_with_plan, monkeypatch):
        """Test ESCALATE_AMBIGUOUS termination reason returns exit code 2."""
        import os

        from spec.executor import TerminationReason
        from spec.executor.runner import StepResult

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        def mock_run_step(*args, **kwargs):
            return StepResult(
                step_id="step-001",
                aip_id="AIP-test",
                termination_reason=TerminationReason.ESCALATE_AMBIGUOUS,
                error="Ambiguous input",
                iterations=[],
            )

        monkeypatch.setattr("spec.executor.StepRunner.run_step", mock_run_step)

        try:
            os.chdir(project_dir)
            result = runner.invoke(app, ["run", str(aip_path), "--step", "1"])
            assert result.exit_code == 2, f"ESCALATE_AMBIGUOUS should exit with code 2, got {result.exit_code}"
        finally:
            os.chdir(old_cwd)

    def test_exit_code_fail_verify_retryable_is_one(self, aip_with_plan, monkeypatch):
        """Test FAIL_VERIFY_RETRYABLE (after max retries) returns exit code 1."""
        import os

        from spec.executor import TerminationReason
        from spec.executor.runner import StepResult

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        def mock_run_step(*args, **kwargs):
            return StepResult(
                step_id="step-001",
                aip_id="AIP-test",
                termination_reason=TerminationReason.FAIL_VERIFY_RETRYABLE,
                error="Tests failed after max iterations",
                iterations=[{}, {}, {}],  # 3 iterations
            )

        monkeypatch.setattr("spec.executor.StepRunner.run_step", mock_run_step)

        try:
            os.chdir(project_dir)
            result = runner.invoke(app, ["run", str(aip_path), "--step", "1"])
            assert result.exit_code == 1, f"FAIL_VERIFY_RETRYABLE should exit with code 1, got {result.exit_code}"
        finally:
            os.chdir(old_cwd)

    def test_exit_code_gate_rejected_is_one(self, aip_with_plan, monkeypatch):
        """Test GATE_REJECTED termination reason returns exit code 1."""
        import os

        from spec.executor import TerminationReason
        from spec.executor.runner import StepResult

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        def mock_run_step(*args, **kwargs):
            return StepResult(
                step_id="step-001",
                aip_id="AIP-test",
                termination_reason=TerminationReason.GATE_REJECTED,
                error="Gate review rejected the changes",
                iterations=[],
            )

        monkeypatch.setattr("spec.executor.StepRunner.run_step", mock_run_step)

        try:
            os.chdir(project_dir)
            result = runner.invoke(app, ["run", str(aip_path), "--step", "1"])
            assert result.exit_code == 1, f"GATE_REJECTED should exit with code 1, got {result.exit_code}"
        finally:
            os.chdir(old_cwd)

    def test_exit_code_gate_deferred_is_two(self, aip_with_plan, monkeypatch):
        """Test GATE_DEFERRED termination reason returns exit code 2."""
        import os

        from spec.executor import TerminationReason
        from spec.executor.runner import StepResult

        project_dir, aip_path = aip_with_plan
        old_cwd = os.getcwd()

        def mock_run_step(*args, **kwargs):
            return StepResult(
                step_id="step-001",
                aip_id="AIP-test",
                termination_reason=TerminationReason.GATE_DEFERRED,
                error="Gate review deferred for further discussion",
                iterations=[],
            )

        monkeypatch.setattr("spec.executor.StepRunner.run_step", mock_run_step)

        try:
            os.chdir(project_dir)
            result = runner.invoke(app, ["run", str(aip_path), "--step", "1"])
            assert result.exit_code == 2, f"GATE_DEFERRED should exit with code 2, got {result.exit_code}"
        finally:
            os.chdir(old_cwd)


class TestHelpOutput:
    """Tests that verify help text shows correct flags."""

    def test_run_help_shows_step_flag(self):
        """Test that `spec run --help` shows --step flag."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--step" in result.stdout
        assert "autonomous" in result.stdout.lower()

    def test_run_help_shows_autonomous_flags(self):
        """Test that autonomous mode flags are documented."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.stdout
        assert "--allow-dirty" in result.stdout
        assert "--max-iterations" in result.stdout
        assert "--adapter" in result.stdout

    def test_run_help_shows_exit_codes(self):
        """Test that exit codes are documented in help."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        # The docstring should mention exit codes
        output = result.stdout.lower()
        assert "exit" in output or "code" in output

    def test_run_help_mentions_gate_outcomes(self):
        """Test that gate rejected/deferred outcomes are in help text."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        # Normalize whitespace since help text may wrap across lines
        output = " ".join(result.stdout.lower().split())
        assert "gate rejected" in output
        assert "gate deferred" in output
