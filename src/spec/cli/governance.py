"""Governance validation CLI commands.

Adds subcommands under `spec validate`:
  spec validate build <project>   — build.yaml vs filesystem
  spec validate epic <epic-id>    — epic cross-reference checks
  spec validate contracts         — op-catalog vs code catalog
"""

from __future__ import annotations

from pathlib import Path

import typer
import yaml  # type: ignore[import]

from spec.governance.models import Severity, ValidationReport
from spec.governor.locator import GovernorLocator

validate_app = typer.Typer(
    help="Validate specs, build files, epics, and contracts.",
    invoke_without_command=True,
)


def _print_report(report: ValidationReport, json_output: bool) -> None:
    """Print a validation report in human or JSON format."""
    if json_output:
        typer.echo(report.to_json())
        return

    # Human-readable output
    typer.secho(f"\nValidation: {report.target}", bold=True)
    typer.echo(f"{'=' * 60}")

    if not report.findings:
        typer.secho("  No findings — clean.", fg=typer.colors.GREEN)
    else:
        for f in report.findings:
            color = typer.colors.RED if f.severity == Severity.error else typer.colors.YELLOW
            tag = "ERR" if f.severity == Severity.error else "WRN"
            typer.secho(f"  [{tag}] {f.category.value}: {f.message}", fg=color)
            if f.path:
                typer.echo(f"        path: {f.path}")

    typer.echo(f"\n  Errors: {report.error_count}  Warnings: {report.warning_count}")
    if report.passed:
        typer.secho("  PASSED", fg=typer.colors.GREEN, bold=True)
    else:
        typer.secho("  FAILED", fg=typer.colors.RED, bold=True)
    typer.echo()


def _resolve_project_build(project: str) -> tuple[Path, dict | None]:
    """Resolve a project name to its repo_path and build.yaml dict.

    Uses GovernorLocator to find the governor root, then looks for
    ``projects/<project>/<project>.build.yaml``.  If *project* is an
    absolute directory path, extracts the directory name as the project.

    Returns (repo_path, build_dict) where build_dict is None if no
    build.yaml exists (caller should warn, not fail).
    """
    candidate = Path(project)

    # If project is a directory path, extract project name for governor lookup
    if candidate.is_dir():
        project = candidate.name

    # Governor-based lookup
    governor_root = GovernorLocator().find(ensure_dirs=False).root
    project_dir = governor_root / "projects" / project
    build_path = project_dir / f"{project}.build.yaml"

    if not build_path.exists():
        # Resolve repo_path even without build.yaml
        repo_path = Path("/workspace") / project
        return repo_path, None

    try:
        build_yaml = yaml.safe_load(build_path.read_text())
    except yaml.YAMLError as e:
        typer.secho(f"Error: Malformed YAML in {build_path}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if not isinstance(build_yaml, dict):
        typer.secho(f"Error: Expected mapping in {build_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    # Resolve repo_path from metadata.repo
    repo_str = (build_yaml.get("metadata") or {}).get("repo", "")
    if not repo_str:
        repo_path = Path("/workspace") / project
    elif repo_str.startswith("/"):
        repo_path = Path(repo_str)
    else:
        # Relative — try /workspace/<repo_str> first, then /<repo_str>
        repo_path = Path("/workspace") / project
        candidate = Path("/") / repo_str
        if candidate.exists() and not repo_path.exists():
            repo_path = candidate

    if not repo_path.exists():
        typer.secho(
            f"Warning: repo path not found: {repo_path} (from metadata.repo='{repo_str}')",
            fg=typer.colors.YELLOW,
            err=True,
        )

    return repo_path, build_yaml


def _fix_build(
    project: str,
    repo_path: Path,
    build_yaml: dict,
    report: ValidationReport,
) -> None:
    """Walk through fixable findings and apply changes to build.yaml.

    Uses ruamel.yaml for round-trip editing so comments and formatting
    are preserved.

    Fixable categories:
      - undeclared_path → add entry to layout
      - missing_path → remove entry from layout
      - frozen_missing → remove entry from frozen list
    """
    from spec.governance.models import Category

    fixable = {Category.undeclared_path, Category.missing_path, Category.frozen_missing}
    to_fix = [f for f in report.findings if f.category in fixable]

    if not to_fix:
        typer.echo("No auto-fixable findings.")
        if not report.passed:
            raise typer.Exit(1)
        return

    # Resolve build file path
    governor_root = GovernorLocator().find(ensure_dirs=False).root
    build_path = governor_root / "projects" / project / f"{project}.build.yaml"

    # Load with ruamel for round-trip preservation
    from ruamel.yaml import YAML
    ryaml = YAML()
    ryaml.preserve_quotes = True
    with build_path.open() as f:
        rt_data = ryaml.load(f)

    typer.secho(f"\n{len(to_fix)} fixable finding(s):\n", bold=True)

    applied = 0
    layout = rt_data.get("layout") or []
    frozen = rt_data.get("frozen") or []

    for finding in to_fix:
        color = typer.colors.RED if finding.severity.value == "error" else typer.colors.YELLOW
        typer.secho(f"  [{finding.category.value}] {finding.message}", fg=color)

        if finding.category == Category.undeclared_path:
            if typer.confirm(f"    Add '{finding.path}' to layout?", default=True):
                name = Path(finding.path).stem
                layout.append({
                    "path": finding.path,
                    "module": name,
                    "role": "TODO: describe role",
                })
                applied += 1

        elif finding.category == Category.missing_path:
            if typer.confirm(f"    Remove '{finding.path}' from layout?", default=True):
                to_remove = [i for i, e in enumerate(layout) if e.get("path") == finding.path]
                for i in reversed(to_remove):
                    del layout[i]
                applied += 1

        elif finding.category == Category.frozen_missing:
            if typer.confirm(f"    Remove '{finding.path}' from frozen?", default=True):
                to_remove = [i for i, e in enumerate(frozen) if e.get("path") == finding.path]
                for i in reversed(to_remove):
                    del frozen[i]
                applied += 1

    if applied == 0:
        typer.echo("\nNo changes applied.")
        if not report.passed:
            raise typer.Exit(1)
        return

    # Write back with ruamel (preserves comments/formatting)
    rt_data["layout"] = layout
    if frozen or "frozen" in rt_data:
        rt_data["frozen"] = frozen

    with build_path.open("w") as f:
        ryaml.dump(rt_data, f)
    typer.secho(f"\nApplied {applied} fix(es) to {build_path}", fg=typer.colors.GREEN)

    # Re-validate with fresh load
    new_build = yaml.safe_load(build_path.read_text())
    from spec.governance.build_validator import BuildValidator
    new_report = BuildValidator(repo_path, new_build).validate()
    _print_report(new_report, json_output=False)

    if not new_report.passed:
        raise typer.Exit(1)


@validate_app.callback()
def validate_callback(ctx: typer.Context) -> None:
    """Validate specs, build files, epics, and contracts.

    Subcommands:
      spec validate spec <file.md>     — validate spec markdown structure
      spec validate build <project>    — build.yaml vs filesystem
      spec validate epic <epic-id>     — epic cross-reference checks
      spec validate contracts           — op-catalog vs code catalog
    """
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@validate_app.command("spec")
def validate_spec(
    spec_path: Path = typer.Argument(None, help="Path to spec .md file (uses current if omitted)"),
    check_only: bool = typer.Option(False, "--check", "-c", help="Check only, don't write validated flag"),
) -> None:
    """Validate a spec markdown file structure.

    Validates YAML frontmatter (required: tier, title, owner, goal),
    plan section, and markdown structure. Writes 'validated: true'
    to frontmatter on success.

    Examples:
        spec validate spec ./my-feature.md
        spec validate spec ./my-feature.md --check
        spec validate spec  # uses current spec from config
    """
    if spec_path is None:
        from spec.cli.spec import find_config
        _, cfg = find_config()
        current_spec = cfg.get("current", {}).get("spec")
        if not current_spec:
            typer.secho("Error: No spec path provided and no current spec set.", fg=typer.colors.RED, err=True)
            typer.echo("  Run: spec config current.spec <path-to-spec.md>")
            raise typer.Exit(1)
        spec_path = Path(current_spec)
        typer.echo(f"Using current spec: {spec_path}")

    if not spec_path.exists():
        typer.secho(f"Error: Spec file not found: {spec_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if spec_path.suffix != ".md":
        typer.secho(f"Error: Spec must be a .md file (got {spec_path.suffix})", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    from spec.compiler.parser import SpecParser

    try:
        content = spec_path.read_text()
        parser = SpecParser(content, source_path=spec_path)
        parser.parse()
        typer.secho("Spec structure valid", fg=typer.colors.GREEN)
    except ValueError as e:
        typer.secho(f"Error: Invalid spec: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Error: Failed to validate spec: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if parser.frontmatter.get("validated"):
        typer.secho(f"Spec already validated: {spec_path}", fg=typer.colors.GREEN)
        return

    if check_only:
        typer.secho(f"Spec is valid: {spec_path}", fg=typer.colors.GREEN)
        typer.echo("  (use without --check to write 'validated: true')")
        return

    # Write validated flag
    from spec.cli.exec_commands import _update_frontmatter
    try:
        updated_content = _update_frontmatter(content, {"validated": True})
        spec_path.write_text(updated_content)
        typer.secho(f"Spec validated: {spec_path}", fg=typer.colors.GREEN)
        typer.echo("  Added 'validated: true' to frontmatter")
    except Exception as e:
        typer.secho(f"Error: Failed to update spec: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@validate_app.command("build")
def validate_build(
    project: str = typer.Argument(..., help="Project name (e.g., 'workman') or repo path"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    fix: bool = typer.Option(False, "--fix", help="Interactively fix stale build.yaml"),
) -> None:
    """Validate build.yaml against repo filesystem.

    Checks layout paths, slot directories, frozen files, placement rules,
    and module dependency references.

    Examples:
        spec validate build workman
        spec validate build lorchestra --json
        spec validate build specwright --fix
    """
    from spec.governance.build_validator import BuildValidator

    repo_path, build_yaml = _resolve_project_build(project)

    if build_yaml is None:
        typer.secho(
            f"Warning: No build.yaml found for project '{project}'",
            fg=typer.colors.YELLOW,
            err=True,
        )
        typer.echo(f"  Looked for: projects/{project}/{project}.build.yaml", err=True)
        if json_output:
            report = ValidationReport(target=project)
            typer.echo(report.to_json())
        raise typer.Exit(0)

    validator = BuildValidator(repo_path, build_yaml)
    report = validator.validate()

    _print_report(report, json_output)

    if fix and report.findings:
        _fix_build(project, repo_path, build_yaml, report)
        return

    if not report.passed:
        raise typer.Exit(1)


@validate_app.command("epic")
def validate_epic(
    epic_prefix: str = typer.Argument(..., help="Epic ID or prefix (e.g., 't004', 'e011')"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Validate epic consistency: specs, dependencies, repo targets.

    Cross-references epic specs against target build.yamls, checks
    depends_on references resolve, and verifies repo targets exist.
    Supports prefix matching (e.g., 't004' resolves to 't004-specwright-governance').

    Examples:
        spec validate epic t004
        spec validate epic e011 --json
    """
    from spec.governance.epic_validator import EpicValidator
    from spec.governor.resolver import ResolveError, resolve_epic

    try:
        resolved = resolve_epic(epic_prefix)
    except ResolveError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    epic_dir = resolved.epic_dir
    try:
        epic_yaml = yaml.safe_load(resolved.epic_yaml.read_text())
    except yaml.YAMLError as e:
        typer.secho(f"Error: Malformed YAML in {resolved.epic_yaml}: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if not isinstance(epic_yaml, dict):
        typer.secho(f"Error: Expected mapping in {resolved.epic_yaml}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    # Load build.yamls for all target repos
    governor_root = GovernorLocator().find(ensure_dirs=False).root
    build_yamls: dict[str, dict] = {}
    for target in epic_yaml.get("targets") or []:
        tid = target.get("id", "")
        gov_project = target.get("governor_project", tid)
        build_path = governor_root / "projects" / gov_project / f"{gov_project}.build.yaml"
        if build_path.exists():
            try:
                loaded = yaml.safe_load(build_path.read_text())
            except yaml.YAMLError:
                continue
            if isinstance(loaded, dict):
                build_yamls[gov_project] = loaded

    # Load op-catalog if it exists (for cross-reference checks)
    op_catalog_path = governor_root / "contracts" / "op-catalog.yaml"
    op_catalog: dict | None = None
    if op_catalog_path.exists():
        try:
            loaded = yaml.safe_load(op_catalog_path.read_text())
            if isinstance(loaded, dict):
                op_catalog = loaded
        except yaml.YAMLError:
            pass

    validator = EpicValidator(
        epic_yaml, build_yamls, epic_dir=epic_dir, op_catalog=op_catalog,
    )
    report = validator.validate()

    _print_report(report, json_output)

    if not report.passed:
        raise typer.Exit(1)


@validate_app.command("contracts")
def validate_contracts(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Validate op-catalog.yaml against code registrations.

    Compares declared operations in op-catalog.yaml against registered
    operations found in workman's catalog.py via AST inspection.

    Examples:
        spec validate contracts
        spec validate contracts --json
    """
    from spec.governance.contract_validator import ContractValidator

    governor_root = GovernorLocator().find(ensure_dirs=False).root
    catalog_path = governor_root / "contracts" / "op-catalog.yaml"

    if not catalog_path.exists():
        typer.secho(f"Error: op-catalog not found: {catalog_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    # Resolve code catalog from build.yaml layout
    from spec.governance.callables import _resolve_code_catalog
    code_catalog = _resolve_code_catalog(governor_root, "workman")
    if not code_catalog.exists():
        typer.secho(
            f"Error: code catalog not found at {code_catalog}",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo("  Contract validation requires the target project to be checked out.", err=True)
        raise typer.Exit(1)

    validator = ContractValidator(catalog_path, code_catalog)
    report = validator.validate()

    _print_report(report, json_output)

    if not report.passed:
        raise typer.Exit(1)
