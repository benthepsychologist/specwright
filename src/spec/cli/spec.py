"""CLI for Specwright: create, validate, and run Agentic Implementation Plans."""

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

import typer
import yaml  # type: ignore[import]

try:
    from importlib.resources import files  # type: ignore[attr-defined]
except ImportError:
    from importlib_resources import files  # type: ignore[import-untyped]

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


def get_template_path(tier: str) -> Path:
    """Get path to template file for given tier (from package resources)."""
    try:
        # Try package resources (installed mode)
        package_files = files("spec")
        template_file = package_files / "templates" / f"tier-{tier.lower()}-template.md"
        if hasattr(template_file, "read_text"):
            # Return a temporary path that we can read from
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / "specwright-templates"
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / f"tier-{tier.lower()}-template.md"
            temp_file.write_text(template_file.read_text())  # type: ignore[attr-defined]
            return temp_file
    except Exception:
        pass

    # Fallback: Development mode - look relative to project root
    # Walk up to find project root (where config/ or src/ exists)
    current = Path(__file__).parent
    while current != current.parent:
        dev_template = current.parent.parent / "config" / "templates" / "specs" / f"tier-{tier.lower()}-template.md"
        if dev_template.exists():
            return dev_template
        current = current.parent

    raise FileNotFoundError(f"Could not find template for tier {tier}")


def get_schema_path() -> Path:
    """Get path to AIP schema (from package resources)."""
    try:
        # Try package resources (installed mode)
        package_files = files("spec")
        schema_file = package_files / "schemas" / "aip.schema.json"
        if hasattr(schema_file, "read_text"):
            # Return a temporary path
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / "specwright-schemas"
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / "aip.schema.json"
            temp_file.write_text(schema_file.read_text())  # type: ignore[attr-defined]
            return temp_file
    except Exception:
        pass

    # Fallback: Development mode
    current = Path(__file__).parent
    while current != current.parent:
        dev_schema = current.parent.parent / "config" / "schemas" / "aip.schema.json"
        if dev_schema.exists():
            return dev_schema
        current = current.parent

    raise FileNotFoundError("Could not find aip.schema.json")


def get_default_config() -> dict:
    """Get default Specwright configuration."""
    return {
        "version": "0.1",
        "paths": {
            "specs": ".specwright/specs",
            "aips": ".specwright/aips",
        },
        "repo": {
            "default_branch": "main"
        },
        "user": {
            "default_owner": None,  # Default owner for new specs
            "default_tier": None    # Default tier (A/B/C) for new specs
        },
        "current": {
            "spec": None,  # Path to current working .md spec
            "aip": None    # Path to current compiled .yaml AIP
        }
    }


def save_config(config_path: Path, config: dict) -> None:
    """Save configuration to file."""
    with open(config_path, 'w') as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)


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

    # Create .specwright directory and copy guide
    spec_dir = Path.cwd() / ".specwright"
    spec_dir.mkdir(exist_ok=True)

    # Copy GUIDE.md to .specwright/
    try:
        from importlib.resources import files
        package_files = files("spec")
        guide_file = package_files / "templates" / "GUIDE.md"
        if hasattr(guide_file, "read_text"):
            guide_content = guide_file.read_text()  # type: ignore[attr-defined]
            guide_dest = spec_dir / "GUIDE.md"
            guide_dest.write_text(guide_content)
            typer.echo(f"✓ Created {guide_dest}")
    except Exception:
        # Silently skip if guide not found (development mode)
        pass

    typer.echo(f"✓ Created {config_path}")
    typer.echo("  You can now use spec commands from anywhere in this project")
    typer.echo("  Read .specwright/GUIDE.md for help writing effective specs")


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
def config(
    key: str | None = typer.Argument(None, help="Config key to set (e.g., 'user', 'current.spec')"),
    value: str | None = typer.Argument(None, help="Value to set"),
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
):
    """
    Manage Specwright configuration.

    Examples:
        spec config user myusername          # Set default owner
        spec config tier C                   # Set default tier
        spec config current.spec path.md     # Set current working spec
        spec config current.aip path.yaml    # Set current working AIP
        spec config --show                   # Show current config
    """
    config_path, cfg = find_config()

    if not config_path:
        typer.echo("Error: No .specwright.yaml found. Run 'spec init' first.", err=True)
        raise typer.Exit(1)

    # Show config if requested or no arguments
    if show or (key is None and value is None):
        typer.echo("Current configuration:")
        typer.echo(yaml.dump(cfg, sort_keys=False, default_flow_style=False))
        return

    if key is None:
        typer.echo("Error: Please provide a key to set", err=True)
        typer.echo('  Examples: spec config user myusername', err=True)
        raise typer.Exit(1)

    if value is None:
        typer.echo(f"Error: Please provide a value for '{key}'", err=True)
        raise typer.Exit(1)

    # Handle nested keys (e.g., "current.spec")
    parts = key.split('.')

    # Shorthands for convenience
    if parts == ["user"]:
        parts = ["user", "default_owner"]
    elif parts == ["tier"]:
        parts = ["user", "default_tier"]
        # Validate tier value
        if value.upper() not in ["A", "B", "C"]:
            typer.echo(f"Error: Invalid tier '{value}'. Must be A, B, or C.", err=True)
            raise typer.Exit(1)
        value = value.upper()  # Normalize to uppercase

    # Navigate to the correct nested dict
    current = cfg
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]

    # Special handling for file paths - validate they exist
    if parts[-1] in ["spec", "aip"]:
        path = Path(value)
        if not path.exists():
            typer.echo(f"Warning: File not found: {path}", err=True)
            if not typer.confirm("Set anyway?", default=False):
                raise typer.Exit(1)

        # Store as string
        current[parts[-1]] = str(path)

        if parts[-1] == "spec":
            typer.secho(f"✓ Set current spec: {value}", fg=typer.colors.GREEN)
            typer.echo("  You can now run: spec compile, spec validate")
        else:
            typer.secho(f"✓ Set current AIP: {value}", fg=typer.colors.GREEN)
            typer.echo("  You can now run: spec validate, spec run")
    else:
        # Set the value
        current[parts[-1]] = value
        typer.secho(f"✓ Set {key}: {value}", fg=typer.colors.GREEN)

    # Save config
    save_config(config_path, cfg)


@app.command()
def create(
    title: str = typer.Argument(..., help="Spec title"),
    tier: RiskTier | None = typer.Option(None, "--tier", "-t", help="Risk tier (A/B/C)"),
    goal: str | None = typer.Option(None, "--goal", "-g", help="Objective (what are we building?)"),
    owner: str | None = typer.Option(None, "--owner", help="GitHub username or team"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Working branch name"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    set_current: bool = typer.Option(False, "--set-current", help="Set as current working spec"),
    yaml_mode: bool = typer.Option(False, "--yaml", help="Generate YAML directly (legacy mode)"),
):
    """Create a new spec from template (Markdown by default, YAML with --yaml flag).

    Examples:
        spec create "Add User Avatars"                    # Uses defaults
        spec create "Add User Avatars" --tier C --goal "Allow profile pictures"
        spec create "Refactor Auth" --set-current
    """

    # Get config
    config_path, cfg = find_config()
    project_root = config_path.parent if config_path else Path.cwd()

    # Get tier from config if not provided
    if tier is None:
        default_tier_str = cfg.get("user", {}).get("default_tier")
        if default_tier_str:
            tier = RiskTier(default_tier_str)
            typer.echo(f"Using default tier: {tier.value}")
        else:
            typer.secho("Error: No tier specified", fg=typer.colors.RED, err=True)
            typer.echo("  Use --tier flag or set default tier with: spec config tier <A|B|C>", err=True)
            raise typer.Exit(1)

    # Get owner from config if not provided
    if owner is None:
        owner = cfg.get("user", {}).get("default_owner")
        if owner is None:
            typer.secho("Error: No owner specified", fg=typer.colors.RED, err=True)
            typer.echo("  Use --owner flag or set default owner with: spec config user <username>", err=True)
            raise typer.Exit(1)
        typer.echo(f"Using default owner: {owner}")

    # Default goal if not provided
    if goal is None:
        goal = f"Implement {title}"
        typer.echo(f"Using default goal: {goal}")

    # Generate slug and branch
    slug = slugify(title)
    if branch is None:
        branch = "feat/" + slug

    if yaml_mode:
        # LEGACY MODE: Generate YAML directly
        aip_id = get_next_aip_id()

        if output is None:
            output = Path(cfg["paths"]["aips"]) / f"{slug}.yaml"

        # Try to find YAML template (for backward compatibility)
        try:
            package_files = files("spec")
            template_file = package_files / "templates" / "aips" / f"tier-{tier.value.lower()}-template.yaml"
            if hasattr(template_file, "read_text"):
                template_content = template_file.read_text()  # type: ignore[attr-defined]
            else:
                raise FileNotFoundError
        except Exception:
            # Fallback to development mode
            template_path = project_root / "config" / "templates" / "aips" / f"tier-{tier.value.lower()}-template.yaml"
            if not template_path.exists():
                typer.echo("Error: YAML template not found", err=True)
                raise typer.Exit(1)
            template_content = template_path.read_text()

        aip = yaml.safe_load(template_content)

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
            "created_at": datetime.now().astimezone().isoformat()
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

        # Get template using helper function (works in both dev and installed mode)
        try:
            template_path = get_template_path(tier.value)
        except FileNotFoundError as e:
            typer.echo(f"Error: {e}", err=True)
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

        # Set as current if requested
        if set_current and config_path:
            if "current" not in cfg:
                cfg["current"] = {"spec": None, "aip": None}
            cfg["current"]["spec"] = str(output)
            save_config(config_path, cfg)
            typer.secho(f"✓ Set as current spec", fg=typer.colors.GREEN)
            typer.echo("  Next steps:")
            typer.echo("    1. Edit the spec")
            typer.echo("    2. Run: spec compile")
            typer.echo("    3. Run: spec validate")
        else:
            typer.echo("  Next steps:")
            typer.echo(f"    1. Edit {output}")
            typer.echo(f"    2. Run: spec compile {output}")
            typer.echo("    3. Run: spec validate <compiled-yaml>")


@app.command()
def compile(
    spec_path: Path | None = typer.Argument(None, help="Path to Markdown spec file (uses current spec if omitted)"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output YAML path (default: aips/<stem>.yaml)"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing compiled file"),
):
    """Compile Markdown spec to validated YAML AIP."""
    from spec.compiler import compile_spec as do_compile

    # Get config
    config_path, cfg = find_config()

    # If no spec_path provided, use current from config
    if spec_path is None:
        current_spec = cfg.get("current", {}).get("spec")
        if not current_spec:
            typer.echo("Error: No spec path provided and no current spec set.", err=True)
            typer.echo("  Run: spec config current.spec <path-to-spec.md>", err=True)
            raise typer.Exit(1)
        spec_path = Path(current_spec)
        typer.echo(f"Using current spec: {spec_path}")

    if not spec_path.exists():
        typer.echo(f"Error: Spec file not found: {spec_path}", err=True)
        raise typer.Exit(1)

    # Get config for default output path
    config_path, cfg = find_config()
    project_root = config_path.parent if config_path else Path.cwd()

    if output is None:
        # Default: specs/foo.md → aips/foo.yaml (relative to project root)
        aips_path = Path(cfg["paths"]["aips"])
        if not aips_path.is_absolute():
            aips_path = project_root / aips_path
        output = aips_path / (spec_path.stem + ".yaml")

    # Create parent directory if it doesn't exist
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        do_compile(spec_path, output, overwrite=overwrite, validate=True)

        # Validate compiled YAML against schema
        with open(output) as f:
            aip = yaml.safe_load(f)

        schema_path = get_schema_path()
        with open(schema_path) as f:
            schema = json.load(f)

        from jsonschema import Draft7Validator  # type: ignore[import]
        validator = Draft7Validator(schema)
        errors = list(validator.iter_errors(aip))

        if errors:
            typer.secho(f"\n✓ Compiled {spec_path} → {output}", fg=typer.colors.GREEN)
            typer.secho(f"✗ But validation failed with {len(errors)} error(s):\n", fg=typer.colors.RED, bold=True, err=True)
            for i, error in enumerate(errors, 1):
                typer.secho(f"  [{i}] {error.message}", fg=typer.colors.RED, err=True)
                if error.path:
                    path_str = ' → '.join(str(p) for p in error.path)
                    typer.secho(f"      at: {path_str}", fg=typer.colors.YELLOW, err=True)
                if error.validator and error.validator != 'required':
                    typer.secho(f"      validator: {error.validator}", fg=typer.colors.BLUE, dim=True, err=True)
                typer.echo("", err=True)
            raise typer.Exit(1)

        typer.secho(f"✓ Compiled {spec_path} → {output}", fg=typer.colors.GREEN)
        typer.secho(f"✓ Validation passed", fg=typer.colors.GREEN)

        # Update current AIP in config
        if config_path and "current" in cfg:
            cfg["current"]["aip"] = str(output)
            save_config(config_path, cfg)
            typer.echo(f"  Set as current AIP")

        typer.echo("  Next steps:")
        typer.echo(f"    1. Run: spec run")
    except Exception as e:
        if isinstance(e, typer.Exit):
            raise
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def validate(
    spec_path: Path | None = typer.Argument(None, help="Path to spec (.md) or AIP (.yaml) file (uses current if omitted)"),
):
    """Validate a Markdown spec or compiled YAML AIP."""

    # Get config
    config_path, cfg = find_config()

    # If no spec_path provided, try current spec or aip
    if spec_path is None:
        current_spec = cfg.get("current", {}).get("spec")
        current_aip = cfg.get("current", {}).get("aip")

        # Prefer spec over aip
        if current_spec:
            spec_path = Path(current_spec)
            typer.echo(f"Using current spec: {spec_path}")
        elif current_aip:
            spec_path = Path(current_aip)
            typer.echo(f"Using current AIP: {spec_path}")
        else:
            typer.echo("Error: No file path provided and no current spec/AIP set.", err=True)
            typer.echo("  Run: spec config current.spec <path-to-file>", err=True)
            raise typer.Exit(1)

    if not spec_path.exists():
        typer.echo(f"Error: File not found: {spec_path}", err=True)
        raise typer.Exit(1)

    # Detect file type and handle accordingly
    if spec_path.suffix == '.md':
        # Parse Markdown spec and validate the resulting AIP structure
        typer.echo(f"Validating Markdown spec: {spec_path}")
        from spec.compiler.parser import SpecParser

        try:
            content = spec_path.read_text(encoding='utf-8')
            parser = SpecParser(content, source_path=spec_path)
            aip = parser.parse()
            typer.secho(f"✓ Markdown parsed successfully", fg=typer.colors.GREEN)
        except (ValueError, KeyError, AttributeError) as e:
            typer.secho(f"\n✗ Markdown parsing failed:", fg=typer.colors.RED, bold=True, err=True)
            typer.secho(f"  {str(e)}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)

        # Now validate the parsed AIP against the schema
        # (Don't return early - fall through to schema validation below)

    elif spec_path.suffix not in ['.yaml', '.yml']:
        typer.echo(f"Error: File must be .md, .yaml, or .yml (got {spec_path.suffix})", err=True)
        raise typer.Exit(1)
    else:
        # Load YAML AIP
        with open(spec_path) as f:
            aip = yaml.safe_load(f)

    # Load schema using helper function (works in both dev and installed mode)
    try:
        schema_path = get_schema_path()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    with open(schema_path) as f:
        schema = json.load(f)

    # Validate and collect ALL errors
    try:
        from jsonschema import Draft7Validator  # type: ignore[import]

        validator = Draft7Validator(schema)
        errors = list(validator.iter_errors(aip))

        if errors:
            typer.secho(f"\n✗ Validation failed with {len(errors)} error(s):\n", fg=typer.colors.RED, bold=True, err=True)
            for i, error in enumerate(errors, 1):
                typer.secho(f"  [{i}] {error.message}", fg=typer.colors.RED, err=True)
                if error.path:
                    path_str = ' → '.join(str(p) for p in error.path)
                    typer.secho(f"      at: {path_str}", fg=typer.colors.YELLOW, err=True)
                if error.validator and error.validator != 'required':
                    typer.secho(f"      validator: {error.validator}", fg=typer.colors.BLUE, dim=True, err=True)
                typer.echo("", err=True)  # Blank line between errors
            raise typer.Exit(1)
        else:
            typer.secho(f"✓ {spec_path} is valid", fg=typer.colors.GREEN, bold=True)
    except ImportError:
        typer.echo("Error: jsonschema package not installed", err=True)
        typer.echo("  Install with: pip install jsonschema", err=True)
        raise typer.Exit(1)


@app.command()
def run(
    aip_path: Path | None = typer.Argument(None, help="Path to AIP YAML file (uses current AIP if omitted)"),
    step: int | None = typer.Option(None, "--step", "-s", help="Run specific step number (1-based)"),
    skip_gates: bool = typer.Option(False, "--skip-gates", help="Skip gate approvals (governance override)"),
):
    """Run an AIP in guided execution mode with gate approvals."""
    from spec.cli.interactive import (
        display_gate_checkpoint,
        show_gate_checklist,
        prompt_checklist_completion,
        prompt_approval_decision,
        display_step_details,
        display_approval_summary,
        confirm_gate_override
    )
    from spec.audit import GateAuditLogger

    # Get config
    config_path, cfg = find_config()

    # If no aip_path provided, use current AIP
    if aip_path is None:
        current_aip = cfg.get("current", {}).get("aip")
        if not current_aip:
            typer.echo("Error: No AIP path provided and no current AIP set.", err=True)
            typer.echo("  Run: spec compile  (to compile and set current AIP)", err=True)
            typer.echo("  Or: spec config current.aip <path-to-aip.yaml>", err=True)
            raise typer.Exit(1)
        aip_path = Path(current_aip)
        typer.echo(f"Using current AIP: {aip_path}\n")

    if not aip_path.exists():
        typer.echo(f"Error: AIP file not found: {aip_path}", err=True)
        raise typer.Exit(1)

    # Load AIP
    with open(aip_path) as f:
        aip = yaml.safe_load(f)

    # Get tier for gate behavior
    tier = aip.get("tier", "C")

    # Initialize audit logger
    aip_id = aip.get("aip_id", "unknown")
    artifacts_dir = aip.get("orchestrator_contract", {}).get("artifacts_dir", f".aip_artifacts/{aip_id}")
    audit_logger = GateAuditLogger(aip_id, artifacts_dir)

    # Display AIP info with acceptance criteria
    typer.echo(f"\n{'='*70}")
    typer.secho(f"AIP: {aip.get('title', 'Untitled')}", bold=True)
    typer.echo(f"Tier: {tier}")
    typer.echo(f"{'='*70}")

    # Display objective
    objective = aip.get("objective", {})
    typer.echo(f"\n📋 Goal: {objective.get('goal', 'Not specified')}")

    # Display acceptance criteria
    acceptance_criteria = objective.get("acceptance_criteria", [])
    if acceptance_criteria:
        typer.echo(f"\n✅ Acceptance Criteria:")
        for i, criterion in enumerate(acceptance_criteria, 1):
            typer.echo(f"  {i}. {criterion}")

    typer.echo(f"\n{'='*70}\n")

    # Handle skip-gates for Tier A/B
    if skip_gates and tier in ["A", "B"]:
        if not confirm_gate_override(tier):
            typer.echo("Aborting execution.", err=True)
            raise typer.Exit(1)

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

    # Execute steps (stop at first incomplete)
    for step_num, step_def in zip(step_numbers, steps_to_run):
        step_id = step_def.get("step_id", "unknown")
        step_role = step_def.get("role", "unknown")
        step_desc = step_def.get("description", "")
        gate_ref = step_def.get("gate_ref")
        gate_review = step_def.get("gate_review")

        typer.secho(f"\n▶ Step {step_num}/{len(plan)}: {step_desc}", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"  ID: {step_id}")
        typer.echo(f"  Role: {step_role}")
        if gate_ref:
            typer.echo(f"  Gate: {gate_ref}")

        # Show step details using rich formatting
        display_step_details(step_def)

        # Ask if step is complete - STOP if not complete
        typer.echo()
        if typer.confirm("  ✓ Mark this step as complete?", default=False):
            typer.secho("  ✅ Step completed", fg=typer.colors.GREEN)
        else:
            typer.secho("  ⏸  Stopping at incomplete step", fg=typer.colors.YELLOW)
            typer.echo(f"\n  Resume later with: spec run --step {step_num}")
            raise typer.Exit(0)  # Exit without error

        # Handle gate review if present
        if gate_review and not skip_gates:
            checklist = gate_review.get("checklist", {})

            # Tier-specific gate behavior
            if tier == "C":
                # Tier C: Auto-approve (log only)
                typer.echo(f"\n📝 [Tier C] Gate auto-approved (checklist logged)")
                audit_logger.log_approval(
                    step_id=step_id,
                    gate_ref=gate_ref or "unknown",
                    decision="approved",
                    reviewer="system",
                    rationale="Tier C auto-approval",
                    completed_checklist=checklist
                )
            elif tier in ["A", "B"]:
                # Tier A/B: Require interactive approval
                display_gate_checkpoint(gate_ref or "Gate", step_desc, tier)

                if checklist:
                    show_gate_checklist(checklist)
                    typer.echo()

                    # Interactive checklist completion
                    completed_items = prompt_checklist_completion(checklist)

                # Prompt for approval decision
                approval = prompt_approval_decision()

                if approval.get("decision") == "cancelled":
                    typer.secho("\n⚠️  Gate approval cancelled. Stopping execution.", fg=typer.colors.YELLOW)
                    raise typer.Exit(0)

                display_approval_summary(approval)

                # Log approval to audit trail
                audit_logger.log_approval(
                    step_id=step_id,
                    gate_ref=gate_ref or "unknown",
                    decision=approval["decision"],
                    reviewer=approval["reviewer"],
                    rationale=approval.get("rationale", ""),
                    conditions=approval.get("conditions", ""),
                    completed_checklist=completed_items,
                    metadata={"timestamp": approval.get("timestamp")}
                )

                # Handle decision
                if approval["decision"] == "rejected":
                    typer.secho("\n❌ Gate REJECTED. Execution halted.", fg=typer.colors.RED, bold=True)
                    typer.echo(f"   Reason: {approval.get('rationale', 'No reason provided')}")
                    raise typer.Exit(1)
                elif approval["decision"] == "deferred":
                    typer.secho("\n⏸️  Gate DEFERRED. Execution paused for review.", fg=typer.colors.YELLOW)
                    typer.echo(f"\n  Resume later with: spec run --step {step_num + 1}")
                    raise typer.Exit(0)
                elif approval["decision"] in ["approved", "conditional"]:
                    if approval["decision"] == "conditional":
                        typer.secho(f"\n⚠️  Gate CONDITIONALLY APPROVED", fg=typer.colors.YELLOW)
                        typer.echo(f"   Conditions: {approval.get('conditions', '')}")
                    else:
                        typer.secho(f"\n✅ Gate APPROVED", fg=typer.colors.GREEN)
                    typer.echo(f"   Proceeding to next step...")

    typer.echo(f"\n{'='*60}")
    typer.echo("✓ AIP execution complete")
    typer.echo(f"{'='*60}\n")


@app.command()
def gate_list(
    aip_path: Path | None = typer.Argument(None, help="Path to AIP YAML file (uses current AIP if omitted)"),
):
    """List all gate approvals from audit trail."""
    from spec.audit import GateAuditLogger

    # Get config
    config_path, cfg = find_config()

    # If no aip_path provided, use current AIP
    if aip_path is None:
        current_aip = cfg.get("current", {}).get("aip")
        if not current_aip:
            typer.echo("Error: No AIP path provided and no current AIP set.", err=True)
            raise typer.Exit(1)
        aip_path = Path(current_aip)

    if not aip_path.exists():
        typer.echo(f"Error: AIP file not found: {aip_path}", err=True)
        raise typer.Exit(1)

    # Load AIP
    with open(aip_path) as f:
        aip = yaml.safe_load(f)

    aip_id = aip.get("aip_id", "unknown")
    artifacts_dir = aip.get("orchestrator_contract", {}).get("artifacts_dir", f".aip_artifacts/{aip_id}")
    audit_logger = GateAuditLogger(aip_id, artifacts_dir)

    approvals = audit_logger.get_approvals()

    if not approvals:
        typer.echo("No gate approvals found in audit trail.")
        return

    typer.echo(f"\n{'='*70}")
    typer.secho(f"Gate Approvals for {aip_id}", bold=True)
    typer.echo(f"{'='*70}\n")

    for approval in approvals:
        decision_colors = {
            "approved": typer.colors.GREEN,
            "rejected": typer.colors.RED,
            "deferred": typer.colors.YELLOW,
            "conditional": typer.colors.YELLOW
        }
        color = decision_colors.get(approval.get("decision", "unknown"), typer.colors.WHITE)

        typer.secho(f"Step: {approval.get('step_id')}", bold=True)
        typer.echo(f"  Gate: {approval.get('gate_ref')}")
        typer.secho(f"  Decision: {approval.get('decision').upper()}", fg=color)
        typer.echo(f"  Reviewer: {approval.get('reviewer')}")
        typer.echo(f"  Timestamp: {approval.get('timestamp')}")

        if approval.get("rationale"):
            typer.echo(f"  Rationale: {approval.get('rationale')}")
        if approval.get("conditions"):
            typer.echo(f"  Conditions: {approval.get('conditions')}")

        typer.echo()


@app.command()
def gate_report(
    aip_path: Path | None = typer.Argument(None, help="Path to AIP YAML file (uses current AIP if omitted)"),
):
    """Generate a summary report of gate approvals."""
    from spec.audit import GateAuditLogger

    # Get config
    config_path, cfg = find_config()

    # If no aip_path provided, use current AIP
    if aip_path is None:
        current_aip = cfg.get("current", {}).get("aip")
        if not current_aip:
            typer.echo("Error: No AIP path provided and no current AIP set.", err=True)
            raise typer.Exit(1)
        aip_path = Path(current_aip)

    if not aip_path.exists():
        typer.echo(f"Error: AIP file not found: {aip_path}", err=True)
        raise typer.Exit(1)

    # Load AIP
    with open(aip_path) as f:
        aip = yaml.safe_load(f)

    aip_id = aip.get("aip_id", "unknown")
    artifacts_dir = aip.get("orchestrator_contract", {}).get("artifacts_dir", f".aip_artifacts/{aip_id}")
    audit_logger = GateAuditLogger(aip_id, artifacts_dir)

    summary = audit_logger.get_summary()

    typer.echo(f"\n{'='*70}")
    typer.secho(f"Gate Approval Summary for {aip_id}", bold=True)
    typer.echo(f"{'='*70}\n")

    typer.echo(f"Total Approvals: {summary['total']}")
    typer.secho(f"  Approved: {summary['approved']}", fg=typer.colors.GREEN)
    typer.secho(f"  Rejected: {summary['rejected']}", fg=typer.colors.RED)
    typer.secho(f"  Deferred: {summary['deferred']}", fg=typer.colors.YELLOW)
    typer.secho(f"  Conditional: {summary['conditional']}", fg=typer.colors.YELLOW)

    if summary["by_gate"]:
        typer.echo(f"\nBy Gate:")
        for gate_ref, stats in summary["by_gate"].items():
            typer.echo(f"\n  {gate_ref}:")
            typer.echo(f"    Total: {stats['total']}")
            typer.echo(f"    Approved: {stats['approved']}")
            typer.echo(f"    Rejected: {stats['rejected']}")
            typer.echo(f"    Deferred: {stats['deferred']}")
            typer.echo(f"    Conditional: {stats['conditional']}")

    typer.echo()


if __name__ == "__main__":
    app()
