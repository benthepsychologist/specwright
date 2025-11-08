"""CLI for Specwright: create, validate, and run Agentic Implementation Plans."""

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

import typer
import yaml  # type: ignore[import]

app = typer.Typer(help="Specwright CLI for managing Agentic Implementation Plans")


class RiskTier(str, Enum):
    """Risk tier enumeration."""
    A = "A"
    B = "B"
    C = "C"


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    import re
    slug = text.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug.strip('-')


def get_next_aip_id() -> str:
    """Generate next AIP ID based on existing AIPs."""
    today = datetime.now().strftime("%Y-%m-%d")
    existing = list(Path("aips").glob(f"AIP-{today}-*.yaml"))
    next_num = len(existing) + 1
    return f"AIP-{today}-{next_num:03d}"


def get_git_remote_url() -> str:
    """Get git remote URL, or return placeholder if not in a git repo."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "git@github.com:org/repo.git"  # Placeholder if no git


def get_default_config() -> dict:
    """Get default Specwright configuration."""
    return {
        "version": "0.1",
        "paths": {
            "specs": "specs",
            "aips": "aips",
            "templates": "config/templates/specs",
            "schemas": "config/schemas",
        },
        "repo": {
            "default_branch": "main"
        }
    }


def find_config() -> tuple[Path | None, dict]:
    """
    Walk up directory tree to find .specwright.yaml config.
    Returns (config_path, config_dict). If not found, returns (None, defaults).
    """
    current = Path.cwd()

    # Walk up directory tree
    while current != current.parent:
        config_path = current / ".specwright.yaml"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    return config_path, config
            except Exception as e:
                typer.echo(f"Warning: Could not load {config_path}: {e}", err=True)
                typer.echo("Using default config instead.", err=True)
                return None, get_default_config()
        current = current.parent

    # Not found, use defaults
    return None, get_default_config()


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
):
    """Initialize Specwright configuration in current directory."""
    config_path = Path.cwd() / ".specwright.yaml"

    if config_path.exists() and not force:
        typer.echo(f"Error: {config_path} already exists", err=True)
        typer.echo("  Use --force to overwrite", err=True)
        raise typer.Exit(1)

    config = get_default_config()

    with open(config_path, "w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)

    typer.echo(f"✓ Created {config_path}")
    typer.echo("  You can now use spec commands from anywhere in this project")


@app.command()
def config():
    """Display current Specwright configuration."""
    config_path, cfg = find_config()

    if config_path:
        typer.echo(f"Config loaded from: {config_path}")
    else:
        typer.echo("No .specwright.yaml found. Using defaults:")

    typer.echo(yaml.dump(cfg, sort_keys=False, default_flow_style=False))


@app.command()
def create(
    tier: RiskTier = typer.Option(..., "--tier", "-t", help="Risk tier (A/B/C)"),
    title: str = typer.Option(..., "--title", help="Spec title"),
    goal: str = typer.Option(..., "--goal", "-g", help="Objective (what are we building?)"),
    owner: str = typer.Option(..., "--owner", help="GitHub username or team"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Working branch name"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    yaml_mode: bool = typer.Option(False, "--yaml", help="Generate YAML directly (legacy mode)"),
):
    """Create a new spec from template (Markdown by default, YAML with --yaml flag)."""

    # Get config
    config_path, cfg = find_config()
    project_root = config_path.parent if config_path else Path.cwd()

    # Generate slug and branch
    slug = slugify(title)
    if branch is None:
        branch = "feat/" + slug

    if yaml_mode:
        # LEGACY MODE: Generate YAML directly
        aip_id = get_next_aip_id()

        if output is None:
            output = Path(cfg["paths"]["aips"]) / f"{slug}.yaml"

        template_path = project_root / "config" / "templates" / "aips" / f"tier-{tier.value.lower()}-template.yaml"

        if not template_path.exists():
            typer.echo(f"Error: Template not found at {template_path}", err=True)
            raise typer.Exit(1)

        with open(template_path) as f:
            aip = yaml.safe_load(f)

        # Replace PLACEHOLDER values
        aip["aip_id"] = aip_id
        aip["title"] = title
        aip["tier"] = tier.value
        aip["objective"]["goal"] = goal
        aip["repo"]["url"] = get_git_remote_url()
        aip["repo"]["working_branch"] = branch
        aip["orchestrator_contract"]["artifacts_dir"] = f".aip_artifacts/{aip_id}"
        aip["pull_request"]["title"] = f"[{aip_id}] {title}"
        aip["meta"] = {
            "created_by": owner,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }

        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w") as f:
            yaml.dump(aip, f, sort_keys=False, default_flow_style=False)

        typer.echo(f"✓ Created Tier {tier.value} AIP at {output}")
        typer.echo(f"  AIP ID: {aip_id}")
        typer.echo(f"  Branch: {branch}")
        typer.echo("  Next steps:")
        typer.echo(f"    1. Edit {output}")
        typer.echo(f"    2. Run: spec validate {output}")
        typer.echo(f"    3. Run: spec run {output}")

    else:
        # NEW DEFAULT: Generate Markdown
        if output is None:
            output = Path(cfg["paths"]["specs"]) / f"{slug}.md"

        template_path = project_root / cfg["paths"]["templates"] / f"tier-{tier.value.lower()}-template.md"

        if not template_path.exists():
            typer.echo(f"Error: Template not found at {template_path}", err=True)
            raise typer.Exit(1)

        # Use Jinja2 to render template
        from jinja2 import Template
        template_content = template_path.read_text()
        template = Template(template_content)
        rendered = template.render(
            tier=tier.value,
            title=title,
            owner=owner,
            goal=goal,
            branch=branch
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)

        typer.echo(f"✓ Created Tier {tier.value} spec at {output}")
        typer.echo(f"  Branch: {branch}")
        typer.echo("  Next steps:")
        typer.echo(f"    1. Edit {output}")
        typer.echo(f"    2. Run: spec compile {output}")
        typer.echo("    3. Run: spec validate <compiled-yaml>")
        typer.echo("    4. Run: spec run <compiled-yaml>")


@app.command()
def compile(
    spec_path: Path = typer.Argument(..., help="Path to Markdown spec file"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output YAML path (default: aips/<stem>.yaml)"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing compiled file"),
):
    """Compile Markdown spec to validated YAML AIP."""
    from spec.compiler import compile_spec as do_compile

    if not spec_path.exists():
        typer.echo(f"Error: Spec file not found: {spec_path}", err=True)
        raise typer.Exit(1)

    # Get config for default output path
    config_path, cfg = find_config()

    if output is None:
        # Default: specs/foo.md → aips/foo.yaml
        output = Path(cfg["paths"]["aips"]) / (spec_path.stem + ".yaml")

    # Create parent directory if it doesn't exist
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        do_compile(spec_path, output, overwrite=overwrite, validate=True)
        typer.echo(f"✓ Compiled {spec_path} → {output}")
        typer.echo("  Next steps:")
        typer.echo(f"    1. Run: spec validate {output}")
        typer.echo(f"    2. Run: spec run {output}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def validate(
    aip_path: Path = typer.Argument(..., help="Path to AIP YAML file"),
):
    """Validate an AIP against the JSON schema."""

    if not aip_path.exists():
        typer.echo(f"Error: AIP file not found: {aip_path}", err=True)
        raise typer.Exit(1)

    # Load AIP
    with open(aip_path) as f:
        aip = yaml.safe_load(f)

    # Load schema (look in config/ directory relative to project root)
    project_root = Path.cwd()
    schema_path = project_root / "config" / "schemas" / "aip.schema.json"

    if not schema_path.exists():
        typer.echo(f"Error: Schema not found at {schema_path}", err=True)
        raise typer.Exit(1)

    with open(schema_path) as f:
        schema = json.load(f)

    # Validate
    try:
        from jsonschema import validate  # type: ignore[import]
        validate(instance=aip, schema=schema)
        typer.echo(f"✓ {aip_path} is valid")
    except Exception as e:
        # Check if it's a ValidationError
        if type(e).__name__ == "ValidationError":
            typer.echo("✗ Validation failed:", err=True)
            typer.echo(f"  {getattr(e, 'message', str(e))}", err=True)
            if hasattr(e, 'path') and e.path:  # type: ignore[attr-defined]
                typer.echo(f"  Path: {' → '.join(str(p) for p in e.path)}", err=True)  # type: ignore[attr-defined]
            raise typer.Exit(1)
        # Check if it's an ImportError
        elif isinstance(e, ImportError):
            typer.echo("Error: jsonschema package not installed", err=True)
            typer.echo("  Install with: pip install jsonschema", err=True)
            raise typer.Exit(1)
        else:
            raise


@app.command()
def run(
    aip_path: Path = typer.Argument(..., help="Path to AIP YAML file"),
    step: int | None = typer.Option(None, "--step", "-s", help="Run specific step number (1-based)"),
):
    """Run an AIP in guided execution mode."""

    if not aip_path.exists():
        typer.echo(f"Error: AIP file not found: {aip_path}", err=True)
        raise typer.Exit(1)

    # Load AIP
    with open(aip_path) as f:
        aip = yaml.safe_load(f)

    # Display AIP info
    typer.echo(f"\n{'='*60}")
    typer.echo(f"AIP: {aip.get('title', 'Untitled')}")
    typer.echo(f"Tier: {aip.get('tier', 'unknown')}")
    typer.echo(f"Goal: {aip.get('objective', {}).get('goal', 'unknown')}")
    typer.echo(f"{'='*60}\n")

    # Get plan
    plan = aip.get("plan", [])
    if not plan:
        typer.echo("Error: No plan steps defined", err=True)
        raise typer.Exit(1)

    # Determine which steps to run
    if step is not None:
        if step < 1 or step > len(plan):
            typer.echo(f"Error: Step {step} out of range (1-{len(plan)})", err=True)
            raise typer.Exit(1)
        steps_to_run = [plan[step - 1]]
        step_numbers = [step]
    else:
        steps_to_run = plan
        step_numbers = list(range(1, len(plan) + 1))

    # Execute steps
    for step_num, step_def in zip(step_numbers, steps_to_run):
        step_id = step_def.get("step_id", "unknown")
        step_role = step_def.get("role", "unknown")
        step_desc = step_def.get("description", "")

        typer.echo(f"[Step {step_num}/{len(plan)}] {step_id}")
        typer.echo(f"  Role: {step_role}")
        typer.echo(f"  {step_desc}")

        # Show prompt if present
        if step_def.get("prompt"):
            typer.echo(f"\n  Prompt: {step_def['prompt']}")

        # Show commands if present
        if step_def.get("commands"):
            typer.echo("\n  Commands:")
            for cmd in step_def["commands"]:
                typer.echo(f"    $ {cmd}")

        # Show outputs if present
        if step_def.get("outputs"):
            typer.echo("\n  Expected outputs:")
            for out in step_def["outputs"]:
                typer.echo(f"    - {out}")

        # Simple execution (just pause and confirm)
        typer.echo()
        if typer.confirm("  Mark as complete?", default=True):
            typer.echo("  ✓ Step completed\n")
        else:
            typer.echo("  ⏭  Skipped\n")

    typer.echo(f"{'='*60}")
    typer.echo("✓ AIP execution complete")
    typer.echo(f"{'='*60}\n")


if __name__ == "__main__":
    app()
