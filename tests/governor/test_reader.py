"""Tests for governor reader module."""

from pathlib import Path

import pytest

from spec.governor.locator import GovernorPaths
from spec.governor.reader import (
    AIPNotFoundError,
    GovernorReader,
    SpecNotFoundError,
)


@pytest.fixture
def mock_paths(tmp_path: Path) -> GovernorPaths:
    """Create mock governor paths with project structure."""
    governor = tmp_path / "local-governor"
    project = governor / "projects" / "test-project"
    (project / "specs").mkdir(parents=True)
    (project / "aips").mkdir()
    (project / "errors").mkdir()
    (project / "runs").mkdir()
    return GovernorPaths.from_root(governor, "test-project")


@pytest.fixture
def sample_spec_content() -> str:
    """Sample spec Markdown content."""
    return """---
title: Test Feature
tier: C
owner: testuser
---

# Objective

Implement test feature.

## Acceptance Criteria

- [ ] Feature works
- [ ] Tests pass
"""


@pytest.fixture
def sample_aip() -> str:
    """Sample AIP YAML content."""
    return """aip_id: AIP-test-2025-12-22-001
title: Test Feature
tier: C
objective:
  goal: Implement test feature
  acceptance_criteria:
    - Feature works
    - Tests pass
plan:
  - step_id: step-001
    description: Implement feature
"""


class TestGovernorReader:
    """Tests for GovernorReader class."""

    def test_read_spec_success(
        self, mock_paths: GovernorPaths, sample_spec_content: str
    ) -> None:
        """Successfully reads spec from governor."""
        # Create spec file
        spec_path = mock_paths.specs / "test-feature.yaml"
        spec_path.write_text(sample_spec_content)

        reader = GovernorReader(mock_paths)
        content = reader.read_spec("test-feature")

        assert "# Objective" in content
        assert "Test Feature" in content

    def test_read_spec_not_found(self, mock_paths: GovernorPaths) -> None:
        """Raises SpecNotFoundError when spec doesn't exist."""
        reader = GovernorReader(mock_paths)

        with pytest.raises(SpecNotFoundError) as exc_info:
            reader.read_spec("nonexistent")

        assert exc_info.value.slug == "nonexistent"
        assert "nonexistent" in str(exc_info.value)

    def test_read_spec_parsed(
        self, mock_paths: GovernorPaths, sample_spec_content: str
    ) -> None:
        """Parses spec with YAML frontmatter."""
        spec_path = mock_paths.specs / "test-feature.md"
        spec_path.write_text(sample_spec_content)

        reader = GovernorReader(mock_paths)
        parsed = reader.read_spec_parsed("test-feature")

        assert parsed["frontmatter"]["title"] == "Test Feature"
        assert parsed["frontmatter"]["tier"] == "C"
        assert "# Objective" in parsed["body"]

    def test_read_aip_success(
        self, mock_paths: GovernorPaths, sample_aip: str
    ) -> None:
        """Successfully reads AIP from governor."""
        aip_path = mock_paths.aips / "AIP-test-2025-12-22-001.yaml"
        aip_path.write_text(sample_aip)

        reader = GovernorReader(mock_paths)
        aip = reader.read_aip("AIP-test-2025-12-22-001")

        assert aip["aip_id"] == "AIP-test-2025-12-22-001"
        assert aip["title"] == "Test Feature"
        assert len(aip["plan"]) == 1

    def test_read_aip_not_found(self, mock_paths: GovernorPaths) -> None:
        """Raises AIPNotFoundError when AIP doesn't exist."""
        reader = GovernorReader(mock_paths)

        with pytest.raises(AIPNotFoundError) as exc_info:
            reader.read_aip("nonexistent")

        assert exc_info.value.aip_id == "nonexistent"

    def test_list_specs_empty(self, mock_paths: GovernorPaths) -> None:
        """Lists empty when no specs exist."""
        reader = GovernorReader(mock_paths)
        specs = reader.list_specs()

        assert specs == []

    def test_list_specs_returns_slugs(
        self, mock_paths: GovernorPaths
    ) -> None:
        """Lists all spec slugs."""
        (mock_paths.specs / "feature-a.md").write_text("# A")
        (mock_paths.specs / "feature-b.yaml").write_text("# B")
        (mock_paths.specs / "feature-c.yml").write_text("# C")

        reader = GovernorReader(mock_paths)
        specs = reader.list_specs()

        assert specs == ["feature-a", "feature-b", "feature-c"]

    def test_list_aips_returns_ids(
        self, mock_paths: GovernorPaths
    ) -> None:
        """Lists all AIP IDs."""
        (mock_paths.aips / "AIP-001.yaml").write_text("aip_id: AIP-001")
        (mock_paths.aips / "AIP-002.yaml").write_text("aip_id: AIP-002")

        reader = GovernorReader(mock_paths)
        aips = reader.list_aips()

        assert aips == ["AIP-001", "AIP-002"]

    def test_spec_exists_true(
        self, mock_paths: GovernorPaths, sample_spec_content: str
    ) -> None:
        """spec_exists returns True when spec exists."""
        (mock_paths.specs / "test.md").write_text(sample_spec_content)

        reader = GovernorReader(mock_paths)
        assert reader.spec_exists("test") is True

    def test_spec_exists_false(self, mock_paths: GovernorPaths) -> None:
        """spec_exists returns False when spec doesn't exist."""
        reader = GovernorReader(mock_paths)
        assert reader.spec_exists("nonexistent") is False

    def test_aip_exists_true(
        self, mock_paths: GovernorPaths, sample_aip: str
    ) -> None:
        """aip_exists returns True when AIP exists."""
        (mock_paths.aips / "AIP-001.yaml").write_text(sample_aip)

        reader = GovernorReader(mock_paths)
        assert reader.aip_exists("AIP-001") is True

    def test_aip_exists_false(self, mock_paths: GovernorPaths) -> None:
        """aip_exists returns False when AIP doesn't exist."""
        reader = GovernorReader(mock_paths)
        assert reader.aip_exists("nonexistent") is False

    def test_get_spec_path(self, mock_paths: GovernorPaths) -> None:
        """get_spec_path returns correct path."""
        reader = GovernorReader(mock_paths)
        path = reader.get_spec_path("test-feature")

        assert path == mock_paths.specs / "test-feature.yaml"

    def test_get_spec_path_prefers_yaml_over_md(self, mock_paths: GovernorPaths) -> None:
        """Resolved path prefers .yaml when both .yaml and .md exist."""
        yaml_path = mock_paths.specs / "dual.yaml"
        md_path = mock_paths.specs / "dual.md"
        yaml_path.write_text("kind: spec\nname: dual\n")
        md_path.write_text("# legacy")

        reader = GovernorReader(mock_paths)
        assert reader.get_spec_path("dual") == yaml_path

    def test_get_aip_path(self, mock_paths: GovernorPaths) -> None:
        """get_aip_path returns correct path."""
        reader = GovernorReader(mock_paths)
        path = reader.get_aip_path("AIP-001")

        assert path == mock_paths.aips / "AIP-001.yaml"

    def test_parse_spec_without_frontmatter(
        self, mock_paths: GovernorPaths
    ) -> None:
        """Handles spec without YAML frontmatter."""
        (mock_paths.specs / "no-frontmatter.md").write_text("# Just content")

        reader = GovernorReader(mock_paths)
        parsed = reader.read_spec_parsed("no-frontmatter")

        assert parsed["frontmatter"] == {}
        assert parsed["body"] == "# Just content"
