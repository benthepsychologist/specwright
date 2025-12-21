"""Tests for GovernanceLoader with local-governor project.build.yaml files."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from spec.autogov.exceptions import (
    AutogovNotInstalledError,
    GovernanceInvalidError,
    GovernanceNotFoundError,
)
from spec.autogov.loader import (
    AppliedPattern,
    AppliedPolicy,
    Decision,
    GovernanceBundle,
    GovernanceLoader,
    Rule,
    _parse_ref,
)


class TestParseRef:
    """Tests for _parse_ref helper function."""

    def test_parse_full_ref(self) -> None:
        """Parse a complete reference string."""
        name, version = _parse_ref("org::policy/credential-hygiene@0.1.0")
        assert name == "credential-hygiene"
        assert version == "0.1.0"

    def test_parse_pattern_ref(self) -> None:
        """Parse a pattern reference string."""
        name, version = _parse_ref("patterns::pattern/registry-kernel@0.1.0")
        assert name == "registry-kernel"
        assert version == "0.1.0"

    def test_parse_ref_without_version(self) -> None:
        """Parse reference without version."""
        name, version = _parse_ref("patterns::pattern/source-stream")
        assert name == "source-stream"
        assert version == "unknown"

    def test_parse_simple_name(self) -> None:
        """Parse simple name without namespace."""
        name, version = _parse_ref("my-policy")
        assert name == "my-policy"
        assert version == "unknown"


class TestGovernanceLoaderNotInstalled:
    """Test behavior when local-governor is not installed."""

    def test_load_raises_when_local_governor_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading should raise AutogovNotInstalledError if local-governor missing."""
        # Point to non-existent directory and clear cached root
        monkeypatch.setenv("LOCAL_GOVERNOR_HOME", str(tmp_path / "nonexistent"))
        # Also override the home directory fallback
        monkeypatch.setenv("HOME", str(tmp_path))

        loader = GovernanceLoader()
        with pytest.raises(AutogovNotInstalledError) as exc_info:
            loader.load_all("test-project", "patterns")

        assert exc_info.value.exit_code == 1
        assert "local-governor not found" in str(exc_info.value)


class TestGovernanceLoaderProjectNotFound:
    """Test behavior when project build file is not found."""

    def test_load_raises_when_project_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading should raise GovernanceNotFoundError if project missing."""
        # Create minimal local-governor structure
        (tmp_path / "projects").mkdir()
        monkeypatch.setenv("LOCAL_GOVERNOR_HOME", str(tmp_path))

        loader = GovernanceLoader()
        with pytest.raises(GovernanceNotFoundError) as exc_info:
            loader.load_all("nonexistent-project", "patterns")

        assert exc_info.value.exit_code == 2
        assert "not found" in str(exc_info.value).lower()


class TestGovernanceLoaderInvalidFiles:
    """Test behavior when build files are invalid."""

    def test_load_raises_on_invalid_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading should raise GovernanceInvalidError on invalid YAML."""
        # Create project with invalid YAML
        project_dir = tmp_path / "projects" / "bad-project"
        project_dir.mkdir(parents=True)
        (project_dir / "bad-project.build.yaml").write_text("invalid: yaml: :")
        monkeypatch.setenv("LOCAL_GOVERNOR_HOME", str(tmp_path))

        loader = GovernanceLoader()
        with pytest.raises(GovernanceInvalidError) as exc_info:
            loader.load_all("bad-project", "patterns")

        assert exc_info.value.exit_code == 3

    def test_load_raises_on_wrong_kind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading should raise GovernanceInvalidError on wrong kind."""
        # Create project with wrong kind
        project_dir = tmp_path / "projects" / "wrong-kind"
        project_dir.mkdir(parents=True)
        build_data = {"kind": "not-a-project-build", "version": "0.1"}
        with open(project_dir / "wrong-kind.build.yaml", "w") as f:
            yaml.dump(build_data, f)
        monkeypatch.setenv("LOCAL_GOVERNOR_HOME", str(tmp_path))

        loader = GovernanceLoader()
        with pytest.raises(GovernanceInvalidError) as exc_info:
            loader.load_all("wrong-kind", "patterns")

        assert exc_info.value.exit_code == 3
        assert "Invalid build file kind" in str(exc_info.value)


class TestGovernanceLoaderSuccess:
    """Test successful loading of project build files."""

    @pytest.fixture
    def mock_local_governor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> Path:
        """Create a mock local-governor with a test project."""
        project_dir = tmp_path / "projects" / "test-project"
        project_dir.mkdir(parents=True)

        build_data = {
            "kind": "project.build",
            "version": "0.1",
            "metadata": {
                "name": "test-project",
                "repo": "workspace/test-project",
                "semver": "1.0.0",
                "owner": "testowner",
                "status": "active",
            },
            "kernel": {
                "description": "A test project for testing governance loading.",
                "invariants": [
                    "Must pass all tests",
                    "No secrets in code",
                ],
            },
            "decisions": [
                {
                    "id": "adr-001",
                    "title": "Use Python",
                    "status": "accepted",
                    "rationale": "Team expertise",
                    "decision": "All code in Python 3.11+",
                },
                {
                    "id": "adr-002",
                    "title": "Use YAML configs",
                    "status": "accepted",
                    "rationale": "Human readable",
                },
            ],
            "rules": {
                "placement": [
                    {
                        "id": "no-toplevel",
                        "message": "No new top-level modules",
                        "severity": "error",
                    }
                ],
                "semantic": [
                    {
                        "id": "test-coverage",
                        "check": "All modules must have tests",
                        "severity": "warning",
                    }
                ],
            },
            "applies": {
                "policies": [
                    "org::policy/credential-hygiene@0.1.0",
                ],
                "patterns": [
                    "patterns::pattern/registry-kernel@0.1.0",
                    "patterns::pattern/source-stream@0.1.0",
                ],
            },
            "frozen": [
                {"path": "src/__init__.py", "reason": "Public API"},
                {"path": "src/interfaces.py", "reason": "Contracts"},
            ],
        }

        with open(project_dir / "test-project.build.yaml", "w") as f:
            yaml.dump(build_data, f)

        monkeypatch.setenv("LOCAL_GOVERNOR_HOME", str(tmp_path))
        return tmp_path

    def test_load_returns_governance_bundle(
        self, mock_local_governor: Path
    ) -> None:
        """Loading should return a GovernanceBundle."""
        loader = GovernanceLoader()
        bundle = loader.load_all("test-project", "patterns")

        assert isinstance(bundle, GovernanceBundle)
        assert bundle.project == "test-project"
        assert bundle.source == "patterns"
        assert bundle.version == "1.0.0"

    def test_load_extracts_description(
        self, mock_local_governor: Path
    ) -> None:
        """Loading should extract kernel description."""
        loader = GovernanceLoader()
        bundle = loader.load_all("test-project", "patterns")

        assert "test project for testing governance" in bundle.description.lower()

    def test_load_extracts_decisions(
        self, mock_local_governor: Path
    ) -> None:
        """Loading should extract decisions."""
        loader = GovernanceLoader()
        bundle = loader.load_all("test-project", "patterns")

        assert len(bundle.decisions) == 2
        assert bundle.decisions[0].id == "adr-001"
        assert bundle.decisions[0].title == "Use Python"
        assert bundle.decisions[0].rationale == "Team expertise"
        assert bundle.decisions[1].id == "adr-002"

    def test_load_extracts_rules(
        self, mock_local_governor: Path
    ) -> None:
        """Loading should extract rules."""
        loader = GovernanceLoader()
        bundle = loader.load_all("test-project", "patterns")

        assert len(bundle.rules) == 2
        placement_rules = [r for r in bundle.rules if r.kind == "placement"]
        semantic_rules = [r for r in bundle.rules if r.kind == "semantic"]
        assert len(placement_rules) == 1
        assert len(semantic_rules) == 1
        assert placement_rules[0].severity == "error"

    def test_load_extracts_policies(
        self, mock_local_governor: Path
    ) -> None:
        """Loading should extract applied policies."""
        loader = GovernanceLoader()
        bundle = loader.load_all("test-project", "patterns")

        assert len(bundle.policies) == 1
        assert bundle.policies[0].name == "credential-hygiene"
        assert bundle.policies[0].version == "0.1.0"

    def test_load_extracts_patterns(
        self, mock_local_governor: Path
    ) -> None:
        """Loading should extract applied patterns."""
        loader = GovernanceLoader()
        bundle = loader.load_all("test-project", "patterns")

        assert len(bundle.patterns) == 2
        pattern_names = [p.name for p in bundle.patterns]
        assert "registry-kernel" in pattern_names
        assert "source-stream" in pattern_names

    def test_load_extracts_invariants(
        self, mock_local_governor: Path
    ) -> None:
        """Loading should extract kernel invariants."""
        loader = GovernanceLoader()
        bundle = loader.load_all("test-project", "patterns")

        assert len(bundle.invariants) == 2
        assert "Must pass all tests" in bundle.invariants

    def test_load_extracts_frozen_paths(
        self, mock_local_governor: Path
    ) -> None:
        """Loading should extract frozen paths."""
        loader = GovernanceLoader()
        bundle = loader.load_all("test-project", "patterns")

        assert len(bundle.frozen_paths) == 2
        assert "src/__init__.py" in bundle.frozen_paths


class TestGovernanceBundleDataclass:
    """Test GovernanceBundle dataclass behavior."""

    def test_bundle_stores_all_fields(self) -> None:
        """GovernanceBundle should store all provided fields."""
        bundle = GovernanceBundle(
            project="my-project",
            source="patterns",
            version="1.0.0",
            description="Test description",
            decisions=[Decision(id="d1", title="Test", status="accepted")],
            rules=[Rule(id="r1", message="Test rule", severity="error", kind="placement")],
            policies=[AppliedPolicy(ref="org::policy/test@1.0", name="test", version="1.0")],
            patterns=[AppliedPattern(ref="patterns::pattern/test@1.0", name="test", version="1.0")],
            invariants=["Must pass tests"],
            frozen_paths=["src/__init__.py"],
        )

        assert bundle.project == "my-project"
        assert bundle.version == "1.0.0"
        assert len(bundle.decisions) == 1
        assert len(bundle.rules) == 1
        assert len(bundle.policies) == 1
        assert len(bundle.patterns) == 1
        assert len(bundle.invariants) == 1
        assert len(bundle.frozen_paths) == 1

    def test_bundle_has_default_empty_lists(self) -> None:
        """GovernanceBundle should have empty lists by default."""
        bundle = GovernanceBundle(
            project="my-project",
            source="patterns",
            version="1.0.0",
            description="Test",
        )

        assert bundle.decisions == []
        assert bundle.rules == []
        assert bundle.policies == []
        assert bundle.patterns == []
        assert bundle.invariants == []
        assert bundle.frozen_paths == []
