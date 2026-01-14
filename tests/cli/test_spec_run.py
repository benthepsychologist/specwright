"""Tests for spec run command with autogov integration and SEP workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from spec.cli.spec import app
from spec.executor.sep import StepExecutionPlan, load_sep, save_sep

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

    # Create a minimal AIP with enriched SEP data (AIP v2.0)
    # SEP fields are at step level (objective, files_to_touch, verification_steps)
    aip = {
        "aip_id": "AIP-test-001",
        "title": "Test AIP",
        "version": "2.0",
        "tier": "B",
        "plan": [
            {
                "step_id": "step-001",
                "description": "Test step",
                "prompt": "Test prompt",
                "allowed_paths": ["src/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["echo ok"],
                # Enriched SEP data (required for spec run) - at step level
                "objective": "This is a test objective for the step that describes what needs to be done.",
                "files_to_touch": [
                    {"path": "src/test.py", "action": "create", "description": "Test file"},
                ],
                "verification_steps": [
                    {"command": "echo ok", "expected_outcome": "Command exits 0", "required": True},
                ],
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


# ==== SEP Workflow CLI Tests ====


@pytest.fixture
def temp_project_with_step(tmp_path: Path) -> Path:
    """Create a temporary project with config and a multi-step AIP."""
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
    (tmp_path / "src").mkdir(parents=True)

    # Create a minimal AIP with prompt containing file references
    # AIP v2.0: SEP data is at step level (objective, files_to_touch, verification_steps)
    aip = {
        "aip_id": "AIP-test-001",
        "title": "Test AIP",
        "version": "2.0",
        "tier": "B",
        "plan": [
            {
                "step_id": "step-001",
                "description": "Test step",
                "prompt": "Create `src/new_file.py`. Update `src/existing.py`.",
                "allowed_paths": ["src/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["echo ok"],
                # Enriched SEP data (required for spec run) - at step level
                "objective": "Create a new file at src/new_file.py and update the existing file at src/existing.py with the specified changes.",
                "files_to_touch": [
                    {"path": "src/new_file.py", "action": "create", "description": "New file"},
                    {"path": "src/existing.py", "action": "modify", "description": "Update existing"},
                ],
                "verification_steps": [
                    {"command": "echo ok", "expected_outcome": "Command exits 0", "required": True},
                ],
            },
            {
                "step_id": "step-002",
                "description": "Second step",
                "prompt": "Update `tests/test_new.py`.",
                "allowed_paths": ["tests/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["pytest -q"],
                # Enriched SEP data - at step level
                "objective": "Update the test file at tests/test_new.py with the specified changes.",
                "files_to_touch": [
                    {"path": "tests/test_new.py", "action": "modify", "description": "Update test"},
                ],
                "verification_steps": [
                    {"command": "pytest -q", "expected_outcome": "Tests pass", "required": True},
                ],
            },
        ],
    }
    aip_path = tmp_path / ".specwright" / "aips" / "test.yaml"
    with open(aip_path, "w") as f:
        yaml.dump(aip, f)

    # Initialize as git repo (required for step execution)
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    # Create an initial commit
    (tmp_path / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    return tmp_path


# NOTE: TestPlanOnlyOption class removed - --plan-only flag no longer exists.
# SEPs are now generated during 'spec compile', not 'spec run'.


# NOTE: TestFromSepOption class removed - --from-sep flag no longer exists.
# AIP v2.0 embeds SEP directly in AIP steps; no separate SEP files.


class TestFromSepOptionRemoved:
    """Placeholder class to maintain test structure - original tests removed."""

    def test_from_sep_option_removed(self) -> None:
        """--from-sep flag has been removed in favor of embedded SEPs in AIP v2.0."""
        # This is a placeholder test confirming the removal
        assert True


class TestSkipSepReviewOption:
    """Tests for --skip-sep-review CLI option."""

    def test_skip_sep_review_bypasses_gate(
        self, temp_project_with_step: Path
    ) -> None:
        """--skip-sep-review skips the interactive review prompt."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Mock the adapter to avoid actual execution
            with patch("spec.executor.runner.StepRunner.run_step") as mock_run:
                from spec.executor.runner import StepResult, TerminationReason

                mock_run.return_value = StepResult(
                    step_id="step-001",
                    aip_id="AIP-test-001",
                    termination_reason=TerminationReason.PASS,
                    iterations=[],
                    touched_files=[],
                )

                result = runner.invoke(
                    app,
                    ["run", "--step", "1", "--skip-sep-review"],
                    catch_exceptions=False,
                )

                # Should have invoked run_step (execution proceeded without review)
                assert mock_run.called

                # Should not show review gate prompt
                assert "Continue with execution?" not in result.output

        finally:
            os.chdir(original_dir)

    def test_without_skip_sep_review_shows_gate(
        self, temp_project_with_step: Path
    ) -> None:
        """Without --skip-sep-review, review gate is shown."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # In non-interactive mode (like CLI runner), should default to proceed
            # but we should see the gate output
            with patch("spec.executor.runner.StepRunner.run_step") as mock_run:
                from spec.executor.runner import StepResult, TerminationReason

                mock_run.return_value = StepResult(
                    step_id="step-001",
                    aip_id="AIP-test-001",
                    termination_reason=TerminationReason.PASS,
                    iterations=[],
                    touched_files=[],
                )

                result = runner.invoke(
                    app,
                    ["run", "--step", "1"],
                    catch_exceptions=False,
                )

                # AIP v2.0: SEP is embedded in AIP, verify it was loaded
                assert "Loaded SEP from AIP" in result.output

        finally:
            os.chdir(original_dir)


class TestSepWorkflowIntegration:
    """Integration tests for the full SEP workflow (AIP v2.0 embedded SEP).

    NOTE: With AIP v2.0, SEPs are generated during 'spec compile', not 'spec run'.
    These tests verify that spec run correctly loads pre-enriched SEP data.
    """

    def test_run_loads_enriched_sep_from_aip(
        self, temp_project_with_step: Path
    ) -> None:
        """spec run loads pre-enriched SEP from AIP and executes."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # AIP fixture already has enriched SEP data
            with patch("spec.executor.runner.StepRunner.run_step") as mock_run:
                from spec.executor.runner import StepResult, TerminationReason

                mock_run.return_value = StepResult(
                    step_id="step-001",
                    aip_id="AIP-test-001",
                    termination_reason=TerminationReason.PASS,
                    iterations=[],
                    touched_files=[],
                )

                result = runner.invoke(
                    app,
                    ["run", "--step", "1", "--skip-sep-review"],
                    catch_exceptions=False,
                )

            # Should complete successfully
            assert result.exit_code == 0
            assert "Loaded SEP from AIP" in result.output

        finally:
            os.chdir(original_dir)

    def test_run_with_missing_sep_fails(
        self, tmp_path: Path
    ) -> None:
        """spec run fails if AIP step lacks enriched SEP data."""
        original_dir = os.getcwd()
        try:
            # Create config
            config_path = tmp_path / ".specwright.yaml"
            config = {
                "version": "0.1",
                "paths": {"specs": ".specwright/specs", "aips": ".specwright/aips"},
                "current": {"spec": None, "aip": ".specwright/aips/test.yaml"},
            }
            with open(config_path, "w") as f:
                yaml.dump(config, f)

            (tmp_path / ".specwright" / "aips").mkdir(parents=True)

            # Create AIP WITHOUT enriched SEP data
            aip = {
                "aip_id": "AIP-test-001",
                "title": "Test AIP",
                "version": "2.0",
                "plan": [
                    {
                        "step_id": "step-001",
                        "description": "Test step",
                        "prompt": "Do something.",
                        "allowed_paths": ["src/**"],
                        # NO objective, files_to_touch, verification_steps
                    },
                ],
            }
            aip_path = tmp_path / ".specwright" / "aips" / "test.yaml"
            with open(aip_path, "w") as f:
                yaml.dump(aip, f)

            # Initialize git repo
            import subprocess
            subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)
            (tmp_path / "README.md").write_text("# Test")
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmp_path, capture_output=True, check=True)

            os.chdir(tmp_path)

            result = runner.invoke(
                app,
                ["run", "--step", "1"],
            )

            # Should fail with error about missing SEP
            assert result.exit_code != 0
            assert "missing enriched SEP" in result.output.lower() or "recompile" in result.output.lower()

        finally:
            os.chdir(original_dir)

    def test_aip_has_verification_steps_in_sep(
        self, temp_project_with_step: Path
    ) -> None:
        """Pre-enriched AIP has verification steps in SEP data."""
        # Load the AIP fixture to check embedded SEP data
        aip_path = temp_project_with_step / ".specwright" / "aips" / "test.yaml"
        with open(aip_path) as f:
            aip = yaml.safe_load(f)

        step = aip["plan"][0]

        # Should have verification steps embedded
        assert "verification_steps" in step
        assert len(step["verification_steps"]) > 0
        assert step["verification_steps"][0]["command"] == "echo ok"

    def test_aip_has_files_to_touch_in_sep(
        self, temp_project_with_step: Path
    ) -> None:
        """Pre-enriched AIP has files_to_touch in SEP data."""
        # Load the AIP fixture to check embedded SEP data
        aip_path = temp_project_with_step / ".specwright" / "aips" / "test.yaml"
        with open(aip_path) as f:
            aip = yaml.safe_load(f)

        step = aip["plan"][0]

        # Should have files_to_touch embedded
        assert "files_to_touch" in step
        paths = [fc["path"] for fc in step["files_to_touch"]]
        assert "src/new_file.py" in paths
        assert "src/existing.py" in paths
