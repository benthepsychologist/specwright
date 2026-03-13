"""Tests for YAML spec scaffolder."""

import yaml

from spec.governance.intent_parser import ParsedIntent
from spec.governance.spec_scaffolder import SpecScaffolder


class TestSpecScaffolder:
    """Tests for SpecScaffolder class."""

    def test_load_build_yaml_from_governor(self, tmp_path):
        governor_root = tmp_path / "governor"
        project_dir = governor_root / "projects" / "myrepo"
        project_dir.mkdir(parents=True)
        (project_dir / "myrepo.build.yaml").write_text("kind: project.build\n")

        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(id="test", title="Test", goal="test goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=governor_root)
        assert scaffolder.build_yaml == {"kind": "project.build"}

    def test_load_build_yaml_from_legacy_location(self, tmp_path):
        repo_path = tmp_path / "myrepo"
        specwright_dir = repo_path / ".specwright"
        specwright_dir.mkdir(parents=True)
        (specwright_dir / "build.yaml").write_text("kind: project.build\n")

        intent = ParsedIntent(id="test", title="Test", goal="test goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "noexist")
        assert scaffolder.build_yaml == {"kind": "project.build"}

    def test_load_build_yaml_missing_returns_none(self, tmp_path):
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()

        intent = ParsedIntent(id="test", title="Test", goal="test goal")
        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "noexist")
        assert scaffolder.build_yaml is None


class TestSpecScaffolderOutput:
    """Tests for scaffold output generation."""

    def test_scaffold_generates_spec_yaml(self, tmp_path):
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()
        intent = ParsedIntent(
            id="e101-07-specwright-yaml-io",
            title="Specwright YAML IO",
            goal="Default to YAML specs",
            tier="c",
            owner="testuser",
            branch="feat/yaml-io",
            expectations=["Compile works", "Run works"],
            constraints=["No new deps"],
        )

        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")
        spec_text = scaffolder.scaffold(num_phases=3)
        spec = yaml.safe_load(spec_text)

        assert spec["kind"] == "spec"
        assert spec["name"] == "e101-07-specwright-yaml-io"
        assert spec["title"] == "Specwright YAML IO"
        assert spec["tier"] == "C"
        assert spec["owner"] == "testuser"
        assert spec["goal"] == "Default to YAML specs"
        assert spec["repo"]["working_branch"] == "feat/yaml-io"
        assert len(spec["phases"]) == 3
        assert spec["phases"][0]["phase_number"] == 1
        assert spec["phases"][2]["phase_number"] == 3
        assert spec["acceptance_criteria"][0]["text"] == "Compile works"
        assert spec["acceptance_criteria"][1]["text"] == "Run works"
        assert spec["constraints"] == ["No new deps"]
        assert "created" in spec
        assert "updated" in spec

    def test_scaffold_defaults_missing_values(self, tmp_path):
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()
        intent = ParsedIntent(id="test", title="Test", goal="goal")

        scaffolder = SpecScaffolder(intent, repo_path, governor_root=tmp_path / "gov")
        spec = yaml.safe_load(scaffolder.scaffold())

        assert spec["tier"] == "B"
        assert spec["owner"] == "TODO"
        assert spec["repo"]["working_branch"] == "feat/test"
        assert spec["acceptance_criteria"] == [{"text": "TODO", "status": "pending"}]
        assert spec["constraints"] == ["TODO"]

