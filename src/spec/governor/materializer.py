"""Materializer: copy AIPs to repo workspaces for execution.

This module handles the L1→L2 transition, copying AIPs from
local-governor to repository workspaces where they can be
executed by agents.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from spec.governor.locator import GovernorPaths


class MaterializationError(Exception):
    """Raised when materialization fails."""

    pass


class TargetRepoNotFoundError(Exception):
    """Raised when a target repository cannot be found."""

    def __init__(self, repo: str, searched_paths: list[str]) -> None:
        self.repo = repo
        self.searched_paths = searched_paths
        paths_str = "\n  - ".join(searched_paths)
        super().__init__(
            f"Target repository '{repo}' not found. Searched:\n  - {paths_str}"
        )


class Materializer:
    """Materializes AIPs into repo workspaces for execution."""

    # Default directory name for materialized files
    TMP_DIR_NAME = "tmp"

    def __init__(self, paths: GovernorPaths) -> None:
        """Initialize the materializer.

        Args:
            paths: GovernorPaths with all path components
        """
        self._paths = paths

    def materialize_aip(
        self,
        aip_id: str,
        target_repo: Path,
        *,
        force: bool = False,
    ) -> Path:
        """Materialize an AIP to a repo's tmp directory.

        Args:
            aip_id: The AIP ID to materialize
            target_repo: Path to the target repository
            force: Overwrite existing materialized file

        Returns:
            Path to the materialized AIP file

        Raises:
            FileNotFoundError: If the AIP doesn't exist
            MaterializationError: If materialization fails
        """
        # Source AIP path
        source_path = self._paths.aips / f"{aip_id}.yaml"
        if not source_path.exists():
            raise FileNotFoundError(f"AIP not found: {source_path}")

        # Target path in repo's tmp directory
        tmp_dir = target_repo / ".specwright" / self.TMP_DIR_NAME
        target_path = tmp_dir / f"{aip_id}.yaml"

        # Check for existing file
        if target_path.exists() and not force:
            raise MaterializationError(
                f"Materialized AIP already exists at {target_path}. "
                "Use force=True to overwrite."
            )

        # Create tmp directory if needed
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # Copy the AIP file
        shutil.copy2(source_path, target_path)

        return target_path

    def materialize_aip_with_step_dir(
        self,
        aip_id: str,
        target_repo: Path,
        step_num: int,
        *,
        force: bool = False,
    ) -> tuple[Path, Path]:
        """Materialize an AIP and create a step artifacts directory.

        Args:
            aip_id: The AIP ID to materialize
            target_repo: Path to the target repository
            step_num: Step number (1-based)
            force: Overwrite existing materialized file

        Returns:
            Tuple of (aip_path, step_dir_path)
        """
        aip_path = self.materialize_aip(aip_id, target_repo, force=force)

        # Create step directory
        step_dir = (
            target_repo
            / ".specwright"
            / self.TMP_DIR_NAME
            / f"step-{step_num:03d}"
        )
        step_dir.mkdir(parents=True, exist_ok=True)

        return aip_path, step_dir

    def cleanup(self, repo: Path) -> int:
        """Remove all materialized files from a repo.

        Args:
            repo: Path to the repository

        Returns:
            Number of files removed
        """
        tmp_dir = repo / ".specwright" / self.TMP_DIR_NAME
        if not tmp_dir.exists():
            return 0

        count = 0
        for item in tmp_dir.iterdir():
            if item.is_file():
                item.unlink()
                count += 1
            elif item.is_dir():
                shutil.rmtree(item)
                count += 1

        return count

    def cleanup_step(self, repo: Path, step_num: int) -> bool:
        """Remove a specific step's artifacts.

        Args:
            repo: Path to the repository
            step_num: Step number to clean up

        Returns:
            True if step directory was removed
        """
        step_dir = (
            repo / ".specwright" / self.TMP_DIR_NAME / f"step-{step_num:03d}"
        )
        if step_dir.exists():
            shutil.rmtree(step_dir)
            return True
        return False

    def get_materialized_path(self, repo: Path, aip_id: str) -> Path:
        """Get the path where an AIP would be materialized.

        Args:
            repo: Path to the repository
            aip_id: The AIP ID

        Returns:
            Path to the materialized file (may not exist)
        """
        return repo / ".specwright" / self.TMP_DIR_NAME / f"{aip_id}.yaml"

    def is_materialized(self, repo: Path, aip_id: str) -> bool:
        """Check if an AIP is already materialized.

        Args:
            repo: Path to the repository
            aip_id: The AIP ID

        Returns:
            True if the AIP is materialized
        """
        return self.get_materialized_path(repo, aip_id).exists()

    def resolve_target_workspaces(
        self,
        targets: list[dict[str, Any]],
        registry: dict[str, str] | None = None,
    ) -> list[tuple[str, Path]]:
        """Resolve target specifications to actual paths.

        Args:
            targets: List of target specifications from spec
            registry: Optional repo name → path mapping

        Returns:
            List of (repo_name, repo_path) tuples

        Raises:
            TargetRepoNotFoundError: If a target repo cannot be found
        """
        registry = registry or {}
        results: list[tuple[str, Path]] = []

        for target in targets:
            repo = target["repo"]
            searched: list[str] = []

            # 1. Check explicit path in target
            if "path" in target:
                path = Path(target["path"]).expanduser().resolve()
                searched.append(f"explicit: {target['path']}")
                if path.exists() and (path / ".specwright.yaml").exists():
                    results.append((repo, path))
                    continue

            # 2. Check registry
            if repo in registry:
                path = Path(registry[repo]).expanduser().resolve()
                searched.append(f"registry: {registry[repo]}")
                if path.exists():
                    results.append((repo, path))
                    continue

            # 3. Check common locations
            common_paths = [
                Path.home() / "projects" / repo,
                Path.home() / "code" / repo,
                Path.home() / "repos" / repo,
                Path.cwd().parent / repo,
            ]

            for common_path in common_paths:
                searched.append(f"common: {common_path}")
                if common_path.exists() and (common_path / ".specwright.yaml").exists():
                    results.append((repo, common_path))
                    break
            else:
                raise TargetRepoNotFoundError(repo, searched)

        return results

    def get_step_artifacts(self, repo: Path, step_num: int) -> dict[str, Path]:
        """Get paths to step artifact files.

        Args:
            repo: Path to the repository
            step_num: Step number

        Returns:
            Dictionary of artifact name → path
        """
        step_dir = (
            repo / ".specwright" / self.TMP_DIR_NAME / f"step-{step_num:03d}"
        )
        return {
            "input": step_dir / "input.yaml",
            "output": step_dir / "output.json",
            "transcript": step_dir / "transcript.md",
            "gate": step_dir / "gate.md",
        }
