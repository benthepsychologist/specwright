"""Interactive UI components for gate approvals and HITL workflows."""

from datetime import datetime
from typing import Any

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()


def display_gate_checkpoint(gate_id: str, gate_name: str, tier: str) -> None:
    """
    Display a gate checkpoint header with tier-specific styling.

    Args:
        gate_id: Gate identifier (e.g., "G0", "G1")
        gate_name: Human-readable gate name
        tier: Risk tier (A/B/C)
    """
    # Tier-specific styling
    tier_colors = {
        "A": "bold red",
        "B": "bold yellow",
        "C": "bold green"
    }
    style = tier_colors.get(tier, "bold blue")

    # Build gate header
    header = f"🔒 GATE CHECKPOINT: [{gate_id}] {gate_name}"
    if tier in ["A", "B"]:
        header += f" (TIER {tier}: Formal Review Required)"

    console.print()
    console.print(Panel(header, style=style, expand=False))
    console.print()


def show_gate_checklist(checklist: dict[str, list[str]]) -> None:
    """
    Display a gate review checklist organized by categories.

    Args:
        checklist: Dict mapping category names to lists of checklist items
                  Example: {"Architecture": ["Item 1", "Item 2"], ...}
    """
    if not checklist:
        return

    console.print("📋 [bold cyan]Gate Review Checklist:[/bold cyan]")
    console.print()

    for category, items in checklist.items():
        console.print(f"  [bold]{category}:[/bold]")
        for item in items:
            console.print(f"    [ ] {item}")
        console.print()


def prompt_checklist_completion(checklist: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Prompt user to interactively complete a checklist.

    Args:
        checklist: Dict mapping category names to lists of checklist items

    Returns:
        Dict mapping category names to lists of completed items
    """
    if not checklist:
        return {}

    console.print("[bold]Complete the review checklist:[/bold]")
    console.print()

    completed = {}

    for category, items in checklist.items():
        if not items:
            continue

        # Create questionary choices
        choices = [
            questionary.Choice(item, value=item, checked=False)
            for item in items
        ]

        # Prompt for completion
        completed_items = questionary.checkbox(
            f"{category}:",
            choices=choices
        ).ask()

        completed[category] = completed_items or []

    return completed


def prompt_approval_decision() -> dict[str, Any]:
    """
    Prompt user for gate approval decision and metadata.

    Returns:
        Dict containing:
            - decision: str ("approved" | "rejected" | "deferred" | "conditional")
            - reviewer: str
            - rationale: str
            - conditions: str (only if conditional)
            - timestamp: str (ISO format)
    """
    console.print()
    console.print("[bold yellow]Actions:[/bold yellow]")
    console.print("  [R] Review artifacts")
    console.print("  [C] Complete checklist")
    console.print("  [A] Approve gate")
    console.print("  [D] Defer gate")
    console.print("  [X] Reject gate")
    console.print()

    # Decision selection
    decision = questionary.select(
        "What is your decision?",
        choices=[
            questionary.Choice("✅ Approve - Proceed to next step", value="approved"),
            questionary.Choice("❌ Reject - Stop execution", value="rejected"),
            questionary.Choice("⏸️  Defer - Mark for later review", value="deferred"),
            questionary.Choice("⚠️  Conditional - Approve with conditions", value="conditional"),
        ]
    ).ask()

    if decision is None:  # User cancelled (Ctrl+C)
        return {"decision": "cancelled"}

    # Reviewer name
    reviewer = questionary.text(
        "Reviewer name (required):",
        validate=lambda x: len(x.strip()) > 0 or "Reviewer name is required"
    ).ask()

    if reviewer is None:
        return {"decision": "cancelled"}

    # Rationale
    rationale = questionary.text(
        "Decision rationale (optional, press Enter to skip):",
        multiline=False
    ).ask()

    if rationale is None:
        return {"decision": "cancelled"}

    # Conditions (if conditional approval)
    conditions = ""
    if decision == "conditional":
        conditions = questionary.text(
            "Approval conditions (required for conditional approval):",
            multiline=True,
            validate=lambda x: len(x.strip()) > 0 or "Conditions are required for conditional approval"
        ).ask()

        if conditions is None:
            return {"decision": "cancelled"}

    return {
        "decision": decision,
        "reviewer": reviewer.strip(),
        "rationale": rationale.strip() if rationale else "",
        "conditions": conditions.strip() if conditions else "",
        "timestamp": datetime.now().isoformat()
    }


def display_step_details(step: dict[str, Any]) -> None:
    """
    Display step details in a formatted table.

    Args:
        step: Step dictionary from compiled AIP
    """
    table = Table(title="Step Details", show_header=False)
    table.add_column("Field", style="cyan", width=15)
    table.add_column("Value", style="white")

    # Add step fields
    if "step_id" in step:
        table.add_row("Step ID", step["step_id"])
    if "role" in step:
        table.add_row("Role", step["role"])
    if "description" in step:
        table.add_row("Description", step["description"])

    console.print(table)
    console.print()

    # Display prompt with syntax highlighting
    if "prompt" in step and step["prompt"]:
        prompt_panel = Panel(
            step["prompt"],
            title="[bold]Prompt[/bold]",
            style="green"
        )
        console.print(prompt_panel)
        console.print()

    # Display commands
    if "commands" in step and step["commands"]:
        commands_text = "\n".join(f"$ {cmd}" for cmd in step["commands"])
        commands_panel = Panel(
            commands_text,
            title="[bold]Commands[/bold]",
            style="yellow"
        )
        console.print(commands_panel)
        console.print()

    # Display expected outputs
    if "outputs" in step and step["outputs"]:
        outputs_text = "\n".join(f"  • {output}" for output in step["outputs"])
        console.print("[bold]Expected Outputs:[/bold]")
        console.print(outputs_text)
        console.print()


def confirm_gate_override(tier: str) -> bool:
    """
    Confirm if user wants to override gate requirements.

    Args:
        tier: Risk tier (for context)

    Returns:
        True if user confirms override, False otherwise
    """
    console.print()
    console.print(Panel(
        f"[bold red]WARNING:[/bold red] This is a Tier {tier} spec.\n"
        "Skipping gates may violate governance requirements.",
        style="red"
    ))

    return questionary.confirm(
        "Do you want to skip gate approval and proceed anyway?",
        default=False
    ).ask()


def display_approval_summary(approval: dict[str, Any]) -> None:
    """
    Display a summary of the gate approval decision.

    Args:
        approval: Approval metadata dict
    """
    decision_icons = {
        "approved": "✅",
        "rejected": "❌",
        "deferred": "⏸️",
        "conditional": "⚠️"
    }

    decision = approval.get("decision", "unknown")
    icon = decision_icons.get(decision, "❓")

    console.print()
    console.print(f"{icon} [bold]Gate Decision: {decision.upper()}[/bold]")
    console.print(f"   Reviewer: {approval.get('reviewer', 'N/A')}")
    console.print(f"   Timestamp: {approval.get('timestamp', 'N/A')}")

    if approval.get("rationale"):
        console.print(f"   Rationale: {approval['rationale']}")

    if approval.get("conditions"):
        console.print(f"   Conditions: {approval['conditions']}")

    console.print()
