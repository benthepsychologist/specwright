"""
CLI commands for the v2 executor engine.

Commands (registered at top-level of spec CLI per e008-05):
- spec compile: Compile JobDef + spec to JobInstance
- spec execute: Execute a pre-compiled JobInstance
- spec run: Compile and execute in one step
- spec status: Show run status
- spec logs: Show run logs
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml

from spec.executor.engine import (
    ExecutorError,
    compile_job,
    execute,
    execute_instance,
    generate_run_id,
)
from spec.executor.jobdefs import (
    JobDefError,
    JobDefNotFoundError,
    list_job_defs,
    load_job_def,
)
from spec.executor.run_writers import ConsolidatedRunWriter
from spec.executor.schemas import (
    JobInstance,
    OutcomeStatus,
    RunStatus,
)
from spec.executor.store import DEFAULT_ROOT as DEFAULT_RUNS_ROOT
from spec.executor.store import RunStore

# Required metadata fields for spec files
REQUIRED_FRONTMATTER = {"tier", "title", "owner", "goal"}
VALID_TIERS = {"A", "B", "C"}

# Free-range chat runs land here, separate from epic/spec runs.
SESSIONS_ROOT = Path.home() / ".local/local-governor/sessions"

# Default prompt for a free-range chat session when none is supplied. The
# claude-code backend requires a prompt to launch, even interactively.
DEFAULT_FREE_RANGE_PROMPT = (
    "Free-range chat session. You are NOT locked to a single repository — "
    "you may roam across the workspace. This session is being recorded "
    "(the transcript is captured into the run record). How can I help?"
)


def _echo_error(message: str) -> None:
    """Print error message in red."""
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)


def _echo_success(message: str) -> None:
    """Print success message in green."""
    typer.secho(message, fg=typer.colors.GREEN)


def _echo_warning(message: str) -> None:
    """Print warning message in yellow."""
    typer.secho(message, fg=typer.colors.YELLOW)


def _parse_spec_frontmatter(content: str) -> dict[str, Any]:
    """Parse and validate YAML frontmatter from .md spec.

    Args:
        content: Full markdown content of spec file

    Returns:
        Parsed and validated frontmatter dict

    Raises:
        ValueError: If frontmatter is missing, malformed, or invalid
    """
    if not content.startswith("---\n"):
        raise ValueError("Spec must start with YAML frontmatter (---)")

    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Frontmatter not closed (missing ---)")

    frontmatter_text = content[4:end]
    frontmatter = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError("Frontmatter must be a YAML mapping")
    return _validate_spec_metadata(frontmatter, source="frontmatter")


def _validate_spec_metadata(frontmatter: dict[str, Any], source: str) -> dict[str, Any]:
    """Validate required metadata fields used by compile/run flows."""
    missing = REQUIRED_FRONTMATTER - set(frontmatter.keys())
    if missing:
        raise ValueError(f"Missing required {source} fields: {missing}")

    tier = str(frontmatter.get("tier", "")).upper()
    if tier not in VALID_TIERS:
        raise ValueError(f"Invalid tier '{frontmatter.get('tier')}'. Must be one of {VALID_TIERS}")
    frontmatter["tier"] = tier

    for key in REQUIRED_FRONTMATTER:
        if key == "tier":
            continue
        val = frontmatter[key]
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"{source.capitalize()} field '{key}' must be a non-empty string")

    return frontmatter


def _update_frontmatter(content: str, updates: dict[str, Any]) -> str:
    """Update frontmatter fields in spec content.

    Args:
        content: Full markdown content
        updates: Dict of fields to add/update in frontmatter

    Returns:
        Updated content with modified frontmatter
    """
    if not content.startswith("---\n"):
        raise ValueError("Spec must start with YAML frontmatter (---)")

    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Frontmatter not closed (missing ---)")

    frontmatter_text = content[4:end]
    frontmatter = yaml.safe_load(frontmatter_text) or {}

    # Apply updates
    frontmatter.update(updates)

    # Rebuild content
    new_frontmatter = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)
    body = content[end + 5:]  # After closing ---

    return f"---\n{new_frontmatter}---\n{body}"


def _load_spec(spec_path: Path) -> tuple[dict[str, Any], str]:
    """Load a spec from either .md or .yaml/.yml format.

    Returns:
        Tuple of (metadata dict, raw spec content string).
    """
    content = spec_path.read_text(encoding="utf-8")

    if spec_path.suffix in (".yaml", ".yml"):
        raw = yaml.safe_load(content) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Expected a YAML mapping in {spec_path}")

        # Registrar-native specs nest document fields under a `document:` key.
        # Fall back to that sub-dict so both flat and envelope formats are accepted.
        doc = raw.get("document") or {}
        if not isinstance(doc, dict):
            doc = {}

        frontmatter: dict[str, Any] = {}
        for key in (
            "tier",
            "title",
            "owner",
            "goal",
            "name",
            "version",
            "epic_artifact_id",
            "labels",
            "constraints",
            "forbidden_legacy_semantics",
            "dependencies",
            "skill",
            "skills",
            "repo",
            "branch",
        ):
            val = raw[key] if key in raw else doc.get(key)
            if val is not None:
                frontmatter[key] = val

        _validate_spec_metadata(frontmatter, source="YAML spec")

        repo_raw = raw.get("repo") or doc.get("repo")
        if isinstance(repo_raw, dict):
            frontmatter["repo"] = repo_raw
            if not frontmatter.get("branch") and repo_raw.get("working_branch"):
                frontmatter["branch"] = repo_raw["working_branch"]

        name = frontmatter.get("name") or raw.get("name")
        if isinstance(name, str) and "-" in name:
            prefix = name.split("-", 1)[0]
            if prefix and prefix[0] in {"e", "s", "t"}:
                frontmatter["epic"] = prefix

        return frontmatter, content

    frontmatter = _parse_spec_frontmatter(content)
    return frontmatter, content


def _resolve_frontmatter_path(raw: Any, *, base_dir: Path) -> str | None:
    """Resolve an optional frontmatter path value against the spec directory."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def _get_spec_path(epic_id: str, spec_id: str) -> Path:
    """Get path to spec file from governor storage.

    Looks in: ~/.local/local-governor/projects/*/specs/{epic_id}/{spec_id}.yaml|.md
    Prefers .yaml when both are present.
    """
    governor_root = Path.home() / ".local/local-governor/projects"
    if not governor_root.exists():
        raise FileNotFoundError(f"Governor root not found: {governor_root}")

    for ext in (".yaml", ".md"):
        for project_dir in governor_root.iterdir():
            if not project_dir.is_dir():
                continue
            specs_dir = project_dir / "specs" / epic_id
            if not specs_dir.exists():
                continue
            spec_file = specs_dir / f"{spec_id}{ext}"
            if spec_file.exists():
                return spec_file

    raise FileNotFoundError(f"Spec not found: {epic_id}/{spec_id} (.yaml or .md)")


def _extract_check_paths(epic: Any, spec_id: str) -> list[str]:
    """Extract file paths from epic checks that apply to this spec.

    Args:
        epic: The Epic object
        spec_id: The spec ID to get checks for

    Returns:
        List of file paths that checks will verify
    """
    paths: list[str] = []

    spec = epic.get_spec(spec_id)
    if not spec:
        return paths

    for check_id in spec.checks:
        check = epic.get_check(check_id)
        if check:
            for inp in check.inputs:
                if inp.type == "file" and inp.path:
                    paths.append(inp.path)
                elif inp.type == "directory" and inp.path:
                    paths.append(inp.path.rstrip("/") + "/")

    return paths


def _echo_step(step_n: int, total: int, step_id: str, backend: str, status: str = "running") -> None:
    """Print step progress."""
    if status == "running":
        typer.echo(f"[{step_n}/{total}] Running step '{step_id}' ({backend})...")
    elif status == "completed":
        typer.secho(f"[{step_n}/{total}] ✓ {step_id}", fg=typer.colors.GREEN)
    elif status == "failed":
        typer.secho(f"[{step_n}/{total}] ✗ {step_id}", fg=typer.colors.RED)
    elif status == "skipped":
        typer.secho(f"[{step_n}/{total}] - {step_id} (skipped)", fg=typer.colors.YELLOW)


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# =============================================================================
# spec compile
# =============================================================================


def compile_command(
    job_id: str = typer.Argument(..., help="Job template ID (e.g., 'aip-1')"),
    spec_path: Path = typer.Argument(..., help="Path to spec .yaml or .md file"),
    output: Path = typer.Option(
        None, "--output", "-o", help="Output path for JobInstance (default: stdout)"
    ),
    repo_path: Path = typer.Option(
        None, "--repo", "-r", help="Repository path (default: current directory)"
    ),
    branch: str = typer.Option(
        None, "--branch", "-b", help="Feature branch name (default: from spec or auto-generated)"
    ),
    agent: str = typer.Option(
        None, "--agent", "-a", help="Agent backend (e.g., 'claude-code', 'copilot'); default: claude-code"
    ),
    models: str = typer.Option(
        None, "--models", "-m", help="Comma-separated model list in priority order (e.g., 'gpt-5.2,claude-opus-4.6')"
    ),
    review_model: str = typer.Option(
        None, "--review-model", help="Model for LLM review steps (acceptance, suggestions); default: gemini-3.1-pro-preview"
    ),
) -> None:
    """Compile a JobDef + spec into a JobInstance.

    Builds an envelope from the spec file and compiles it into a JobInstance
    that can be executed with 'spec execute'.

    Examples:
        spec compile aip-1 ./my-feature.yaml
        spec compile aip-1 ./my-feature.yaml --output job.yaml
        spec compile aip-1 ./my-feature.yaml --repo /workspace/target
    """
    # Validate inputs
    if not spec_path.exists():
        _echo_error(f"Spec file not found: {spec_path}")
        raise typer.Exit(1)

    # Load JobDef from local-governor
    try:
        job_def = load_job_def(job_id)
    except JobDefNotFoundError:
        _echo_error(f"Unknown job_id: {job_id}")
        available = list_job_defs()
        if available:
            typer.echo(f"Available job IDs: {', '.join(available)}")
        else:
            typer.echo("No JobDefs installed. Run 'spec init' to install defaults.")
        raise typer.Exit(1)
    except JobDefError as e:
        _echo_error(f"Failed to load JobDef: {e}")
        raise typer.Exit(1)

    # Load spec
    try:
        frontmatter, spec_md = _load_spec(spec_path)
    except ValueError as e:
        _echo_error(f"Invalid spec: {e}")
        raise typer.Exit(1)
    except Exception as e:
        _echo_error(f"Failed to load spec: {e}")
        raise typer.Exit(1)

    # Resolve repo path
    if repo_path is None:
        repo_path = Path.cwd()
    repo_path = repo_path.resolve()

    # Resolve branch from frontmatter or generate from title
    # Check multiple locations: top-level "branch", repo.working_branch, or generate
    if branch is None:
        branch = (
            frontmatter.get("branch")  # Top-level branch (new simple format)
            or frontmatter.get("repo", {}).get("working_branch")  # Nested repo.working_branch
        )
        if not branch:
            title_slug = frontmatter["title"].lower().replace(" ", "-")
            branch = f"feat/{title_slug}"

    # Build envelope (job_def is included, not just job_id)
    payload_agent = agent or "claude-code"  # Default to claude-code if not specified
    payload_models = [m.strip() for m in models.split(",") if m.strip()] if models else []
    payload: dict[str, Any] = {
        "spec_md": spec_md,  # Full spec content (YAML or markdown)
        "spec_path": str(spec_path.resolve()),
        "repo_path": str(repo_path),
        "feature_branch": branch,
        "spec_id": spec_path.stem,
        "epic_spec": None,  # No epic context when compiling from file
        "agent": payload_agent,
        "project": repo_path.name,  # Project name for refs.sync (derived from repo dir)
        "skill": _resolve_frontmatter_path(frontmatter.get("skill"), base_dir=spec_path.parent),
        "skills": frontmatter.get("skills"),
        # Epic folder carrying AGENTS.md + CLAUDE.md pointer for refs.sync to
        # materialize into the target repo (None when not inside an epic).
        "epic_dir": _resolve_epic_dir(spec_path),
        "models": payload_models,
    }

    # Add model overrides if specified
    if review_model:
        payload["review_model"] = review_model

    envelope = {
        "job_def": job_def.model_dump(),
        "payload": payload,
        "ctx": {
            "spec_id": spec_path.stem,
        },
    }

    # Compile to JobInstance (job_def already loaded above)
    try:
        job_instance = compile_job(job_def, envelope)
    except ExecutorError as e:
        _echo_error(f"Compilation failed: {e}")
        raise typer.Exit(1)

    # Output
    instance_dict = job_instance.model_dump(mode="json")

    if output:
        _write_yaml(output, instance_dict)
        _echo_success(f"JobInstance written to: {output}")
        typer.echo(f"  Job ID:     {job_instance.job_id}")
        typer.echo(f"  Job Hash:   {job_instance.job_hash}")
        typer.echo(f"  Steps:      {len(job_instance.steps)}")
    else:
        # Print to stdout
        print(yaml.dump(instance_dict, default_flow_style=False, allow_unicode=True, sort_keys=False))


# =============================================================================
# spec execute
# =============================================================================


def execute_command(
    job_instance_path: Path = typer.Argument(..., help="Path to JobInstance YAML file"),
    run_id: str = typer.Option(
        None, "--run-id", help="Custom run ID (default: auto-generated)"
    ),
) -> None:
    """Execute a pre-compiled JobInstance.

    Runs the steps in the JobInstance without recompiling.
    Useful for testing job definitions or replaying a run.

    Examples:
        spec execute ./job_instance.yaml
        spec execute ./job_instance.yaml --run-id custom-run-001
    """
    # Validate input
    if not job_instance_path.exists():
        _echo_error(f"JobInstance file not found: {job_instance_path}")
        raise typer.Exit(1)

    # Load JobInstance
    try:
        instance_data = _load_yaml(job_instance_path)
        job_instance = JobInstance.model_validate(instance_data)
    except Exception as e:
        _echo_error(f"Failed to load JobInstance: {e}")
        raise typer.Exit(1)

    # Generate run_id if not provided
    if run_id is None:
        run_id = generate_run_id()

    typer.echo(f"Executing JobInstance: {job_instance.job_id}")
    typer.echo(f"  Run ID:   {run_id}")
    typer.echo(f"  Steps:    {len(job_instance.steps)}")
    typer.echo("")

    # Execute directly from JobInstance (no recompilation)
    store = _new_store(_infer_runs_root())

    try:
        result = execute_instance(job_instance, store=store, run_id=run_id)
    except ExecutorError as e:
        _echo_error(f"Execution failed: {e}")
        raise typer.Exit(1)

    # Show results
    _show_run_summary(result, store)

    # Exit code based on status
    if result.status == RunStatus.failed:
        raise typer.Exit(1)
    elif result.status == RunStatus.completed_with_errors:
        raise typer.Exit(2)


# =============================================================================
# spec run
# =============================================================================


def run_command(
    job_id: str = typer.Argument(..., help="Job template ID (e.g., 'aip-1')"),
    spec_path: Path = typer.Argument(None, help="Path to spec .yaml or .md file (optional if --epic/--spec used)"),
    repo_path: Path = typer.Option(
        None, "--repo", "-r", help="Repository path (default: current directory)"
    ),
    branch: str = typer.Option(
        None, "--branch", "-b", help="Feature branch name (default: from spec or auto-generated)"
    ),
    agent: str = typer.Option(
        None, "--agent", "-a", help="Agent backend (e.g., 'claude-code', 'copilot'); default: claude-code"
    ),
    models: str = typer.Option(
        None, "--models", "-m", help="Comma-separated model list in priority order (e.g., 'gpt-5.2,claude-opus-4.6')"
    ),
    review_model: str = typer.Option(
        None, "--review-model", help="Model for LLM review steps (acceptance, suggestions); default: gemini-3.1-pro-preview"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Compile and print JobInstance without executing"
    ),
    run_id: str = typer.Option(
        None, "--run-id", help="Custom run ID (default: auto-generated)"
    ),
    epic_id: str = typer.Option(
        None, "--epic", "-e", help="Epic ID to load spec from (use with --spec)"
    ),
    spec_id: str = typer.Option(
        None, "--spec", "-s", help="Spec ID to load from (use with --epic)"
    ),
    legacy_output: bool = typer.Option(
        False,
        "--legacy-output",
        help=(
            "EXPLICIT escape hatch: legacy multi-file tree output, no gated "
            "emission. Default is local scratch + row emission through the gate."
        ),
    ),
    free_range: bool = typer.Option(
        False,
        "--free-range",
        help="Free-range chat mode: launch the agent without a spec (no repo lock), "
        "routing the run record to the sessions store. Use with chat-1.",
    ),
) -> None:
    """Compile and execute a job in one step.

    Builds an envelope from the spec file, compiles it to a JobInstance,
    and executes the steps.

    Examples:
        spec run aip-1 ./my-feature.yaml
        spec run aip-1 ./my-feature.yaml --repo /workspace/target
        spec run aip-1 ./my-feature.yaml --dry-run
        spec run aip-1 --epic e005-command-plane --spec e005-01-schemas
    """
    # Validate inputs - must have either spec_path or epic/spec.
    # Free-range mode bypasses this gate entirely (no spec required).
    if not free_range:
        if spec_path is None and (epic_id is None or spec_id is None):
            _echo_error("Must provide either SPEC_PATH or both --epic and --spec")
            raise typer.Exit(1)

        if spec_path is not None and (epic_id is not None or spec_id is not None):
            _echo_error("Cannot use both SPEC_PATH and --epic/--spec")
            raise typer.Exit(1)

    # Load JobDef from local-governor
    try:
        job_def = load_job_def(job_id)
    except JobDefNotFoundError:
        _echo_error(f"Unknown job_id: {job_id}")
        available = list_job_defs()
        if available:
            typer.echo(f"Available job IDs: {', '.join(available)}")
        else:
            typer.echo("No JobDefs installed. Run 'spec init' to install defaults.")
        raise typer.Exit(1)
    except JobDefError as e:
        _echo_error(f"Failed to load JobDef: {e}")
        raise typer.Exit(1)

    # Free-range chat mode: skip all spec loading/validation, build a minimal
    # envelope, and route the run record to a dedicated sessions store.
    if free_range:
        _run_free_range(
            job_def=job_def,
            repo_path=repo_path,
            agent=agent,
            run_id=run_id,
            dry_run=dry_run,
        )
        return

    # Load spec - either from file or from epic/spec
    epic_spec = None  # Will be populated for epic/spec mode
    resolved_spec_id = spec_id  # For ctx

    if epic_id and spec_id:
        # Load spec from governor
        from spec.epic.loader import load_epic

        try:
            spec_path = _get_spec_path(epic_id, spec_id)
        except FileNotFoundError as e:
            _echo_error(f"Failed to load spec from epic/spec: {e}")
            raise typer.Exit(1)

        # Load epic to get spec expectations for drift checking
        try:
            epic = load_epic(epic_id)
            spec_ref = epic.get_spec(spec_id)
            if spec_ref:
                epic_spec = {
                    "expectations": spec_ref.expectations,
                    "constraints": spec_ref.constraints,
                    "check_paths": _extract_check_paths(epic, spec_id),
                }
                # Get repo path from epic target (spec_ref.repo is target ID)
                if repo_path is None and spec_ref.repo:
                    target = epic.get_target(spec_ref.repo)
                    if target and target.repo_path:
                        repo_path = Path(target.repo_path)
                    else:
                        _echo_error(
                            f"Spec '{spec_id}' references repo '{spec_ref.repo}' "
                            f"but no matching target found in epic '{epic_id}'"
                        )
                        raise typer.Exit(1)
        except typer.Exit:
            raise  # Re-raise Exit exceptions
        except Exception as e:
            # Non-fatal - epic_spec is optional enhancement
            typer.secho(f"Warning: Could not load epic context: {e}", fg=typer.colors.YELLOW, err=True)

    # Load spec content
    if not spec_path.exists():
        _echo_error(f"Spec file not found: {spec_path}")
        raise typer.Exit(1)

    try:
        frontmatter, spec_md = _load_spec(spec_path)
    except ValueError as e:
        _echo_error(f"Invalid spec: {e}")
        raise typer.Exit(1)
    except Exception as e:
        _echo_error(f"Failed to load spec: {e}")
        raise typer.Exit(1)

    # Use filename as spec_id if not from epic mode
    if resolved_spec_id is None:
        resolved_spec_id = spec_path.stem

    # Resolve repo path - MUST be explicit, no fallback to cwd
    if repo_path is None:
        _echo_error(
            "No repo_path resolved. For epic/spec mode, ensure the epic has a matching "
            "target with repo_path. For file mode, use --repo to specify the target repo."
        )
        raise typer.Exit(1)
    repo_path = repo_path.resolve()

    # Verify repo exists
    if not repo_path.exists():
        _echo_error(f"Target repo does not exist: {repo_path}")
        raise typer.Exit(1)
    if not (repo_path / ".git").exists():
        _echo_error(f"Target repo is not a git repository: {repo_path}")
        raise typer.Exit(1)

    # Resolve branch from frontmatter or generate from title
    # Check multiple locations: top-level "branch", repo.working_branch, or generate
    if branch is None:
        branch = (
            frontmatter.get("branch")  # Top-level branch (new simple format)
            or frontmatter.get("repo", {}).get("working_branch")  # Nested repo.working_branch
        )
        if not branch:
            title_slug = frontmatter["title"].lower().replace(" ", "-")
            branch = f"feat/{title_slug}"

    # Build envelope (job_def is included, not just job_id)
    payload_agent = agent or "claude-code"  # Default to claude-code if not specified
    payload_models = [m.strip() for m in models.split(",") if m.strip()] if models else []
    payload: dict[str, Any] = {
        "spec_md": spec_md,  # Full spec content (YAML or markdown)
        "spec_path": str(spec_path.resolve()),
        "repo_path": str(repo_path),
        "feature_branch": branch,
        "epic_id": epic_id or frontmatter.get("epic"),
        "spec_id": resolved_spec_id,
        "epic_spec": epic_spec,  # Epic expectations for drift checking (may be None)
        "agent": payload_agent,
        "project": repo_path.name,  # Project name for refs.sync (derived from repo dir)
        "skill": _resolve_frontmatter_path(frontmatter.get("skill"), base_dir=spec_path.parent),
        "skills": frontmatter.get("skills"),
        # Epic folder carrying AGENTS.md + CLAUDE.md pointer for refs.sync to
        # materialize into the target repo (None when not inside an epic).
        "epic_dir": _resolve_epic_dir(spec_path),
        "models": payload_models,
    }

    # Add model overrides if specified
    if review_model:
        payload["review_model"] = review_model

    envelope = {
        "job_def": job_def.model_dump(),
        "payload": payload,
        "ctx": {
            "spec_id": resolved_spec_id,
            "epic_id": epic_id or frontmatter.get("epic"),
        },
    }

    if dry_run:
        # Compile and print without executing
        try:
            job_instance = compile_job(job_def, envelope)
        except ExecutorError as e:
            _echo_error(f"Compilation failed: {e}")
            raise typer.Exit(1)

        typer.echo("Dry run - JobInstance compiled but not executed:")
        typer.echo("")
        instance_dict = job_instance.model_dump(mode="json")
        print(yaml.dump(instance_dict, default_flow_style=False, allow_unicode=True, sort_keys=False))
        return

    effective_epic_id = epic_id or frontmatter.get("epic") or "adhoc"

    # Generate run_id if not provided
    if run_id is None:
        run_id = generate_run_id(spec_id=f"{effective_epic_id}-{resolved_spec_id}")

    typer.echo(f"Running job: {job_def.job_id}")
    typer.echo(f"  Run ID:   {run_id}")
    if epic_id and spec_id:
        typer.echo(f"  Epic:     {epic_id}")
        typer.echo(f"  Spec:     {resolved_spec_id}")
    else:
        typer.echo(f"  Spec:     {spec_path}")
    typer.echo(f"  Repo:     {repo_path}")
    typer.echo(f"  Branch:   {branch}")
    typer.echo("")

    # Execute.
    # Default (gated) mode: bulk artifacts + consolidated YAML land in local
    # scratch, and the run/run_step/run_report records are emitted through
    # the storacle gate at finalize. The projection repo receives NOTHING.
    # --legacy-output is the only tree-writing path, and it is explicit —
    # there is no silent fallback (that fallback is how legacy trees kept
    # appearing in epic folders).
    store: Any
    if legacy_output:
        store = _new_store(_infer_runs_root(spec_path))
    else:
        store = ConsolidatedRunWriter(root=_scratch_runs_root() / effective_epic_id)

    # Claim BEFORE execution (t019-04 D(a)): a run row (status=running)
    # lands under this run's identity so a kill mid-flight still leaves a
    # governed record that the run started. --legacy-output has no
    # finalize emission to supersede it, so it gets no claim either.
    if not legacy_output:
        _emit_claim_record(
            run_id=run_id,
            job_id=job_def.job_id,
            epic_id=effective_epic_id,
            spec_id=resolved_spec_id,
        )

    try:
        result = execute(envelope, store=store, run_id=run_id)
    except ExecutorError as e:
        _echo_error(f"Execution failed: {e}")
        raise typer.Exit(1)

    # Show results
    _show_run_summary(result, store)

    # Emit-once-at-finalize: push the run records through the gate. Emission
    # failures fail loudly (exit 1) — NO fallback to tree-writing. The
    # scratch files remain as local evidence either way.
    if not legacy_output:
        _emit_gated_run_records(store=store, run_id=run_id)

    # Exit code based on status
    if result.status == RunStatus.failed:
        raise typer.Exit(1)
    elif result.status == RunStatus.completed_with_errors:
        raise typer.Exit(2)


# =============================================================================
# Free-range chat helper
# =============================================================================


def _run_free_range(
    *,
    job_def: Any,
    repo_path: Path | None,
    agent: str | None,
    run_id: str | None,
    dry_run: bool,
) -> None:
    """Compile + execute a free-range chat job without a spec.

    Builds a minimal envelope (no spec_md/spec_id/epic_dir), generates a run
    id, and routes the run store to the dedicated sessions root so free-range
    chat runs are kept separate from epic/spec runs.
    """
    from datetime import UTC, datetime

    # Launch cwd: explicit --repo, else current directory. No .git requirement.
    launch_cwd = (repo_path or Path.cwd()).resolve()

    payload_agent = agent or "claude-code"
    run_started_at = datetime.now(UTC).isoformat()

    payload: dict[str, Any] = {
        "agent": payload_agent,
        "repo_path": str(launch_cwd),
        "prompt": DEFAULT_FREE_RANGE_PROMPT,
        # Threaded to the session.capture_transcript collector so it can resolve
        # the run directory (runs_root/run_id) and select the session JSONL.
        "runs_root": str(SESSIONS_ROOT),
        "run_started_at": run_started_at,
    }

    envelope = {
        "job_def": job_def.model_dump(),
        "payload": payload,
        "ctx": {},
    }

    if dry_run:
        try:
            job_instance = compile_job(job_def, envelope)
        except ExecutorError as e:
            _echo_error(f"Compilation failed: {e}")
            raise typer.Exit(1)

        typer.echo("Dry run - JobInstance compiled but not executed:")
        typer.echo("")
        instance_dict = job_instance.model_dump(mode="json")
        print(yaml.dump(instance_dict, default_flow_style=False, allow_unicode=True, sort_keys=False))
        return

    if run_id is None:
        run_id = generate_run_id(spec_id="chat")

    store = _new_store(SESSIONS_ROOT)

    typer.echo(f"Running free-range chat: {job_def.job_id}")
    typer.echo(f"  Run ID:   {run_id}")
    typer.echo(f"  Launch:   {launch_cwd}")
    typer.echo(f"  Sessions: {SESSIONS_ROOT}")
    typer.echo("")

    try:
        result = execute(envelope, store=store, run_id=run_id)
    except ExecutorError as e:
        _echo_error(f"Execution failed: {e}")
        raise typer.Exit(1)

    _show_run_summary(result, store)

    if result.status == RunStatus.failed:
        raise typer.Exit(1)
    elif result.status == RunStatus.completed_with_errors:
        raise typer.Exit(2)


# =============================================================================
# spec status
# =============================================================================


def status_command(
    run_id: str = typer.Argument(None, help="Run ID to show status for (optional)"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of recent runs to show"),
) -> None:
    """Show run status.

    Without run_id: List recent runs.
    With run_id: Show detailed run status.

    Examples:
        spec status
        spec status run-20260123-143052-abc123
        spec status --limit 20
    """
    hint_root = _infer_runs_root()
    store = _new_store(hint_root)

    if run_id is None:
        # List recent runs
        runs = store.list_runs()
        if not runs:
            typer.echo("No runs found.")
            return

        # Show most recent first
        runs = sorted(runs, reverse=True)[:limit]

        typer.echo(f"Recent runs ({len(runs)} shown):")
        typer.echo("")
        typer.echo(f"{'RUN ID':<40} {'STATUS':<20} {'JOB':<15}")
        typer.echo("-" * 75)

        for rid in runs:
            try:
                record = store.read_run_record(rid)
                status_color = _status_color(record.status)
                typer.echo(f"{rid:<40} ", nl=False)
                typer.secho(f"{record.status.value:<20}", fg=status_color, nl=False)
                typer.echo(f" {record.job_id:<15}")
            except Exception:
                typer.echo(f"{rid:<40} {'<error reading>':<20}")
    else:
        # Show specific run
        resolved_store = _store_for_run_id(run_id, hint_runs_root=hint_root)
        if resolved_store is None:
            _echo_error(f"Run not found: {run_id}")
            raise typer.Exit(1)

        record = resolved_store.read_run_record(run_id)
        _show_run_details(record, resolved_store)


# =============================================================================
# spec logs
# =============================================================================


def logs_command(
    run_id: str = typer.Argument(..., help="Run ID to show logs for"),
    step_n: int = typer.Argument(None, help="Step number to show logs for (optional)"),
    patch: bool = typer.Option(False, "--patch", "-p", help="Show git diff patch"),
    stderr: bool = typer.Option(False, "--stderr", "-e", help="Show stderr instead of stdout"),
) -> None:
    """Show run logs.

    Without step_n: Show run summary.
    With step_n: Show step stdout/stderr.

    Examples:
        spec logs run-20260123-143052-abc123
        spec logs run-20260123-143052-abc123 2
        spec logs run-20260123-143052-abc123 2 --stderr
        spec logs run-20260123-143052-abc123 2 --patch
    """
    hint_root = _infer_runs_root()
    store = _store_for_run_id(run_id, hint_runs_root=hint_root)
    if store is None:
        _echo_error(f"Run not found: {run_id}")
        raise typer.Exit(1)

    if step_n is None:
        # Show run summary
        record = store.read_run_record(run_id)
        _show_run_details(record, store)
    else:
        # Show step logs
        step_path = store.get_step_path(run_id, step_n)
        if not step_path.exists():
            _echo_error(f"Step {step_n} not found in run {run_id}")
            raise typer.Exit(1)

        if patch:
            # Show git diff
            patch_file = step_path / "changes.patch"
            if patch_file.exists():
                typer.echo(f"Git diff for step {step_n}:")
                typer.echo("-" * 40)
                print(patch_file.read_text())
            else:
                typer.echo(f"No patch file for step {step_n}")
        else:
            # Show stdout or stderr
            if stderr:
                log_file = step_path / "stderr.txt"
                log_type = "stderr"
            else:
                log_file = step_path / "stdout.txt"
                log_type = "stdout"

            if log_file.exists():
                content = log_file.read_text()
                if content:
                    typer.echo(f"Step {step_n} {log_type}:")
                    typer.echo("-" * 40)
                    print(content)
                else:
                    typer.echo(f"Step {step_n} {log_type} is empty")
            else:
                typer.echo(f"No {log_type} file for step {step_n}")


# =============================================================================
# Helper Functions
# =============================================================================


def _status_color(status: RunStatus) -> str:
    """Get color for status."""
    if status == RunStatus.completed:
        return typer.colors.GREEN
    elif status == RunStatus.completed_with_errors:
        return typer.colors.YELLOW
    elif status == RunStatus.failed:
        return typer.colors.RED
    elif status == RunStatus.running:
        return typer.colors.BLUE
    else:
        return typer.colors.WHITE


def _show_run_summary(result, store: Any) -> None:
    """Show run summary after execution."""
    typer.echo("")
    typer.echo("=" * 50)

    status_color = _status_color(result.status)
    typer.echo("Run completed: ", nl=False)
    typer.secho(result.status.value, fg=status_color)
    typer.echo(f"  Run ID:     {result.run_id}")
    typer.echo(f"  Job:        {result.job_id}")

    # Show step summary
    steps = store.list_steps(result.run_id)
    completed = 0
    failed = 0
    for step_n in steps:
        try:
            outcome = store.read_step_outcome(result.run_id, step_n)
            if outcome.outcome == OutcomeStatus.completed:
                completed += 1
            else:
                failed += 1
        except Exception:
            pass

    typer.echo(f"  Steps:      {completed} completed, {failed} failed")
    typer.echo(f"  Artifacts:  {store.get_run_path(result.run_id)}")

    if result.error:
        _echo_error(f"Error: {result.error}")


def _find_epic_dir_for_spec_path(spec_path: Path) -> Path | None:
    """Infer epic directory from a spec path.

    Expected layout (local-governor epics):
        <epic_dir>/epic.yaml
        <epic_dir>/specs/<spec>.yaml|.md
    """
    try:
        spec_path = spec_path.resolve()
    except Exception:
        return None

    if spec_path.parent.name == "specs":
        epic_dir = spec_path.parent.parent
        if (epic_dir / "epic.yaml").exists():
            return epic_dir

    # Fallback: walk upward looking for epic.yaml
    for parent in [spec_path.parent, *spec_path.parents]:
        if (parent / "epic.yaml").exists():
            return parent
    return None


def _resolve_epic_dir(spec_path: Path) -> str | None:
    """Resolve the epic folder for a spec, as a string (or None).

    Used to populate the refs.sync payload so the epic's AGENTS.md + CLAUDE.md
    pointer can be materialized into the target repo. Returns None when the spec
    is not inside an epic (e.g. ad-hoc file mode).
    """
    epic_dir = _find_epic_dir_for_spec_path(spec_path)
    return str(epic_dir) if epic_dir is not None else None


def _find_epic_dir_from_cwd() -> Path | None:
    """Infer epic directory from current working directory by walking upward."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "epic.yaml").exists():
            return parent
    return None


def _infer_runs_root(spec_path: Path | None = None) -> Path:
    """Choose a runs root.

    Priority:
      1) If spec_path is in an epic, use <epic_dir>/runs
      2) If cwd is inside an epic, use <epic_dir>/runs
      3) Legacy default (~/.local/local-governor/runs)
    """
    epic_dir = None
    if spec_path is not None:
        epic_dir = _find_epic_dir_for_spec_path(spec_path)
    if epic_dir is None:
        epic_dir = _find_epic_dir_from_cwd()
    if epic_dir is not None:
        return epic_dir / "runs"
    return DEFAULT_RUNS_ROOT


def _load_workspace_config() -> dict[str, Any]:
    """Load .specwright.yaml via existing config discovery helper."""
    from spec.cli.spec import find_config

    _, cfg = find_config()
    return cfg


DEFAULT_SCRATCH_RUNS_ROOT = Path.home() / ".local" / "specwright" / "runs"


def _scratch_runs_root() -> Path:
    """Local scratch root for run output (bulk artifacts + consolidated YAML).

    Never the projection repo, never an epic folder. Bulk artifacts live
    here as the accept-lost tier; the durable record is the gated rows.
    """
    import os

    env_root = os.environ.get("SPECWRIGHT_SCRATCH_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return DEFAULT_SCRATCH_RUNS_ROOT


def _emit_claim_record(
    *, run_id: str, job_id: str, epic_id: str | None, spec_id: str | None
) -> None:
    """Write the governed run CLAIM before execute() runs (t019-04 D(a)).

    Wrapper so tests can monkeypatch emission without a live gate/DB —
    mirrors _emit_gated_run_records below. Hard-fails (exit before any
    step executes) if a claim is attempted but refused; silently skipped
    when LIFEOS_CLOUD_DB is unset (unit-test convention — see
    gate_emission.emit_claim_record).
    """
    from spec.executor.gate_emission import GateEmissionError, emit_claim_record

    try:
        emit_claim_record(run_id=run_id, job_id=job_id, epic_id=epic_id, spec_id=spec_id)
    except GateEmissionError as e:
        _echo_error(f"Governed run claim FAILED (aborting before execution): {e}")
        raise typer.Exit(1)


def _emit_gated_run_records(*, store: Any, run_id: str) -> None:
    """Emit run/run_step/run_report rows through the gate; fail loudly.

    Wrapper so tests can monkeypatch emission without a live gate/DB.
    """
    from spec.executor.gate_emission import GateEmissionError, emit_run_records

    try:
        emission = emit_run_records(store=store, run_id=run_id)
    except GateEmissionError as e:
        _echo_error(f"Gated emission FAILED (no tree-writing fallback): {e}")
        _echo_error(f"Local scratch evidence remains at: {store.get_run_path(run_id)}")
        raise typer.Exit(1)

    typer.echo(
        f"Emitted {emission.total_emitted} run records through the gate "
        f"({len(emission.emitted_names['run'])} run, "
        f"{len(emission.emitted_names['run_step'])} steps, "
        f"{len(emission.emitted_names['run_report'])} report) — "
        f"{emission.verified_rows} rows verified in {emission.table}"
    )


def _resolve_projection_repo_path() -> Path | None:
    """Resolve projection repo path (read-side only: locating older
    consolidated runs). Run output never writes to the projection repo."""
    import os

    env_path = os.environ.get("SPECWRIGHT_PROJECTION_REPO")
    if env_path:
        return Path(env_path).expanduser().resolve()

    cfg = _load_workspace_config()
    for key in ("projection_repo", "projection"):
        section = cfg.get(key)
        if isinstance(section, dict):
            value = section.get("path")
            if isinstance(value, str) and value.strip():
                return Path(value).expanduser().resolve()

    governor_cfg = Path("~/.local/local-governor/config.yaml").expanduser()
    if governor_cfg.exists():
        raw = yaml.safe_load(governor_cfg.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            for key in ("projection_repo", "projection"):
                section = raw.get(key)
                if isinstance(section, dict):
                    value = section.get("path")
                    if isinstance(value, str) and value.strip():
                        return Path(value).expanduser().resolve()

    return None


def _new_store(root: Path | None = None) -> RunStore:
    """Create a RunStore, resilient to test monkeypatching.

    Some tests monkeypatch `spec.cli.exec_commands.RunStore` with a zero-arg
    callable. Prefer `RunStore(root=...)` but fall back to setting `store.root`.
    """
    if root is None:
        return RunStore()

    try:
        return RunStore(root=root)
    except TypeError:
        # Tests may monkeypatch RunStore to a zero-arg callable that already
        # returns a store rooted where the test expects. In that case, do not
        # attempt to override `.root`.
        return RunStore()


def _store_for_run_id(run_id: str, hint_runs_root: Path | None = None) -> Any | None:
    """Find which RunStore contains a run_id.

    Tries hinted root, then legacy default root, then scans local-governor epics.
    """
    candidates: list[Path] = []
    if hint_runs_root is not None:
        candidates.append(hint_runs_root)
    candidates.append(DEFAULT_RUNS_ROOT)

    for root in candidates:
        store = _new_store(root)
        if store.run_exists(run_id):
            return store

    # Gated-mode scratch root: <scratch>/<epic_id>/<run_id>/run.yaml
    scratch_root = _scratch_runs_root()
    if scratch_root.exists():
        for epic_runs_root in scratch_root.iterdir():
            if not epic_runs_root.is_dir():
                continue
            scratch_store = ConsolidatedRunWriter(root=epic_runs_root)
            if scratch_store.run_exists(run_id):
                return scratch_store

    projection_repo = _resolve_projection_repo_path()
    if projection_repo is not None:
        projection_runs = projection_repo / "runs"
        if projection_runs.exists():
            for epic_runs_root in projection_runs.iterdir():
                if not epic_runs_root.is_dir():
                    continue
                consolidated_store = ConsolidatedRunWriter(root=epic_runs_root)
                if consolidated_store.run_exists(run_id):
                    return consolidated_store

    # Scan epics for <epic_dir>/runs/<run_id>/run.yaml
    epics_root = Path.home() / ".local" / "local-governor" / "epics"
    if epics_root.exists():
        try:
            for run_yaml in epics_root.rglob(f"runs/{run_id}/run.yaml"):
                # run_yaml = <epic_dir>/runs/<run_id>/run.yaml
                run_dir = run_yaml.parent
                runs_root = run_dir.parent
                store = _new_store(runs_root)
                if store.run_exists(run_id):
                    return store
                break
        except Exception:
            # Non-fatal: fallback to None
            pass

    return None


def _show_run_details(record, store: RunStore) -> None:
    """Show detailed run information."""
    status_color = _status_color(record.status)

    typer.echo(f"Run: {record.run_id}")
    typer.echo("  Status:     ", nl=False)
    typer.secho(record.status.value, fg=status_color)
    typer.echo(f"  Job:        {record.job_id}")
    typer.echo(f"  Job Hash:   {record.job_hash}")
    typer.echo(f"  Repo:       {record.repo.repo_path}")
    typer.echo(f"  Branch:     {record.repo.branch}")
    typer.echo(f"  Base:       {record.repo.base_commit[:8]}")
    typer.echo(f"  Created:    {record.created_at}")

    if record.error:
        typer.echo("  Error:      ", nl=False)
        typer.secho(record.error, fg=typer.colors.RED)

    # Show steps
    steps = store.list_steps(record.run_id)
    if steps:
        typer.echo("")
        typer.echo("Steps:")
        for step_n in steps:
            try:
                outcome = store.read_step_outcome(record.run_id, step_n)
                if outcome.outcome == OutcomeStatus.completed:
                    status_icon = "✓"
                    color = typer.colors.GREEN
                elif outcome.outcome == OutcomeStatus.failed:
                    status_icon = "✗"
                    color = typer.colors.RED
                elif outcome.outcome == OutcomeStatus.timeout:
                    status_icon = "⏱"
                    color = typer.colors.YELLOW
                else:
                    status_icon = "?"
                    color = typer.colors.WHITE

                typer.echo(f"  [{step_n}] ", nl=False)
                typer.secho(f"{status_icon} ", fg=color, nl=False)
                typer.echo(f"{outcome.step_id} ({outcome.duration_ms}ms)")

                if outcome.error:
                    typer.echo("      ", nl=False)
                    typer.secho(outcome.error, fg=typer.colors.RED)
            except Exception as e:
                typer.echo(f"  [{step_n}] <error: {e}>")

    # Show attempts
    attempts = store.list_attempts(record.run_id)
    if attempts:
        typer.echo("")
        typer.echo(f"Attempts: {len(attempts)}")


# =============================================================================
# spec validate
# =============================================================================


def validate_command(
    spec_path: Path = typer.Argument(None, help="Path to spec .yaml or .md file (uses current if omitted)"),
    check_only: bool = typer.Option(
        False, "--check", "-c", help="Check only, don't write validated flag"
    ),
) -> None:
    """Validate a spec file and mark it as validated.

    For `.yaml` specs, validates required metadata fields used by the
    executor and does not modify the file.

    For `.md` specs, validates:
    - YAML frontmatter with required fields (tier, title, owner, goal)
    - Plan section with at least one step
    - Proper markdown structure

    If valid, writes 'validated: true' to the frontmatter.

    Examples:
        spec validate ./my-feature.yaml
        spec validate ./my-feature.yaml --check
        spec validate  # uses current spec from config
    """
    from spec.compiler.parser import SpecParser

    # Resolve spec path from config if not provided
    if spec_path is None:
        from spec.cli.spec import find_config
        _, cfg = find_config()
        current_spec = cfg.get("current", {}).get("spec")
        if not current_spec:
            _echo_error("No spec path provided and no current spec set.")
            typer.echo("  Run: spec config current.spec <path-to-spec.yaml>")
            raise typer.Exit(1)
        spec_path = Path(current_spec)
        typer.echo(f"Using current spec: {spec_path}")

    if not spec_path.exists():
        _echo_error(f"Spec file not found: {spec_path}")
        raise typer.Exit(1)

    if spec_path.suffix in (".yaml", ".yml"):
        try:
            _load_spec(spec_path)
            typer.secho("✓ YAML spec metadata valid", fg=typer.colors.GREEN)
            _echo_success(f"Spec is valid: {spec_path}")
            typer.echo("  YAML specs are not auto-mutated with validated: true")
            return
        except ValueError as e:
            _echo_error(f"Invalid spec: {e}")
            raise typer.Exit(1)
        except Exception as e:
            _echo_error(f"Failed to validate spec: {e}")
            raise typer.Exit(1)

    if spec_path.suffix != ".md":
        _echo_error(f"Spec must be a .md or .yaml file (got {spec_path.suffix})")
        raise typer.Exit(1)

    # Full validation using SpecParser
    try:
        content = spec_path.read_text()
        parser = SpecParser(content, source_path=spec_path)
        parser.parse()  # This validates frontmatter, sections, and plan
        typer.secho("✓ Spec structure valid", fg=typer.colors.GREEN)
    except ValueError as e:
        _echo_error(f"Invalid spec: {e}")
        raise typer.Exit(1)
    except Exception as e:
        _echo_error(f"Failed to validate spec: {e}")
        raise typer.Exit(1)

    # Check if already validated
    if parser.frontmatter.get("validated"):
        _echo_success(f"Spec already validated: {spec_path}")
        return

    if check_only:
        _echo_success(f"Spec is valid: {spec_path}")
        typer.echo("  (use without --check to write 'validated: true')")
        return

    # Write validated flag
    try:
        updated_content = _update_frontmatter(content, {"validated": True})
        spec_path.write_text(updated_content)
        _echo_success(f"Spec validated: {spec_path}")
        typer.echo("  Added 'validated: true' to frontmatter")
    except Exception as e:
        _echo_error(f"Failed to update spec: {e}")
        raise typer.Exit(1)
