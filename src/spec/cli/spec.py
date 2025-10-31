"""CLI for Specwright: create, validate, and run Agentic Implementation Plans."""

from pathlib import Path
from typing import Optional
import yaml  # type: ignore[import]
import typer
from datetime import datetime
from enum import Enum
import json

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


@app.command()
def create(
    tier: RiskTier = typer.Option(..., "--tier", "-t", help="Risk tier (A/B/C)"),
    title: str = typer.Option(..., "--title", help="AIP title"),
    goal: str = typer.Option(..., "--goal", "-g", help="Objective (what are we building?)"),
    owner: str = typer.Option(..., "--owner", help="GitHub username or team"),
    branch: Optional[str] = typer.Option(None, "--branch", "-b", help="Working branch name"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path (default: aips/<slugified-title>.yaml)"),
):
    """Create a new AIP from a tier template."""
    
    # Generate AIP ID
    aip_id = get_next_aip_id()
    
    # Generate output path from title if not provided
    if output is None:
        slug = slugify(title)
        output = Path("aips") / f"{slug}.yaml"
    
    # Generate branch name if not provided
    if branch is None:
        branch = "feat/" + slugify(title)
    
    # Load template (look in config/ directory relative to project root)
    project_root = Path.cwd()
    template_path = project_root / "config" / "templates" / "aips" / f"tier-{tier.value.lower()}-template.yaml"
    
    if not template_path.exists():
        typer.echo(f"Error: Template not found at {template_path}", err=True)
        raise typer.Exit(1)
    
    with open(template_path) as f:
        aip = yaml.safe_load(f)
    
    # Replace all PLACEHOLDER values
    aip["aip_id"] = aip_id
    aip["title"] = title
    aip["tier"] = tier.value
    aip["objective"]["goal"] = goal
    aip["repo"]["url"] = get_git_remote_url()
    aip["repo"]["working_branch"] = branch
    aip["orchestrator_contract"]["artifacts_dir"] = f".aip_artifacts/{aip_id}"
    aip["pull_request"]["title"] = f"[{aip_id}] {title}"
    
    # Add metadata
    aip["meta"] = {
        "created_by": owner,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    
    # Write to output
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        yaml.dump(aip, f, sort_keys=False, default_flow_style=False)
    
    typer.echo(f"✓ Created Tier {tier.value} AIP at {output}")
    typer.echo(f"  AIP ID: {aip_id}")
    typer.echo(f"  Branch: {branch}")
    typer.echo(f"  Next steps:")
    typer.echo(f"    1. Edit {output} to refine acceptance criteria and plan steps")
    typer.echo(f"    2. Run: spec validate {output}")
    typer.echo(f"    3. Run: spec run {output}")


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
    
    import json
    with open(schema_path) as f:
        schema = json.load(f)
    
    # Validate
    try:
        from jsonschema import validate, ValidationError  # type: ignore[import]
        validate(instance=aip, schema=schema)
        typer.echo(f"✓ {aip_path} is valid")
    except Exception as e:
        # Check if it's a ValidationError
        if type(e).__name__ == "ValidationError":
            typer.echo(f"✗ Validation failed:", err=True)
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
    step: Optional[int] = typer.Option(None, "--step", "-s", help="Run specific step number (1-based)"),
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
            typer.echo(f"\n  Commands:")
            for cmd in step_def["commands"]:
                typer.echo(f"    $ {cmd}")
        
        # Show outputs if present
        if step_def.get("outputs"):
            typer.echo(f"\n  Expected outputs:")
            for out in step_def["outputs"]:
                typer.echo(f"    - {out}")
        
        # Simple execution (just pause and confirm)
        typer.echo()
        if typer.confirm("  Mark as complete?", default=True):
            typer.echo(f"  ✓ Step completed\n")
        else:
            typer.echo(f"  ⏭  Skipped\n")
    
    typer.echo(f"{'='*60}")
    typer.echo(f"✓ AIP execution complete")
    typer.echo(f"{'='*60}\n")


if __name__ == "__main__":
    app()
