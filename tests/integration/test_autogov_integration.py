"""End-to-end integration tests for autogov integration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from spec.autogov.loader import (
    AppliedPattern,
    AppliedPolicy,
    Decision,
    GovernanceBundle,
    Rule,
)
from spec.cli.spec import app

runner = CliRunner()


def create_realistic_mock_bundle(project: str, source: str) -> GovernanceBundle:
    """Create a realistic mock governance bundle for testing."""
    return GovernanceBundle(
        project=project,
        source=source,
        version="2.1.0",
        description="ACME project governance - security-first development.",
        decisions=[
            Decision(
                id="adr-001",
                title="Use Typer for CLI",
                status="accepted",
                rationale="Typer provides type-safe CLI parsing with minimal boilerplate",
            ),
            Decision(
                id="adr-002",
                title="YAML for configuration",
                status="accepted",
                rationale="YAML is human-readable and well-supported",
            ),
        ],
        rules=[
            Rule(
                id="sec-001",
                message="Never hardcode credentials or secrets",
                severity="error",
                kind="placement",
            ),
            Rule(
                id="sec-002",
                message="Use environment variables for configuration",
                severity="error",
                kind="semantic",
            ),
        ],
        policies=[
            AppliedPolicy(
                ref="org::policy/credential-hygiene@0.1.0",
                name="credential-hygiene",
                version="0.1.0",
            ),
        ],
        patterns=[
            AppliedPattern(
                ref="patterns::pattern/registry-kernel@0.1.0",
                name="registry-kernel",
                version="0.1.0",
            ),
        ],
        invariants=[
            "No secrets in code",
            "All API calls must be authenticated",
        ],
        frozen_paths=[
            "src/__init__.py",
            "src/interfaces.py",
        ],
    )


@pytest.fixture
def temp_project_autogov(tmp_path: Path) -> Path:
    """Create a temporary project with autogov enabled and realistic config."""
    config_path = tmp_path / ".specwright.yaml"
    config = {
        "version": "0.1",
        "paths": {
            "specs": ".specwright/specs",
            "aips": ".specwright/aips",
        },
        "user": {
            "default_owner": "testuser",
            "default_tier": "B",
        },
        "current": {
            "spec": None,
            "aip": None,
        },
        "autogov": {
            "enabled": True,
            "source": "org",
        },
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    # Create directories
    (tmp_path / ".specwright" / "specs").mkdir(parents=True)
    (tmp_path / ".specwright" / "aips").mkdir(parents=True)

    return tmp_path


class TestE2ESpecCreateWithAutogov:
    """End-to-end tests for spec create with autogov."""

    def test_create_spec_with_governance_content(self, temp_project_autogov: Path) -> None:
        """End-to-end: create spec with autogov produces governance content."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_autogov)

            # Create mock bundle
            mock_bundle = create_realistic_mock_bundle("acme-project", "org")

            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                return_value=mock_bundle,
            ):
                # Create spec with autogov
                result = runner.invoke(
                    app,
                    ["create", "Add User Avatars", "--autogov", "acme-project"],
                    catch_exceptions=False,
                )

                assert result.exit_code == 0
                assert "Created Tier B spec" in result.output

            # Verify spec file exists and has governance content
            spec_file = (
                temp_project_autogov / ".specwright" / "specs" / "add-user-avatars.md"
            )
            assert spec_file.exists()

            content = spec_file.read_text()

            # Check governance section
            assert "### Governance" in content
            assert "acme-project" in content

            # Check decisions
            assert "adr-001" in content
            assert "Use Typer for CLI" in content

            # Check rules
            assert "sec-001" in content
            assert "Never hardcode credentials" in content

            # Check policies
            assert "credential-hygiene" in content

            # Check patterns
            assert "registry-kernel" in content

            # Check invariants
            assert "No secrets in code" in content

            # Check frozen paths
            assert "src/__init__.py" in content

            # Parse frontmatter
            parts = content.split("---")
            frontmatter = yaml.safe_load(parts[1])

            assert "autogov" in frontmatter
            assert frontmatter["autogov"]["project"] == "acme-project"
            assert frontmatter["autogov"]["source"] == "org"
            assert "captured_at" in frontmatter["autogov"]

        finally:
            os.chdir(original_dir)

    def test_spec_without_autogov_has_no_governance(self, tmp_path: Path) -> None:
        """Spec created without autogov has no governance section."""
        # Create config without autogov
        config_path = tmp_path / ".specwright.yaml"
        config = {
            "version": "0.1",
            "paths": {"specs": ".specwright/specs", "aips": ".specwright/aips"},
            "user": {"default_owner": "test", "default_tier": "B"},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        (tmp_path / ".specwright" / "specs").mkdir(parents=True)

        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(
                app,
                ["create", "Simple Feature"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0

            spec_file = tmp_path / ".specwright" / "specs" / "simple-feature.md"
            content = spec_file.read_text()

            # Should NOT have governance section
            assert "### Governance" not in content
            assert "autogov" not in content.split("---")[1]  # Not in frontmatter
        finally:
            os.chdir(original_dir)


class TestE2EExitCodes:
    """End-to-end tests for correct exit codes across the workflow."""

    def test_exit_codes_match_spec(self, temp_project_autogov: Path) -> None:
        """All exit codes match the specified values (1-5)."""
        from spec.autogov.exceptions import (
            AutogovNotInstalledError,
            GovernanceInvalidError,
            GovernanceNotFoundError,
        )

        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_autogov)

            # Test exit code 1 (AutogovNotInstalled)
            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                side_effect=AutogovNotInstalledError("autogov failed to load"),
            ):
                result = runner.invoke(
                    app, ["create", "Test", "--autogov", "project"]
                )
                assert result.exit_code == 1

            # Test exit code 2 (GovernanceNotFound)
            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                side_effect=GovernanceNotFoundError("Policy not found"),
            ):
                result = runner.invoke(
                    app, ["create", "Test", "--autogov", "project"]
                )
                assert result.exit_code == 2

            # Test exit code 3 (GovernanceInvalid)
            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                side_effect=GovernanceInvalidError("Invalid YAML"),
            ):
                result = runner.invoke(
                    app, ["create", "Test", "--autogov", "project"]
                )
                assert result.exit_code == 3

            # Test exit code 5 (CLIUsageError - missing --autogov)
            result = runner.invoke(app, ["create", "Test"])
            assert result.exit_code == 5
            assert "--autogov is required" in result.output

        finally:
            os.chdir(original_dir)

    def test_exit_code_4_missing_source(self, tmp_path: Path) -> None:
        """Exit code 4 for missing autogov.source in config."""
        # Create config with autogov enabled but missing source
        config_path = tmp_path / ".specwright.yaml"
        config = {
            "version": "0.1",
            "paths": {"specs": ".specwright/specs", "aips": ".specwright/aips"},
            "user": {"default_owner": "test", "default_tier": "B"},
            "autogov": {"enabled": True},  # source is missing
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        (tmp_path / ".specwright" / "specs").mkdir(parents=True)

        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(
                app, ["create", "Test", "--autogov", "project"]
            )
            assert result.exit_code == 4
            assert "Missing autogov.source" in result.output
        finally:
            os.chdir(original_dir)


class TestNoSourceCLIFlag:
    """Verify there is no --source CLI flag on create/run commands."""

    def test_create_has_no_source_flag(self) -> None:
        """spec create should not have a --source flag."""
        result = runner.invoke(app, ["create", "--help"])
        assert result.exit_code == 0
        # --source should NOT appear in create help
        # (source comes from config only)
        help_text = result.output
        # Find the options section
        assert "--autogov" in help_text
        # Ensure --source is not listed for create
        lines = help_text.split("\n")
        in_create_options = False
        for line in lines:
            if "--autogov" in line:
                in_create_options = True
            # --source should not be in create's options
            if in_create_options and "--source" in line:
                # This would mean --source is an option for create
                pytest.fail("--source should not be an option for spec create")



class TestBackwardCompatibility:
    """Tests for backward compatibility with old configs and contracts."""

    def test_old_config_without_autogov_works(self, tmp_path: Path) -> None:
        """Old configs without autogov section work correctly."""
        config_path = tmp_path / ".specwright.yaml"
        config = {
            "version": "0.1",
            "paths": {"specs": ".specwright/specs", "aips": ".specwright/aips"},
            "user": {"default_owner": "test", "default_tier": "B"},
            # No autogov section at all
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        (tmp_path / ".specwright" / "specs").mkdir(parents=True)

        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            # Create spec without autogov (should work)
            result = runner.invoke(
                app,
                ["create", "Test Feature"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "Created Tier B spec" in result.output

            # Verify spec has no governance section
            spec_file = tmp_path / ".specwright" / "specs" / "test-feature.md"
            content = spec_file.read_text()
            assert "### Governance" not in content
        finally:
            os.chdir(original_dir)

