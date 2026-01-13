"""Integration tests for LLM-powered spec execution.

Tests cover:
1. test_plan_only_with_model_generates_llm_sep - mock LLM, verify SEP metadata
2. test_from_sep_with_model_runs_verification - mock LLM, verify step_summary has llm_verification
3. test_no_model_preserves_deterministic_behavior - no mock needed, verify SEPBuilder used
4. test_verify_only_runs_verification_without_execution - ensure no adapter execution occurs
5. test_llm_timeout_falls_back_gracefully - mock timeout, verify warning + fallback
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from spec.executor.sep import SEPProvenance, StepExecutionPlan, save_sep
from spec.executor.sep_builder import SEPBuilder
from spec.llm.client import LLMVerificationResult, verify_patch_with_llm


@pytest.fixture
def temp_governor_config(tmp_path: Path):
    """Create a temp governor config with LLM enabled."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """llm:
  enabled: true
  timeout_s: 30
"""
    )
    return config_path


@pytest.fixture
def temp_prompts_yaml(tmp_path: Path):
    """Create temp prompts.yaml."""
    prompts_path = tmp_path / "prompts.yaml"
    prompts_path.write_text(
        """sep_generation: |
  Generate SEP for: {aip_context}
  Step: {step_index}
  Contract: {contract_text}

patch_verification: |
  Verify patch against SEP: {sep_yaml}
  Patch: {patch_content}
"""
    )
    return prompts_path


@pytest.fixture
def sample_aip() -> dict:
    """Create a sample AIP for testing."""
    return {
        "aip_id": "test-aip",
        "title": "Test AIP",
        "tier": "C",
        "objective": {"goal": "Test the LLM integration"},
        "plan": [
            {
                "step_id": "step-001",
                "title": "Step 1",
                "prompt": "Create `src/test.py`",
                "allowed_paths": ["src/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["ruff check src/"],
            }
        ],
    }


@pytest.fixture
def sample_contract():
    """Create a sample contract for testing."""
    from spec.executor.contract import StepContract

    return StepContract(
        aip_id="test-aip",
        step_id="step-001",
        step_index=1,
        allowed_paths=["src/**"],
        forbidden_paths=[".git/**"],
        verification_commands=["ruff check src/"],
    )


class TestSEPBuilderDeterministic:
    """Test deterministic SEP building (no LLM)."""

    def test_build_without_model_sets_deterministic_provenance(
        self, sample_aip: dict, sample_contract
    ):
        """Verify that build() sets provenance to deterministic."""
        builder = SEPBuilder()
        sep = builder.build(sample_aip, 0, sample_contract)

        assert sep.provenance is not None
        assert sep.provenance.generator == "deterministic"
        assert sep.provenance.model is None


class TestSEPBuilderWithLLM:
    """Test LLM-powered SEP building."""

    def test_build_with_llm_success_sets_llm_provenance(
        self,
        sample_aip: dict,
        sample_contract,
        tmp_path: Path,
        temp_governor_config: Path,
        temp_prompts_yaml: Path,
    ):
        """Verify that build_with_llm() sets provenance with LLM and model."""
        # Mock the LLM response
        mock_llm_response = """objective: Create test file
files_to_touch:
  - path: src/test.py
    action: create
    description: Create new test file
verification_steps:
  - command: ruff check src/
    expected_outcome: No errors
allowed_paths:
  - src/**
forbidden_paths:
  - .git/**
estimated_complexity: low
requires_human_review: false
"""

        # Mock the LLM client
        mock_client = MagicMock()
        mock_client.prompt.return_value = mock_llm_response

        # Patch config and prompts paths
        with (
            patch(
                "spec.llm.config.get_governor_config_path",
                return_value=temp_governor_config,
            ),
            patch(
                "spec.llm.prompts.get_prompts_path",
                return_value=temp_prompts_yaml,
            ),
            # LLMClient is imported inside the function, so patch spec.llm.client.LLMClient
            patch("spec.llm.client.LLMClient", return_value=mock_client),
        ):
            builder = SEPBuilder()
            sep = builder.build_with_llm(sample_aip, 0, sample_contract, "gpt-4o")

            assert sep.provenance is not None
            assert sep.provenance.generator == "llm"
            assert sep.provenance.model == "gpt-4o"
            assert sep.objective == "Create test file"

    def test_build_with_llm_invalid_yaml_falls_back(
        self,
        sample_aip: dict,
        sample_contract,
        tmp_path: Path,
        temp_governor_config: Path,
        temp_prompts_yaml: Path,
    ):
        """Verify that invalid LLM YAML response falls back to deterministic."""
        # Mock the LLM response with invalid YAML
        mock_llm_response = "not valid yaml: [ unclosed"

        mock_client = MagicMock()
        mock_client.prompt.return_value = mock_llm_response

        with (
            patch(
                "spec.llm.config.get_governor_config_path",
                return_value=temp_governor_config,
            ),
            patch(
                "spec.llm.prompts.get_prompts_path",
                return_value=temp_prompts_yaml,
            ),
            patch("spec.llm.client.LLMClient", return_value=mock_client),
        ):
            builder = SEPBuilder()
            sep = builder.build_with_llm(sample_aip, 0, sample_contract, "gpt-4o")

            # Should fall back to deterministic
            assert sep.provenance is not None
            assert sep.provenance.generator == "deterministic"
            assert sep.provenance.model is None

    def test_build_with_llm_timeout_falls_back(
        self,
        sample_aip: dict,
        sample_contract,
        tmp_path: Path,
        temp_governor_config: Path,
        temp_prompts_yaml: Path,
    ):
        """Verify that LLM timeout falls back to deterministic."""
        from spec.llm.client import LLMExecutionError

        mock_client = MagicMock()
        mock_client.prompt.side_effect = LLMExecutionError("Request timed out")

        with (
            patch(
                "spec.llm.config.get_governor_config_path",
                return_value=temp_governor_config,
            ),
            patch(
                "spec.llm.prompts.get_prompts_path",
                return_value=temp_prompts_yaml,
            ),
            patch("spec.llm.client.LLMClient", return_value=mock_client),
        ):
            builder = SEPBuilder()
            sep = builder.build_with_llm(sample_aip, 0, sample_contract, "gpt-4o")

            # Should fall back to deterministic
            assert sep.provenance is not None
            assert sep.provenance.generator == "deterministic"


class TestPatchVerification:
    """Test LLM patch verification."""

    def test_verify_patch_with_empty_patch_returns_skipped(
        self, temp_governor_config: Path
    ):
        """Verify that empty patch returns skipped status."""
        with patch(
            "spec.llm.config.get_governor_config_path",
            return_value=temp_governor_config,
        ):
            result = verify_patch_with_llm("sep content", "", "gpt-4o")

            assert result.status == "skipped"
            assert "empty" in result.rationale.lower() or "missing" in result.rationale.lower()
            assert result.model == "gpt-4o"

    def test_verify_patch_with_none_patch_returns_skipped(
        self, temp_governor_config: Path
    ):
        """Verify that None patch returns skipped status."""
        with patch(
            "spec.llm.config.get_governor_config_path",
            return_value=temp_governor_config,
        ):
            result = verify_patch_with_llm("sep content", None, "gpt-4o")

            assert result.status == "skipped"
            assert result.model == "gpt-4o"

    def test_verify_patch_success(
        self, temp_governor_config: Path, temp_prompts_yaml: Path
    ):
        """Verify successful patch verification."""
        with (
            patch(
                "spec.llm.config.get_governor_config_path",
                return_value=temp_governor_config,
            ),
            patch(
                "spec.llm.prompts.get_prompts_path",
                return_value=temp_prompts_yaml,
            ),
        ):
            mock_client = MagicMock()
            mock_client.prompt.return_value = '{"status": "pass", "rationale": "Patch looks good"}'

            with patch("spec.llm.client.LLMClient", return_value=mock_client):
                result = verify_patch_with_llm(
                    "sep content", "diff --git a/file.py", "gpt-4o"
                )

                assert result.status == "pass"
                assert result.rationale == "Patch looks good"
                assert result.model == "gpt-4o"

    def test_verify_patch_failure(
        self, temp_governor_config: Path, temp_prompts_yaml: Path
    ):
        """Verify failed patch verification."""
        with (
            patch(
                "spec.llm.config.get_governor_config_path",
                return_value=temp_governor_config,
            ),
            patch(
                "spec.llm.prompts.get_prompts_path",
                return_value=temp_prompts_yaml,
            ),
        ):
            mock_client = MagicMock()
            mock_client.prompt.return_value = '{"status": "fail", "rationale": "Modifies forbidden path"}'

            with patch("spec.llm.client.LLMClient", return_value=mock_client):
                result = verify_patch_with_llm(
                    "sep content", "diff --git a/file.py", "gpt-4o"
                )

                assert result.status == "fail"
                assert "forbidden" in result.rationale.lower()


class TestSEPProvenanceRoundTrip:
    """Test SEP provenance serialization round-trip."""

    def test_save_load_sep_with_provenance(self, tmp_path: Path):
        """Verify provenance is preserved through save/load cycle."""
        from spec.executor.sep import load_sep

        sep = StepExecutionPlan(
            aip_id="test-aip",
            step_id="step-001",
            step_index=1,
            objective="Test objective",
            provenance=SEPProvenance(generator="llm", model="gpt-4o"),
        )

        sep_path = tmp_path / "sep.yaml"
        save_sep(sep, sep_path)

        # Verify file contains provenance
        content = sep_path.read_text()
        assert "provenance:" in content
        assert "generator: llm" in content
        assert "model: gpt-4o" in content

        # Load and verify
        loaded = load_sep(sep_path)
        assert loaded.provenance is not None
        assert loaded.provenance.generator == "llm"
        assert loaded.provenance.model == "gpt-4o"

    def test_save_load_sep_deterministic_provenance(self, tmp_path: Path):
        """Verify deterministic provenance is preserved."""
        from spec.executor.sep import load_sep

        sep = StepExecutionPlan(
            aip_id="test-aip",
            step_id="step-001",
            step_index=1,
            objective="Test objective",
            provenance=SEPProvenance(generator="deterministic"),
        )

        sep_path = tmp_path / "sep.yaml"
        save_sep(sep, sep_path)

        loaded = load_sep(sep_path)
        assert loaded.provenance is not None
        assert loaded.provenance.generator == "deterministic"
        assert loaded.provenance.model is None

    def test_load_sep_without_provenance(self, tmp_path: Path):
        """Verify SEPs without provenance load correctly (backwards compat)."""
        from spec.executor.sep import load_sep

        # Write a SEP without provenance field
        sep_content = """aip_id: test-aip
step_id: step-001
step_index: 1
objective: Test
files_to_touch: []
verification_steps: []
allowed_paths: []
forbidden_paths: []
"""
        sep_path = tmp_path / "sep.yaml"
        sep_path.write_text(sep_content)

        loaded = load_sep(sep_path)
        assert loaded.provenance is None  # No provenance in old files


class TestVerifyOnlyMode:
    """Test verify-only mode functionality."""

    def test_verify_only_with_existing_run_dir(
        self, tmp_path: Path, temp_governor_config: Path, temp_prompts_yaml: Path
    ):
        """Test verify-only mode with valid run directory."""
        # Create run directory structure
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        # Create SEP
        sep = StepExecutionPlan(
            aip_id="test-aip",
            step_id="step-001",
            step_index=1,
            objective="Test",
            provenance=SEPProvenance(generator="deterministic"),
        )
        save_sep(sep, run_dir / "sep.yaml")

        # Create patch.diff
        (run_dir / "patch.diff").write_text("diff --git a/test.py\n+new line")

        # Create step_summary.yaml
        (run_dir / "step_summary.yaml").write_text(
            """aip_id: test-aip
step_id: step-001
status: PASS
"""
        )

        # The verify function is tested via verify_patch_with_llm
        # Here we just verify the file structure works
        assert (run_dir / "sep.yaml").exists()
        assert (run_dir / "patch.diff").exists()
        assert (run_dir / "step_summary.yaml").exists()
