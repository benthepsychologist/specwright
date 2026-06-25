"""Governance validation callables for the python backend.

These functions match the python backend callable contract:
  fn(payload: dict, repo_path: Path) -> {"passed": bool, "data": dict, "summary": str}

They wrap the validators and return structured ValidationReport data.
"""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import]


def _governor_root() -> Path:
    """Get governor root via the standard locator (env → config → default)."""
    from spec.governor.locator import GovernorLocator

    return GovernorLocator().find(ensure_dirs=False).root


def _resolve_code_catalog(governor_root: Path, project: str) -> Path:
    """Derive code catalog path from a project's build.yaml.

    Finds the layout entry for the ``catalog`` module and constructs the
    full path using ``metadata.repo``.
    """
    build_path = governor_root / "projects" / project / f"{project}.build.yaml"
    if not build_path.exists():
        # Fall back to /workspace/<project>/src/<project>/catalog.py
        return Path(f"/workspace/{project}/src/{project}/catalog.py")

    build = yaml.safe_load(build_path.read_text()) or {}
    repo_str = (build.get("metadata") or {}).get("repo", "")
    if repo_str.startswith("/"):
        repo_path = Path(repo_str)
    elif repo_str:
        repo_path = Path("/") / repo_str
        if not repo_path.exists():
            repo_path = Path("/workspace") / project
    else:
        repo_path = Path("/workspace") / project

    # Find the catalog module in layout
    for entry in build.get("layout") or []:
        if entry.get("module") == "catalog":
            return repo_path / entry["path"]

    # Fallback: conventional location
    return repo_path / "src" / project / "catalog.py"


def _safe_load_yaml(path: Path) -> dict | None:
    """Load YAML with error handling. Returns None on failure."""
    try:
        data = yaml.safe_load(path.read_text())
        if data is None:
            return {}
        if not isinstance(data, dict):
            return None
        return data
    except yaml.YAMLError:
        return None


def validate_build(*, payload: dict, repo_path: Path) -> dict:
    """Validate a project's build.yaml against the repo filesystem.

    Payload keys:
        project: str — project name (e.g., "workman")
    """
    from spec.governance.build_validator import BuildValidator

    project = payload.get("project", repo_path.name)
    governor_root = _governor_root()

    build_path = governor_root / "projects" / project / f"{project}.build.yaml"
    if not build_path.exists():
        return {
            "passed": False,
            "data": {"error": f"build.yaml not found: {build_path}"},
            "summary": f"FAILED: build.yaml not found for project '{project}'",
        }

    build_yaml = _safe_load_yaml(build_path)
    if build_yaml is None:
        return {
            "passed": False,
            "data": {"error": f"Malformed YAML in {build_path}"},
            "summary": f"FAILED: cannot parse {build_path}",
        }

    validator = BuildValidator(repo_path, build_yaml)
    report = validator.validate()

    return {
        "passed": report.passed,
        "data": report.to_dict(),
        "summary": _format_summary(report),
    }


def validate_epic(*, payload: dict, repo_path: Path) -> dict:
    """Validate an epic's cross-references and consistency.

    Payload keys:
        epic_id: str — epic ID or prefix (e.g., "t004")
    """
    from spec.governance.epic_validator import EpicValidator
    from spec.governor.resolver import ResolveError, resolve_epic

    epic_prefix = payload.get("epic_id", "")
    if not epic_prefix:
        return {
            "passed": False,
            "data": {"error": "epic_id required in payload"},
            "summary": "FAILED: epic_id not provided",
        }

    try:
        resolved = resolve_epic(epic_prefix)
    except ResolveError as e:
        return {
            "passed": False,
            "data": {"error": str(e)},
            "summary": f"FAILED: {e}",
        }

    epic_yaml = _safe_load_yaml(resolved.epic_yaml)
    if epic_yaml is None:
        return {
            "passed": False,
            "data": {"error": f"Malformed YAML in {resolved.epic_yaml}"},
            "summary": f"FAILED: cannot parse {resolved.epic_yaml}",
        }

    governor_root = _governor_root()
    build_yamls: dict[str, dict] = {}
    for target in epic_yaml.get("targets") or []:
        tid = target.get("id", "")
        gov_project = target.get("governor_project", tid)
        bp = governor_root / "projects" / gov_project / f"{gov_project}.build.yaml"
        if bp.exists():
            loaded = _safe_load_yaml(bp)
            if loaded is not None:
                build_yamls[gov_project] = loaded

    validator = EpicValidator(
        epic_yaml, build_yamls, epic_dir=resolved.epic_dir,
    )
    report = validator.validate()

    return {
        "passed": report.passed,
        "data": report.to_dict(),
        "summary": _format_summary(report),
    }


def validate_contracts(*, payload: dict, repo_path: Path) -> dict:
    """Validate op-catalog.yaml against code registrations.

    Payload keys:
        catalog_path: str — optional override for op-catalog.yaml path
        code_path: str — path to the code catalog (e.g., workman's catalog.py)
        project: str — project name to derive code_path from build.yaml
    """
    from spec.governance.contract_validator import ContractValidator

    governor_root = _governor_root()
    catalog_path = Path(
        payload.get("catalog_path", str(governor_root / "contracts" / "op-catalog.yaml"))
    )
    code_path_str = payload.get("code_path", "")
    if code_path_str:
        code_path = Path(code_path_str)
    else:
        project = payload.get("project", "workman")
        code_path = _resolve_code_catalog(governor_root, project)

    if not catalog_path.exists():
        return {
            "passed": False,
            "data": {"error": f"op-catalog not found: {catalog_path}"},
            "summary": f"FAILED: op-catalog not found at {catalog_path}",
        }

    if not code_path.exists():
        return {
            "passed": False,
            "data": {"error": f"code catalog not found: {code_path}"},
            "summary": f"FAILED: code catalog not found at {code_path}",
        }

    validator = ContractValidator(catalog_path, code_path)
    report = validator.validate()

    return {
        "passed": report.passed,
        "data": report.to_dict(),
        "summary": _format_summary(report),
    }


def _format_summary(report) -> str:
    """Format a ValidationReport as a human-readable summary."""
    lines = [f"Validation: {report.target}"]
    if report.passed:
        lines.append(f"PASSED ({report.warning_count} warnings)")
    else:
        lines.append(f"FAILED ({report.error_count} errors, {report.warning_count} warnings)")
    for f in report.findings:
        tag = "ERR" if f.severity.value == "error" else "WRN"
        lines.append(f"  [{tag}] {f.category.value}: {f.message}")
    return "\n".join(lines)


def register_all() -> None:
    """Register all governance callables with the python backend."""
    from spec.executor.backends.python import register_callable
    from spec.governance.session_capture import capture_transcript
    from spec.governance.sync_refs import sync_refs

    register_callable("governance.validate_build", validate_build)
    register_callable("governance.validate_epic", validate_epic)
    register_callable("governance.validate_contracts", validate_contracts)
    register_callable("agent.sync_refs", sync_refs)
    register_callable("session.capture_transcript", capture_transcript)
