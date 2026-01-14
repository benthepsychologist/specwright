"""CLI for Specwright: create, validate, and run Agentic Implementation Plans."""

import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import typer
import yaml  # type: ignore[import]

try:
    from importlib.resources import files  # type: ignore[attr-defined,no-redef]
except ImportError:
    from importlib_resources import files  # type: ignore[import-untyped,no-redef,import-not-found]

import functools

from spec.autogov.exceptions import SpecwrightError


def _specwright_exception_handler(func):
    """Decorator to catch SpecwrightError and exit with proper exit code."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SpecwrightError as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(e.exit_code)
    return wrapper


app = typer.Typer(help="Specwright CLI for managing Agentic Implementation Plans")

# Register epic subcommands
from spec.cli.epic import epic_app

app.add_typer(epic_app, name="epic")


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


def get_default_config(*, legacy: bool = False) -> dict:
    """Get default Specwright configuration.

    Args:
        legacy: If True, return legacy v0.1 format. Otherwise v0.6 minimal format.
    """
    if legacy:
        # Legacy v0.1 format (deprecated)
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

    # New v0.6 minimal format - governor-based
    return {
        "version": "0.6",
        "governor": {
            "path": "~/.local/local-governor"
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


def is_legacy_config(cfg: dict) -> bool:
    """Check if config is legacy v0.1 format (has paths section)."""
    return cfg.get("version") == "0.1" or "paths" in cfg


def _get_project_name(cfg: dict, project_root: Path) -> str:
    """Get project name from config or default to directory name."""
    # Try config's project_slug
    project = cfg.get("project_slug")
    if project:
        return project
    # Try autogov source
    autogov = cfg.get("autogov", {})
    if autogov.get("source"):
        return autogov["source"]
    # Default to directory name
    return project_root.name


def get_specs_path(cfg: dict, project_root: Path) -> Path:
    """Get specs path based on config version.

    For v0.6 (governor): Returns governor/projects/{project}/specs path
    For v0.1 (legacy): Returns .specwright/specs
    """
    if is_legacy_config(cfg):
        specs_dir = cfg.get("paths", {}).get("specs", ".specwright/specs")
        path = Path(specs_dir)
        if not path.is_absolute():
            path = project_root / path
        return path
    else:
        # v0.6: Use governor path with project structure
        governor_path = Path(cfg.get("governor", {}).get("path", "~/.local/local-governor")).expanduser()
        project = _get_project_name(cfg, project_root)
        return governor_path / "projects" / project / "specs"


def get_aips_path(cfg: dict, project_root: Path) -> Path:
    """Get AIPs path based on config version.

    For v0.6 (governor): Returns governor/projects/{project}/aips path
    For v0.1 (legacy): Returns .specwright/aips
    """
    if is_legacy_config(cfg):
        aips_dir = cfg.get("paths", {}).get("aips", ".specwright/aips")
        path = Path(aips_dir)
        if not path.is_absolute():
            path = project_root / path
        return path
    else:
        # v0.6: Use governor path with project structure
        governor_path = Path(cfg.get("governor", {}).get("path", "~/.local/local-governor")).expanduser()
        project = _get_project_name(cfg, project_root)
        return governor_path / "projects" / project / "aips"


def get_user_default(cfg: dict, key: str) -> str | None:
    """Get user default value from config (works for both v0.1 and v0.6)."""
    # v0.1: user.default_owner, user.default_tier
    if is_legacy_config(cfg):
        return cfg.get("user", {}).get(key)
    # v0.6: No user defaults stored in config
    return None


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
    claude: bool = typer.Option(True, "--claude/--no-claude", help="Install Claude Code slash commands"),
    autogov: bool = typer.Option(False, "--autogov", help="Enable autogov governance integration"),
    legacy_mode: bool = typer.Option(False, "--legacy-mode", help="Use legacy v0.1 repo-local config (deprecated)"),
    governor_path: str | None = typer.Option(None, "--governor", help="Custom local-governor path"),
):
    """Initialize Specwright configuration in current directory.

    Examples:
        spec init                    # v0.6 minimal config (governor-based)
        spec init --autogov          # Enable autogov (prompts for registry source)
        spec init --legacy-mode      # v0.1 repo-local specs (deprecated)
        spec init --governor /path   # Custom governor location
    """
    config_path = Path.cwd() / ".specwright.yaml"

    if config_path.exists() and not force:
        typer.echo(f"Error: {config_path} already exists", err=True)
        typer.echo("  Use --force to overwrite", err=True)
        raise typer.Exit(1)

    # Get config based on mode
    config = get_default_config(legacy=legacy_mode)

    if legacy_mode:
        typer.secho("Warning: --legacy-mode is deprecated. Consider using v0.6 format.", fg=typer.colors.YELLOW)

    # Set custom governor path if provided
    if governor_path and not legacy_mode:
        config["governor"]["path"] = governor_path

    # Add autogov section if enabled (prompt for source interactively)
    if autogov:
        import click
        typer.echo("Autogov governance enabled.")
        source = typer.prompt(
            "Registry source (org/patterns)",
            type=click.Choice(["org", "patterns"]),
            default="org",
        )
        config["autogov"] = {
            "enabled": True,
            "source": source,
        }
        typer.echo(f"✓ Autogov enabled with source: {source}")

    with open(config_path, "w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)

    # Create .specwright directory structure
    spec_dir = Path.cwd() / ".specwright"
    spec_dir.mkdir(exist_ok=True)

    # Create tmp directory for materialized AIPs (v0.6 model)
    if not legacy_mode:
        tmp_dir = spec_dir / "tmp"
        tmp_dir.mkdir(exist_ok=True)
        typer.echo(f"✓ Created {tmp_dir} (for materialized AIPs)")

        # Update .gitignore if it exists
        gitignore_path = Path.cwd() / ".gitignore"
        if gitignore_path.exists():
            gitignore_content = gitignore_path.read_text()
            if ".specwright/tmp/" not in gitignore_content:
                with open(gitignore_path, "a") as f:
                    f.write("\n# Specwright ephemeral artifacts\n.specwright/tmp/\n")
                typer.echo("✓ Added .specwright/tmp/ to .gitignore")
    else:
        # Legacy mode: Create subdirectories for repo-local specs/aips
        (spec_dir / "specs").mkdir(exist_ok=True)
        (spec_dir / "aips").mkdir(exist_ok=True)

    # Common directories
    (spec_dir / "runs").mkdir(exist_ok=True)
    (spec_dir / "artifacts" / "schemas").mkdir(parents=True, exist_ok=True)

    # Copy GUIDE.md and schemas to .specwright/
    try:
        from importlib.resources import files
        package_files = files("spec")

        # Copy GUIDE.md
        guide_file = package_files / "templates" / "GUIDE.md"
        if hasattr(guide_file, "read_text"):
            guide_content = guide_file.read_text()  # type: ignore[attr-defined]
            guide_dest = spec_dir / "GUIDE.md"
            guide_dest.write_text(guide_content)
            typer.echo(f"✓ Created {guide_dest}")
    except Exception:
        # Silently skip if guide not found (development mode)
        pass

    # Copy claude_output.schema.json
    try:
        # Try package resources first
        from importlib.resources import files as pkg_files
        package_files = pkg_files("spec")
        # Schema might be in artifacts/schemas relative to package root
        schema_source = Path(__file__).parent.parent.parent.parent / "artifacts" / "schemas" / "claude_output.schema.json"
        if schema_source.exists():
            schema_dest = spec_dir / "artifacts" / "schemas" / "claude_output.schema.json"
            schema_dest.write_text(schema_source.read_text())
            typer.echo(f"✓ Created {schema_dest}")
    except Exception:
        # Silently skip if schema not found
        pass

    # Copy Claude Code slash commands if requested
    if claude:
        claude_dir = Path.cwd() / ".claude" / "commands"
        claude_dir.mkdir(parents=True, exist_ok=True)

        slash_commands = [
            "spec-run.md",
            "spec-status.md",
            "spec-next.md",
            "spec-pause.md",
            "README.md"
        ]

        copied_count = 0
        try:
            # First, try to find commands in the package installation
            spec_package_dir = Path(__file__).parent.parent.parent.parent
            source_claude_dir = spec_package_dir / ".claude" / "commands"

            if source_claude_dir.exists():
                for cmd_file in slash_commands:
                    src = source_claude_dir / cmd_file
                    dst = claude_dir / cmd_file
                    if src.exists():
                        dst.write_text(src.read_text())
                        copied_count += 1

                if copied_count > 0:
                    typer.echo(f"✓ Installed {copied_count} Claude Code slash commands to .claude/commands/")
                    typer.echo("  Use /spec-run, /spec-status, /spec-next, /spec-pause in Claude Code")
        except Exception as e:
            typer.echo(f"  Warning: Could not install Claude Code commands: {e}", err=True)
            typer.echo("  You can manually copy them from the specwright repo's .claude/commands/", err=True)

    typer.echo(f"✓ Created {config_path}")
    typer.echo("  You can now use spec commands from anywhere in this project")
    typer.echo("  Read .specwright/GUIDE.md for help writing effective specs")


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
@_specwright_exception_handler
def create(
    title: str = typer.Argument(..., help="Spec title"),
    tier: RiskTier | None = typer.Option(None, "--tier", "-t", help="Risk tier (A/B/C)"),
    goal: str | None = typer.Option(None, "--goal", "-g", help="Objective (what are we building?)"),
    owner: str | None = typer.Option(None, "--owner", help="GitHub username or team"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Working branch name"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    set_current: bool = typer.Option(False, "--set-current", help="Set as current working spec"),
    yaml_mode: bool = typer.Option(False, "--yaml", help="Generate YAML directly (legacy mode)"),
    autogov_project: str | None = typer.Option(None, "--autogov", help="Autogov project name (required when autogov.enabled: true)"),
):
    """Create a new spec from template (Markdown by default, YAML with --yaml flag).

    Examples:
        spec create "Add User Avatars"                                   # Uses defaults
        spec create "Add User Avatars" --tier C --goal "Allow profile pictures"
        spec create "Refactor Auth" --set-current
        spec create "Add OAuth" --autogov myproject --tier B             # With governance
    """
    from spec.autogov.exceptions import CLIUsageError, RegistryConfigError

    # Get config
    config_path, cfg = find_config()

    # Check autogov configuration
    autogov_cfg = cfg.get("autogov", {})
    autogov_enabled = autogov_cfg.get("enabled", False)
    governance_bundle = None

    if autogov_enabled:
        # Validate config has source
        if "source" not in autogov_cfg:
            raise RegistryConfigError(
                "Missing autogov.source in .specwright.yaml. "
                "Add 'autogov.source: org' or 'autogov.source: patterns' to your config."
            )
        # Require --autogov flag when enabled
        if not autogov_project:
            raise CLIUsageError(
                "--autogov is required when autogov.enabled: true in .specwright.yaml. "
                "Use: spec create <title> --autogov <project-name>"
            )
        # Load governance (lazy import)
        from spec.autogov.loader import GovernanceLoader
        loader = GovernanceLoader()
        governance_bundle = loader.load_all(autogov_project, autogov_cfg["source"])
    project_root = config_path.parent if config_path else Path.cwd()

    # Get tier from config if not provided
    if tier is None:
        default_tier_str = get_user_default(cfg, "default_tier")
        if default_tier_str:
            tier = RiskTier(default_tier_str)
            typer.echo(f"Using default tier: {tier.value}")
        else:
            typer.secho("Error: No tier specified", fg=typer.colors.RED, err=True)
            typer.echo("  Use --tier flag or set default tier with: spec config tier <A|B|C>", err=True)
            raise typer.Exit(1)

    # Get owner from config if not provided
    if owner is None:
        owner = get_user_default(cfg, "default_owner")
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
            output = get_aips_path(cfg, project_root) / f"{slug}.yaml"

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
            output = get_specs_path(cfg, project_root) / f"{slug}.md"

        # Get template using helper function (works in both dev and installed mode)
        try:
            template_path = get_template_path(tier.value)
        except FileNotFoundError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        # Get project slug from git remote
        import subprocess
        try:
            repo_url = subprocess.check_output(
                ['git', 'config', '--get', 'remote.origin.url'],
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
            # Extract repo name from URL
            if "github.com" in repo_url:
                project_slug = repo_url.split("/")[-1].replace(".git", "").lower()
            else:
                project_slug = "project"
        except (subprocess.CalledProcessError, FileNotFoundError):
            project_slug = "project"

        # Generate timestamps
        now = datetime.now().astimezone().isoformat()

        # Build base template context
        base_context = {
            "tier": tier.value,
            "title": title,
            "owner": owner,
            "goal": goal,
            "branch": branch,
            "project_slug": project_slug,
            "created": now,
            "updated": now,
        }

        # Merge governance context if available
        if governance_bundle is not None:
            from spec.autogov.context_builder import SpecContextBuilder
            context_builder = SpecContextBuilder()
            template_context = context_builder.merge_with_template_context(
                bundle=governance_bundle,
                base_context=base_context,
                project=autogov_project,  # type: ignore[arg-type]
                source=autogov_cfg["source"],
            )
        else:
            template_context = base_context

        # Use Jinja2 to render template
        from jinja2 import BaseLoader, Environment
        # Use Environment with trim_blocks/lstrip_blocks for cleaner output
        env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)
        template_content = template_path.read_text()
        template = env.from_string(template_content)
        rendered = template.render(**template_context)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)

        # Log spec creation to audit trail
        from datetime import date

        from spec.audit.execution_logger import ExecutionAuditLogger
        today = date.today()
        aip_id = f"AIP-{project_slug}-{today.year}-{today.month:02d}-{today.day:02d}-001"

        audit_logger = ExecutionAuditLogger()
        audit_logger.log_spec_created(
            aip_id=aip_id,
            project_slug=project_slug,
            spec_path=str(output),
            spec_version="1.0.0",
            author=owner,
            tier=tier.value,
            title=title
        )

        typer.echo(f"✓ Created Tier {tier.value} spec at {output}")
        typer.echo(f"  Branch: {branch}")

        # Set as current if requested
        if set_current and config_path:
            if "current" not in cfg:
                cfg["current"] = {"spec": None, "aip": None}
            cfg["current"]["spec"] = str(output)
            save_config(config_path, cfg)
            typer.secho("✓ Set as current spec", fg=typer.colors.GREEN)
            typer.echo("  Next steps:")
            typer.echo("    1. Edit the spec")
            typer.echo("    2. Run: spec compile")
            typer.echo("    3. Run: spec validate")
        else:
            typer.echo("  Next steps:")
            typer.echo(f"    1. Edit {output}")
            typer.echo(f"    2. Run: spec compile {output}")
            typer.echo("    3. Run: spec validate <compiled-yaml>")


DEFAULT_MODEL = "gemini-3-pro-preview"


def _enrich_aip_with_seps(
    aip: dict[str, Any],
    aip_path: Path,
    model: str,
    no_llm: bool,
) -> dict[str, Any]:
    """
    Enrich all steps in AIP with Step Execution Plan (SEP) data.

    For each step, generates SEP using LLM (or deterministic if --no-llm)
    and embeds it directly in the AIP step.

    Args:
        aip: The parsed AIP dictionary
        aip_path: Path to write the updated AIP
        model: LLM model to use for generation
        no_llm: If True, use deterministic builder instead of LLM

    Returns:
        Updated AIP dictionary with enriched steps
    """
    from spec.executor.contract import build_contract
    from spec.executor.sep_builder import SEPBuilder

    plan = aip.get("plan", [])
    sep_builder = SEPBuilder()

    for step_idx, step in enumerate(plan):
        step_id = step.get("step_id", f"step-{step_idx + 1:03d}")
        typer.echo(f"  [{step_idx + 1}/{len(plan)}] {step_id}...", nl=False)

        # Build contract for this step (needed for SEP generation)
        contract = build_contract(aip, step_idx, autogov_policy=None, mode_override=None)

        if no_llm:
            sep = sep_builder.build(aip, step_idx, contract)
            typer.secho(" deterministic", fg=typer.colors.YELLOW)
        else:
            try:
                sep = sep_builder.build_with_llm(aip, step_idx, contract, model)
                if sep.provenance and sep.provenance.generator == "llm":
                    typer.secho(f" ✓ LLM ({sep.provenance.model})", fg=typer.colors.GREEN)
                else:
                    typer.secho(" deterministic (LLM fallback)", fg=typer.colors.YELLOW)
            except Exception as e:
                typer.secho(f" ✗ LLM failed: {e}", fg=typer.colors.RED)
                typer.echo(f"    Falling back to deterministic...")
                sep = sep_builder.build(aip, step_idx, contract)

        # Embed SEP data in AIP step
        aip["plan"][step_idx]["objective"] = sep.objective
        aip["plan"][step_idx]["files_to_touch"] = [
            {"path": fc.path, "action": fc.action, "description": fc.description or ""}
            for fc in sep.files_to_touch
        ]
        aip["plan"][step_idx]["verification_steps"] = [
            {"command": vs.command, "expected_outcome": vs.expected_outcome, "required": vs.required}
            for vs in sep.verification_steps
        ]
        if sep.provenance:
            aip["plan"][step_idx]["provenance"] = {
                "generator": sep.provenance.generator,
                "model": sep.provenance.model,
            }

    # Save enriched AIP
    with open(aip_path, "w") as f:
        yaml.dump(aip, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return aip


@app.command()
def compile(
    spec_path: Path | None = typer.Argument(None, help="Path to Markdown spec file (uses current spec if omitted)"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output YAML path (default: aips/<stem>.yaml)"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing compiled file"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM SEP enrichment, use placeholder SEPs only."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="LLM model for SEP generation."),
):
    """Compile Markdown spec to validated YAML AIP with LLM-enriched SEPs.

    By default, uses LLM to generate detailed Step Execution Plans (SEPs)
    for each step in the spec. Use --no-llm for placeholder-only mode.
    """
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
        # Default: specs/foo.md → aips/foo.yaml
        # Special-case repo-local specs under .specwright/specs to avoid writing to
        # the governor AIPs path (v0.6) when the user is clearly working repo-local.
        repo_local_specs = (project_root / ".specwright" / "specs").resolve()
        resolved_spec = spec_path.resolve()

        try:
            resolved_spec.relative_to(repo_local_specs)
            output = project_root / ".specwright" / "aips" / (spec_path.stem + ".yaml")
        except ValueError:
            aips_path = get_aips_path(cfg, project_root)
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
        typer.secho("✓ Validation passed", fg=typer.colors.GREEN)

        # ==== SEP ENRICHMENT ====
        # Enrich all steps with LLM-generated SEPs (or placeholders if --no-llm)
        plan = aip.get("plan", [])
        if plan:
            typer.echo(f"\nEnriching {len(plan)} step(s) with SEP data...")
            aip = _enrich_aip_with_seps(aip, output, model, no_llm)
            typer.secho(f"✓ SEP enrichment complete", fg=typer.colors.GREEN)

        # Log compilation to audit trail
        import hashlib

        from spec.audit.execution_logger import ExecutionAuditLogger

        # Calculate source hash
        with open(spec_path, 'rb') as f:
            source_hash = hashlib.sha256(f.read()).hexdigest()

        audit_logger = ExecutionAuditLogger()
        audit_logger.log_spec_compiled(
            aip_id=aip.get("aip_id", "unknown"),
            project_slug=aip.get("project_slug", "unknown"),
            spec_path=str(spec_path),
            aip_path=str(output),
            source_hash=f"sha256:{source_hash}",
            compiler_version="0.6.0"
        )

        # Update current AIP in config
        if config_path and "current" in cfg:
            cfg["current"]["aip"] = str(output)
            save_config(config_path, cfg)
            typer.echo("  Set as current AIP")

        typer.echo("  Next steps:")
        typer.echo("    1. Run: spec run")
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
            typer.secho("✓ Markdown parsed successfully", fg=typer.colors.GREEN)
        except (ValueError, KeyError, AttributeError) as e:
            typer.secho("\n✗ Markdown parsing failed:", fg=typer.colors.RED, bold=True, err=True)
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


# Exit code constants for autonomous mode
EXIT_PASS = 0
EXIT_FAIL = 1  # FAIL_* termination reasons
EXIT_ESCALATE = 2  # ESCALATE_* termination reasons
EXIT_NO_AIP = 3  # AIP not found or SEP not enriched


def _show_commit_suggestions(project_root: Path, step_def: dict, step_num: int) -> None:
    """
    Show git status and suggested commit commands after step completion.

    This does NOT auto-commit - it prints commands for the user to run.
    """
    import subprocess

    step_id = step_def.get("step_id") or step_def.get("id", f"step-{step_num:03d}")
    step_desc = step_def.get("description", "")

    typer.echo(f"\n{'='*60}")
    typer.secho("Review changes before committing:", bold=True)
    typer.echo(f"{'='*60}")

    # Get and display git status
    typer.echo("\nGit Status:")
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            status_output = result.stdout.strip()
            if status_output:
                for line in status_output.split("\n"):
                    typer.echo(f"  {line}")
            else:
                typer.echo("  (no changes)")
        else:
            typer.echo("  (could not get git status)")
    except FileNotFoundError:
        typer.echo("  (git not found)")

    # Build commit message
    commit_msg = f"spec: {step_id}"
    if step_desc:
        # Truncate description if too long
        desc_short = step_desc[:50] + "..." if len(step_desc) > 50 else step_desc
        commit_msg = f"spec: {step_id} - {desc_short}"

    # Display suggested commands
    typer.echo("\nSuggested commit commands:")
    typer.secho("  git add -A", fg=typer.colors.CYAN)
    typer.secho(f'  git commit -m "{commit_msg}"', fg=typer.colors.CYAN)
    typer.echo(f"{'='*60}")


def _update_step_summary_with_llm_verification(
    step_summary_path: Path,
    llm_verification: dict,
) -> None:
    """Update an existing step_summary.yaml with LLM verification results.

    Args:
        step_summary_path: Path to step_summary.yaml
        llm_verification: Dict with status, rationale, model
    """
    try:
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.preserve_quotes = True

        # Load existing summary
        with open(step_summary_path) as f:
            summary = yaml.load(f)

        if summary is None:
            summary = {}

        # Add llm_verification
        summary["llm_verification"] = llm_verification

        # Write back
        with open(step_summary_path, "w") as f:
            yaml.dump(summary, f)

    except Exception:
        # If ruamel.yaml fails, try stdlib yaml
        import yaml as pyyaml

        with open(step_summary_path) as f:
            summary = pyyaml.safe_load(f) or {}

        summary["llm_verification"] = llm_verification

        with open(step_summary_path, "w") as f:
            pyyaml.dump(summary, f, default_flow_style=False, sort_keys=False)


def _run_verify_only(run_dir_path: str, model: str | None) -> None:
    """Run LLM verification on existing artifacts without execution.

    Args:
        run_dir_path: Path to existing run directory
        model: LLM model alias (required)
    """
    from spec.llm.client import verify_patch_with_llm

    run_dir = Path(run_dir_path)

    # Validate inputs
    if model is None:
        typer.secho("Error: --verify-only requires --model", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if not run_dir.exists():
        typer.secho(f"Error: Run directory not found: {run_dir}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    # Find SEP file in input directory (AIP v2.0: SEP is written to input/ for adapters)
    sep_path = run_dir / "input" / "sep.yaml"
    if not sep_path.exists():
        typer.secho(f"Error: SEP file not found: {sep_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    # Find patch file (optional)
    patch_path = run_dir / "patch.diff"
    patch_content = None
    if patch_path.exists():
        patch_content = patch_path.read_text()

    typer.echo(f"{'='*60}")
    typer.secho("Verify-Only Mode", bold=True)
    typer.echo(f"{'='*60}")
    typer.echo(f"  Run directory: {run_dir}")
    typer.echo(f"  SEP: {sep_path}")
    typer.echo(f"  Patch: {'exists' if patch_content else 'not found'}")
    typer.echo(f"  Model: {model}")
    typer.echo()

    # Load SEP content
    sep_yaml_content = sep_path.read_text()

    # Run verification
    typer.echo("Running LLM patch verification...")
    llm_result = verify_patch_with_llm(sep_yaml_content, patch_content, model)

    # Display result
    typer.echo()
    if llm_result.status == "pass":
        typer.secho(f"  LLM Verification: ✓ PASS", fg=typer.colors.GREEN)
    elif llm_result.status == "skipped":
        typer.secho(f"  LLM Verification: ⊘ SKIPPED", fg=typer.colors.YELLOW)
    else:
        typer.secho(f"  LLM Verification: ✗ FAIL", fg=typer.colors.RED)

    # Show rationale (truncate if very long)
    rationale = llm_result.rationale
    if len(rationale) > 300:
        typer.echo(f"  Rationale: {rationale[:300]}...")
    else:
        typer.echo(f"  Rationale: {rationale}")
    typer.echo(f"  Model: {llm_result.model}")

    # Update step_summary.yaml
    step_summary_path = run_dir / "step_summary.yaml"
    if step_summary_path.exists():
        _update_step_summary_with_llm_verification(
            step_summary_path,
            {
                "status": llm_result.status,
                "rationale": llm_result.rationale,
                "model": llm_result.model,
            },
        )
        typer.echo(f"\n✓ Updated {step_summary_path}")
    else:
        typer.secho(f"\n⚠ step_summary.yaml not found, could not update", fg=typer.colors.YELLOW)

    typer.echo(f"{'='*60}")

    # Exit with appropriate code
    if llm_result.status == "pass":
        raise typer.Exit(EXIT_PASS)
    elif llm_result.status == "skipped":
        raise typer.Exit(EXIT_PASS)  # Skipped is not a failure
    else:
        raise typer.Exit(EXIT_FAIL)


def _run_autonomous_step(
    aip_path: Path,
    step_num: int,
    dry_run: bool,
    allow_dirty: bool,
    max_iterations: int,
    adapter: str,
    governance_bundle: Any = None,
    autogov_project: str | None = None,
    autogov_source: str | None = None,
    mode_override: str | None = None,
    skip_sep_review: bool = False,
    model: str | None = None,
) -> None:
    """
    Run a step autonomously with scope enforcement.

    SEP Workflow (AIP v2.0):
    1. Load pre-enriched SEP from AIP (generated during compile)
    2. If not --skip-sep-review: show SEP, prompt for continue
    3. Execute step

    For v0.6 governor config:
    - Auto-materializes AIP from governor if needed
    - Writes errors to local-governor on failure
    - Writes provenance to local-governor on completion
    - Cleans up materialized files after run

    Args:
        governance_bundle: Optional GovernanceBundle from autogov loader
        skip_sep_review: Skip SEP review gate

    Exit codes:
        0 = PASS (step completed successfully)
        1 = FAIL_* (scope violation, patch apply failure, verification failure, protocol error, dirty worktree)
        2 = ESCALATE_* (needs human review, ambiguous)
    """
    from datetime import datetime

    from spec.executor import StepRunner, TerminationReason
    from spec.executor.artifacts import get_artifact_root
    from spec.executor.contract import build_contract
    from spec.executor.sep import StepExecutionPlan, load_sep_from_aip

    # Get config
    config_path, cfg = find_config()
    project_root = config_path.parent if config_path else Path.cwd()

    # Governor integration setup
    materialized_path: Path | None = None
    governor_paths = None
    using_governor = not is_legacy_config(cfg)

    if using_governor:
        try:
            from spec.governor import GovernorLocator
            locator = GovernorLocator(config=cfg)
            if locator.exists():
                governor_paths = locator.find()
        except Exception as e:
            typer.echo(f"Warning: Could not access governor: {e}", err=True)
            governor_paths = None

    # Load AIP (may need to materialize from governor first)
    actual_aip_path = aip_path

    # If v0.6 config and AIP path doesn't exist locally, try to materialize from governor
    if using_governor and governor_paths and not aip_path.exists():
        aip_id = aip_path.stem  # Assume path is AIP ID
        try:
            from spec.governor import Materializer
            materializer = Materializer(governor_paths)
            materialized_path = materializer.materialize_aip(aip_id, project_root)
            actual_aip_path = materialized_path
            typer.echo(f"✓ Materialized {aip_id} from governor")
        except Exception as e:
            typer.echo(f"Error: Could not materialize AIP: {e}", err=True)
            raise typer.Exit(EXIT_FAIL)

    with open(actual_aip_path) as f:
        aip = yaml.safe_load(f)

    # AIP v2.0 version validation
    aip_version = aip.get("version", "0.1")
    if aip_version not in ("2.0", "0.1"):
        typer.echo(f"Error: Unsupported AIP version '{aip_version}'.", err=True)
        typer.echo("  Supported versions: 2.0, 0.1 (legacy)", err=True)
        raise typer.Exit(EXIT_FAIL)

    # Validate step number
    plan = aip.get("plan", [])
    if not plan:
        typer.echo("Error: No plan steps defined in AIP", err=True)
        raise typer.Exit(EXIT_FAIL)

    if step_num < 1 or step_num > len(plan):
        typer.echo(f"Error: Step {step_num} out of range (1-{len(plan)})", err=True)
        raise typer.Exit(EXIT_FAIL)

    # Convert to 0-based index
    step_idx = step_num - 1

    # Display step info
    step_def = plan[step_idx]

    # Claude adapter runs in interactive mode by default - force single iteration
    # (no auto-retry when human is babysitting)
    if adapter == "claude" and max_iterations > 1:
        max_iterations = 1

    aip_id = aip.get("aip_id", "unknown")
    step_id = step_def.get("step_id") or step_def.get("id") or f"step-{step_num:03d}"

    typer.echo(f"\n{'='*60}")
    typer.secho(f"Executing Step {step_num}/{len(plan)} (autonomous mode)", bold=True)
    typer.echo(f"  ID: {step_id}")
    typer.echo(f"  Adapter: {adapter}")
    if dry_run:
        typer.secho("  Mode: DRY RUN (preview only)", fg=typer.colors.YELLOW)
    typer.echo(f"{'='*60}\n")

    # Resolve artifact root (defaults to local-governor for v0.6 config)
    project_slug = cfg.get("project_slug") if cfg else None
    governor_path = None
    if governor_paths:
        governor_path = governor_paths.root
    runs_dir = get_artifact_root(
        project_slug=project_slug,
        governor_path=governor_path,
        project_root=project_root,
    )

    # Build governance context if bundle is available
    governance_context = None
    if governance_bundle is not None and autogov_project and autogov_source:
        from spec.autogov.context_builder import SpecContextBuilder
        context_builder = SpecContextBuilder()
        governance_context = context_builder.build_governance_context(
            bundle=governance_bundle,
            project=autogov_project,
            source=autogov_source,
        )

    # ==== SEP WORKFLOW (AIP v2.0) ====
    # SEP data must be pre-enriched in AIP steps during compile.
    # If not enriched, error out and point user to recompile.
    sep: StepExecutionPlan | None = None
    run_step_dir: Path | None = None

    # Build contract (needed for execution)
    autogov_policy = None
    if governance_context:
        autogov_policy = governance_context.get("autogov", {})

    contract = build_contract(aip, step_idx, autogov_policy, mode_override)

    # Check if AIP step has enriched SEP data (at step level, not nested)
    step_objective = step_def.get("objective", "")
    has_enriched_sep = (
        step_objective
        and len(step_objective) > 20  # More than just a stub
        and step_def.get("files_to_touch")  # Has files defined
    )

    if not has_enriched_sep:
        typer.secho(f"\n✗ Step {step_id} is missing enriched SEP data.", fg=typer.colors.RED, err=True)
        typer.echo("  SEPs are generated during compilation.", err=True)
        typer.echo("\nTo fix, recompile the spec:", err=True)
        typer.echo(f"  spec compile <your-spec.md>", err=True)
        typer.echo("\nOr use --no-llm for placeholder SEPs:", err=True)
        typer.echo(f"  spec compile <your-spec.md> --no-llm", err=True)
        raise typer.Exit(EXIT_NO_AIP)

    # Load existing SEP from AIP step
    sep = load_sep_from_aip(aip, step_idx)
    typer.secho(f"✓ Loaded SEP from AIP step {step_id}", fg=typer.colors.GREEN)
    typer.echo(f"  Objective: {sep.objective[:80]}..." if len(sep.objective) > 80 else f"  Objective: {sep.objective}")
    typer.echo(f"  Files to touch: {len(sep.files_to_touch)}")
    typer.echo(f"  Verification steps: {len(sep.verification_steps)}")

    # SEP review gate (unless --skip-sep-review)
    if not skip_sep_review:
        typer.echo(f"\n{'='*60}")
        typer.secho("SEP Review Gate", bold=True)
        typer.echo(f"{'='*60}")
        typer.echo(f"\nReview the SEP in AIP: {actual_aip_path} (step {step_id})")
        typer.echo("\nPlanned file changes:")
        for fc in sep.files_to_touch:
            typer.echo(f"  [{fc.action}] {fc.path}")
        typer.echo()

        import sys

        # In non-interactive contexts (tests/CI), prompting causes click.Abort.
        # Honor the default choice and continue.
        if sys.stdin is None or not sys.stdin.isatty():
            proceed = True
        else:
            proceed = typer.confirm("Continue with execution?", default=True)

        if not proceed:
            typer.secho("\nExecution cancelled by user.", fg=typer.colors.YELLOW)
            typer.echo(f"SEP embedded in AIP: {actual_aip_path}")
            typer.echo("\nTo resume later:")
            typer.echo(f"  spec run --step {step_num} {actual_aip_path}")
            raise typer.Exit(EXIT_PASS)

        # Create run directory for execution artifacts (not for SEP)
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        run_step_dir = runs_dir / aip_id / timestamp / step_id
        run_step_dir.mkdir(parents=True, exist_ok=True)

    # ==== EXECUTE STEP ====
    runner = StepRunner(repo_root=project_root, runs_dir=runs_dir, adapter_name=adapter)

    # Execute step
    result = runner.run_step(
        aip=aip,
        step_idx=step_idx,
        dry_run=dry_run,
        max_iterations=max_iterations,
        allow_dirty=allow_dirty,
        governance_context=governance_context,
        mode_override=mode_override,
        run_dir=run_step_dir,
        sep=sep,
    )

    # Display result
    typer.echo(f"\n{'='*60}")

    # Map termination reasons to display info and exit codes
    # INVARIANT: All TerminationReason values must be explicitly mapped here.
    # UPDATE THIS MAPPING when TerminationReason enum changes.
    reason_info: dict[TerminationReason, tuple[str, str, int]] = {
        # (label, color, exit_code)
        # Success
        TerminationReason.PASS: ("PASSED", typer.colors.GREEN, EXIT_PASS),
        # Failures -> exit code 1
        TerminationReason.FAIL_SCOPE: ("SCOPE VIOLATION", typer.colors.RED, EXIT_FAIL),
        TerminationReason.FAIL_PATCH_APPLY: ("PATCH APPLY FAILED", typer.colors.RED, EXIT_FAIL),
        TerminationReason.FAIL_VERIFY_RETRYABLE: ("VERIFICATION FAILED (max retries)", typer.colors.RED, EXIT_FAIL),
        TerminationReason.FAIL_ADAPTER_PROTOCOL: ("ADAPTER PROTOCOL ERROR", typer.colors.RED, EXIT_FAIL),
        TerminationReason.FAIL_DIRTY_WORKTREE: ("DIRTY WORKTREE", typer.colors.RED, EXIT_FAIL),
        TerminationReason.GATE_REJECTED: ("GATE REJECTED", typer.colors.RED, EXIT_FAIL),
        # Escalations -> exit code 2
        TerminationReason.ESCALATE_NEEDS_HUMAN: ("NEEDS HUMAN REVIEW", typer.colors.YELLOW, EXIT_ESCALATE),
        TerminationReason.ESCALATE_AMBIGUOUS: ("AMBIGUOUS (needs input)", typer.colors.YELLOW, EXIT_ESCALATE),
        TerminationReason.GATE_DEFERRED: ("GATE DEFERRED", typer.colors.YELLOW, EXIT_ESCALATE),
    }

    info = reason_info.get(result.termination_reason)
    if info:
        label, color, exit_code = info
        symbol = "✓" if exit_code == EXIT_PASS else ("⚠" if exit_code == EXIT_ESCALATE else "✗")
        typer.secho(f"Result: {symbol} {label}", fg=color, bold=True)
    else:
        label = result.termination_reason.value
        exit_code = EXIT_FAIL
        typer.secho(f"Result: ? {label}", bold=True)

    if result.error:
        typer.echo(f"  Error: {result.error}")

    typer.echo(f"  Iterations: {len(result.iterations)}")
    if result.touched_files:
        typer.echo(f"  Files touched: {len(result.touched_files)}")

    if result.artifacts_dir:
        typer.echo(f"  Artifacts: {runs_dir / result.artifacts_dir}/")

    # SEP is now embedded in AIP (v2.0) - show input path if it exists
    if run_step_dir:
        input_sep_path = run_step_dir / "input" / "sep.yaml"
        if input_sep_path.exists():
            typer.echo(f"  SEP: {input_sep_path}")

    typer.echo(f"{'='*60}")

    # ==== LLM VERIFICATION ====
    # If --model was provided and not dry_run, run LLM verification on patch
    if model is not None and not dry_run:
        from spec.llm.client import verify_patch_with_llm

        typer.echo("\nRunning LLM patch verification...")

        # Load SEP and patch content
        sep_yaml_content = ""
        patch_content = None
        patch_path = run_step_dir / "patch.diff"

        # SEP is now at input/sep.yaml (written by runner for adapter)
        input_sep_path = run_step_dir / "input" / "sep.yaml"
        if input_sep_path.exists():
            sep_yaml_content = input_sep_path.read_text()
        if patch_path.exists():
            patch_content = patch_path.read_text()

        # Run verification
        llm_result = verify_patch_with_llm(sep_yaml_content, patch_content, model)

        # Display result
        if llm_result.status == "pass":
            typer.secho(f"  LLM Verification: ✓ PASS", fg=typer.colors.GREEN)
        elif llm_result.status == "skipped":
            typer.secho(f"  LLM Verification: ⊘ SKIPPED", fg=typer.colors.YELLOW)
        else:
            typer.secho(f"  LLM Verification: ✗ FAIL", fg=typer.colors.RED)
        typer.echo(f"  Rationale: {llm_result.rationale[:200]}..." if len(llm_result.rationale) > 200 else f"  Rationale: {llm_result.rationale}")
        typer.echo(f"  Model: {llm_result.model}")

        # Update step_summary.yaml with llm_verification
        step_summary_path = run_step_dir / "step_summary.yaml"
        if step_summary_path.exists():
            _update_step_summary_with_llm_verification(
                step_summary_path,
                {
                    "status": llm_result.status,
                    "rationale": llm_result.rationale,
                    "model": llm_result.model,
                },
            )

    # Show dry run command
    if dry_run and result.dry_run_command:
        typer.echo(f"\nDry run command:\n  {result.dry_run_command}")

    # Show gate package path
    if result.artifacts_dir:
        gate_path = runs_dir / result.artifacts_dir / "gate.md"
        if gate_path.exists():
            typer.echo(f"\nGate package: {gate_path}")
            typer.echo("  Review and approve before committing changes.")

    # Final message based on result
    if exit_code == EXIT_PASS:
        if not dry_run:
            typer.secho("\n✓ Step completed successfully.", fg=typer.colors.GREEN)
            # Show git status and suggested commit commands
            _show_commit_suggestions(project_root, step_def, step_num)
    elif exit_code == EXIT_ESCALATE:
        typer.secho("\n⚠ Step requires human review.", fg=typer.colors.YELLOW)
    else:
        typer.secho("\n✗ Step failed.", fg=typer.colors.RED)

    # Governor integration: write errors/provenance and cleanup
    if using_governor and governor_paths and not dry_run:
        aip_id = aip.get("aip_id", "unknown")
        repo_name = project_root.name

        try:
            from spec.governor import GovernorWriter
            from spec.governor.provenance import ProvenanceSnapshot, RunStatus

            writer = GovernorWriter(governor_paths)

            # Write error record on failure
            if exit_code == EXIT_FAIL and result.error:
                from spec.governor.errors import ErrorRecord, ErrorType

                # Map termination reason to error type
                error_type_map = {
                    TerminationReason.FAIL_SCOPE: ErrorType.FAIL_SCOPE,
                    TerminationReason.FAIL_PATCH_APPLY: ErrorType.FAIL_PATCH_APPLY,
                    TerminationReason.FAIL_VERIFY_RETRYABLE: ErrorType.FAIL_VERIFY_RETRYABLE,
                    TerminationReason.FAIL_ADAPTER_PROTOCOL: ErrorType.FAIL_ADAPTER_PROTOCOL,
                    TerminationReason.FAIL_DIRTY_WORKTREE: ErrorType.FAIL_DIRTY_WORKTREE,
                    TerminationReason.GATE_REJECTED: ErrorType.GATE_REJECTED,
                }
                error_type = error_type_map.get(result.termination_reason, ErrorType.GOVERNOR_ERROR)

                error_record = ErrorRecord(
                    error_id=f"ERR-{datetime.now().strftime('%Y-%m-%d')}-{step_num:03d}",
                    error_type=error_type,
                    message=result.error,
                    timestamp=datetime.now(),
                    repo=repo_name,
                    aip_ref=f"aips/{aip_id}.yaml",
                    step=step_num,
                )
                error_path = writer.write_error(error_record)
                typer.echo(f"✓ Error recorded to governor: {error_path.name}")

            # Write provenance on completion (success or failure)
            run_status = RunStatus.COMPLETED if exit_code == EXIT_PASS else RunStatus.FAILED
            provenance = ProvenanceSnapshot(
                run_id=f"RUN-{datetime.now().strftime('%Y-%m-%d')}-{step_num:03d}",
                aip_ref=f"aips/{aip_id}.yaml",
                repo=repo_name,
                started_at=datetime.now(),  # Approximate
                status=run_status,
                steps_executed=[step_num],
            )
            prov_path = writer.write_provenance(provenance)
            typer.echo(f"✓ Provenance recorded to governor: {prov_path.name}")

        except Exception as e:
            typer.echo(f"Warning: Could not write to governor: {e}", err=True)

        # Cleanup materialized files
        if materialized_path and materialized_path.exists():
            try:
                from spec.governor import Materializer
                materializer = Materializer(governor_paths)
                count = materializer.cleanup(project_root)
                if count > 0:
                    typer.echo(f"✓ Cleaned up {count} materialized file(s)")
            except Exception as e:
                typer.echo(f"Warning: Could not cleanup materialized files: {e}", err=True)

    raise typer.Exit(exit_code)


@app.command()
@_specwright_exception_handler
def run(
    aip_path: Path | None = typer.Argument(None, help="Path to AIP YAML file (uses current AIP if omitted)"),
    step: int | None = typer.Option(None, "--step", "-s", help="Run specific step autonomously (1-based). Without this flag, runs interactive HITL mode."),
    skip_gates: bool = typer.Option(False, "--skip-gates", help="Skip gate approvals (governance override, HITL mode only)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Write input bundle only, don't execute (autonomous mode only)"),
    allow_dirty: bool = typer.Option(False, "--allow-dirty", help="Allow execution with dirty working tree (autonomous mode only)"),
    max_iterations: int = typer.Option(3, "--max-iterations", "-m", help="Maximum retry iterations (autonomous mode only)"),
    adapter: str = typer.Option("claude", "--adapter", help="Agent adapter to use (autonomous mode only)"),
    mode: str | None = typer.Option(None, "--mode", "-M", help="Adapter mode: 'oneshot' (headless, constrained) or 'interactive' (TUI). Default: oneshot."),
    autogov_project: str | None = typer.Option(None, "--autogov", help="Autogov project name (required when autogov.enabled: true)"),
    skip_sep_review: bool = typer.Option(
        False,
        "--skip-sep-review",
        help="Skip SEP review gate (use with caution).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="LLM model for post-execution verification (e.g., gpt-4o, claude-sonnet).",
    ),
    verify_only: str | None = typer.Option(
        None,
        "--verify-only",
        help="Path to existing run directory. Re-runs LLM verification on existing artifacts without execution. Requires --model.",
    ),
):
    """Run an AIP - either in interactive HITL mode or autonomous step execution.

    Without --step: Interactive human-in-the-loop mode with gate approvals.
    With --step N: Autonomous execution of step N with scope enforcement.

    NOTE: SEPs must be pre-generated via 'spec compile'. Use 'spec compile --no-llm'
    for placeholder-only mode if LLM enrichment is not desired.

    Autonomous mode (--step N):
        Executes the full step lifecycle:
        1. Load pre-enriched SEP from AIP (generated during compile)
        2. Run agent (Claude by default)
        3. Apply patch
        4. Check scope violations
        5. Run verification commands
        6. Retry on verification failure (up to --max-iterations)
        7. Write gate package for human review

        Exit codes:
            0 = PASS (step completed successfully)
            1 = FAIL (scope violation, patch failure, verification failure, protocol error, gate rejected)
            2 = ESCALATE (needs human review, ambiguous input, gate deferred)

    Examples:
        spec run                       # Interactive HITL mode
        spec run --step 1              # Execute step 1 autonomously
        spec run --step 1 --dry-run    # Preview what would be executed
        spec run --step 2 --allow-dirty --max-iterations 5
    """
    from spec.audit import GateAuditLogger
    from spec.autogov.exceptions import CLIUsageError, RegistryConfigError
    from spec.cli.interactive import (
        confirm_gate_override,
        display_approval_summary,
        display_gate_checkpoint,
        display_step_details,
        prompt_approval_decision,
        prompt_checklist_completion,
        show_gate_checklist,
    )

    # ==== VERIFY-ONLY MODE ====
    # Handle --verify-only before any other processing
    if verify_only is not None:
        _run_verify_only(verify_only, model)
        return  # _run_verify_only exits via typer.Exit

    # Get config
    config_path, cfg = find_config()

    # Check autogov configuration and load governance ONCE at run() level
    autogov_cfg = cfg.get("autogov", {})
    autogov_enabled = autogov_cfg.get("enabled", False)
    governance_bundle = None

    if autogov_enabled:
        # Validate config has source
        if "source" not in autogov_cfg:
            raise RegistryConfigError(
                "Missing autogov.source in .specwright.yaml. "
                "Add 'autogov.source: org' or 'autogov.source: patterns' to your config."
            )
        # Require --autogov flag when enabled
        if not autogov_project:
            raise CLIUsageError(
                "--autogov is required when autogov.enabled: true in .specwright.yaml. "
                "Use: spec run --autogov <project-name> --step <N>"
            )
        # Load governance (lazy import, exceptions bubble up to handler)
        from spec.autogov.loader import GovernanceLoader
        loader = GovernanceLoader()
        governance_bundle = loader.load_all(autogov_project, autogov_cfg["source"])

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

    # Validate mode if provided
    if mode is not None and mode not in ("oneshot", "interactive"):
        typer.echo(f"Error: Invalid mode '{mode}'. Must be 'oneshot' or 'interactive'.", err=True)
        raise typer.Exit(1)

    # AUTONOMOUS MODE: --step N provided
    if step is not None:
        kwargs: dict[str, Any] = {
            "aip_path": aip_path,
            "step_num": step,
            "dry_run": dry_run,
            "allow_dirty": allow_dirty,
            "max_iterations": max_iterations,
            "adapter": adapter,
            "governance_bundle": governance_bundle,
            "autogov_project": autogov_project,
            "autogov_source": autogov_cfg.get("source") if autogov_enabled else None,
        }

        # Optional flags
        if skip_sep_review:
            kwargs["skip_sep_review"] = skip_sep_review
        if model is not None:
            kwargs["model"] = model

        # Backward-compatible: only pass mode_override when explicitly set.
        if mode is not None:
            kwargs["mode_override"] = mode

        _run_autonomous_step(**kwargs)
        return  # Never reached due to typer.Exit in _run_autonomous_step

    # INTERACTIVE HITL MODE: no --step flag
    # Warn if autonomous-only flags are used
    if dry_run or allow_dirty or max_iterations != 3 or adapter != "claude":
        typer.echo("Warning: --dry-run, --allow-dirty, --max-iterations, and --adapter are ignored in interactive mode.", err=True)
        typer.echo("  Use --step N to run in autonomous mode.", err=True)
        typer.echo()

    # Load AIP
    with open(aip_path) as f:
        aip = yaml.safe_load(f)

    # Get tier for gate behavior
    tier = aip.get("tier", "C")

    # Initialize audit loggers
    aip_id = aip.get("aip_id", "unknown")
    project_slug = aip.get("project_slug", "unknown")
    artifacts_dir = aip.get("orchestrator_contract", {}).get("artifacts_dir", f".aip_artifacts/{aip_id}")
    audit_logger = GateAuditLogger(aip_id, artifacts_dir)

    # Log execution start to execution history
    from spec.audit.execution_logger import ExecutionAuditLogger
    exec_logger = ExecutionAuditLogger()
    git_snapshot = exec_logger.log_execution_started(
        aip_id=aip_id,
        project_slug=project_slug,
        executor=cfg.get("user", {}).get("default_owner", "unknown"),
        aip_path=str(aip_path)
    )

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
        typer.echo("\n✅ Acceptance Criteria:")
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
                typer.echo("\n📝 [Tier C] Gate auto-approved (checklist logged)")
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
                        typer.secho("\n⚠️  Gate CONDITIONALLY APPROVED", fg=typer.colors.YELLOW)
                        typer.echo(f"   Conditions: {approval.get('conditions', '')}")
                    else:
                        typer.secho("\n✅ Gate APPROVED", fg=typer.colors.GREEN)
                    typer.echo("   Proceeding to next step...")

    # Log execution completion
    exec_logger.log_execution_completed(
        aip_id=aip_id,
        project_slug=project_slug,
        status="success",
        start_git_commit=git_snapshot.get("commit"),
        artifacts_path=artifacts_dir
    )

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
        decision = approval.get("decision", "unknown")
        typer.secho(f"  Decision: {decision.upper()}", fg=color)
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
        typer.echo("\nBy Gate:")
        for gate_ref, stats in summary["by_gate"].items():
            typer.echo(f"\n  {gate_ref}:")
            typer.echo(f"    Total: {stats['total']}")
            typer.echo(f"    Approved: {stats['approved']}")
            typer.echo(f"    Rejected: {stats['rejected']}")
            typer.echo(f"    Deferred: {stats['deferred']}")
            typer.echo(f"    Conditional: {stats['conditional']}")

    typer.echo()


@app.command()
def materialize(
    aip_id: str = typer.Argument(..., help="AIP ID to materialize from governor"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output directory (default: .specwright/tmp/)"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing materialized file"),
):
    """Materialize an AIP from local-governor to repo workspace.

    Copies the AIP from governor storage to the local repo's .specwright/tmp/
    directory for execution.

    Examples:
        spec materialize AIP-project-2025-12-22-001
        spec materialize AIP-001 --output ./custom-path/
        spec materialize AIP-001 --force
    """
    from spec.governor import GovernorLocator, Materializer
    from spec.governor.locator import GovernorNotFoundError, GovernorValidationError

    # Get config
    config_path, cfg = find_config()
    project_root = config_path.parent if config_path else Path.cwd()

    # Find governor
    try:
        locator = GovernorLocator(cfg)
        paths = locator.find()
    except GovernorNotFoundError as e:
        typer.secho("Error: " + str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except GovernorValidationError as e:
        typer.secho("Error: " + str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    # Materialize AIP
    materializer = Materializer(paths)

    target_repo = output.parent if output else project_root

    try:
        aip_path = materializer.materialize_aip(aip_id, target_repo, force=force)
        typer.secho(f"✓ Materialized {aip_id} to {aip_path}", fg=typer.colors.GREEN)
        typer.echo("  Ready for execution with: spec run")
    except FileNotFoundError:
        typer.secho(f"Error: AIP '{aip_id}' not found in governor", fg=typer.colors.RED, err=True)
        typer.echo("  Available AIPs:", err=True)
        from spec.governor import GovernorReader
        reader = GovernorReader(paths)
        for aid in reader.list_aips()[:10]:
            typer.echo(f"    - {aid}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def migrate(
    from_repo: bool = typer.Option(False, "--from-repo", help="Migrate repo-local specs/AIPs to governor"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be migrated without making changes"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files in governor"),
):
    """Migrate from legacy repo-local specs to governor model.

    Moves specs and AIPs from .specwright/specs/ and .specwright/aips/
    to local-governor, and updates .specwright.yaml to v0.6 format.

    Examples:
        spec migrate --from-repo --dry-run    # Preview migration
        spec migrate --from-repo               # Execute migration
        spec migrate --from-repo --force       # Overwrite existing in governor
    """
    from spec.governor import GovernorLocator, GovernorReader, GovernorWriter
    from spec.governor.locator import GovernorNotFoundError

    if not from_repo:
        typer.echo("Error: Please specify --from-repo to migrate from repo-local to governor", err=True)
        typer.echo("  Usage: spec migrate --from-repo", err=True)
        raise typer.Exit(1)

    # Get config
    config_path, cfg = find_config()
    if not config_path:
        typer.echo("Error: No .specwright.yaml found. Nothing to migrate.", err=True)
        raise typer.Exit(1)

    project_root = config_path.parent

    # Check for legacy specs/aips directories
    specs_dir = project_root / cfg.get("paths", {}).get("specs", ".specwright/specs")
    aips_dir = project_root / cfg.get("paths", {}).get("aips", ".specwright/aips")

    if not specs_dir.is_absolute():
        specs_dir = project_root / specs_dir
    if not aips_dir.is_absolute():
        aips_dir = project_root / aips_dir

    specs_to_migrate = list(specs_dir.glob("*.md")) if specs_dir.exists() else []
    aips_to_migrate = list(aips_dir.glob("*.yaml")) if aips_dir.exists() else []

    if not specs_to_migrate and not aips_to_migrate:
        typer.echo("No specs or AIPs found to migrate.")
        raise typer.Exit(0)

    # Find governor
    try:
        locator = GovernorLocator(cfg)
        paths = locator.find()
    except GovernorNotFoundError:
        typer.secho("Error: local-governor not found.", fg=typer.colors.RED, err=True)
        typer.echo("  Run 'governor init' to create local-governor first.", err=True)
        raise typer.Exit(1)

    reader = GovernorReader(paths)
    writer = GovernorWriter(paths)

    typer.echo(f"\n{'='*60}")
    typer.secho("Migration Preview" if dry_run else "Migrating", bold=True)
    typer.echo(f"{'='*60}\n")

    typer.echo(f"Source: {project_root}")
    typer.echo(f"Target: {paths.root}\n")

    migrated_specs = 0
    migrated_aips = 0
    skipped = 0

    # Migrate specs
    if specs_to_migrate:
        typer.secho("Specs:", bold=True)
        for spec_path in specs_to_migrate:
            slug = spec_path.stem

            if reader.spec_exists(slug) and not force:
                typer.echo(f"  ⏭  {slug}.md (already exists, use --force)")
                skipped += 1
            else:
                typer.echo(f"  → {slug}.md")
                if not dry_run:
                    content = spec_path.read_text()
                    writer.write_spec(slug, content)
                    migrated_specs += 1
        typer.echo()

    # Migrate AIPs
    if aips_to_migrate:
        typer.secho("AIPs:", bold=True)
        for aip_path in aips_to_migrate:
            aip_id = aip_path.stem

            if reader.aip_exists(aip_id) and not force:
                typer.echo(f"  ⏭  {aip_id}.yaml (already exists, use --force)")
                skipped += 1
            else:
                typer.echo(f"  → {aip_id}.yaml")
                if not dry_run:
                    with open(aip_path) as f:
                        aip = yaml.safe_load(f)
                    writer.write_aip(aip_id, aip)
                    migrated_aips += 1
        typer.echo()

    # Update config to v0.6
    if not dry_run and (migrated_specs > 0 or migrated_aips > 0):
        new_config = {
            "version": "0.6",
            "governor": {
                "path": str(paths.root),
            },
        }
        if cfg.get("autogov", {}).get("enabled"):
            new_config["autogov"] = cfg["autogov"]

        save_config(config_path, new_config)
        typer.secho("✓ Updated .specwright.yaml to v0.6 format", fg=typer.colors.GREEN)

        # Create tmp directory
        tmp_dir = project_root / ".specwright" / "tmp"
        tmp_dir.mkdir(exist_ok=True)
        typer.secho(f"✓ Created {tmp_dir}", fg=typer.colors.GREEN)

    # Summary
    typer.echo(f"\n{'='*60}")
    if dry_run:
        typer.secho("Dry Run Summary:", bold=True)
        typer.echo(f"  Specs to migrate: {len(specs_to_migrate) - skipped}")
        typer.echo(f"  AIPs to migrate: {len(aips_to_migrate)}")
        typer.echo(f"  Would skip: {skipped}")
        typer.echo("\nRun without --dry-run to execute migration.")
    else:
        typer.secho("Migration Complete:", bold=True)
        typer.echo(f"  Specs migrated: {migrated_specs}")
        typer.echo(f"  AIPs migrated: {migrated_aips}")
        typer.echo(f"  Skipped: {skipped}")

    typer.echo(f"{'='*60}\n")


@app.command("list")
def list_specs(
    specs: bool = typer.Option(True, "--specs/--no-specs", help="List specs"),
    aips: bool = typer.Option(True, "--aips/--no-aips", help="List AIPs"),
):
    """List specs and AIPs in local-governor.

    Examples:
        spec list              # List both specs and AIPs
        spec list --no-aips    # List only specs
        spec list --no-specs   # List only AIPs
    """
    from spec.governor import GovernorLocator, GovernorReader
    from spec.governor.locator import GovernorNotFoundError, GovernorValidationError

    # Get config
    _, cfg = find_config()

    # Find governor
    try:
        locator = GovernorLocator(cfg)
        paths = locator.find()
    except (GovernorNotFoundError, GovernorValidationError) as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    reader = GovernorReader(paths)

    if specs:
        spec_list = reader.list_specs()
        typer.secho(f"\nSpecs ({len(spec_list)}):", bold=True)
        if spec_list:
            for slug in spec_list:
                typer.echo(f"  - {slug}")
        else:
            typer.echo("  (none)")

    if aips:
        aip_list = reader.list_aips()
        typer.secho(f"\nAIPs ({len(aip_list)}):", bold=True)
        if aip_list:
            for aip_id in aip_list:
                typer.echo(f"  - {aip_id}")
        else:
            typer.echo("  (none)")

    typer.echo()


if __name__ == "__main__":
    app()
