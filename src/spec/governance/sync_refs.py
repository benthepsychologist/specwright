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

import shutil
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

# Agent skills discovery directories (relative to repo root).
# Agents not listed here do not currently support native skill discovery.
AGENT_SKILLS_PATHS: dict[str, str] = {
    "claude-code": ".claude/skills",
    "copilot": ".claude/skills",
    "cursor": ".claude/skills",
    "codex": ".agents/skills",
}


def _governor_root() -> Path:
    """Get governor root via the standard locator."""
    from spec.governor.locator import GovernorLocator

    return GovernorLocator().find(ensure_dirs=False).root


def _home_dir() -> Path:
    """Return the current user's home directory."""
    return Path.home()


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


def _load_skills_yaml(governor_root: Path) -> dict | None:
    """Load skills registry manifest from governor store."""
    skills_path = governor_root / "skills" / "skills.yaml"
    if not skills_path.exists():
        return None
    try:
        data = yaml.safe_load(skills_path.read_text())
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _skill_names(raw: Any) -> list[str]:
    """Normalize a raw skills value to a list of non-empty names."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        names: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                names.append(item)
        return names
    return []


def _load_skill_registry(skills_manifest: dict | None) -> tuple[dict[str, str], list[str]]:
    """Read skill statuses and global skill list from skills manifest."""
    if not skills_manifest:
        return {}, []

    statuses: dict[str, str] = {}
    for item in skills_manifest.get("skills") or []:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name:
                status = item.get("status")
                statuses[name] = str(status) if isinstance(status, str) and status else "active"

    # Also support mapping form: skills: {name: {status: active}}
    skills_mapping = skills_manifest.get("skills")
    if isinstance(skills_mapping, dict):
        for name, cfg in skills_mapping.items():
            if not isinstance(name, str) or not name:
                continue
            if isinstance(cfg, dict):
                status = cfg.get("status")
                statuses[name] = str(status) if isinstance(status, str) and status else "active"
            elif isinstance(cfg, str):
                statuses[name] = cfg
            else:
                statuses[name] = "active"

    global_skills = _skill_names(skills_manifest.get("global"))
    return statuses, global_skills


def _resolve_skills(
    *,
    build: dict,
    spec_skills: Any,
    skills_manifest: dict | None,
) -> tuple[list[str], list[str], dict[str, str]]:
    """Resolve deduplicated skill names from global, project, and spec tiers."""
    statuses, global_skills = _load_skill_registry(skills_manifest)
    project_skills = _skill_names(build.get("skills"))
    requested_spec_skills = _skill_names(spec_skills)

    resolved: list[str] = []
    seen: set[str] = set()
    for name in [*global_skills, *project_skills, *requested_spec_skills]:
        if name in seen:
            continue
        seen.add(name)
        resolved.append(name)

    return resolved, global_skills, statuses


def _target_roots(agents: list[str], *, repo_path: Path | None) -> list[Path]:
    """Resolve unique skills target roots for the selected agents."""
    roots: list[Path] = []
    seen: set[Path] = set()
    for agent in agents:
        rel = AGENT_SKILLS_PATHS.get(agent)
        if not rel:
            continue
        root = _home_dir() / rel if repo_path is None else repo_path / rel
        if root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return roots


def _project_skills(
    *,
    governor_root: Path,
    skills: list[str],
    status_by_name: dict[str, str],
    target_roots: list[Path],
    projection_targets: dict[str, list[str]],
    skills_warnings: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Copy skill directories into native discovery paths."""
    projected: set[str] = set()
    skipped: set[str] = set()
    errors: list[str] = []

    for skill_name in skills:
        status = status_by_name.get(skill_name, "active")
        if status in {"draft", "retired"}:
            skills_warnings.append(f"Skill '{skill_name}' has status '{status}' and was skipped")
            skipped.add(skill_name)
            continue

        source_dir = governor_root / "skills" / skill_name
        if not source_dir.exists() or not source_dir.is_dir():
            skills_warnings.append(
                f"Skill '{skill_name}' directory not found: {source_dir}"
            )
            skipped.add(skill_name)
            continue

        if not target_roots:
            continue

        for root in target_roots:
            dest = root / skill_name
            try:
                root.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source_dir, dest, dirs_exist_ok=True)
            except OSError as exc:
                errors.append(f"Skill '{skill_name}' projection failed at {dest}: {exc}")
                continue
            projection_targets.setdefault(skill_name, []).append(str(dest))

        if projection_targets.get(skill_name):
            projected.add(skill_name)

    return sorted(projected), sorted(skipped), errors


def _project_global_skills(
    *,
    governor_root: Path,
    global_skills: list[str],
    status_by_name: dict[str, str],
    target_roots: list[Path],
    projection_targets: dict[str, list[str]],
    skills_warnings: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Project global skills to user-level native discovery paths."""
    return _project_skills(
        governor_root=governor_root,
        skills=global_skills,
        status_by_name=status_by_name,
        target_roots=target_roots,
        projection_targets=projection_targets,
        skills_warnings=skills_warnings,
    )


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


def _extract_spec_stub(spec_md: str, spec_id: str) -> str:
    """Extract a lightweight stub from full spec markdown.

    Returns only the spec header, goal, and acceptance criteria —
    enough for the agent to stay oriented without bloating the context file.
    """
    lines = spec_md.split("\n")
    stub_lines = [f"## Current Spec: {spec_id}", ""]

    # Extract goal from frontmatter
    in_fm = False
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            if not in_fm:
                in_fm = True
                continue
            else:
                break
        if in_fm and stripped.startswith("goal:"):
            goal = stripped[5:].strip().strip('"').strip("'")
            stub_lines.append(f"**Goal:** {goal}")
            stub_lines.append("")
            break

    # Extract acceptance criteria section
    in_ac = False
    for line in lines:
        if line.strip().lower().startswith("## acceptance criteria"):
            in_ac = True
            stub_lines.append(line)
            continue
        if in_ac:
            if line.startswith("## ") and "acceptance" not in line.lower():
                break
            stub_lines.append(line)

    if not in_ac:
        stub_lines.append("(No acceptance criteria section found in spec)")

    return "\n".join(stub_lines)


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
        agents: list[str] — agent types to sync/project (claude-code, copilot,
                            codex, cursor, aider, roo-code, goose, opencode)
        project: str — project name to read build.yaml from
        spec_md: str | None — optional full spec markdown content to inject
        spec_id: str | None — optional spec ID for marker identification
        skills: list[str] | None — optional spec-level skill names to project

    Returns:
        Callable contract dict with passed, data, summary
    """
    # Extract payload parameters
    agents = payload.get("agents")
    project = payload.get("project")
    spec_md = payload.get("spec_md")
    spec_id = payload.get("spec_id")
    spec_skills = payload.get("skills")

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
    supported_agents = set(AGENT_REF_TARGETS.keys()) | set(AGENT_SKILLS_PATHS.keys())
    unknown_agents = [a for a in agents if a not in supported_agents]
    if unknown_agents:
        available = ", ".join(sorted(supported_agents))
        return {
            "passed": False,
            "data": {
                "error": f"Unknown agents: {unknown_agents}",
                "available": available,
            },
            "summary": f"FAILED: unknown agents {unknown_agents}. Available: {available}",
        }

    # Load build.yaml — missing is non-fatal (repo may not have one yet)
    governor_root = _governor_root()
    build = _load_build_yaml(governor_root, project)
    skills_manifest = _load_skills_yaml(governor_root)

    results: list[dict] = []
    skills_warnings: list[str] = []
    projection_targets: dict[str, list[str]] = {}
    build_skipped = False

    if build is None:
        build = {}
        build_skipped = True
        skills_warnings.append(
            f"No build.yaml for project '{project}' - skipping project context"
        )

    context = _extract_context(build)
    context_sections = [k for k, v in context.items() if v]

    # Sync to each agent
    sync_agents = [agent for agent in agents if agent in AGENT_REF_TARGETS]
    for agent in sync_agents:
        result = _sync_single_agent(agent, project, context, repo_path)
        result["agent"] = agent
        results.append(result)

    successes = [r for r in results if r["success"]]

    # Build summary (no emoji per CLAUDE.md guidelines)
    summary_lines = [f"Synced {project} context to {len(successes)}/{len(sync_agents)} agents:"]
    for r in results:
        status = "[OK]" if r["success"] else "[FAIL]"
        line = f"  {status} {r['agent']}: {r['target_path']}"
        if r["error"]:
            line += f" ({r['error']})"
        summary_lines.append(line)

    # Inject spec stub into CLAUDE.md (independent of build.yaml)
    spec_synced = None
    if spec_md and spec_id:
        try:
            claude_md_path = repo_path / "CLAUDE.md"
            existing = claude_md_path.read_text() if claude_md_path.exists() else ""
            begin = f"<!-- BEGIN SPEC: {spec_id} -->"
            end = f"<!-- END SPEC: {spec_id} -->"
            spec_section = _extract_spec_stub(spec_md, spec_id)
            merged = _merge_content(existing, spec_section, begin, end)
            claude_md_path.write_text(merged)
            spec_synced = str(claude_md_path)
            summary_lines.append(f"  [OK] spec stub (id={spec_id}): {spec_synced}")
        except OSError as e:
            summary_lines.append(f"  [FAIL] spec (id={spec_id}): {e}")

    # Resolve and project skills.
    resolved_skills, global_skills, status_by_name = _resolve_skills(
        build=build,
        spec_skills=spec_skills,
        skills_manifest=skills_manifest,
    )

    repo_skill_roots = _target_roots(agents, repo_path=repo_path)
    global_skill_roots = _target_roots(agents, repo_path=None)

    projected_repo, skipped_repo, projection_errors_repo = _project_skills(
        governor_root=governor_root,
        skills=resolved_skills,
        status_by_name=status_by_name,
        target_roots=repo_skill_roots,
        projection_targets=projection_targets,
        skills_warnings=skills_warnings,
    )
    projected_global, skipped_global, projection_errors_global = _project_global_skills(
        governor_root=governor_root,
        global_skills=global_skills,
        status_by_name=status_by_name,
        target_roots=global_skill_roots,
        projection_targets=projection_targets,
        skills_warnings=skills_warnings,
    )

    skills_projected = sorted(set(projected_repo) | set(projected_global))
    skills_skipped = sorted(set(skipped_repo) | set(skipped_global))
    projection_errors = projection_errors_repo + projection_errors_global
    for err in projection_errors:
        summary_lines.append(f"  [FAIL] {err}")

    if skills_projected:
        summary_lines.append(f"  [OK] skills projected: {', '.join(skills_projected)}")
    if skills_skipped:
        summary_lines.append(f"  [OK] skills skipped: {', '.join(skills_skipped)}")

    # Determine overall success — build.yaml skip is not a failure
    agent_failures = [r for r in results if not r["success"]]

    return {
        "passed": len(agent_failures) == 0 and len(projection_errors) == 0,
        "data": {
            "project": project,
            "agents": agents,
            "results": results,
            "synced_count": len([r for r in results if r["success"]]),
            "failed_count": len(agent_failures),
            "build_skipped": build_skipped,
            "context_sections": context_sections,
            "spec_synced": spec_synced,
            "spec_id": spec_id,
            "skills_projected": skills_projected,
            "skills_skipped": skills_skipped,
            "skills_warnings": skills_warnings,
            "projection_targets": projection_targets,
        },
        "summary": "\n".join(summary_lines),
    }
