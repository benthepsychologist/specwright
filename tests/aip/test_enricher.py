"""Tests for AIP v3 enricher."""

from unittest.mock import patch

import pytest

from spec.aip.enricher import (
    EnrichMode,
    enrich_aip,
)
from spec.aip.models import (
    AIPMetadata,
    AIPStep,
    AIPv3,
    AIPWorkspace,
    WorkspaceMode,
)


@pytest.fixture
def sample_aip():
    """Create a sample AIP for testing."""
    return AIPv3(
        version="3.0",
        kind="context-packet",
        metadata=AIPMetadata(
            epic_id="test-epic",
            spec_id="test-spec",
            owner="tester",
            created="2026-01-16T00:00:00+00:00",
        ),
        workspace=AIPWorkspace(
            mode=WorkspaceMode.SINGLE_REPO,
            repo_path="/workspace/test",
            branch="feat/test",
            base_branch="main",
        ),
        goal="Implement a test feature",
        expectations=["Feature works", "Tests pass"],
    )


@pytest.fixture
def sample_aip_with_steps(sample_aip):
    """Create a sample AIP with existing phases."""
    sample_aip.phases = [
        AIPStep(
            id="phase-1",
            title="First phase",
            objective="Do the first thing",
        ),
        AIPStep(
            id="phase-2",
            title="Second phase",
            objective="Do the second thing",
        ),
    ]
    return sample_aip


class TestEnrichMode:
    """Tests for EnrichMode enum."""

    def test_smart_mode(self):
        """Test smart mode value."""
        assert EnrichMode.SMART.value == "smart"

    def test_guidance_only_mode(self):
        """Test guidance_only mode value."""
        assert EnrichMode.GUIDANCE_ONLY.value == "guidance_only"

    def test_generate_steps_mode(self):
        """Test generate_steps mode value."""
        assert EnrichMode.GENERATE_STEPS.value == "generate_steps"

    def test_overwrite_steps_mode(self):
        """Test overwrite_steps mode value."""
        assert EnrichMode.OVERWRITE_STEPS.value == "overwrite_steps"


class TestEnrichAip:
    """Tests for enrich_aip function."""

    @patch("spec.aip.enricher._generate_steps")
    @patch("spec.aip.enricher._generate_guidance")
    def test_smart_mode_generates_steps_when_empty(
        self, mock_gen_guidance, mock_gen_steps, sample_aip
    ):
        """Test that smart mode generates steps when AIP has no steps."""
        mock_gen_steps.return_value = [
            AIPStep(id="step-1", title="Generated", objective="Generated step")
        ]

        result = enrich_aip(sample_aip, mode=EnrichMode.SMART)

        assert result.steps_generated is True
        mock_gen_steps.assert_called_once()

    @patch("spec.aip.enricher._generate_steps")
    @patch("spec.aip.enricher._generate_guidance")
    def test_smart_mode_skips_generation_when_steps_exist(
        self, mock_gen_guidance, mock_gen_steps, sample_aip_with_steps
    ):
        """Test that smart mode skips step generation when steps exist."""
        result = enrich_aip(sample_aip_with_steps, mode=EnrichMode.SMART)

        assert result.steps_generated is False
        mock_gen_steps.assert_not_called()

    @patch("spec.aip.enricher._generate_steps")
    @patch("spec.aip.enricher._generate_guidance")
    def test_guidance_only_never_generates_steps(
        self, mock_gen_guidance, mock_gen_steps, sample_aip
    ):
        """Test that guidance_only mode never generates steps."""
        result = enrich_aip(sample_aip, mode=EnrichMode.GUIDANCE_ONLY)

        assert result.steps_generated is False
        mock_gen_steps.assert_not_called()

    @patch("spec.aip.enricher._generate_steps")
    @patch("spec.aip.enricher._generate_guidance")
    def test_overwrite_mode_clears_existing_steps(
        self, mock_gen_guidance, mock_gen_steps, sample_aip_with_steps
    ):
        """Test that overwrite mode clears existing steps."""
        mock_gen_steps.return_value = [
            AIPStep(id="step-new", title="New", objective="New step")
        ]

        enrich_aip(sample_aip_with_steps, mode=EnrichMode.OVERWRITE_STEPS)

        # Should have called generate with cleared steps
        mock_gen_steps.assert_called_once()

    @patch("spec.aip.enricher._generate_steps")
    def test_llm_failure_returns_warning(self, mock_gen_steps, sample_aip):
        """Test that LLM failure returns a warning instead of raising."""
        mock_gen_steps.side_effect = Exception("LLM error")

        result = enrich_aip(sample_aip, mode=EnrichMode.SMART)

        assert len(result.warnings) > 0
        assert "Failed to generate phases" in result.warnings[0]
        assert result.steps_generated is False

    def test_enriched_aip_is_deep_copy(self, sample_aip_with_steps):
        """Test that enrich returns a deep copy, not mutating original."""
        original_phase_count = len(sample_aip_with_steps.phases)

        with patch("spec.aip.enricher._generate_guidance"):
            result = enrich_aip(sample_aip_with_steps, mode=EnrichMode.GUIDANCE_ONLY)

        # Original should be unchanged
        assert len(sample_aip_with_steps.phases) == original_phase_count
        # Result should have same structure
        assert len(result.aip.phases) == original_phase_count
