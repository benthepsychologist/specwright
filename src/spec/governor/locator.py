"""Governor locator: find and validate local-governor path.

This module handles discovery of the local-governor directory using a
precedence chain:
1. SPECWRIGHT_GOVERNOR_ROOT environment variable
2. .specwright.yaml governor.path configuration
3. Default: ~/.local/local-governor
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class GovernorNotFoundError(Exception):
    """Raised when local-governor cannot be found."""

    def __init__(self, searched_paths: list[str]) -> None:
        self.searched_paths = searched_paths
        paths_str = "\n  - ".join(searched_paths)
        super().__init__(
            f"Could not find local-governor. Searched:\n  - {paths_str}\n\n"
            "To fix this:\n"
            "  1. Install local-governor: governor init\n"
            "  2. Or set SPECWRIGHT_GOVERNOR_ROOT environment variable\n"
            "  3. Or add governor.path to .specwright.yaml"
        )


class GovernorValidationError(Exception):
    """Raised when local-governor directory structure is invalid."""

    def __init__(self, path: Path, missing_dirs: list[str]) -> None:
        self.path = path
        self.missing_dirs = missing_dirs
        dirs_str = ", ".join(missing_dirs)
        super().__init__(
            f"Invalid local-governor at {path}\n"
            f"Missing required directories: {dirs_str}\n\n"
            "Run 'governor init' to create the required structure."
        )


@dataclass(frozen=True)
class GovernorPaths:
    """Paths within a local-governor directory for a specific project."""

    root: Path
    project: str
    project_root: Path
    specs: Path
    aips: Path
    errors: Path
    runs: Path
    governance: Path

    @classmethod
    def from_root(cls, root: Path, project: str) -> GovernorPaths:
        """Create GovernorPaths from root directory and project name.

        Args:
            root: The local-governor root directory
            project: The project name (e.g., "specwright")

        Returns:
            GovernorPaths with all paths under projects/{project}/
        """
        project_root = root / "projects" / project
        return cls(
            root=root,
            project=project,
            project_root=project_root,
            specs=project_root / "specs",
            aips=project_root / "aips",
            errors=project_root / "errors",
            runs=project_root / "runs",
            governance=project_root,  # {project}.build.yaml lives here
        )


class GovernorLocator:
    """Locates and validates the local-governor directory."""

    # Environment variable for governor path
    ENV_VAR = "SPECWRIGHT_GOVERNOR_ROOT"

    # Default governor path
    DEFAULT_PATH = Path.home() / ".local" / "local-governor"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        project: str | None = None,
    ) -> None:
        """Initialize the locator.

        Args:
            config: Optional configuration dict (from .specwright.yaml)
            project: Project name for per-project paths. If None, uses
                     config's project_slug or defaults to repo directory name.
        """
        self._config = config or {}
        self._project = project

    def find(self, ensure_dirs: bool = False) -> GovernorPaths:
        """Find and validate the local-governor path.

        Args:
            ensure_dirs: If True, create project directories if they don't exist

        Returns:
            GovernorPaths with all path components

        Raises:
            GovernorNotFoundError: If no valid governor found
            GovernorValidationError: If governor exists but project is invalid
        """
        root = self._resolve_path()
        project = self._resolve_project()
        self._validate_structure(root, project, ensure_dirs)
        return GovernorPaths.from_root(root, project)

    def _resolve_project(self) -> str:
        """Resolve project name from config or default."""
        if self._project:
            return self._project
        # Try config's project_slug
        project = self._config.get("project_slug")
        if project:
            return project
        # Default to current directory name
        return Path.cwd().name

    def _resolve_path(self) -> Path:
        """Resolve governor path using precedence chain."""
        searched: list[str] = []

        # 1. Environment variable (highest precedence)
        env_path = os.environ.get(self.ENV_VAR)
        if env_path:
            path = Path(env_path).expanduser().resolve()
            searched.append(f"${self.ENV_VAR}={env_path}")
            if path.exists():
                return path

        # 2. Config file governor.path
        config_path = self._config.get("governor", {}).get("path")
        if config_path:
            path = Path(config_path).expanduser().resolve()
            searched.append(f"config: {config_path}")
            if path.exists():
                return path

        # 3. Default path
        searched.append(f"default: {self.DEFAULT_PATH}")
        if self.DEFAULT_PATH.exists():
            return self.DEFAULT_PATH

        raise GovernorNotFoundError(searched)

    def _validate_structure(
        self, root: Path, project: str, ensure_dirs: bool
    ) -> None:
        """Validate the governor directory structure.

        Args:
            root: Governor root path
            project: Project name
            ensure_dirs: If True, create missing directories

        Raises:
            GovernorValidationError: If required directories are missing
        """
        # Check that projects directory exists
        projects_dir = root / "projects"
        if not projects_dir.is_dir():
            raise GovernorValidationError(root, ["projects"])

        # Check/create project directory
        project_dir = projects_dir / project
        if ensure_dirs:
            project_dir.mkdir(parents=True, exist_ok=True)
            # Create subdirectories
            for subdir in ["specs", "aips", "errors", "runs"]:
                (project_dir / subdir).mkdir(exist_ok=True)
        elif not project_dir.is_dir():
            raise GovernorValidationError(
                root, [f"projects/{project}"]
            )

    @classmethod
    def get_default_path(cls) -> Path:
        """Get the default governor path."""
        return cls.DEFAULT_PATH

    def exists(self, project: str | None = None) -> bool:
        """Check if a valid governor exists without raising exceptions.

        Args:
            project: Optional project name to check

        Returns:
            True if a valid governor exists, False otherwise
        """
        try:
            self.find()
            return True
        except (GovernorNotFoundError, GovernorValidationError):
            return False
