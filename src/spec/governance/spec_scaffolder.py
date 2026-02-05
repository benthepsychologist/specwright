"""Spec scaffolder for generating scaffolded specs from intents.

Generates properly-structured specs from intent documents, grounded in
the current build.yaml and explicit about build_delta changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from spec.governance.intent_parser import ParsedIntent


class SpecScaffolder:
    """Generate scaffolded specs from intents."""

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

        # Check governor location first
        governor_build = (
            self.governor_root / "projects" / repo_name / f"{repo_name}.build.yaml"
        )
        if governor_build.exists():
            return yaml.safe_load(governor_build.read_text())

        # Check legacy location
        legacy_build = self.repo_path / ".specwright" / "build.yaml"
        if legacy_build.exists():
            return yaml.safe_load(legacy_build.read_text())

        # Check simple location
        simple_build = self.repo_path / "build.yaml"
        if simple_build.exists():
            return yaml.safe_load(simple_build.read_text())

        return None

    def scaffold(self, num_phases: int = 2) -> str:
        """Generate scaffolded spec markdown.

        Args:
            num_phases: Number of placeholder phases to generate.

        Returns:
            Complete spec markdown string.
        """
        sections = [
            self._render_frontmatter(),
            self._render_header(),
            self._render_objective(),
            self._render_problem(),
            self._render_current_capabilities(),
            self._render_proposed_build_delta(),
            self._render_acceptance_criteria(),
            self._render_constraints(),
            "---",
            *[self._render_phase(i) for i in range(1, num_phases + 1)],
        ]
        return "\n\n".join(sections)

    def _render_frontmatter(self) -> str:
        """Render YAML frontmatter."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        branch = self.intent.branch or f"feat/{self.intent.id}"

        lines = [
            "---",
            f"id: {self.intent.id}",
            f'title: "{self.intent.title}"',
            f"tier: {self.intent.tier or 'B'}",
            f"owner: {self.intent.owner or 'TODO'}",
            f'goal: "{self.intent.goal}"',
            f"branch: {branch}",
            "status: draft",
            f"created: {now}",
            "---",
        ]
        return "\n".join(lines)

    def _render_header(self) -> str:
        """Render spec header with title and metadata."""
        branch = self.intent.branch or f"feat/{self.intent.id}"
        epic_id = self.intent.epic_id or "TODO"
        tier = self.intent.tier or "B"

        return f"""# {self.intent.id}: {self.intent.title}

**Epic:** {epic_id}
**Branch:** `{branch}`
**Tier:** {tier}"""

    def _render_objective(self) -> str:
        """Render objective section."""
        goal = self.intent.goal or "TODO: Define the goal"

        return f"""## Objective

> {goal}

<!-- TODO: Expand with 2-3 paragraphs explaining what we're building and why -->"""

    def _render_problem(self) -> str:
        """Render problem section."""
        return """## Problem

<!-- TODO: List numbered problems with the current state -->
1. ...
2. ..."""

    def _render_current_capabilities(self) -> str:
        """Render Current Capabilities section from build.yaml."""
        capabilities = self._format_current_capabilities()

        return f"""## Current Capabilities

{capabilities}"""

    def _format_current_capabilities(self) -> str:
        """Format kernel.surfaces, modules, layout for spec."""
        if not self.build_yaml:
            return "<!-- No build.yaml found for this repository -->"

        sections: list[str] = []

        # kernel.surfaces
        kernel = self.build_yaml.get("kernel", {})
        surfaces = kernel.get("surfaces", [])
        if surfaces:
            entries: list[str] = []
            for surface in surfaces:
                for ep in surface.get("entrypoints", []):
                    cmd = ep.get("command", "")
                    entries.append(f'- command: "{cmd}"')
                    if ep.get("usage"):
                        entries.append(f'  usage: "{ep["usage"]}"')
            if entries:
                sections.append(
                    "### kernel.surfaces\n\n```yaml\n" + "\n".join(entries) + "\n```"
                )

        # modules
        modules = self.build_yaml.get("modules", [])
        if modules:
            entries = []
            for m in modules[:10]:  # Limit to 10
                name = m.get("name", "unknown")
                provides = m.get("provides", [])
                entries.append(f"- name: {name}")
                entries.append(f"  provides: {provides}")
            if entries:
                sections.append(
                    "### modules\n\n```yaml\n" + "\n".join(entries) + "\n```"
                )

        # layout
        layout = self.build_yaml.get("layout", [])
        if layout:
            entries = []
            for item in layout[:10]:  # Limit to 10
                path = item.get("path", "")
                entries.append(f"- path: {path}")
                if item.get("role"):
                    entries.append(f'  role: "{item["role"]}"')
            if entries:
                sections.append("### layout\n\n```yaml\n" + "\n".join(entries) + "\n```")

        if not sections:
            return "<!-- build.yaml has no kernel/modules/layout -->"

        return "\n\n".join(sections)

    def _render_proposed_build_delta(self) -> str:
        """Render proposed build_delta section."""
        # Determine target build.yaml path
        repo_name = self.repo_path.name
        if self.build_yaml:
            target = f"projects/{repo_name}/{repo_name}.build.yaml"
        else:
            target = f"projects/{repo_name}/{repo_name}.build.yaml  # TODO: verify path"

        return f"""## Proposed build_delta

```yaml
target: "{target}"
summary: "TODO: One-line summary of structural changes"

adds:
  layout: []
  modules: []
  kernel_surfaces: []
modifies: {{}}
removes: {{}}
```

<!-- TODO: Fill in structural changes this spec makes.
     The build_delta is the real constraint:
     - adds.layout drives files_to_touch
     - adds.kernel_surfaces drives acceptance criteria
     - adds.modules drives verification commands
-->"""

    def _render_acceptance_criteria(self) -> str:
        """Render acceptance criteria section."""
        criteria = self.intent.expectations or ["TODO: Add acceptance criteria"]
        items = "\n".join(f"- [ ] {c}" for c in criteria)
        return f"## Acceptance Criteria\n\n{items}"

    def _render_constraints(self) -> str:
        """Render constraints section."""
        constraints = self.intent.constraints or ["TODO: Add constraints"]
        items = "\n".join(f"- {c}" for c in constraints)
        return f"## Constraints\n\n{items}"

    def _render_phase(self, n: int) -> str:
        """Render a placeholder phase section."""
        return f"""## Phase {n}: [Title]

### Objective
<!-- TODO: What this phase accomplishes -->

### Files to Touch
<!-- TODO: Derive from build_delta -->
- `path/to/file.py` (create|modify) — description

### Implementation Notes
<!-- TODO: How to implement, patterns to follow -->

### Verification
<!-- TODO: Commands and expected outcomes -->
- `pytest tests/...` → passes
- `ruff check src/` → clean"""
