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
    aip = {
        "aip_id": "AIP-test-001",
        "title": "Test AIP",
        "tier": "B",
        "plan": [
            {
                "step_id": "step-001",
                "description": "Test step",
                "prompt": "Create `src/new_file.py`. Update `src/existing.py`.",
                "allowed_paths": ["src/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["echo ok"],
            },
            {
                "step_id": "step-002",
                "description": "Second step",
                "prompt": "Update `tests/test_new.py`.",
                "allowed_paths": ["tests/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["pytest -q"],
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


class TestPlanOnlyOption:
    """Tests for --plan-only CLI option."""

    def test_plan_only_generates_sep_and_exits(
        self, temp_project_with_step: Path
    ) -> None:
        """--plan-only generates SEP file and exits without execution."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)
            result = runner.invoke(
                app,
                ["run", "--step", "1", "--plan-only"],
                catch_exceptions=False,
            )

            # Should exit with code 0 (success)
            assert result.exit_code == 0

            # SEP file should exist in runs directory
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            sep_files = list(runs_dir.glob("**/sep.yaml"))
            assert len(sep_files) == 1

            # SEP should be valid
            sep = load_sep(sep_files[0])
            assert sep.aip_id == "AIP-test-001"
            assert sep.step_id == "step-001"
            assert sep.step_index == 1

        finally:
            os.chdir(original_dir)

    def test_plan_only_shows_resume_command(
        self, temp_project_with_step: Path
    ) -> None:
        """--plan-only output includes command to resume with --from-sep."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)
            result = runner.invoke(
                app,
                ["run", "--step", "1", "--plan-only"],
                catch_exceptions=False,
            )

            # Should show how to execute from the SEP
            assert "--from-sep" in result.output

        finally:
            os.chdir(original_dir)

    def test_plan_only_extracts_files_from_prompt(
        self, temp_project_with_step: Path
    ) -> None:
        """--plan-only SEP contains files extracted from prompt."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)
            runner.invoke(
                app,
                ["run", "--step", "1", "--plan-only"],
                catch_exceptions=False,
            )

            # Load the generated SEP
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            sep_files = list(runs_dir.glob("**/sep.yaml"))
            sep = load_sep(sep_files[0])

            # Should have extracted files from prompt
            assert len(sep.files_to_touch) == 2
            paths = [fc.path for fc in sep.files_to_touch]
            assert "src/new_file.py" in paths
            assert "src/existing.py" in paths

        finally:
            os.chdir(original_dir)


class TestFromSepOption:
    """Tests for --from-sep CLI option."""

    def test_from_sep_loads_and_validates_sep(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep loads SEP from file and validates it."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # First generate a SEP using plan-only
            runner.invoke(
                app,
                ["run", "--step", "1", "--plan-only"],
                catch_exceptions=False,
            )

            # Find the generated SEP
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            sep_files = list(runs_dir.glob("**/sep.yaml"))
            sep_path = sep_files[0]

            # Now run with --from-sep (use dry-run to avoid actual execution)
            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path), "--dry-run"],
                catch_exceptions=False,
            )

            # Should complete successfully (dry-run avoids adapter execution)
            assert result.exit_code == 0

        finally:
            os.chdir(original_dir)

    def test_from_sep_missing_file_exits_6(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep with missing file exits with code 6."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)
            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", "/nonexistent/sep.yaml"],
            )

            # Exit code 6 = SEP file error
            assert result.exit_code == 6
            assert "not found" in result.output.lower() or "SEP file" in result.output

        finally:
            os.chdir(original_dir)

    def test_from_sep_invalid_yaml_exits_6(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep with invalid YAML exits with code 6."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Create invalid SEP file
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            aip_dir = runs_dir / "AIP-test-001" / "2025-01-01T00-00-00" / "step-001"
            aip_dir.mkdir(parents=True)
            sep_path = aip_dir / "sep.yaml"
            sep_path.write_text("invalid: [yaml: broken", encoding="utf-8")

            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path)],
            )

            # Exit code 6 = SEP file error (malformed)
            assert result.exit_code == 6

        finally:
            os.chdir(original_dir)

    def test_from_sep_aip_id_mismatch_exits_7(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep with mismatched aip_id exits with code 7."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Create SEP with wrong aip_id
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            aip_dir = runs_dir / "AIP-test-001" / "2025-01-01T00-00-00" / "step-001"
            aip_dir.mkdir(parents=True)
            sep_path = aip_dir / "sep.yaml"

            sep = StepExecutionPlan(
                aip_id="AIP-wrong-001",  # Wrong AIP ID
                step_id="step-001",
                step_index=1,
                created_at="2025-01-01T00:00:00+00:00",
                allowed_paths=["src/**"],
                forbidden_paths=[".git/**"],
            )
            save_sep(sep, sep_path)

            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path)],
            )

            # Exit code 7 = SEP mismatch error
            assert result.exit_code == 7
            assert "mismatch" in result.output.lower()

        finally:
            os.chdir(original_dir)

    def test_from_sep_step_id_mismatch_exits_7(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep with mismatched step_id exits with code 7."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Create SEP with wrong step_id
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            aip_dir = runs_dir / "AIP-test-001" / "2025-01-01T00-00-00" / "step-001"
            aip_dir.mkdir(parents=True)
            sep_path = aip_dir / "sep.yaml"

            sep = StepExecutionPlan(
                aip_id="AIP-test-001",
                step_id="step-wrong",  # Wrong step ID
                step_index=1,
                created_at="2025-01-01T00:00:00+00:00",
                allowed_paths=["src/**"],
                forbidden_paths=[".git/**"],
            )
            save_sep(sep, sep_path)

            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path)],
            )

            # Exit code 7 = SEP mismatch error
            assert result.exit_code == 7
            assert "mismatch" in result.output.lower()

        finally:
            os.chdir(original_dir)

    def test_from_sep_step_index_mismatch_exits_7(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep with mismatched step_index exits with code 7."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Create SEP with wrong step_index
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            aip_dir = runs_dir / "AIP-test-001" / "2025-01-01T00-00-00" / "step-001"
            aip_dir.mkdir(parents=True)
            sep_path = aip_dir / "sep.yaml"

            sep = StepExecutionPlan(
                aip_id="AIP-test-001",
                step_id="step-001",
                step_index=2,  # Wrong step index (should be 1)
                created_at="2025-01-01T00:00:00+00:00",
                allowed_paths=["src/**"],
                forbidden_paths=[".git/**"],
            )
            save_sep(sep, sep_path)

            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path)],
            )

            # Exit code 7 = SEP mismatch error
            assert result.exit_code == 7
            assert "mismatch" in result.output.lower()

        finally:
            os.chdir(original_dir)

    def test_from_sep_wrong_filename_exits_7(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep with non-standard filename exits with code 7."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Create SEP with wrong filename
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            aip_dir = runs_dir / "AIP-test-001" / "2025-01-01T00-00-00" / "step-001"
            aip_dir.mkdir(parents=True)
            sep_path = aip_dir / "plan.yaml"  # Wrong filename (should be sep.yaml)

            sep = StepExecutionPlan(
                aip_id="AIP-test-001",
                step_id="step-001",
                step_index=1,
                created_at="2025-01-01T00:00:00+00:00",
                allowed_paths=["src/**"],
                forbidden_paths=[".git/**"],
            )
            save_sep(sep, sep_path)

            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path)],
            )

            # Exit code 7 = SEP mismatch (path must end with sep.yaml)
            assert result.exit_code == 7
            assert "sep.yaml" in result.output.lower()

        finally:
            os.chdir(original_dir)

    def test_from_sep_wrong_directory_exits_7(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep with SEP in wrong directory exits with code 7."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Create SEP in wrong directory (step-002 instead of step-001)
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            aip_dir = runs_dir / "AIP-test-001" / "2025-01-01T00-00-00" / "step-002"
            aip_dir.mkdir(parents=True)
            sep_path = aip_dir / "sep.yaml"

            sep = StepExecutionPlan(
                aip_id="AIP-test-001",
                step_id="step-001",  # Correct step_id
                step_index=1,
                created_at="2025-01-01T00:00:00+00:00",
                allowed_paths=["src/**"],
                forbidden_paths=[".git/**"],
            )
            save_sep(sep, sep_path)

            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path)],
            )

            # Exit code 7 = SEP mismatch (directory mismatch)
            assert result.exit_code == 7
            assert "mismatch" in result.output.lower()

        finally:
            os.chdir(original_dir)

    def test_from_sep_allowed_paths_widening_exits_7(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep with SEP that widens allowed_paths exits with code 7."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Create SEP with extra allowed_paths
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            aip_dir = runs_dir / "AIP-test-001" / "2025-01-01T00-00-00" / "step-001"
            aip_dir.mkdir(parents=True)
            sep_path = aip_dir / "sep.yaml"

            sep = StepExecutionPlan(
                aip_id="AIP-test-001",
                step_id="step-001",
                step_index=1,
                created_at="2025-01-01T00:00:00+00:00",
                allowed_paths=["src/**", "bin/**"],  # Extra path not in contract
                forbidden_paths=[".git/**"],
            )
            save_sep(sep, sep_path)

            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path)],
            )

            # Exit code 7 = SEP mismatch (scope widening)
            assert result.exit_code == 7
            assert "widening" in result.output.lower() or "allowed_paths" in result.output

        finally:
            os.chdir(original_dir)

    def test_from_sep_forbidden_paths_weakening_exits_7(
        self, temp_project_with_step: Path
    ) -> None:
        """--from-sep with SEP that weakens forbidden_paths exits with code 7."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Create SEP with missing forbidden_paths
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            aip_dir = runs_dir / "AIP-test-001" / "2025-01-01T00-00-00" / "step-001"
            aip_dir.mkdir(parents=True)
            sep_path = aip_dir / "sep.yaml"

            sep = StepExecutionPlan(
                aip_id="AIP-test-001",
                step_id="step-001",
                step_index=1,
                created_at="2025-01-01T00:00:00+00:00",
                allowed_paths=["src/**"],
                forbidden_paths=[],  # Missing .git/** from contract
            )
            save_sep(sep, sep_path)

            result = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path)],
            )

            # Exit code 7 = SEP mismatch (scope weakening)
            assert result.exit_code == 7
            assert "weakening" in result.output.lower() or "forbidden_paths" in result.output

        finally:
            os.chdir(original_dir)


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

                # Should generate a SEP under runs/ even in non-interactive mode
                runs_dir = temp_project_with_step / ".specwright" / "runs"
                sep_files = list(runs_dir.glob("**/sep.yaml"))
                assert len(sep_files) == 1

        finally:
            os.chdir(original_dir)

    def test_skip_sep_review_with_plan_only_ignored(
        self, temp_project_with_step: Path
    ) -> None:
        """--skip-sep-review is effectively ignored with --plan-only."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # --plan-only exits before execution, so --skip-sep-review is moot
            result = runner.invoke(
                app,
                ["run", "--step", "1", "--plan-only", "--skip-sep-review"],
                catch_exceptions=False,
            )

            # Should still exit with plan-only behavior
            assert result.exit_code == 0

            # Should still have written a SEP
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            sep_files = list(runs_dir.glob("**/sep.yaml"))
            assert len(sep_files) == 1

        finally:
            os.chdir(original_dir)


class TestSepWorkflowIntegration:
    """Integration tests for the full SEP workflow."""

    def test_plan_only_then_from_sep_workflow(
        self, temp_project_with_step: Path
    ) -> None:
        """Full workflow: generate SEP with --plan-only, then execute with --from-sep."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            # Step 1: Generate SEP
            result1 = runner.invoke(
                app,
                ["run", "--step", "1", "--plan-only"],
                catch_exceptions=False,
            )
            assert result1.exit_code == 0

            # Find the generated SEP
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            sep_files = list(runs_dir.glob("**/sep.yaml"))
            sep_path = sep_files[0]

            # Step 2: Execute from SEP (with dry-run to avoid actual execution)
            result2 = runner.invoke(
                app,
                ["run", "--step", "1", "--from-sep", str(sep_path), "--dry-run"],
                catch_exceptions=False,
            )

            # Should complete successfully (dry-run avoids adapter execution)
            assert result2.exit_code == 0

        finally:
            os.chdir(original_dir)

    def test_sep_contains_verification_steps(
        self, temp_project_with_step: Path
    ) -> None:
        """Generated SEP includes verification steps from AIP."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            runner.invoke(
                app,
                ["run", "--step", "1", "--plan-only"],
                catch_exceptions=False,
            )

            # Load the generated SEP
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            sep_files = list(runs_dir.glob("**/sep.yaml"))
            sep = load_sep(sep_files[0])

            # Should have verification steps from AIP
            assert len(sep.verification_steps) > 0
            assert sep.verification_steps[0].command == "echo ok"

        finally:
            os.chdir(original_dir)

    def test_sep_inherits_scope_from_contract(
        self, temp_project_with_step: Path
    ) -> None:
        """Generated SEP inherits scope constraints from contract."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_project_with_step)

            runner.invoke(
                app,
                ["run", "--step", "1", "--plan-only"],
                catch_exceptions=False,
            )

            # Load the generated SEP
            runs_dir = temp_project_with_step / ".specwright" / "runs"
            sep_files = list(runs_dir.glob("**/sep.yaml"))
            sep = load_sep(sep_files[0])

            # Should have scope from AIP step
            assert "src/**" in sep.allowed_paths
            # forbidden_paths should include defaults
            assert any(".git" in fp for fp in sep.forbidden_paths)

        finally:
            os.chdir(original_dir)
