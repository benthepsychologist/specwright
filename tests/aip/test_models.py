"""Tests for AIP v3 models."""


import pytest

from spec.aip.models import (
    AIPMetadata,
    AIPStep,
    AIPStepGuidance,
    AIPv3,
    AIPVerification,
    AIPWorkspace,
    PatternReference,
    WorkspaceMode,
)
from spec.aip.validation import validate_aip


@pytest.fixture
def sample_aip() -> AIPv3:
    """Create a sample AIP v3 for testing."""
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
        constraints=["No breaking changes"],
        phases=[
            AIPStep(
                id="phase-1",
                title="First phase",
                objective="Do the first thing",
                guidance=AIPStepGuidance(
                    likely_files=["src/test.py"],
                    patterns_to_follow=[
                        PatternReference(file="src/example.py", note="Follow this pattern")
                    ],
                    approach="1. Do this\n2. Then that",
                    watch_out_for=["Don't do X"],
                ),
                verification=[
                    AIPVerification(cmd="pytest tests/", expected="All tests pass")
                ],
            )
        ],
    )


class TestAIPv3:
    """Tests for AIPv3 dataclass."""

    def test_create_minimal_aip(self):
        """Test creating a minimal AIP."""
        aip = AIPv3(
            version="3.0",
            kind="context-packet",
            metadata=AIPMetadata(
                epic_id="e001",
                spec_id="s001",
                owner="test",
                created="2026-01-01T00:00:00+00:00",
            ),
            workspace=AIPWorkspace(
                mode=WorkspaceMode.SINGLE_REPO,
                repo_path="/repo",
                branch="main",
                base_branch="main",
            ),
            goal="Test goal",
        )
        assert aip.metadata.epic_id == "e001"
        assert aip.version == "3.0"

    def test_version_defaults_to_3_0(self):
        """Test that version defaults to 3.0."""
        aip = AIPv3(
            version="2.0",  # Will be overridden
            kind="context-packet",
            metadata=AIPMetadata(
                epic_id="e001",
                spec_id="s001",
                owner="test",
                created="2026-01-01T00:00:00+00:00",
            ),
            workspace=AIPWorkspace(
                mode=WorkspaceMode.SINGLE_REPO,
                repo_path="/repo",
                branch="main",
                base_branch="main",
            ),
            goal="Test",
        )
        assert aip.version == "3.0"

    def test_to_dict_roundtrip(self, sample_aip):
        """Test serialization roundtrip."""
        data = sample_aip.to_dict()

        # Check structure
        assert data["version"] == "3.0"
        assert data["kind"] == "context-packet"
        assert data["metadata"]["epic_id"] == "test-epic"
        assert data["workspace"]["mode"] == "single-repo"
        assert len(data["phases"]) == 1

        # Roundtrip
        aip2 = AIPv3.from_dict(data)
        assert aip2.metadata.epic_id == sample_aip.metadata.epic_id
        assert aip2.workspace.mode == WorkspaceMode.SINGLE_REPO
        assert len(aip2.phases) == 1
        assert aip2.phases[0].guidance is not None
        assert aip2.phases[0].guidance.likely_files == ["src/test.py"]

    def test_to_dict_omits_empty_fields(self):
        """Test that empty fields are omitted from dict."""
        aip = AIPv3(
            version="3.0",
            kind="context-packet",
            metadata=AIPMetadata(
                epic_id="e001",
                spec_id="s001",
                owner="test",
                created="2026-01-01T00:00:00+00:00",
            ),
            workspace=AIPWorkspace(
                mode=WorkspaceMode.SINGLE_REPO,
                repo_path="/repo",
                branch="main",
                base_branch="main",
            ),
            goal="Test",
        )
        data = aip.to_dict()

        # Empty lists should be omitted
        assert "expectations" not in data
        assert "constraints" not in data
        assert "steps" not in data


class TestAIPValidation:
    """Tests for AIP v3 validation."""

    def test_valid_aip_passes_validation(self, sample_aip):
        """Test that a valid AIP passes validation."""
        errors = validate_aip(sample_aip)
        assert errors == []

    def test_invalid_version_fails_validation(self):
        """Test that invalid version fails validation."""
        data = {
            "version": "2.0",  # Invalid - should be 3.0
            "kind": "context-packet",
            "metadata": {
                "epic_id": "e001",
                "spec_id": "s001",
                "owner": "test",
                "created": "2026-01-01T00:00:00+00:00",
            },
            "workspace": {
                "mode": "single-repo",
                "repo_path": "/repo",
                "branch": "main",
                "base_branch": "main",
            },
            "goal": "Test",
        }
        errors = validate_aip(data)
        assert len(errors) > 0
        assert any("version" in e for e in errors)

    def test_missing_required_field_fails_validation(self):
        """Test that missing required field fails validation."""
        data = {
            "version": "3.0",
            "kind": "context-packet",
            # Missing metadata
            "workspace": {
                "mode": "single-repo",
                "repo_path": "/repo",
                "branch": "main",
                "base_branch": "main",
            },
            "goal": "Test",
        }
        errors = validate_aip(data)
        assert len(errors) > 0
        assert any("metadata" in e for e in errors)


class TestWorkspaceMode:
    """Tests for WorkspaceMode enum."""

    def test_single_repo_mode(self):
        """Test single-repo mode."""
        mode = WorkspaceMode("single-repo")
        assert mode == WorkspaceMode.SINGLE_REPO

    def test_multi_repo_mode(self):
        """Test multi-repo mode."""
        mode = WorkspaceMode("multi-repo")
        assert mode == WorkspaceMode.MULTI_REPO
