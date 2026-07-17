"""CLI for Specwright: create, validate, and run Agentic Implementation Plans."""

import functools
from pathlib import Path

import typer
import yaml  # type: ignore[import]

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

# Register validate as a Typer subgroup (supports subcommands: spec, build, epic, contracts)
# The validate group preserves legacy `spec validate <file.yaml/.md>` behavior.
from spec.cli.governance import validate_app  # noqa: E402

app.add_typer(validate_app, name="validate")

# Register spec finish as a top-level command (lifecycle, not validation)
from spec.cli.finish import finish_command  # noqa: E402

app.command("finish")(finish_command)

# Register spec delta subcommand group (build delta management)
from spec.cli.delta import delta_app  # noqa: E402

app.add_typer(delta_app, name="delta")


def get_default_config() -> dict:
    """Get default Specwright configuration (v0.7 format)."""
    return {
        "version": "0.7",
        "governor": {
            "path": "~/.local/local-governor"
        },
        "jobdefs": {
            "path": "~/.local/local-governor/jobdefs/specwright",
            "fallback": "bundled",
        },
        "defaults": {
            "jobs": {
                "headless": "aip-1",
                "interactive": "interactive-1",
            }
        },
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


def get_user_default(cfg: dict, key: str) -> str | None:
    """Get user default value from config.

    Supports legacy v0.1 format (user.default_owner) and
    newer formats where this may not be stored.
    """
    # v0.1 legacy: user.default_owner, user.default_tier
    if "user" in cfg:
        return cfg.get("user", {}).get(key)
    return None


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
    claude: bool = typer.Option(True, "--claude/--no-claude", help="Install Claude Code slash commands"),
    governor_path: str | None = typer.Option(None, "--governor", help="Custom local-governor path"),
):
    """Initialize Specwright configuration.

    Creates .specwright.yaml with governor path and installs JobDefs.

    Examples:
        spec init
        spec init --governor /custom/path
        spec init --no-claude
    """
    config_path = Path.cwd() / ".specwright.yaml"

    if config_path.exists() and not force:
        typer.echo(f"Error: {config_path} already exists", err=True)
        typer.echo("  Use --force to overwrite", err=True)
        raise typer.Exit(1)

    # Get minimal config
    config = get_default_config()

    # Set custom governor path if provided
    if governor_path:
        config["governor"]["path"] = governor_path
        config["jobdefs"]["path"] = f"{governor_path}/jobdefs/specwright"

    with open(config_path, "w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)

    typer.secho(f"✓ Created {config_path}", fg=typer.colors.GREEN)

    # Install default JobDefs to local-governor
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

    # Copy Claude Code slash commands if requested
    if claude:
        _install_slash_commands()

    typer.echo("\n  You can now use spec commands from anywhere in this project")


def _install_slash_commands() -> None:
    """Install Claude Code slash commands to .claude/commands/."""
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


@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
):
    """Show Specwright configuration.

    Examples:
        spec config --show    # Show current config
        spec config           # Same as --show
    """
    config_path, cfg = find_config()

    if not config_path:
        typer.echo("No .specwright.yaml found. Run 'spec init' first.")
        typer.echo("\nUsing defaults:")
        typer.echo(yaml.dump(get_default_config(), sort_keys=False, default_flow_style=False))
        return

    typer.echo(f"Configuration: {config_path}\n")
    typer.echo(yaml.dump(cfg, sort_keys=False, default_flow_style=False))


# =============================================================================
if __name__ == "__main__":
    app()
