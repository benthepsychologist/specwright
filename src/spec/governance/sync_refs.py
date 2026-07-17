"""Agent reference file synchronization for context, spec stubs, and skills.

This module provides the `agent.sync_refs` callable that best-effort syncs
governor-backed project context, spec stubs, and projected skills into
agent-specific reference files (CLAUDE.md, COPILOT.md, .goosehints, etc.).

Callable contract:
  fn(payload: dict, repo_path: Path) -> {"passed": bool, "data": dict, "summary": str}

Payload keys:
    agents: list[str] — agent types to sync (e.g., ["claude-code", "goose"])
    project: str — project name for optional governor-backed context lookup
    epic_dir: str — path to the epic folder carrying AGENTS.md + CLAUDE.md stub
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import]

# Non-clobbering placement for an epic's synced AGENTS.md / CLAUDE.md pointer.
# We never overwrite the target repo's own AGENTS.md/CLAUDE.md at the repo root;
# instead the epic pointer is materialized under .claude/ so native discovery
# (.claude/) finds it while the repo's own files remain authoritative.
EPIC_CONTEXT_DEST_DIR = ".claude"

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


def _is_truthy(value: Any) -> bool:
    """Return whether a config-like value should be treated as enabled."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _governor_root() -> Path:
    """Get governor root via locator path resolution only.

    This intentionally resolves only the root path and does not validate that a
    project directory exists. `refs.sync` must degrade gracefully when a repo has
    no governor project directory or no build file.
    """
    from spec.governor.locator import GovernorLocator

    locator = GovernorLocator(config=_find_local_config(Path.cwd()))
    return locator._resolve_path()


def _find_local_config(start_path: Path) -> dict[str, Any] | None:
    """Find and parse `.specwright.yaml` by walking up from start_path."""
    current = start_path.resolve()
    for parent in [current, *current.parents]:
        config_path = parent / ".specwright.yaml"
        if not config_path.exists():
            continue
        try:
            raw = yaml.safe_load(config_path.read_text()) or {}
        except yaml.YAMLError:
            return None
        if isinstance(raw, dict):
            return raw
        return None
    return None


def _fallback_governor_roots(repo_path: Path) -> list[Path]:
    """Find likely workspace-local governor roots near the repo."""
    candidates: list[Path] = []
    seen: set[Path] = set()
    for parent in [repo_path.resolve(), *repo_path.resolve().parents]:
        candidate = parent / "local-governor"
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            candidates.append(candidate)
    return candidates


def _resolve_governor_root(repo_path: Path) -> tuple[Path | None, list[str]]:
    """Resolve a usable governor root for `refs.sync`.

    Returns a tuple of `(root_or_none, warnings)`.
    """
    warnings: list[str] = []

    try:
        return _governor_root(), warnings
    except Exception as exc:
        warnings.append(f"Governor root lookup failed: {exc}")

    for candidate in _fallback_governor_roots(repo_path):
        if (candidate / "projects").is_dir() or (candidate / "skills").is_dir():
            warnings.append(f"Using fallback governor root: {candidate}")
            return candidate, warnings

    warnings.append("No usable governor root found - skipping governor-backed context and named skills")
    return None, warnings


def _home_dir() -> Path:
    """Return the current user's home directory."""
    return Path.home()


def _skill_library_roots(governor_root: Path | None, epic_dir: Path | None) -> list[Path]:
    """Resolve directories that may contain the shared skill library.

    The canonical 12 skills are authored as ``SKILL.yaml`` under a cloud-governor
    projection (``skills/<name>/SKILL.yaml``), while the legacy local-governor
    store keeps them under ``governor_root/skills``. Rather than force one
    location, search several in priority order; the first directory that holds a
    matching skill wins (per-skill, see ``_resolve_skill_dir``).

    Priority:
      1. ``$SPECWRIGHT_SKILL_LIBRARY`` (explicit override; may be comma-separated)
      2. ``governor_root/skills`` (legacy local-governor store)
      3. ``<epic_dir>/../../../skills`` then ``<governor-projection>/skills``
         discovered by walking up from the epic folder (cloud-governor layout:
         ``<root>/skills`` and ``<root>/epics/<series>/<epic>/``)
    """
    roots: list[Path] = []
    seen: set[Path] = set()

    def _add(candidate: Path) -> None:
        resolved = candidate.expanduser()
        if resolved in seen:
            return
        seen.add(resolved)
        if resolved.is_dir():
            roots.append(resolved)

    env_value = os.environ.get("SPECWRIGHT_SKILL_LIBRARY")
    if env_value:
        for part in env_value.split(os.pathsep) + env_value.split(","):
            part = part.strip()
            if part:
                _add(Path(part))

    if governor_root is not None:
        _add(governor_root / "skills")

    if epic_dir is not None:
        # Walk up from the epic folder; in the cloud-governor layout a sibling
        # `skills/` directory lives at the projection root.
        for parent in [epic_dir, *epic_dir.parents]:
            candidate = parent / "skills"
            if candidate.is_dir():
                _add(candidate)

    return roots


def _resolve_skill_dir(name: str, library_roots: list[Path]) -> Path | None:
    """Find a skill directory for ``name`` across the library roots.

    SKILL.yaml-aware: a directory qualifies if it contains either a SKILL.yaml
    (canonical) or a SKILL.md (legacy). Returns the first match, or None.
    """
    for root in library_roots:
        candidate = root / name
        if not candidate.is_dir():
            continue
        if (candidate / "SKILL.yaml").exists() or (candidate / "SKILL.md").exists():
            return candidate
    return None


def _parse_agents_md_skills(agents_md: str) -> list[str]:
    """Parse skill names from an epic AGENTS.md pointer.

    Reads the ``## Skills`` section and collects list-item entries. Each item may
    be a bare name, an inline-code name (`` `name` ``), or a markdown link
    ``[name](...)``; the first token-like name is extracted. Stops at the next
    ``##`` heading.
    """
    names: list[str] = []
    in_skills = False
    for raw_line in agents_md.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            in_skills = heading.startswith("skills")
            continue
        if not in_skills:
            continue
        if not (stripped.startswith("- ") or stripped.startswith("* ")):
            continue
        item = stripped[2:].strip()
        if not item:
            continue
        # [name](path) -> name
        link = re.match(r"\[([^\]]+)\]\([^)]*\)", item)
        if link:
            item = link.group(1).strip()
        # `name` -> name
        item = item.strip("`").strip()
        # take the leading token (skill names have no spaces)
        token = item.split()[0] if item.split() else ""
        token = token.strip("`*_").strip()
        if token:
            names.append(token)
    # dedupe preserving order
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _copy_skill_dir(
    *,
    name: str,
    source_dir: Path,
    target_roots: list[Path],
    projection_targets: dict[str, list[str]],
) -> list[str]:
    """Copy a resolved skill directory into each native discovery root.

    Returns a list of error strings (empty on success).
    """
    errors: list[str] = []
    for root in target_roots:
        dest = root / name
        try:
            root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_dir, dest, dirs_exist_ok=True)
        except OSError as exc:
            errors.append(f"Skill '{name}' projection failed at {dest}: {exc}")
            continue
        projection_targets.setdefault(name, []).append(str(dest))
    return errors


def _materialize_epic_context(
    *,
    epic_dir: Path,
    repo_path: Path,
) -> tuple[list[str], list[str], str | None]:
    """Materialize an epic's AGENTS.md + CLAUDE.md stub into the target repo.

    Non-clobbering: the files land under ``<repo>/.claude/`` so the repo's own
    root AGENTS.md/CLAUDE.md are never overwritten. Returns
    ``(materialized_paths, warnings, agents_md_text)``. Degrades gracefully:
    a missing epic AGENTS.md is a warning, not a failure.
    """
    materialized: list[str] = []
    warnings: list[str] = []
    agents_md_text: str | None = None

    dest_dir = repo_path / EPIC_CONTEXT_DEST_DIR

    for filename in ("AGENTS.md", "CLAUDE.md"):
        source = epic_dir / filename
        if not source.exists():
            warnings.append(f"Epic {filename} not found at {source} - skipped")
            continue
        try:
            content = source.read_text()
        except OSError as exc:
            warnings.append(f"Could not read epic {filename}: {exc}")
            continue
        if filename == "AGENTS.md":
            agents_md_text = content
        dest = dest_dir / filename
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
        except OSError as exc:
            warnings.append(f"Could not write {dest}: {exc}")
            continue
        materialized.append(str(dest))

    return materialized, warnings, agents_md_text


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


def _skill_paths(raw: Any) -> list[str]:
    """Normalize raw skill path input to a list of non-empty path strings."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        paths: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                paths.append(item.strip())
        return paths
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


def _project_skill_paths(
    *,
    skill_paths: list[str],
    target_roots: list[Path],
    projection_targets: dict[str, list[str]],
    skills_warnings: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Project explicit skill file or directory paths into native discovery paths."""
    projected: set[str] = set()
    skipped: set[str] = set()
    errors: list[str] = []

    for raw_path in skill_paths:
        source = Path(raw_path).expanduser()
        source_dir = source if source.is_dir() else source.parent
        skill_name = source_dir.name or source.stem

        if not source.exists():
            skills_warnings.append(f"Skill path not found: {source}")
            if skill_name:
                skipped.add(skill_name)
            continue

        if not source_dir.exists() or not source_dir.is_dir():
            skills_warnings.append(f"Skill source directory not found: {source_dir}")
            if skill_name:
                skipped.add(skill_name)
            continue

        skill_md = source_dir / "SKILL.md"
        if not skill_md.exists():
            skills_warnings.append(
                f"Skill path '{source}' does not resolve to a skill directory with SKILL.md"
            )
            if skill_name:
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


def _format_spec_stub(spec_md: str, spec_id: str, format_type: str) -> str:
    """Format a spec stub for an agent-specific reference file."""
    stub = _extract_spec_stub(spec_md, spec_id)
    if format_type == "aider":
        lines: list[str] = []
        for line in stub.split("\n"):
            if line:
                lines.append(f"# {line}")
            else:
                lines.append("#")
        return "\n".join(lines)
    return stub


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
    *,
    empty_context: bool = False,
) -> dict:
    """Sync context to a single agent's reference file.

    Returns:
        Dict with keys: success (bool), target_path (str), error (str|None)
    """
    filename, format_type = AGENT_REF_TARGETS[agent]
    target_path = repo_path / filename

    # Format content for this agent
    content = "" if empty_context else _format_content(context, project, format_type)

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


def _sync_spec_stub_for_agent(
    *,
    agent: str,
    spec_md: str,
    spec_id: str,
    repo_path: Path,
) -> dict[str, Any]:
    """Sync the current spec stub into an agent reference file."""
    filename, format_type = AGENT_REF_TARGETS[agent]
    target_path = repo_path / filename
    begin_marker, end_marker = _get_markers(f"SPEC: {spec_id}", format_type)
    spec_section = _format_spec_stub(spec_md, spec_id, format_type)

    existing = ""
    if target_path.exists():
        try:
            existing = target_path.read_text()
        except OSError as exc:
            return {
                "success": False,
                "agent": agent,
                "target_path": str(target_path),
                "error": f"Cannot read: {exc}",
            }

    merged = _merge_content(existing, spec_section, begin_marker, end_marker)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(merged)
    except OSError as exc:
        return {
            "success": False,
            "agent": agent,
            "target_path": str(target_path),
            "error": f"Cannot write: {exc}",
        }

    return {
        "success": True,
        "agent": agent,
        "target_path": str(target_path),
        "error": None,
    }


def sync_refs(*, payload: dict, repo_path: Path) -> dict:
    """Sync best-effort governor context, spec stubs, and skills to agents.

    Payload keys:
        agents: list[str] — agent types to sync/project (claude-code, copilot,
                            codex, cursor, aider, roo-code, goose, opencode)
        project: str — project name for optional governor-backed context lookup
        spec_md: str | None — optional full spec markdown content to inject
        spec_id: str | None — optional spec ID for marker identification
        skill: str | list[str] | None — optional explicit skill file/directory path(s)
        skills: list[str] | None — optional spec-level skill names to project
        epic_dir: str | None — optional path to the epic folder. When provided,
                  the epic's AGENTS.md + CLAUDE.md stub are materialized into the
                  target repo under .claude/ (non-clobbering), and the skills the
                  AGENTS.md names are resolved from the shared library
                  (SKILL.yaml-aware) and copied into .claude/skills/.

    Returns:
        Callable contract dict with passed, data, summary
    """
    if _is_truthy(payload.get("skip_sync")) or _is_truthy(os.environ.get("SPECWRIGHT_SKIP_REFS_SYNC")):
        reason = "payload.skip_sync" if _is_truthy(payload.get("skip_sync")) else "SPECWRIGHT_SKIP_REFS_SYNC"
        return {
            "passed": True,
            "data": {
                "project": payload.get("project"),
                "agents": payload.get("agents", []),
                "skipped": True,
                "skip_reason": reason,
            },
            "summary": f"SKIPPED: refs.sync disabled via {reason}",
        }

    # Extract payload parameters
    agents = payload.get("agents")
    project = payload.get("project")
    spec_md = payload.get("spec_md")
    spec_id = payload.get("spec_id")
    explicit_skill_paths = _skill_paths(payload.get("skill"))
    spec_skills = payload.get("skills")
    epic_dir_raw = payload.get("epic_dir")
    epic_dir: Path | None = None
    if isinstance(epic_dir_raw, str) and epic_dir_raw.strip():
        epic_dir = Path(epic_dir_raw).expanduser()
    elif isinstance(epic_dir_raw, Path):
        epic_dir = epic_dir_raw

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

    results: list[dict] = []
    skills_warnings: list[str] = []
    projection_targets: dict[str, list[str]] = {}
    build_skipped = False
    governor_root, governor_warnings = _resolve_governor_root(repo_path)
    skills_warnings.extend(governor_warnings)

    build: dict[str, Any] | None = None
    skills_manifest: dict[str, Any] | None = None
    if governor_root is not None:
        build = _load_build_yaml(governor_root, project)
        skills_manifest = _load_skills_yaml(governor_root)

    if build is None:
        build = {}
        build_skipped = True
        if governor_root is None:
            skills_warnings.append(
                f"Governor unavailable for project '{project}' - skipping project context and governor-backed named skills"
            )
        else:
            skills_warnings.append(
                f"No build.yaml for project '{project}' - skipping project context"
            )

    context = _extract_context(build)
    context_sections = [k for k, v in context.items() if v]

    # Sync to each agent
    sync_agents = [agent for agent in agents if agent in AGENT_REF_TARGETS]
    for agent in sync_agents:
        result = _sync_single_agent(agent, project, context, repo_path, empty_context=build_skipped)
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
    spec_synced_paths: list[str] = []
    if spec_md and spec_id:
        for agent in sync_agents:
            result = _sync_spec_stub_for_agent(
                agent=agent,
                spec_md=spec_md,
                spec_id=spec_id,
                repo_path=repo_path,
            )
            if result["success"]:
                spec_synced_paths.append(result["target_path"])
                summary_lines.append(
                    f"  [OK] spec stub (id={spec_id}, agent={agent}): {result['target_path']}"
                )
            else:
                summary_lines.append(
                    f"  [FAIL] spec stub (id={spec_id}, agent={agent}): {result['error']}"
                )
        if spec_synced_paths:
            spec_synced = spec_synced_paths[0]

    # Resolve and project skills.
    resolved_skills: list[str] = []
    global_skills: list[str] = []
    status_by_name: dict[str, str] = {}
    if governor_root is not None:
        resolved_skills, global_skills, status_by_name = _resolve_skills(
            build=build,
            spec_skills=spec_skills,
            skills_manifest=skills_manifest,
        )
    elif _skill_names(spec_skills):
        skills_warnings.append(
            "Governor unavailable - skipped named skills declared via payload/build/skills manifest"
        )

    repo_skill_roots = _target_roots(agents, repo_path=repo_path)
    global_skill_roots = _target_roots(agents, repo_path=None)

    projected_repo: list[str] = []
    skipped_repo: list[str] = []
    projection_errors_repo: list[str] = []
    projected_global: list[str] = []
    skipped_global: list[str] = []
    projection_errors_global: list[str] = []

    if governor_root is not None:
        projected_repo, skipped_repo, projection_errors_repo = _project_skills(
            governor_root=governor_root,
            skills=resolved_skills,
            status_by_name=status_by_name,
            target_roots=repo_skill_roots,
            projection_targets=projection_targets,
            skills_warnings=skills_warnings,
        )
    projected_explicit, skipped_explicit, projection_errors_explicit = _project_skill_paths(
        skill_paths=explicit_skill_paths,
        target_roots=repo_skill_roots,
        projection_targets=projection_targets,
        skills_warnings=skills_warnings,
    )
    if governor_root is not None:
        projected_global, skipped_global, projection_errors_global = _project_global_skills(
            governor_root=governor_root,
            global_skills=global_skills,
            status_by_name=status_by_name,
            target_roots=global_skill_roots,
            projection_targets=projection_targets,
            skills_warnings=skills_warnings,
        )

    # Materialize the epic's AGENTS.md + CLAUDE.md stub into the target repo
    # (non-clobbering) and copy the skills its AGENTS.md names from the shared
    # library (SKILL.yaml-aware). Docs are referenced by path, never copied.
    epic_context_materialized: list[str] = []
    agents_md_skills_projected: list[str] = []
    agents_md_skills_skipped: list[str] = []
    agents_md_skill_errors: list[str] = []
    if epic_dir is not None:
        if not epic_dir.is_dir():
            skills_warnings.append(
                f"Epic folder not found: {epic_dir} - skipped epic context materialization"
            )
        else:
            materialized, mat_warnings, agents_md_text = _materialize_epic_context(
                epic_dir=epic_dir,
                repo_path=repo_path,
            )
            epic_context_materialized.extend(materialized)
            skills_warnings.extend(mat_warnings)

            if agents_md_text:
                named = _parse_agents_md_skills(agents_md_text)
                library_roots = _skill_library_roots(governor_root, epic_dir)
                seen_named: set[str] = set()
                for name in named:
                    if name in seen_named:
                        continue
                    seen_named.add(name)
                    source_dir = _resolve_skill_dir(name, library_roots)
                    if source_dir is None:
                        skills_warnings.append(
                            f"Skill '{name}' (named in epic AGENTS.md) not found in "
                            f"shared library - skipped"
                        )
                        agents_md_skills_skipped.append(name)
                        continue
                    if not repo_skill_roots:
                        continue
                    errors = _copy_skill_dir(
                        name=name,
                        source_dir=source_dir,
                        target_roots=repo_skill_roots,
                        projection_targets=projection_targets,
                    )
                    if errors:
                        agents_md_skill_errors.extend(errors)
                    if projection_targets.get(name):
                        agents_md_skills_projected.append(name)

    skills_projected = sorted(
        set(projected_repo)
        | set(projected_explicit)
        | set(projected_global)
        | set(agents_md_skills_projected)
    )
    skills_skipped = sorted(
        set(skipped_repo)
        | set(skipped_explicit)
        | set(skipped_global)
        | set(agents_md_skills_skipped)
    )
    projection_errors = (
        projection_errors_repo
        + projection_errors_explicit
        + projection_errors_global
        + agents_md_skill_errors
    )
    for err in projection_errors:
        summary_lines.append(f"  [FAIL] {err}")

    if epic_context_materialized:
        summary_lines.append(
            f"  [OK] epic context materialized: {', '.join(epic_context_materialized)}"
        )
    if skills_projected:
        summary_lines.append(f"  [OK] skills projected: {', '.join(skills_projected)}")
    if skills_skipped:
        summary_lines.append(f"  [OK] skills skipped: {', '.join(skills_skipped)}")
    for warning in skills_warnings:
        summary_lines.append(f"  [WARN] {warning}")

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
            "governor_root": str(governor_root) if governor_root is not None else None,
            "context_sections": context_sections,
            "spec_synced": spec_synced,
            "spec_synced_paths": spec_synced_paths,
            "spec_id": spec_id,
            "skills_projected": skills_projected,
            "skills_skipped": skills_skipped,
            "skills_warnings": skills_warnings,
            "projection_targets": projection_targets,
            "epic_context_materialized": epic_context_materialized,
            "epic_dir": str(epic_dir) if epic_dir is not None else None,
        },
        "summary": "\n".join(summary_lines),
    }
