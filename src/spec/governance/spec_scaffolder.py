"""Spec scaffolder for generating spec-v2 YAML from intents."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from spec.governance.intent_parser import ParsedIntent


# The epic AGENTS.md is a *pointer/index*, not a context dump: a `## Skills`
# section naming shared-library skills (copied into .claude/skills/ at run by
# agent.sync_refs) and a `## Docs` section linking docs by path (read on demand,
# never copied). A one-line CLAUDE.md stub points Claude Code at AGENTS.md so it
# and Codex/Copilot land on the same canonical file.
CLAUDE_STUB_CONTENT = "See [AGENTS.md](AGENTS.md) for the skills and docs that apply to this epic.\n"


def render_agents_md_pointer(
    *,
    title: str,
    skills: list[str] | None = None,
    docs: list[str] | None = None,
) -> str:
    """Render an epic AGENTS.md pointer.

    The pointer is short by design:
      - a `## Skills` section listing shared-library skill names (one per line);
        agent.sync_refs resolves each from the shared library and copies it into
        `.claude/skills/<name>/` for native discovery.
      - a `## Docs` section linking relevant docs by path; docs are referenced,
        never copied.

    Empty sections are still emitted (with a TODO placeholder) so the convention
    is visible and easy to fill in at authoring time.
    """
    skills = skills or []
    docs = docs or []

    lines: list[str] = [f"# {title} — Agent Context", ""]
    lines.append(
        "This is a pointer (not a context dump): it names the skills that apply "
        "and links the relevant docs."
    )
    lines.append("")

    lines.append("## Skills")
    lines.append("")
    lines.append("Shared-library skills copied into `.claude/skills/` at run for native discovery:")
    lines.append("")
    if skills:
        for name in skills:
            lines.append(f"- {name}")
    else:
        lines.append("- TODO: name shared-library skills that apply (one per line)")
    lines.append("")

    lines.append("## Docs")
    lines.append("")
    lines.append("Relevant docs, referenced by path (read on demand, not copied):")
    lines.append("")
    if docs:
        for doc in docs:
            lines.append(f"- [{doc}]({doc})")
    else:
        lines.append("- TODO: link relevant docs by path")
    lines.append("")

    return "\n".join(lines)


def write_epic_context_files(
    epic_dir: Path,
    *,
    title: str,
    skills: list[str] | None = None,
    docs: list[str] | None = None,
    overwrite: bool = False,
) -> list[Path]:
    """Author an epic's AGENTS.md pointer + CLAUDE.md stub in ``epic_dir``.

    Always creates both files at epic creation. Existing files are left in place
    unless ``overwrite`` is True, so re-running never clobbers human edits.

    Returns the list of file paths written.
    """
    epic_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    agents_path = epic_dir / "AGENTS.md"
    if overwrite or not agents_path.exists():
        agents_path.write_text(
            render_agents_md_pointer(title=title, skills=skills, docs=docs)
        )
        written.append(agents_path)

    claude_path = epic_dir / "CLAUDE.md"
    if overwrite or not claude_path.exists():
        claude_path.write_text(CLAUDE_STUB_CONTENT)
        written.append(claude_path)

    return written


class SpecScaffolder:
    """Generate scaffolded YAML specs from intents."""

    def __init__(
        self,
        intent: ParsedIntent,
        repo_path: Path,
        governor_root: Path | None = None,
        context: str | None = None,
    ):
        """Initialize scaffolder.

        Args:
            intent: Parsed intent to scaffold from.
            repo_path: Path to the target repository.
            governor_root: Override governor root (for testing).
            context: Additional context content to include.
        """
        self.intent = intent
        self.repo_path = repo_path
        self.governor_root = governor_root or Path.home() / ".local" / "local-governor"
        self.context = context
        self.build_yaml = self._load_build_yaml()

    def _load_build_yaml(self) -> dict[str, Any] | None:
        """Find and load build.yaml for repo.

        Checks these locations in order:
        1. governor/projects/{repo_name}/{repo_name}.build.yaml
        2. {repo_path}/.specwright/build.yaml (legacy)
        3. {repo_path}/build.yaml (simple)

        Returns:
            Parsed build.yaml dict, or None if not found.
        """
        repo_name = self.repo_path.name

        governor_build = (
            self.governor_root / "projects" / repo_name / f"{repo_name}.build.yaml"
        )
        if governor_build.exists():
            return yaml.safe_load(governor_build.read_text())

        legacy_build = self.repo_path / ".specwright" / "build.yaml"
        if legacy_build.exists():
            return yaml.safe_load(legacy_build.read_text())

        simple_build = self.repo_path / "build.yaml"
        if simple_build.exists():
            return yaml.safe_load(simple_build.read_text())

        return None

    def scaffold(self, num_phases: int = 2) -> str:
        """Generate scaffolded spec as YAML (spec-v2.1 format)."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        branch = self.intent.branch or f"feat/{self.intent.id}"
        tier = (self.intent.tier or "B").upper()

        spec = {
            "artifact_id": "",
            "name": self.intent.id,
            "version": "0.1.0",
            "kind": "spec",
            "title": self.intent.title,
            "epic_artifact_id": "",
            "tier": tier,
            "owner": self.intent.owner or "TODO",
            "goal": self.intent.goal,
            "objective": "TODO: describe the objective",
            "key_decisions": [],
            "forbidden_legacy_semantics": [],
            "phases": [
                {
                    "phase_number": i,
                    "title": "TODO",
                    "objective": "TODO",
                    "files_to_touch": [],
                    "notes": "",
                    "verification": [],
                }
                for i in range(1, num_phases + 1)
            ],
            "acceptance_criteria": [
                {"text": c, "status": "pending"}
                for c in (self.intent.expectations or ["TODO"])
            ],
            "constraints": self.intent.constraints or ["TODO"],
            "dependencies": [],
            "labels": [],
            "repo": {
                "name": self.repo_path.name,
                "url": str(self.repo_path),
                "working_branch": branch,
            },
            "created": now,
            "updated": now,
            "metadata": {},
        }
        return yaml.dump(
            spec,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
