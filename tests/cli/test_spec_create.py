"""Tests for spec create command with autogov integration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from spec.cli.spec import app

runner = CliRunner()


# Mock autogov types
@dataclass
class MockDenyPath:
    path: str
    reason: str


@dataclass
class MockDenyConstraints:
    paths: list[MockDenyPath] = field(default_factory=list)


@dataclass
class MockConstraints:
    deny: MockDenyConstraints | None = None


@dataclass
class MockRule:
    id: str
    name: str
    description: str
    severity: str


@dataclass
class MockPolicyPack:
    name: str = "test-policy"
    version: str = "1.0.0"
    constraints: MockConstraints | None = None
    rules: list[MockRule] = field(default_factory=list)


@dataclass
class MockDecision:
    id: str
    title: str
    summary: str | None = None


@dataclass
class MockArchPack:
    name: str = "test-arch"
    version: str = "1.0.0"
    decisions: list[MockDecision] = field(default_factory=list)


@dataclass
class MockStatePack:
    name: str = "test-state"
    version: str = "1.0.0"


class MockArtifactNotFoundError(Exception):
    """Mock autogov not found error."""


class MockArtifactValidationError(Exception):
    """Mock autogov validation error."""


def create_mock_autogov_modules() -> dict:
    """Create mock autogov modules."""
    mock_autogov = MagicMock()
    mock_exceptions = MagicMock()
    mock_exceptions.ArtifactNotFoundError = MockArtifactNotFoundError
    mock_exceptions.ArtifactValidationError = MockArtifactValidationError
    return {
        "autogov": mock_autogov,
        "autogov.exceptions": mock_exceptions,
    }


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project with .specwright.yaml config."""
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
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    # Create directories
    (tmp_path / ".specwright" / "specs").mkdir(parents=True)
    (tmp_path / ".specwright" / "aips").mkdir(parents=True)

    return tmp_path


@pytest.fixture
def temp_project_with_autogov(tmp_path: Path) -> Path:
    """Create a temporary project with autogov enabled."""
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


@pytest.fixture
def temp_project_autogov_missing_source(tmp_path: Path) -> Path:
    """Create a temporary project with autogov enabled but missing source."""
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
        "autogov": {
            "enabled": True,
            # source is missing
        },
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    (tmp_path / ".specwright" / "specs").mkdir(parents=True)
    return tmp_path


class TestSpecCreateWithoutAutogov:
    """Tests for spec create when autogov is not enabled."""

    def test_create_without_autogov_succeeds(self, temp_project: Path) -> None:
        """Creating spec without autogov works when not enabled."""
        # Change to temp project directory
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(
                app,
                ["create", "Test Feature"],
                catch_exceptions=False,
            )

            # Should succeed (exit code 0 or not errored)
            assert result.exit_code == 0
            assert "Created Tier B spec" in result.output
        finally:
            os.chdir(original_dir)

    def test_create_ignores_autogov_flag_when_disabled(self, temp_project: Path) -> None:
        """--autogov flag is ignored when autogov not enabled in config."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(
                app,
                ["create", "Test Feature", "--autogov", "myproject"],
                catch_exceptions=False,
            )

            # Should still succeed - autogov flag ignored when not enabled
            assert result.exit_code == 0
        finally:
            os.chdir(original_dir)


class TestSpecCreateAutgovRequired:
    """Tests for spec create when autogov is enabled."""

    def test_missing_autogov_flag_fails_with_exit_5(
        self, temp_project_with_autogov: Path
    ) -> None:
        """Missing --autogov when enabled fails with CLIUsageError (exit 5)."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_autogov)
            result = runner.invoke(
                app,
                ["create", "Test Feature"],
            )

            assert result.exit_code == 5
            assert "--autogov is required" in result.output
        finally:
            os.chdir(original_dir)

    def test_missing_source_in_config_fails_with_exit_4(
        self, temp_project_autogov_missing_source: Path
    ) -> None:
        """Missing autogov.source when enabled fails with RegistryConfigError (exit 4)."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_autogov_missing_source)
            result = runner.invoke(
                app,
                ["create", "Test Feature", "--autogov", "myproject"],
            )

            assert result.exit_code == 4
            assert "Missing autogov.source" in result.output
        finally:
            os.chdir(original_dir)


class TestSpecCreateAutgovLoading:
    """Tests for autogov artifact loading during spec create."""

    def test_autogov_not_installed_fails_with_exit_1(
        self, temp_project_with_autogov: Path
    ) -> None:
        """Autogov import failure fails with AutogovNotInstalledError (exit 1)."""
        from spec.autogov.exceptions import AutogovNotInstalledError

        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_autogov)
            # Patch the GovernanceLoader to raise AutogovNotInstalledError
            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                side_effect=AutogovNotInstalledError(
                    "autogov failed to load: No module named 'autogov'"
                ),
            ):
                result = runner.invoke(
                    app,
                    ["create", "Test Feature", "--autogov", "myproject"],
                )

                assert result.exit_code == 1
                assert "autogov failed to load" in result.output
        finally:
            os.chdir(original_dir)

    def test_nonexistent_project_fails_with_exit_2(
        self, temp_project_with_autogov: Path
    ) -> None:
        """Nonexistent autogov project fails with GovernanceNotFoundError (exit 2)."""
        from spec.autogov.exceptions import GovernanceNotFoundError

        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_autogov)

            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                side_effect=GovernanceNotFoundError("Project not found"),
            ):
                result = runner.invoke(
                    app,
                    ["create", "Test Feature", "--autogov", "nonexistent"],
                )

                assert result.exit_code == 2
                assert "not found" in result.output.lower()
        finally:
            os.chdir(original_dir)

    def test_invalid_artifact_fails_with_exit_3(
        self, temp_project_with_autogov: Path
    ) -> None:
        """Invalid/malformed artifact fails with GovernanceInvalidError (exit 3)."""
        from spec.autogov.exceptions import GovernanceInvalidError

        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_autogov)

            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                side_effect=GovernanceInvalidError("Invalid YAML"),
            ):
                result = runner.invoke(
                    app,
                    ["create", "Test Feature", "--autogov", "badproject"],
                )

                assert result.exit_code == 3
                assert "invalid" in result.output.lower()
        finally:
            os.chdir(original_dir)


class TestSpecCreateWithValidAutogov:
    """Tests for successful spec creation with autogov."""

    def test_create_with_valid_autogov_produces_governance_section(
        self, temp_project_with_autogov: Path
    ) -> None:
        """Creating spec with valid autogov produces governance section."""
        from spec.autogov.loader import (
            AppliedPattern,
            AppliedPolicy,
            Decision,
            GovernanceBundle,
            Rule,
        )

        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_autogov)

            # Create mock bundle with new structure
            mock_bundle = GovernanceBundle(
                project="myproject",
                source="org",
                version="1.0.0",
                description="Test project for governance testing.",
                decisions=[
                    Decision(
                        id="adr-001",
                        title="Use Typer",
                        status="accepted",
                        rationale="For CLI framework",
                    )
                ],
                rules=[
                    Rule(
                        id="no-secrets",
                        message="No hardcoded secrets",
                        severity="error",
                        kind="placement",
                    )
                ],
                policies=[
                    AppliedPolicy(
                        ref="org::policy/credential-hygiene@0.1.0",
                        name="credential-hygiene",
                        version="0.1.0",
                    )
                ],
                patterns=[
                    AppliedPattern(
                        ref="patterns::pattern/registry-kernel@0.1.0",
                        name="registry-kernel",
                        version="0.1.0",
                    )
                ],
                invariants=["Must pass all tests"],
                frozen_paths=["src/__init__.py"],
            )

            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                return_value=mock_bundle,
            ):
                result = runner.invoke(
                    app,
                    ["create", "Test Feature", "--autogov", "myproject"],
                    catch_exceptions=False,
                )

            assert result.exit_code == 0
            assert "Created Tier B spec" in result.output

            # Check the generated spec file
            spec_file = temp_project_with_autogov / ".specwright" / "specs" / "test-feature.md"
            assert spec_file.exists()

            content = spec_file.read_text()

            # Should have governance section
            assert "### Governance" in content
            assert "myproject" in content

            # Should have decision
            assert "adr-001" in content
            assert "Use Typer" in content

            # Should have rule
            assert "no-secrets" in content

            # Should have policy
            assert "credential-hygiene" in content

            # Should have pattern
            assert "registry-kernel" in content

            # Should have frozen path
            assert "src/__init__.py" in content
        finally:
            os.chdir(original_dir)

    def test_create_with_autogov_includes_frontmatter(
        self, temp_project_with_autogov: Path
    ) -> None:
        """Created spec includes autogov frontmatter."""
        from spec.autogov.loader import GovernanceBundle

        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_autogov)

            mock_bundle = GovernanceBundle(
                project="myproject",
                source="org",
                version="1.0.0",
                description="Test project",
            )

            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                return_value=mock_bundle,
            ):
                result = runner.invoke(
                    app,
                    ["create", "Test Feature", "--autogov", "myproject"],
                    catch_exceptions=False,
                )

            assert result.exit_code == 0

            spec_file = temp_project_with_autogov / ".specwright" / "specs" / "test-feature.md"
            content = spec_file.read_text()

            # Parse frontmatter
            parts = content.split("---")
            frontmatter = yaml.safe_load(parts[1])

            assert "autogov" in frontmatter
            assert frontmatter["autogov"]["project"] == "myproject"
            assert frontmatter["autogov"]["source"] == "org"
            assert "captured_at" in frontmatter["autogov"]
        finally:
            os.chdir(original_dir)
