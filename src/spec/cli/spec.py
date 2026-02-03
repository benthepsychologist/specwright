"""CLI for Specwright: create, validate, and run Agentic Implementation Plans."""

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

import typer
import yaml  # type: ignore[import]

try:
    from importlib.resources import files  # type: ignore[attr-defined,no-redef]
except ImportError:
    from importlib_resources import files  # type: ignore[import-untyped,no-redef,import-not-found]

import functools

from spec.core.exceptions import SpecwrightError


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
from spec.cli.epic import epic_app  # noqa: E402

app.add_typer(epic_app, name="epic")

# Register v2 executor commands at top level (per e008-05 spec)
from spec.cli.exec_commands import (  # noqa: E402
    compile_command,
    execute_command,
    logs_command,
    run_command,
    status_command,
)

app.command("compile")(compile_command)
app.command("execute")(execute_command)
app.command("run")(run_command)
app.command("status")(status_command)
app.command("logs")(logs_command)

# Register validate as a Typer subgroup (supports subcommands: build, epic, contracts)
# The callback handles the existing `spec validate <file.md>` behavior
from spec.cli.governance import validate_app  # noqa: E402

app.add_typer(validate_app, name="validate")

# Register spec finish as a top-level command (lifecycle, not validation)
from spec.cli.finish import finish_command  # noqa: E402

app.command("finish")(finish_command)

# Register spec delta subcommand group (build delta management)
from spec.cli.delta import delta_app  # noqa: E402

app.add_typer(delta_app, name="delta")


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
    legacy_mode: bool = typer.Option(False, "--legacy-mode", help="Use legacy v0.1 repo-local config (deprecated)"),
    governor_path: str | None = typer.Option(None, "--governor", help="Custom local-governor path"),
):
    """Initialize Specwright configuration in current directory.

    Examples:
        spec init                    # v0.6 minimal config (governor-based)
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

    # Install default JobDefs to local-governor
    if not legacy_mode:
        try:
            from spec.executor.jobdefs import get_jobdefs_dir, install_default_jobdefs

            gov_path = Path(governor_path).expanduser() if governor_path else None
            installed = install_default_jobdefs(gov_path, overwrite=force)
            jobdefs_dir = get_jobdefs_dir(gov_path)

            if installed:
                typer.echo(f"✓ Installed {len(installed)} JobDefs to {jobdefs_dir}")
                for path in installed:
                    typer.echo(f"    - {path.name}")
            else:
                typer.echo(f"✓ JobDefs already installed at {jobdefs_dir}")
                typer.echo("    Use --force to overwrite")
        except Exception as e:
            typer.echo(f"  Warning: Could not install JobDefs: {e}", err=True)

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
):
    """Create a new spec from template (Markdown by default, YAML with --yaml flag).

    Examples:
        spec create "Add User Avatars"                                   # Uses defaults
        spec create "Add User Avatars" --tier C --goal "Allow profile pictures"
        spec create "Refactor Auth" --set-current
    """
    # Get config
    config_path, cfg = find_config()
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


@app.command("spec-compile")
def spec_compile(
    spec_path: Path | None = typer.Argument(None, help="Path to Markdown spec file (uses current spec if omitted)"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output YAML path (default: aips/<stem>.yaml)"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing compiled file"),
):
    """Compile Markdown spec to validated YAML AIP (v1 authoring command).

    This converts a Markdown spec file to a validated YAML AIP format.
    For v2 executor JobInstance compilation, use 'spec compile'.
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


# Note: validate command is registered from exec_commands.validate_command above


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


# =============================================================================
if __name__ == "__main__":
    app()
