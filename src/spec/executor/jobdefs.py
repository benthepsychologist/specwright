"""JobDef loader: load JobDef YAML files with configurable lookup + fallback.

Lookup order:
1. `.specwright.yaml` -> `jobdefs.path` (if configured)
2. Bundled templates (`src/spec/templates/jobdefs`)
3. Governor defaults (`~/.local/local-governor/jobdefs/specwright` or explicit governor_path)
   when no explicit/configured jobdefs path is set

The execute() function expects the full JobDef in the envelope, not a
job_id reference. This separation keeps the executor library stateless.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import]

from spec.executor.schemas import JobDef

if TYPE_CHECKING:
    pass


class JobDefError(Exception):
    """Base exception for JobDef loading errors."""

    def __init__(self, message: str, *, job_id: str | None = None) -> None:
        self.job_id = job_id
        super().__init__(message)


class JobDefNotFoundError(JobDefError):
    """Raised when a JobDef file is not found."""

    def __init__(self, job_id: str, searched_paths: list[Path]) -> None:
        self.searched_paths = searched_paths
        paths_str = "\n  - ".join(str(p) for p in searched_paths)
        super().__init__(
            f"JobDef '{job_id}' not found. Searched:\n  - {paths_str}\n\n"
            "Run 'spec init' to install default JobDefs.",
            job_id=job_id,
        )


def get_jobdefs_dir(governor_path: Path | None = None) -> Path:
    """Get the path to the JobDefs directory.

    Args:
        governor_path: Optional governor root path (defaults to ~/.local/local-governor)

    Returns:
        Path to ~/.local/local-governor/jobdefs/specwright/
    """
    if governor_path is None:
        governor_path = Path.home() / ".local" / "local-governor"
    return governor_path / "jobdefs" / "specwright"


def _find_local_config(start_path: Path | None = None) -> dict[str, Any] | None:
    """Find and parse `.specwright.yaml` by walking up from start_path."""
    current = (start_path or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        config_path = parent / ".specwright.yaml"
        if not config_path.exists():
            continue
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            return None
        return raw
    return None


def _configured_jobdefs_dir(start_path: Path | None = None) -> Path | None:
    """Return configured jobdefs.path from `.specwright.yaml` if present."""
    config = _find_local_config(start_path)
    if not config:
        return None

    jobdefs_cfg = config.get("jobdefs")
    if not isinstance(jobdefs_cfg, dict):
        return None

    path_value = jobdefs_cfg.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        return None

    return Path(path_value).expanduser().resolve()


def _jobdef_search_dirs(
    *,
    governor_path: Path | None = None,
    jobdefs_path: Path | None = None,
) -> list[Path]:
    """Build ordered search directories for JobDef files."""
    dirs: list[Path] = []

    if jobdefs_path is not None:
        dirs.append(jobdefs_path.expanduser().resolve())
    else:
        configured = _configured_jobdefs_dir()
        if configured is not None:
            dirs.append(configured)
        else:
            dirs.append(get_jobdefs_dir(governor_path))

    bundled = _find_default_jobdefs_dir()
    if bundled is not None:
        dirs.append(bundled)

    # Preserve order; remove duplicates.
    deduped: list[Path] = []
    seen: set[Path] = set()
    for d in dirs:
        if d in seen:
            continue
        seen.add(d)
        deduped.append(d)
    return deduped


def load_job_def(
    job_id: str,
    governor_path: Path | None = None,
    jobdefs_path: Path | None = None,
) -> JobDef:
    """Load a JobDef by ID from the jobdefs directory.

    Args:
        job_id: The JobDef ID (e.g., "aip-1", "interactive-1")
        governor_path: Optional governor root path

    Returns:
        Parsed JobDef

    Raises:
        JobDefNotFoundError: If the JobDef file doesn't exist
        JobDefError: If the JobDef file is invalid
    """
    searched_paths: list[Path] = []
    filename = f"{job_id}.yaml"

    for search_dir in _jobdef_search_dirs(
        governor_path=governor_path,
        jobdefs_path=jobdefs_path,
    ):
        candidate = search_dir / filename
        searched_paths.append(candidate)
        if candidate.exists():
            return load_job_def_from_path(candidate)

    raise JobDefNotFoundError(job_id, searched_paths)


def load_job_def_from_path(path: Path) -> JobDef:
    """Load a JobDef from a specific file path.

    Args:
        path: Path to the JobDef YAML file

    Returns:
        Parsed JobDef

    Raises:
        JobDefError: If the file is invalid
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except Exception as e:
        raise JobDefError(f"Failed to read JobDef from {path}: {e}") from e

    if not isinstance(raw, dict):
        raise JobDefError(f"JobDef must be a YAML mapping, got {type(raw).__name__}")

    try:
        return JobDef.model_validate(raw)
    except Exception as e:
        job_id = raw.get("job_id", "unknown")
        raise JobDefError(f"Invalid JobDef '{job_id}': {e}", job_id=job_id) from e


def list_job_defs(governor_path: Path | None = None) -> list[str]:
    """List all available JobDef IDs.

    Args:
        governor_path: Optional governor root path

    Returns:
        List of JobDef IDs (without .yaml extension)
    """
    names: set[str] = set()
    for search_dir in _jobdef_search_dirs(governor_path=governor_path):
        if not search_dir.exists():
            continue
        for path in search_dir.glob("*.yaml"):
            if path.is_file():
                names.add(path.stem)
    return sorted(names)


def install_default_jobdefs(
    governor_path: Path | None = None,
    source_dir: Path | None = None,
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Install default JobDefs from the specwright package to local-governor.

    Args:
        governor_path: Optional governor root path
        source_dir: Optional source directory for default JobDefs
            (defaults to specwright repo's jobdefs/ directory)
        overwrite: If True, overwrite existing JobDefs

    Returns:
        List of paths to installed JobDefs
    """
    import shutil

    jobdefs_dir = get_jobdefs_dir(governor_path)
    jobdefs_dir.mkdir(parents=True, exist_ok=True)

    # Find source directory
    if source_dir is None:
        # Look for jobdefs/ relative to the specwright package
        # This assumes the package is installed from the repo
        source_dir = _find_default_jobdefs_dir()

    if source_dir is None or not source_dir.exists():
        raise JobDefError(
            "Could not find default JobDefs directory. "
            "Ensure specwright is properly installed."
        )

    installed = []
    for src_path in source_dir.glob("*.yaml"):
        dest_path = jobdefs_dir / src_path.name

        if dest_path.exists() and not overwrite:
            continue

        shutil.copy2(src_path, dest_path)
        installed.append(dest_path)

    return installed


def _find_default_jobdefs_dir() -> Path | None:
    """Find the default jobdefs directory.

    Looks in several locations:
    1. In the templates directory (src/spec/templates/jobdefs)
    2. Via importlib.resources for installed packages

    Returns:
        Path to jobdefs directory, or None if not found
    """
    # Try relative to this module: src/spec/executor -> src/spec/templates/jobdefs
    module_path = Path(__file__).resolve()
    templates_jobdefs = module_path.parent.parent / "templates" / "jobdefs"

    if templates_jobdefs.exists():
        return templates_jobdefs

    return None
