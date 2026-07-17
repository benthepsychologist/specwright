"""CLI commands: spec delta — build delta management."""

from __future__ import annotations

import typer

delta_app = typer.Typer(help="Build delta management commands.")


@delta_app.command("generate")
def generate_command(
    spec_query: str = typer.Argument(
        ..., help="Spec ID or prefix (e.g., 't004-02')"
    ),
    model: str | None = typer.Option(
        None, "--model", help="LLM model name (overrides config)"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt"
    ),
) -> None:
    """Generate a build_delta for a spec using LLM.

    Reads the spec's expectations and the current build.yaml, then
    uses an LLM to draft a build_delta. Presents it for approval
    before writing to epic.yaml.

    Examples:
        spec delta generate t004-02
        spec delta generate t004-02 --model gemini-3.1-pro-preview
        spec delta generate t004-02 --yes
    """
    from spec.governance.delta_generator import DeltaGenerationError, DeltaGenerator
    from spec.governance.epic_updater import EpicUpdateError, EpicUpdater
    from spec.governor.resolver import ResolveError, resolve_spec

    # 1. Resolve spec
    try:
        resolved = resolve_spec(spec_query)
    except ResolveError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    epic_yaml = resolved.epic.epic_yaml
    spec_id = resolved.spec_id

    # 2. Load epic via EpicUpdater (single load, used for reads and writes)
    try:
        updater = EpicUpdater(epic_yaml)
    except EpicUpdateError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(e.exit_code)

    spec_entry = updater.get_spec_entry(spec_id)

    # 3. Check for existing build_delta
    if spec_entry.get("build_delta"):
        typer.secho(
            f"Spec '{spec_id}' already has a build_delta. "
            "Remove it from epic.yaml first to regenerate.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(1)

    # 4. Get expectations
    expectations = spec_entry.get("expectations", [])
    if not expectations:
        typer.secho(
            f"Spec '{spec_id}' has no expectations. "
            "Cannot generate a build_delta without expectations.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(1)

    # 5. Find target build.yaml
    repo_id = spec_entry.get("repo")
    target_entry = updater.get_target(repo_id) if repo_id else None

    if target_entry is None:
        typer.secho(
            f"Error: Target repo '{repo_id}' not found in epic targets",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    # Resolve build.yaml path
    governor_project = target_entry.get("governor_project", repo_id)
    from spec.governor.resolver import _get_governor_root

    governor_root = _get_governor_root()
    build_path = (
        governor_root / "projects" / governor_project / f"{governor_project}.build.yaml"
    )

    if not build_path.exists():
        typer.secho(
            f"Error: build.yaml not found at {build_path}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    build_yaml_content = build_path.read_text()
    target_path = f"projects/{governor_project}/{governor_project}.build.yaml"

    # 6. Generate
    typer.echo(f"Generating build_delta for '{spec_id}'...")
    typer.echo(f"  Model: {model or '(from config)'}")
    typer.echo(f"  Target: {target_path}")
    typer.echo(f"  Expectations: {len(expectations)}")
    typer.echo()

    generator = DeltaGenerator(
        expectations=list(expectations),
        build_yaml_content=build_yaml_content,
        target_path=target_path,
        model_name=model,
    )

    try:
        delta = generator.generate()
    except DeltaGenerationError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(e.exit_code)

    # 7. Show result
    import yaml as pyyaml

    delta_yaml = pyyaml.dump(delta, default_flow_style=False, sort_keys=False)
    typer.secho("Generated build_delta:", bold=True)
    typer.echo()
    typer.echo(delta_yaml)

    # 8. Confirm
    if not yes:
        if not typer.confirm("Write this build_delta to epic.yaml?", default=False):
            typer.echo("Aborted.")
            raise typer.Exit(0)

    # 9. Write to epic (reuse same updater — single load)
    try:
        updater.add_build_delta(spec_id, delta)
        updater.set_updated()
        updater.save()
        typer.secho(
            f"Wrote build_delta to '{spec_id}' in {epic_yaml.name}",
            fg=typer.colors.GREEN,
        )
    except EpicUpdateError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(e.exit_code)

    typer.echo(
        f"\nNext: review the delta in epic.yaml, then run 'spec finish {spec_query}' to apply it."
    )
