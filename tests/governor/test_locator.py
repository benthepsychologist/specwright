"""Tests for governor locator module."""

from pathlib import Path

import pytest

from spec.governor.locator import (
    GovernorLocator,
    GovernorNotFoundError,
    GovernorPaths,
    GovernorValidationError,
)


@pytest.fixture
def mock_governor(tmp_path: Path) -> Path:
    """Create a valid mock governor directory structure with project."""
    governor = tmp_path / "local-governor"
    project = governor / "projects" / "test-project"
    (project / "specs").mkdir(parents=True)
    (project / "aips").mkdir()
    (project / "errors").mkdir()
    (project / "runs").mkdir()
    return governor


class TestGovernorPaths:
    """Tests for GovernorPaths dataclass."""

    def test_from_root_creates_all_paths(self, tmp_path: Path) -> None:
        """GovernorPaths.from_root creates all path components."""
        paths = GovernorPaths.from_root(tmp_path, "my-project")

        assert paths.root == tmp_path
        assert paths.project == "my-project"
        assert paths.project_root == tmp_path / "projects" / "my-project"
        assert paths.specs == tmp_path / "projects" / "my-project" / "specs"
        assert paths.aips == tmp_path / "projects" / "my-project" / "aips"
        assert paths.errors == tmp_path / "projects" / "my-project" / "errors"
        assert paths.runs == tmp_path / "projects" / "my-project" / "runs"
        assert paths.governance == tmp_path / "projects" / "my-project"


class TestGovernorLocator:
    """Tests for GovernorLocator class."""

    def test_find_from_env_var(
        self, mock_governor: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SPECWRIGHT_GOVERNOR_ROOT env var takes precedence."""
        monkeypatch.setenv("SPECWRIGHT_GOVERNOR_ROOT", str(mock_governor))

        locator = GovernorLocator(project="test-project")
        paths = locator.find()

        assert paths.root == mock_governor
        assert paths.project == "test-project"

    def test_find_from_config(self, mock_governor: Path) -> None:
        """Falls back to config governor.path."""
        config = {"governor": {"path": str(mock_governor)}}
        locator = GovernorLocator(config, project="test-project")
        paths = locator.find()

        assert paths.root == mock_governor

    def test_find_from_config_with_tilde(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Config path with ~ is expanded."""
        # Create governor in fake home
        fake_home = tmp_path / "home"
        governor = fake_home / ".local" / "local-governor"
        project = governor / "projects" / "test-project"
        for d in ["specs", "aips", "errors", "runs"]:
            (project / d).mkdir(parents=True)

        monkeypatch.setenv("HOME", str(fake_home))

        config = {"governor": {"path": "~/.local/local-governor"}}
        locator = GovernorLocator(config, project="test-project")
        paths = locator.find()

        assert paths.root == governor

    def test_find_not_found_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises GovernorNotFoundError when not found."""
        # Clear env var and set DEFAULT_PATH to non-existent location
        monkeypatch.delenv("SPECWRIGHT_GOVERNOR_ROOT", raising=False)
        fake_governor = tmp_path / "nonexistent" / "local-governor"

        # Patch the class attribute
        monkeypatch.setattr(GovernorLocator, "DEFAULT_PATH", fake_governor)

        locator = GovernorLocator(project="test-project")

        with pytest.raises(GovernorNotFoundError) as exc_info:
            locator.find()

        # Error includes searched paths
        assert "Could not find local-governor" in str(exc_info.value)
        assert "default:" in str(exc_info.value)

    def test_find_invalid_structure_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises GovernorValidationError when projects dir is missing."""
        # Create governor without projects directory
        governor = tmp_path / "local-governor"
        governor.mkdir()
        # Missing: projects/

        monkeypatch.setenv("SPECWRIGHT_GOVERNOR_ROOT", str(governor))

        locator = GovernorLocator(project="test-project")

        with pytest.raises(GovernorValidationError) as exc_info:
            locator.find()

        assert "projects" in exc_info.value.missing_dirs

    def test_find_missing_project_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raises GovernorValidationError when project doesn't exist."""
        # Create governor with projects dir but no project
        governor = tmp_path / "local-governor"
        (governor / "projects").mkdir(parents=True)

        monkeypatch.setenv("SPECWRIGHT_GOVERNOR_ROOT", str(governor))

        locator = GovernorLocator(project="nonexistent-project")

        with pytest.raises(GovernorValidationError) as exc_info:
            locator.find()

        assert "projects/nonexistent-project" in exc_info.value.missing_dirs

    def test_find_with_ensure_dirs_creates_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """find(ensure_dirs=True) creates project directories."""
        governor = tmp_path / "local-governor"
        (governor / "projects").mkdir(parents=True)

        monkeypatch.setenv("SPECWRIGHT_GOVERNOR_ROOT", str(governor))

        locator = GovernorLocator(project="new-project")
        paths = locator.find(ensure_dirs=True)

        assert paths.specs.exists()
        assert paths.aips.exists()
        assert paths.errors.exists()
        assert paths.runs.exists()

    def test_exists_returns_true_when_valid(
        self, mock_governor: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """exists() returns True when valid governor found."""
        monkeypatch.setenv("SPECWRIGHT_GOVERNOR_ROOT", str(mock_governor))

        locator = GovernorLocator(project="test-project")
        assert locator.exists() is True

    def test_exists_returns_false_when_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """exists() returns False when governor not found."""
        monkeypatch.delenv("SPECWRIGHT_GOVERNOR_ROOT", raising=False)
        monkeypatch.setattr(
            GovernorLocator, "DEFAULT_PATH", tmp_path / "nonexistent"
        )

        locator = GovernorLocator(project="test-project")
        assert locator.exists() is False

    def test_get_default_path(self) -> None:
        """get_default_path returns expected default."""
        path = GovernorLocator.get_default_path()
        assert path == Path.home() / ".local" / "local-governor"

    def test_env_var_takes_precedence_over_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env var is checked before config."""
        # Create two governors with projects
        env_governor = tmp_path / "env-governor"
        config_governor = tmp_path / "config-governor"

        for g in [env_governor, config_governor]:
            project = g / "projects" / "test-project"
            for d in ["specs", "aips", "errors", "runs"]:
                (project / d).mkdir(parents=True)

        monkeypatch.setenv("SPECWRIGHT_GOVERNOR_ROOT", str(env_governor))

        config = {"governor": {"path": str(config_governor)}}
        locator = GovernorLocator(config, project="test-project")
        paths = locator.find()

        # Should use env var, not config
        assert paths.root == env_governor

    def test_resolve_project_from_config(
        self, mock_governor: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Project is resolved from config's project_slug."""
        # Create a project directory for the config's project_slug
        project = mock_governor / "projects" / "config-project"
        for d in ["specs", "aips", "errors", "runs"]:
            (project / d).mkdir(parents=True)

        monkeypatch.setenv("SPECWRIGHT_GOVERNOR_ROOT", str(mock_governor))

        config = {"project_slug": "config-project"}
        locator = GovernorLocator(config)
        paths = locator.find()

        assert paths.project == "config-project"

