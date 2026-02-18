"""Agent reference file synchronization from build.yaml.

This module provides the `agent.sync_refs` callable that syncs project
architecture context from canonical build.yaml files into agent-specific
reference files (CLAUDE.md, .goosehints, etc.).

Callable contract:
  fn(payload: dict, repo_path: Path) -> {"passed": bool, "data": dict, "summary": str}

Payload keys:
  agents: list[str] — agent types to sync (e.g., ["claude-code", "goose"])
  project: str — project name to read build.yaml from
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import]

# Agent reference file targets
# Maps agent type to (filename, format_type)
# format_type: "markdown" for HTML comment markers, "hash" for # comment markers
#
# Note on cursor: .cursorrules is deprecated but still works.
# Cursor now prefers .cursor/rules/ directory or AGENTS.md.
# We use .cursorrules for backwards compatibility.
AGENT_REF_TARGETS: dict[str, tuple[str, str]] = {
    "claude-code": ("CLAUDE.md", "markdown"),
    "copilot": ("COPILOT.md", "markdown"),
    "cursor": (".cursorrules", "markdown"),
    "aider": (".aider.conf.yml", "aider"),
    "roo-code": (".roo/rules.md", "markdown"),
    "goose": (".goosehints", "hash"),
    "opencode": (".opencode/instructions.md", "markdown"),
}


def _governor_root() -> Path:
    """Get governor root via the standard locator."""
    from spec.governor.locator import GovernorLocator

    return GovernorLocator().find(ensure_dirs=False).root


def _load_build_yaml(governor_root: Path, project: str) -> dict | None:
    """Load build.yaml for a project. Returns None if not found or invalid."""
    build_path = governor_root / "projects" / project / f"{project}.build.yaml"
    if not build_path.exists():
        return None

    try:
        data = yaml.safe_load(build_path.read_text())
        if not isinstance(data, dict):
            return None
        return data
    except yaml.YAMLError:
        return None


def _extract_context(build: dict) -> dict[str, Any]:
    """Extract relevant context from build.yaml.

    Returns a dict with:
      - description: kernel description
      - invariants: list of kernel invariants
      - boundaries: list of boundary dicts
      - decisions: list of decision dicts
    """
    kernel = build.get("kernel") or {}
    return {
        "description": kernel.get("description", ""),
        "invariants": kernel.get("invariants") or [],
        "boundaries": build.get("boundaries") or [],
        "decisions": build.get("decisions") or [],
    }


def _format_consumers(consumers: Any) -> str:
    """Safely format consumers field which may be string or list."""
    if isinstance(consumers, list):
        return ", ".join(str(c) for c in consumers)
    return str(consumers)


def _format_markdown(context: dict[str, Any], project: str) -> str:
    """Format extracted context as markdown content."""
    lines: list[str] = []

    # Project header
    lines.append(f"# {project.title()} Project Context")
    lines.append("")

    # Description
    if context["description"]:
        lines.append("## Description")
        lines.append("")
        lines.append(context["description"])
        lines.append("")

    # Invariants
    if context["invariants"]:
        lines.append("## Invariants")
        lines.append("")
        for inv in context["invariants"]:
            lines.append(f"- {inv}")
        lines.append("")

    # Boundaries
    if context["boundaries"]:
        lines.append("## Boundaries")
        lines.append("")
        for boundary in context["boundaries"]:
            name = boundary.get("name", "unnamed")
            btype = boundary.get("type", "")
            contract = boundary.get("contract", "")
            lines.append(f"### {name}")
            if btype:
                lines.append(f"- Type: {btype}")
            if contract:
                lines.append(f"- Contract: {contract}")
            if boundary.get("requires"):
                lines.append(f"- Requires: {boundary['requires']}")
            if boundary.get("consumers"):
                lines.append(f"- Consumers: {_format_consumers(boundary['consumers'])}")
            lines.append("")

    # Decisions
    if context["decisions"]:
        lines.append("## Architecture Decisions")
        lines.append("")
        for decision in context["decisions"]:
            did = decision.get("id", "")
            title = decision.get("title", "")
            status = decision.get("status", "")
            lines.append(f"### {did}: {title}")
            if status:
                lines.append(f"**Status:** {status}")
            if decision.get("rationale"):
                lines.append(f"\n**Rationale:** {decision['rationale']}")
            if decision.get("decision"):
                lines.append(f"\n**Decision:** {decision['decision']}")
            lines.append("")

    return "\n".join(lines)


def _get_markers(project: str, format_type: str) -> tuple[str, str]:
    """Get begin/end markers based on format type.

    Args:
        project: Project name for the marker
        format_type: "markdown", "hash", or "aider"

    Returns:
        Tuple of (begin_marker, end_marker)
    """
    if format_type == "markdown":
        return (
            f"<!-- BEGIN SYNCED: {project} -->",
            f"<!-- END SYNCED: {project} -->",
        )
    else:
        # hash and aider use hash comments
        return (
            f"# BEGIN SYNCED: {project}",
            f"# END SYNCED: {project}",
        )


def _format_content(context: dict[str, Any], project: str, format_type: str) -> str:
    """Format context based on target format type.

    All formats currently use markdown since it's readable as plain text.
    The format_type mainly affects the marker style (HTML vs hash comments).
    """
    if format_type == "aider":
        # Aider: output markdown as comments since .aider.conf.yml is YAML config
        # TODO: Research proper aider config format. See known_issues.md.
        lines = ["# Project context from build.yaml (for reference only)"]
        md = _format_markdown(context, project)
        for line in md.split("\n"):
            if line:
                lines.append(f"# {line}")
            else:
                lines.append("#")
        return "\n".join(lines)
    else:
        return _format_markdown(context, project)


def _merge_content(
    existing: str,
    new_content: str,
    begin_marker: str,
    end_marker: str,
) -> str:
    """Merge new synced content into existing file content.

    Preserves all content outside the markers.
    If markers don't exist, appends new content at the end.

    Args:
        existing: Current file content (may be empty)
        new_content: New content to insert between markers
        begin_marker: Start marker line
        end_marker: End marker line

    Returns:
        Merged content with updated synced section
    """
    # Build the synced block
    synced_block = f"{begin_marker}\n{new_content}\n{end_marker}"

    if not existing.strip():
        # Empty file - just return the synced block
        return synced_block + "\n"

    # Look for existing markers
    begin_idx = existing.find(begin_marker)
    end_idx = existing.find(end_marker)

    if begin_idx == -1 or end_idx == -1:
        # No markers found - append at end with separator
        if existing.endswith("\n\n"):
            return existing + synced_block + "\n"
        elif existing.endswith("\n"):
            return existing + "\n" + synced_block + "\n"
        else:
            return existing + "\n\n" + synced_block + "\n"

    if end_idx < begin_idx:
        # Malformed markers - append at end
        if existing.endswith("\n"):
            return existing + "\n" + synced_block + "\n"
        else:
            return existing + "\n\n" + synced_block + "\n"

    # Replace content between markers (inclusive)
    # Find the end of the end_marker line
    end_line_end = existing.find("\n", end_idx)
    if end_line_end == -1:
        end_line_end = len(existing)
    else:
        end_line_end += 1  # Include the newline

    before = existing[:begin_idx]
    after = existing[end_line_end:]

    # Clean up spacing
    merged = before.rstrip("\n")
    if merged:
        merged += "\n\n"
    merged += synced_block
    if after.strip():
        merged += "\n\n" + after.lstrip("\n")
    else:
        merged += "\n"

    return merged


def _sync_single_agent(
    agent: str,
    project: str,
    context: dict[str, Any],
    repo_path: Path,
) -> dict:
    """Sync context to a single agent's reference file.

    Returns:
        Dict with keys: success (bool), target_path (str), error (str|None)
    """
    filename, format_type = AGENT_REF_TARGETS[agent]
    target_path = repo_path / filename

    # Format content for this agent
    content = _format_content(context, project, format_type)

    # Get markers
    begin_marker, end_marker = _get_markers(project, format_type)

    # Read existing content
    existing = ""
    if target_path.exists():
        try:
            existing = target_path.read_text()
        except OSError as e:
            return {
                "success": False,
                "target_path": str(target_path),
                "error": f"Cannot read: {e}",
            }

    # Merge content
    merged = _merge_content(existing, content, begin_marker, end_marker)

    # Write file
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(merged)
    except OSError as e:
        return {
            "success": False,
            "target_path": str(target_path),
            "error": f"Cannot write: {e}",
        }

    return {
        "success": True,
        "target_path": str(target_path),
        "error": None,
    }


def sync_refs(*, payload: dict, repo_path: Path) -> dict:
    """Sync build.yaml architecture context to agent reference files.

    Payload keys:
        agents: list[str] — agent types to sync (claude-code, cursor, aider,
                            roo-code, goose, opencode)
        project: str — project name to read build.yaml from

    Returns:
        Callable contract dict with passed, data, summary
    """
    # Extract payload parameters
    agents = payload.get("agents")
    project = payload.get("project")

    # Validate required parameters
    if agents is None:
        return {
            "passed": False,
            "data": {"error": "agents list required in payload"},
            "summary": "FAILED: agents not provided",
        }

    if not isinstance(agents, list):
        return {
            "passed": False,
            "data": {"error": "agents must be a list"},
            "summary": "FAILED: agents must be a list",
        }

    if len(agents) == 0:
        return {
            "passed": False,
            "data": {"error": "agents list cannot be empty"},
            "summary": "FAILED: agents list is empty",
        }

    if not project:
        return {
            "passed": False,
            "data": {"error": "project required in payload"},
            "summary": "FAILED: project not provided",
        }

    # Validate all agent types upfront
    unknown_agents = [a for a in agents if a not in AGENT_REF_TARGETS]
    if unknown_agents:
        available = ", ".join(sorted(AGENT_REF_TARGETS.keys()))
        return {
            "passed": False,
            "data": {
                "error": f"Unknown agents: {unknown_agents}",
                "available": available,
            },
            "summary": f"FAILED: unknown agents {unknown_agents}. Available: {available}",
        }

    # Load build.yaml
    governor_root = _governor_root()
    build = _load_build_yaml(governor_root, project)

    if build is None:
        build_path = governor_root / "projects" / project / f"{project}.build.yaml"
        return {
            "passed": False,
            "data": {"error": f"build.yaml not found or invalid: {build_path}"},
            "summary": f"FAILED: cannot load build.yaml for project '{project}'",
        }

    # Extract context once
    context = _extract_context(build)

    # Sync to each agent
    results: list[dict] = []
    for agent in agents:
        result = _sync_single_agent(agent, project, context, repo_path)
        result["agent"] = agent
        results.append(result)

    # Determine overall success
    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    # Build summary (no emoji per CLAUDE.md guidelines)
    summary_lines = [f"Synced {project} context to {len(successes)}/{len(agents)} agents:"]
    for r in results:
        status = "[OK]" if r["success"] else "[FAIL]"
        line = f"  {status} {r['agent']}: {r['target_path']}"
        if r["error"]:
            line += f" ({r['error']})"
        summary_lines.append(line)

    return {
        "passed": len(failures) == 0,
        "data": {
            "project": project,
            "agents": agents,
            "results": results,
            "synced_count": len(successes),
            "failed_count": len(failures),
            "context_sections": [k for k, v in context.items() if v],
        },
        "summary": "\n".join(summary_lines),
    }
