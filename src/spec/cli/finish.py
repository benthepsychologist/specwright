"""CLI command: spec finish — apply build delta and close spec lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import typer


def finish_command(
    spec_query: str = typer.Argument(
        ..., help="Spec ID or prefix (e.g., 't004-01')"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show changes without applying"
    ),
    force: bool = typer.Option(
        False, "--force", help="Finish from any status, skip spec file check"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON"
    ),
) -> None:
    """Mark a spec as done, applying its build_delta to the target build.yaml.

    Resolves the spec by prefix, applies structural changes from the spec's
    build_delta to the target build.yaml, updates the spec status to done,
    and runs post-validation.

    Examples:
        spec finish t004-01
        spec finish t004-01 --dry-run
        spec finish t004-02 --force
    """
    from spec.core.exceptions import SpecwrightError
    from spec.governance.delta_applicator import (
        BuildDeltaApplicator,
        DeltaConflictError,
    )
    from spec.governance.epic_updater import EpicUpdateError, EpicUpdater
    from spec.governor.resolver import ResolveError, resolve_spec

    # 1. Resolve the spec
    try:
        resolved = resolve_spec(spec_query)
    except ResolveError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    epic_yaml = resolved.epic.epic_yaml
    spec_id = resolved.spec_id

    # 2. Load epic and find spec entry
    try:
        updater = EpicUpdater(epic_yaml)
    except EpicUpdateError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(e.exit_code)

    # 3. Check status
    current_status = updater.get_spec_status(spec_id)
    if not dry_run:
        if current_status == "done" and not force:
            typer.secho(
                f"Spec '{spec_id}' is already done. Use --force to re-finish.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            raise typer.Exit(1)

        if current_status not in ("active", "planned", "done") and not force:
            typer.secho(
                f"Spec '{spec_id}' has status '{current_status}'. "
                f"Expected 'active' or 'planned'. Use --force to override.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            raise typer.Exit(1)

    # 4. Read build_delta from the updater's already-loaded data
    spec_entry = updater.get_spec_entry(spec_id)
    build_delta = spec_entry.get("build_delta")
    has_delta = build_delta is not None and build_delta != {}

    # 5. Resolve build.yaml target path
    build_path = None
    applicator = None
    if has_delta:
        target = build_delta.get("target")
        if not target:
            typer.secho(
                "Error: build_delta has no 'target' field",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)

        from spec.governor.resolver import _get_governor_root

        governor_root = _get_governor_root()

        build_path = governor_root / target
        if not build_path.exists():
            typer.secho(
                f"Error: build.yaml not found at {build_path}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)

        applicator = BuildDeltaApplicator(build_path, dict(build_delta))

    # 6. Dry run
    if dry_run:
        result = {
            "spec_id": spec_id,
            "current_status": current_status,
            "new_status": "done",
            "has_build_delta": has_delta,
        }

        if json_output:
            if has_delta and applicator:
                conflicts = applicator.validate()
                result["build_delta_preview"] = build_delta.get("summary", "")
                result["conflicts"] = conflicts
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.secho("Dry run — no changes will be made\n", bold=True)
            typer.echo(f"  Spec:   {spec_id}")
            typer.echo(f"  Status: {current_status} → done")
            if has_delta and applicator:
                typer.echo(f"  Target: {build_path}")
                typer.echo("\n  Build delta:")
                typer.echo(applicator.preview())
                conflicts = applicator.validate()
                if conflicts:
                    typer.secho("\n  Conflicts:", fg=typer.colors.RED)
                    for c in conflicts:
                        typer.echo(f"    {c}")
                else:
                    typer.secho(
                        "\n  No conflicts — safe to apply",
                        fg=typer.colors.GREEN,
                    )
            else:
                typer.echo("  No build_delta — status-only update")

        raise typer.Exit(0)

    # 7. Apply build delta
    warnings: list[str] = []
    if has_delta and applicator:
        try:
            applicator.apply()
            if not json_output:
                typer.secho(
                    f"Applied build_delta to {build_path}",
                    fg=typer.colors.GREEN,
                )
        except DeltaConflictError as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(e.exit_code)
        except SpecwrightError as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(e.exit_code)

        # Post-validation: warn but don't fail
        try:
            repo_id = spec_entry.get("repo")
            target_entry = updater.get_target(repo_id) if repo_id else None
            repo_path_str = target_entry.get("repo_path") if target_entry else None
            _run_post_validation(build_path, warnings, repo_path_str=repo_path_str)
        except Exception as e:
            warnings.append(f"Post-validation error: {e}")

    # 8. Update epic
    try:
        updater.set_spec_status(spec_id, "done")
        updater.set_updated()
        updater.save()
        if not json_output:
            typer.secho(
                f"Updated '{spec_id}' status → done in {epic_yaml.name}",
                fg=typer.colors.GREEN,
            )
    except EpicUpdateError as e:
        typer.secho(f"Error updating epic: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(e.exit_code)

    # 9. Summary
    if json_output:
        result = {
            "spec_id": spec_id,
            "status": "done",
            "build_delta_applied": has_delta,
            "warnings": warnings,
        }
        typer.echo(json.dumps(result, indent=2))
    else:
        if warnings:
            typer.secho("\nPost-validation warnings:", fg=typer.colors.YELLOW)
            for w in warnings:
                typer.echo(f"  {w}")
        typer.secho("\nDone.", bold=True)


def _run_post_validation(
    build_path: Path,
    warnings: list[str],
    repo_path_str: str | None = None,
) -> None:
    """Run spec validate build on the affected project.

    Args:
        build_path: Path to the build.yaml that was just modified.
        warnings: Mutable list to append findings to.
        repo_path_str: Authoritative repo path from epic targets[].repo_path.
            If provided, used directly. Otherwise falls back to build_path.parent.
    """
    import yaml as pyyaml

    from spec.governance.build_validator import BuildValidator

    build_data = pyyaml.safe_load(build_path.read_text())
    if build_data is None:
        warnings.append(f"Could not load {build_path} for post-validation")
        return

    # Resolve repo path: epic target > fallback to build.yaml parent dir
    if repo_path_str:
        repo_path = Path(repo_path_str).expanduser().resolve()
    else:
        repo_path = build_path.parent

    if not repo_path.exists():
        warnings.append(f"Repo path not found: {repo_path}")
        return

    report = BuildValidator(repo_path, build_data).validate()
    for finding in report.findings:
        warnings.append(
            f"[{finding.severity.value.upper()}] {finding.category.value}: {finding.message}"
        )
