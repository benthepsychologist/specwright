"""Tests for spec run command with autogov integration."""

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
    version: str = "2.0.0"
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
def temp_project_with_aip(tmp_path: Path) -> Path:
    """Create a temporary project with .specwright.yaml config and an AIP."""
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
            "aip": ".specwright/aips/test.yaml",
        },
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    # Create directories
    (tmp_path / ".specwright" / "specs").mkdir(parents=True)
    (tmp_path / ".specwright" / "aips").mkdir(parents=True)
    (tmp_path / ".specwright" / "runs").mkdir(parents=True)

    # Create a minimal AIP
    aip = {
        "aip_id": "AIP-test-001",
        "title": "Test AIP",
        "tier": "B",
        "plan": [
            {
                "step_id": "step-001",
                "description": "Test step",
                "allowed_paths": ["src/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["echo ok"],
            }
        ],
    }
    aip_path = tmp_path / ".specwright" / "aips" / "test.yaml"
    with open(aip_path, "w") as f:
        yaml.dump(aip, f)

    return tmp_path


@pytest.fixture
def temp_project_autogov_enabled(tmp_path: Path) -> Path:
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
            "aip": ".specwright/aips/test.yaml",
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
    (tmp_path / ".specwright" / "runs").mkdir(parents=True)

    # Create a minimal AIP
    aip = {
        "aip_id": "AIP-test-001",
        "title": "Test AIP",
        "tier": "B",
        "plan": [
            {
                "step_id": "step-001",
                "description": "Test step",
                "allowed_paths": ["src/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["echo ok"],
            }
        ],
    }
    aip_path = tmp_path / ".specwright" / "aips" / "test.yaml"
    with open(aip_path, "w") as f:
        yaml.dump(aip, f)

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

    (tmp_path / ".specwright" / "aips").mkdir(parents=True)

    aip = {
        "aip_id": "AIP-test-001",
        "title": "Test AIP",
        "tier": "B",
        "plan": [{"step_id": "step-001", "description": "Test"}],
    }
    aip_path = tmp_path / ".specwright" / "aips" / "test.yaml"
    with open(aip_path, "w") as f:
        yaml.dump(aip, f)

    return tmp_path


class TestSpecRunWithoutAutogov:
    """Tests for spec run when autogov is not enabled."""

    def test_run_without_autogov_ignores_flag(
        self, temp_project_with_aip: Path
    ) -> None:
        """--autogov flag is ignored when autogov not enabled in config."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_aip)
            # This should work without autogov validation since it's not enabled
            # We use --dry-run to avoid actually executing the step
            result = runner.invoke(
                app,
                ["run", "--step", "1", "--autogov", "myproject", "--dry-run"],
                catch_exceptions=False,
            )

            # Should fail for other reasons (not autogov)
            # but not exit code 5 (CLIUsageError)
            assert result.exit_code != 5
        finally:
            os.chdir(original_dir)


class TestSpecRunAutgovRequired:
    """Tests for spec run when autogov is enabled."""

    def test_missing_autogov_flag_fails_with_exit_5(
        self, temp_project_autogov_enabled: Path
    ) -> None:
        """Missing --autogov when enabled fails with CLIUsageError (exit 5)."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_autogov_enabled)
            result = runner.invoke(
                app,
                ["run", "--step", "1"],
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
                ["run", "--step", "1", "--autogov", "myproject"],
            )

            assert result.exit_code == 4
            assert "Missing autogov.source" in result.output
        finally:
            os.chdir(original_dir)


class TestSpecRunAutgovLoading:
    """Tests for autogov artifact loading during spec run."""

    def test_autogov_not_installed_fails_with_exit_1(
        self, temp_project_autogov_enabled: Path
    ) -> None:
        """Autogov import failure fails with AutogovNotInstalledError (exit 1)."""
        from spec.autogov.exceptions import AutogovNotInstalledError

        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_autogov_enabled)
            # Patch the GovernanceLoader to raise AutogovNotInstalledError
            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                side_effect=AutogovNotInstalledError(
                    "autogov failed to load: No module named 'autogov'"
                ),
            ):
                result = runner.invoke(
                    app,
                    ["run", "--step", "1", "--autogov", "myproject"],
                )

                assert result.exit_code == 1
                assert "autogov failed to load" in result.output
        finally:
            os.chdir(original_dir)

    def test_nonexistent_project_fails_with_exit_2(
        self, temp_project_autogov_enabled: Path
    ) -> None:
        """Nonexistent autogov project fails with GovernanceNotFoundError (exit 2)."""
        from spec.autogov.exceptions import GovernanceNotFoundError

        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_autogov_enabled)
            with patch(
                "spec.autogov.loader.GovernanceLoader.load_all",
                side_effect=GovernanceNotFoundError(
                    "Policy artifact 'nonexistent' not found in registry 'org'"
                ),
            ):
                result = runner.invoke(
                    app,
                    ["run", "--step", "1", "--autogov", "nonexistent"],
                )

                assert result.exit_code == 2
                assert "not found" in result.output.lower()
        finally:
            os.chdir(original_dir)


class TestContractGovernanceField:
    """Tests for governance field in StepContract."""

    def test_contract_has_governance_field(self) -> None:
        """StepContract has optional governance field."""
        from spec.executor.contract import StepContract

        # Without governance
        contract = StepContract(
            aip_id="test",
            step_id="step-001",
            step_index=1,
            allowed_paths=["src/**"],
            forbidden_paths=[".git/**"],
        )
        assert contract.governance is None

        # With governance
        contract_with_gov = StepContract(
            aip_id="test",
            step_id="step-001",
            step_index=1,
            allowed_paths=["src/**"],
            forbidden_paths=[".git/**"],
            governance={
                "guidance": {
                    "forbidden_paths": [{"path": ".env", "reason": "secrets"}],
                }
            },
        )
        assert contract_with_gov.governance is not None
        assert "guidance" in contract_with_gov.governance

    def test_old_contracts_without_governance_load(self, tmp_path: Path) -> None:
        """Old contracts without governance field still deserialize correctly."""
        from spec.executor.contract import load_contract

        # Create old-style contract YAML without governance field
        old_contract_yaml = """
aip_id: test-old
step_id: step-001
step_index: 0
allowed_paths:
  - src/**
forbidden_paths:
  - .git/**
verification_commands:
  - echo ok
adapter:
  name: claude
  mode: interactive
max_iterations: 3
created_at: "2025-01-01T00:00:00+00:00"
baseline_commit: abc123
"""
        contract_path = tmp_path / "old_contract.yaml"
        contract_path.write_text(old_contract_yaml)

        # Should load without error, governance should be None
        contract = load_contract(contract_path)
        assert contract.aip_id == "test-old"
        assert contract.governance is None

    def test_contract_with_governance_saves_and_loads(self, tmp_path: Path) -> None:
        """Contracts with governance field save and load correctly."""
        from spec.executor.contract import (
            StepContract,
            load_contract,
            save_contract,
        )

        contract = StepContract(
            aip_id="test-gov",
            step_id="step-001",
            step_index=1,
            allowed_paths=["src/**"],
            forbidden_paths=[".git/**"],
            governance={
                "guidance": {
                    "forbidden_paths": [{"path": ".env", "reason": "secrets"}],
                    "policy_name": "test-policy",
                    "policy_version": "1.0.0",
                }
            },
        )

        contract_path = tmp_path / "gov_contract.yaml"
        save_contract(contract, contract_path)

        loaded = load_contract(contract_path)
        assert loaded.governance is not None
        assert loaded.governance["guidance"]["policy_name"] == "test-policy"


class TestPromptGovernanceHeader:
    """Tests for governance header in agent prompt."""

    def test_prompt_begins_with_governance_header(self) -> None:
        """When governance context provided, prompt begins with header."""
        from spec.executor.contract import StepContract
        from spec.executor.runner import StepRunner

        # Create a runner (we'll call the private method directly for testing)
        runner = StepRunner(repo_root=Path.cwd(), runs_dir=Path("/tmp/runs"))

        step = {"step_id": "step-001", "description": "Test step"}
        contract = StepContract(
            aip_id="test",
            step_id="step-001",
            step_index=1,
            allowed_paths=["src/**"],
            forbidden_paths=[".git/**"],
        )

        governance_context = {
            "autogov_policy_name": "test-policy",
            "autogov_policy_version": "1.0.0",
            "autogov_arch_decisions": [
                {"id": "ADR-001", "title": "Use Typer", "summary": "For CLI"}
            ],
            "autogov_policy_rules": [
                {"id": "RULE-001", "name": "no-secrets", "description": "No hardcoded secrets"}
            ],
            "autogov_forbidden_paths": [
                {"path": ".env", "reason": "Contains secrets"}
            ],
        }

        prompt = runner._build_prompt(step, contract, governance_context)

        # Check prompt begins with governance header
        assert prompt.startswith("=== GOVERNANCE (AUTOGOV) ===")
        assert "Policy: test-policy v1.0.0" in prompt

        # Check governance content is included
        assert "### Architecture Decisions" in prompt
        assert "ADR-001" in prompt
        assert "Use Typer" in prompt

        assert "### Policy Rules" in prompt
        assert "RULE-001" in prompt
        assert "no-secrets" in prompt

        assert "### Governance Forbidden Paths (advisory)" in prompt
        assert ".env" in prompt

    def test_prompt_without_governance_no_header(self) -> None:
        """Without governance context, prompt has no governance header."""
        from spec.executor.contract import StepContract
        from spec.executor.runner import StepRunner

        runner = StepRunner(repo_root=Path.cwd(), runs_dir=Path("/tmp/runs"))

        step = {"step_id": "step-001", "description": "Test step"}
        contract = StepContract(
            aip_id="test",
            step_id="step-001",
            step_index=1,
            allowed_paths=["src/**"],
            forbidden_paths=[".git/**"],
        )

        prompt = runner._build_prompt(step, contract, governance_context=None)

        # Should NOT have governance header
        assert "=== GOVERNANCE (AUTOGOV) ===" not in prompt
        # Should start with step info
        assert prompt.startswith("# Step: step-001")
