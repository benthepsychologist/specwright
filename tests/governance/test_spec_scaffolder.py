"""Tests for spec scaffolder."""

import tempfile
from pathlib import Path

import pytest
import yaml

from spec.governance.intent_parser import ParsedIntent
from spec.governance.spec_scaffolder import SpecScaffolder


class TestSpecScaffolder:
    """Tests for SpecScaffolder class."""

    def test_load_build_yaml_from_governor(self, tmp_path):
        """Build.yaml is loaded from governor location."""
        # Setup: create governor structure
        governor_root = tmp_path / "governor"
        project_dir = governor_root / "projects" / "myrepo"
        project_dir.mkdir(parents=True)

        build_yaml = {
            "kind": "project.build",
            "version": "0.1",
            "modules": [{"name": "core", "provides": ["utilities"]}],
        }
        (project_dir / "myrepo.build.yaml").write_text(yaml.dump(build_yaml))

        # Create repo path
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(id="test", title="Test", goal="test goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=governor_root)

        assert scaffolder.build_yaml is not None
        assert scaffolder.build_yaml["modules"][0]["name"] == "core"

    def test_load_build_yaml_from_legacy_location(self, tmp_path):
        """Build.yaml is loaded from legacy .specwright location."""
        repo_path = tmp_path / "myrepo"
        specwright_dir = repo_path / ".specwright"
        specwright_dir.mkdir(parents=True)

        build_yaml = {
            "kind": "project.build",
            "version": "0.1",
            "modules": [{"name": "legacy", "provides": ["compat"]}],
        }
        (specwright_dir / "build.yaml").write_text(yaml.dump(build_yaml))

        intent = ParsedIntent(id="test", title="Test", goal="test goal")
        # Use a non-existent governor root to force legacy lookup
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "noexist")

        assert scaffolder.build_yaml is not None
        assert scaffolder.build_yaml["modules"][0]["name"] == "legacy"

    def test_load_build_yaml_missing_returns_none(self, tmp_path):
        """Missing build.yaml returns None."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(id="test", title="Test", goal="test goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "noexist")

        assert scaffolder.build_yaml is None

    def test_format_current_capabilities_no_build_yaml(self, tmp_path):
        """No build.yaml produces placeholder comment."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(id="test", title="Test", goal="test goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "noexist")

        capabilities = scaffolder._format_current_capabilities()
        assert "No build.yaml found" in capabilities

    def test_format_current_capabilities_with_full_build(self, tmp_path):
        """Build.yaml with kernel, modules, layout is formatted correctly."""
        governor_root = tmp_path / "governor"
        project_dir = governor_root / "projects" / "myrepo"
        project_dir.mkdir(parents=True)

        build_yaml = {
            "kernel": {
                "surfaces": [
                    {
                        "name": "cli",
                        "entrypoints": [
                            {"command": "spec run", "usage": "spec run <spec>"},
                            {"command": "spec status"},
                        ],
                    }
                ]
            },
            "modules": [
                {"name": "core", "provides": ["utilities", "config"]},
                {"name": "cli", "provides": ["commands"]},
            ],
            "layout": [
                {"path": "src/spec/", "role": "Main source code"},
                {"path": "tests/", "role": "Test suite"},
            ],
        }
        (project_dir / "myrepo.build.yaml").write_text(yaml.dump(build_yaml))

        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(id="test", title="Test", goal="test goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=governor_root)

        capabilities = scaffolder._format_current_capabilities()

        # Check kernel.surfaces
        assert "### kernel.surfaces" in capabilities
        assert 'command: "spec run"' in capabilities
        assert 'usage: "spec run <spec>"' in capabilities
        assert 'command: "spec status"' in capabilities

        # Check modules
        assert "### modules" in capabilities
        assert "- name: core" in capabilities
        assert "- name: cli" in capabilities

        # Check layout
        assert "### layout" in capabilities
        assert "- path: src/spec/" in capabilities
        assert 'role: "Main source code"' in capabilities


class TestSpecScaffolderOutput:
    """Tests for scaffold output generation."""

    def test_scaffold_generates_valid_frontmatter(self, tmp_path):
        """Scaffold produces valid YAML frontmatter."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(
            id="t005-03",
            title="Test Feature",
            goal="Make it work",
            tier="B",
            owner="testuser",
            branch="feat/t005-03",
            epic_id="t005",
        )
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")

        spec = scaffolder.scaffold()

        # Extract frontmatter
        assert spec.startswith("---\n")
        end = spec.find("\n---\n", 4)
        assert end != -1
        frontmatter = yaml.safe_load(spec[4:end])

        assert frontmatter["id"] == "t005-03"
        assert frontmatter["title"] == "Test Feature"
        assert frontmatter["goal"] == "Make it work"
        assert frontmatter["tier"] == "B"
        assert frontmatter["owner"] == "testuser"
        assert frontmatter["branch"] == "feat/t005-03"
        assert frontmatter["status"] == "draft"
        assert "created" in frontmatter

    def test_scaffold_includes_all_sections(self, tmp_path):
        """Scaffold includes all required sections."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(
            id="test",
            title="Test",
            goal="goal",
            expectations=["exp1", "exp2"],
            constraints=["cons1"],
        )
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")

        spec = scaffolder.scaffold(num_phases=2)

        # Required sections
        assert "## Objective" in spec
        assert "## Problem" in spec
        assert "## Current Capabilities" in spec
        assert "## Proposed build_delta" in spec
        assert "## Acceptance Criteria" in spec
        assert "## Constraints" in spec
        assert "## Phase 1:" in spec
        assert "## Phase 2:" in spec

    def test_scaffold_includes_acceptance_criteria_from_intent(self, tmp_path):
        """Scaffold uses expectations from intent as acceptance criteria."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(
            id="test",
            title="Test",
            goal="goal",
            expectations=["First criterion", "Second criterion"],
        )
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")

        spec = scaffolder.scaffold()

        assert "- [ ] First criterion" in spec
        assert "- [ ] Second criterion" in spec

    def test_scaffold_includes_constraints_from_intent(self, tmp_path):
        """Scaffold uses constraints from intent."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(
            id="test",
            title="Test",
            goal="goal",
            constraints=["Must be fast", "No breaking changes"],
        )
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")

        spec = scaffolder.scaffold()

        assert "- Must be fast" in spec
        assert "- No breaking changes" in spec

    def test_scaffold_phase_has_required_subsections(self, tmp_path):
        """Each phase has Objective, Files to Touch, Implementation Notes, Verification."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(id="test", title="Test", goal="goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")

        spec = scaffolder.scaffold(num_phases=1)

        # Phase subsections
        assert "### Objective" in spec
        assert "### Files to Touch" in spec
        assert "### Implementation Notes" in spec
        assert "### Verification" in spec

    def test_scaffold_defaults_missing_values(self, tmp_path):
        """Missing intent values get sensible defaults."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(
            id="test",
            title="Test",
            goal="goal",
            # No tier, owner, branch, epic_id
        )
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")

        spec = scaffolder.scaffold()

        # Check defaults are applied
        assert "tier: B" in spec  # Default tier
        assert "owner: TODO" in spec  # Placeholder
        assert "branch: feat/test" in spec  # Generated from id
        assert "**Epic:** TODO" in spec  # Placeholder

    def test_scaffold_num_phases_parameter(self, tmp_path):
        """num_phases parameter controls number of phase sections."""
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(id="test", title="Test", goal="goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")

        spec = scaffolder.scaffold(num_phases=4)

        assert "## Phase 1:" in spec
        assert "## Phase 2:" in spec
        assert "## Phase 3:" in spec
        assert "## Phase 4:" in spec
        assert "## Phase 5:" not in spec

    def test_scaffold_with_build_yaml_shows_capabilities(self, tmp_path):
        """Scaffold includes Current Capabilities from build.yaml."""
        governor_root = tmp_path / "governor"
        project_dir = governor_root / "projects" / "myrepo"
        project_dir.mkdir(parents=True)

        build_yaml = {
            "modules": [{"name": "test-module", "provides": ["test-feature"]}]
        }
        (project_dir / "myrepo.build.yaml").write_text(yaml.dump(build_yaml))

        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(id="test", title="Test", goal="goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=governor_root)

        spec = scaffolder.scaffold()

        assert "## Current Capabilities" in spec
        assert "test-module" in spec
