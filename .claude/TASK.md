---
id: t004-04-spec-draft
title: "Spec draft: scaffolded spec generation from intents with build.yaml context"
tier: B
owner: benthepsychologist
goal: "Add spec draft command that generates properly-structured specs from intent documents, grounded in current build.yaml and explicit about build_delta changes"
branch: feat/spec-draft
status: draft
---

# t004-04: spec draft — Scaffolded spec generation from intent documents

**Epic:** t004-specwright-governance
**Branch:** `feat/spec-draft`
**Tier:** B

## Objective

Add a `spec draft` command that generates properly-structured specs from minimal intent documents. The output conforms to `spec-v1.0.schema.json` and includes the current build.yaml context plus a proposed `build_delta` section. This ensures specs are grounded in what exists and explicit about what they're changing.

## Problem

1. **Specs are disconnected from build.yaml.** Authors write specs without seeing current capabilities. This leads to:
   - Proposed features that duplicate existing functionality
   - Missing context about module boundaries
   - build_deltas that conflict with current state

2. **No scaffolding enforces schema compliance.** The spec schema requires frontmatter, phases, files_to_touch, verification — but nothing generates this structure automatically.

3. **Intent documents aren't specs.** Epic entries have expectations and constraints, but these are prompts, not implementation plans. The gap between intent and executable spec is filled ad-hoc.

## Current Capabilities (from specwright.build.yaml)

### kernel.surfaces

```yaml
- command: "spec compile"
  usage: "spec compile aip-1 ./my-feature.md"
- command: "spec run"
  usage: "spec run aip-1 ./my-feature.md --repo /workspace/target"
- command: "spec create"
  usage: "spec create 'feature name' --tier C"
- command: "spec validate spec"
  usage: "spec validate spec ./my-feature.md"
- command: "spec validate build"
  usage: "spec validate build specwright [--json] [--fix]"
- command: "spec validate epic"
  usage: "spec validate epic t004 [--json]"
- command: "spec finish"
  usage: "spec finish <spec-id> [--dry-run]"
```

### modules

```yaml
- name: governance
  kind: module
  provides: ["build validation", "epic validation", "contract validation"]
  depends_on: [governor, epic]
- name: cli
  kind: entrypoint
  provides: ["spec command-line interface"]
  depends_on: [executor, epic, governance, compiler, core]
```

### layout

```yaml
- path: src/spec/cli/
  module: cli
  role: "Typer CLI commands and subcommand registration"
- path: src/spec/governance/
  module: governance
  role: "Build, epic, and contract validation"
```

## Proposed build_delta

```yaml
build_delta:
  target: "projects/specwright/specwright.build.yaml"
  summary: "Add spec draft command for scaffolded spec generation from intents"

  adds:
    kernel_surfaces:
      - command: "spec draft"
        usage: "spec draft <intent> [--repo <path>] [--llm] [--output <path>]"
        description: "Generate scaffolded spec from intent document or epic entry"

  modifies:
    modules:
      - name: governance
        provides:
          - "build validation"
          - "epic validation"
          - "contract validation"
          - "spec scaffolding"      # NEW
          - "intent parsing"        # NEW

    layout:
      - path: src/spec/governance/
        adds:
          - intent_parser.py        # NEW
          - spec_scaffolder.py      # NEW
          - spec_drafter.py         # NEW (LLM mode)

  removes: {}
```

## Acceptance Criteria

**spec draft \<intent\> [--repo \<path\>]:**
- [ ] Parses intent from markdown file or epic spec entry
- [ ] Loads current build.yaml for target repo
- [ ] Generates spec with valid frontmatter (per spec-v1.0.schema.json)
- [ ] Includes "Current Capabilities" section with kernel.surfaces, modules, layout
- [ ] Includes "Proposed build_delta" section formatted for `spec finish` consumption
- [ ] Templates phases with required subsections: Objective, Files to Touch, Verification
- [ ] Prints to stdout by default; `--output <path>` writes to file

**spec draft \<intent\> --llm:**
- [ ] Does all scaffolding first
- [ ] Launches Claude Code with read-only tools to explore repo
- [ ] Fills in Problem section, Context, files_to_touch, implementation notes
- [ ] Proposes concrete build_delta based on exploration

**Epic entry support:**
- [ ] `spec draft t005/t005-03` loads intent from epic spec entry
- [ ] Auto-resolves repo path from epic.targets
- [ ] Uses epic.expectations as acceptance criteria source

**Schema compliance:**
- [ ] Output validates against spec-v1.0.schema.json
- [ ] Frontmatter has required fields: tier, title, owner, goal
- [ ] At least one phase with objective

## Constraints

- build_delta is the real constraint — files_to_touch and acceptance criteria derive from it
- Scaffolding mode (default) is deterministic — no LLM calls
- LLM mode uses read-only tool allowlist — no file writes during exploration
- Output validates against spec-v1.0.schema.json

## Context

### What a scaffolded spec looks like

Input intent (t005-03 from epic):
```yaml
- id: t005-03-workstation-containers
  title: "Workstation containers: life + dev"
  repo: vm-workstation-manager
  expectations:
    - "life container starts reliably"
    - "dev container starts reliably"
  constraints:
    - "Maintain trust gradient: agent < life < dev"
```

Output from `spec draft t005/t005-03`:

```markdown
---
id: t005-03-workstation-containers
title: "Workstation containers: life + dev"
tier: B
owner: benthepsychologist
goal: "life container starts reliably"
branch: feat/t005-03-workstation-containers
---

# t005-03: Workstation containers: life + dev

**Epic:** t005-vmctl-docker-isolation
**Branch:** `feat/t005-03-workstation-containers`
**Tier:** B

## Objective

> life container starts reliably

<!-- TODO: Expand objective -->

## Problem

<!-- TODO: What's wrong with current state -->

## Current Capabilities

### kernel.surfaces (from vm-workstation-manager.build.yaml)

\`\`\`yaml
- command: "vmctl up"
- command: "vmctl ps"
- command: "vmctl logs"
\`\`\`

### modules

\`\`\`yaml
- name: compose
  provides: ["agent app", "gateway app"]
\`\`\`

### layout

\`\`\`yaml
- path: compose/
  contains: [agent/, gateway/]
- path: vmctl/
  contains: [cli.py, commands/]
\`\`\`

## Proposed build_delta

\`\`\`yaml
adds:
  layout:
    - path: compose/life/
      description: "Life container compose config"
    - path: compose/dev/
      description: "Dev container compose config"
  modules:
    - name: life
      kind: compose-app
      provides: ["operator environment"]
    - name: dev
      kind: compose-app
      provides: ["builder environment"]
modifies: {}
removes: {}
\`\`\`

## Acceptance Criteria

- [ ] life container starts reliably
- [ ] dev container starts reliably

## Constraints

- Maintain trust gradient: agent < life < dev

---

## Phase 1: [Title]

### Objective
<!-- TODO -->

### Files to Touch
<!-- Derived from build_delta.adds.layout -->
- \`compose/life/docker-compose.yaml\` (create)
- \`compose/dev/docker-compose.yaml\` (create)

### Implementation Notes
<!-- TODO -->

### Verification
<!-- TODO: Commands to verify phase completion -->
```

### Why build_delta is the constraint

The build_delta defines:
1. **What capabilities are added** → drives acceptance criteria
2. **What modules are touched** → drives files_to_touch
3. **What surfaces are exposed** → drives verification (test the new commands)

Everything in the spec should trace back to the build_delta. If it's not in the delta, it's not in scope.

---

## Phase 1: Intent parser

### Objective
Parse intent from markdown files and epic spec entries into a structured format.

### Files to Touch
- `src/spec/governance/intent_parser.py` (create) — IntentParser class and ParsedIntent dataclass
- `tests/governance/test_intent_parser.py` (create) — unit tests for both parse methods

### Implementation Notes

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml
import re

@dataclass
class ParsedIntent:
    """Structured intent extracted from markdown or epic entry."""
    id: str
    title: str
    goal: str
    tier: str | None = None
    owner: str | None = None
    branch: str | None = None
    epic_id: str | None = None
    repo_id: str | None = None
    expectations: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    raw_content: str = ""

class IntentParser:
    """Parse intent from various sources."""

    def parse_markdown(self, content: str) -> ParsedIntent:
        """Parse markdown intent (YAML frontmatter + body)."""
        # Extract frontmatter
        if content.startswith("---\n"):
            end = content.find("\n---\n", 4)
            if end != -1:
                fm = yaml.safe_load(content[4:end])
                body = content[end + 5:]
            else:
                fm, body = {}, content
        else:
            fm, body = {}, content

        # Extract sections from body
        expectations = self._extract_bullets(body, "Acceptance Criteria")
        constraints = self._extract_bullets(body, "Constraints")

        return ParsedIntent(
            id=fm.get("id", ""),
            title=fm.get("title", ""),
            goal=fm.get("goal", expectations[0] if expectations else ""),
            tier=fm.get("tier"),
            owner=fm.get("owner"),
            branch=fm.get("branch"),
            expectations=expectations,
            constraints=constraints,
            raw_content=content,
        )

    def parse_epic_entry(self, epic: "Epic", spec_id: str) -> ParsedIntent:
        """Parse epic spec entry as intent."""
        spec = next((s for s in epic.specs if s.id == spec_id), None)
        if not spec:
            raise ValueError(f"Spec {spec_id} not found in epic {epic.id}")

        return ParsedIntent(
            id=spec.id,
            title=spec.title,
            goal=spec.expectations[0] if spec.expectations else "",
            branch=spec.branch,
            epic_id=epic.id,
            repo_id=spec.repo,
            expectations=spec.expectations,
            constraints=spec.constraints,
        )

    def _extract_bullets(self, content: str, section: str) -> list[str]:
        """Extract bullet points from a section."""
        pattern = rf"##\s+{section}.*?\n((?:[-*]\s+.+\n?)+)"
        match = re.search(pattern, content, re.IGNORECASE)
        if not match:
            return []
        return [line.lstrip("-* ").strip() for line in match.group(1).strip().split("\n") if line.strip()]
```

### Verification
- `pytest tests/governance/test_intent_parser.py -v`
- `python -c "from spec.governance.intent_parser import IntentParser; print('OK')"`
- Parse markdown with frontmatter → extracts id, title, goal, expectations
- Parse markdown without frontmatter → extracts from body sections
- Parse epic entry → extracts all specRef fields

---

## Phase 2: Build.yaml loader for scaffolding

### Objective
Load and format build.yaml for inclusion in scaffolded specs.

### Files to Touch
- `src/spec/governance/spec_scaffolder.py` (create) — SpecScaffolder class with build.yaml loading
- `src/spec/governance/__init__.py` (modify) — export IntentParser, SpecScaffolder

### Implementation Notes

```python
from pathlib import Path
from typing import Any
import yaml

class SpecScaffolder:
    """Generate scaffolded specs from intents."""

    def __init__(
        self,
        intent: ParsedIntent,
        repo_path: Path,
        governor_root: Path | None = None,
    ):
        self.intent = intent
        self.repo_path = repo_path
        self.governor_root = governor_root or Path.home() / ".local" / "local-governor"
        self.build_yaml = self._load_build_yaml()

    def _load_build_yaml(self) -> dict[str, Any] | None:
        """Find and load build.yaml for repo."""
        repo_name = self.repo_path.name

        # Check governor location first
        governor_build = self.governor_root / "projects" / repo_name / f"{repo_name}.build.yaml"
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

    def _format_current_capabilities(self) -> str:
        """Format kernel.surfaces, modules, layout for spec."""
        if not self.build_yaml:
            return "<!-- No build.yaml found for this repository -->"

        sections = []

        # kernel.surfaces
        kernel = self.build_yaml.get("kernel", {})
        surfaces = kernel.get("surfaces", [])
        if surfaces:
            entries = []
            for surface in surfaces:
                for ep in surface.get("entrypoints", []):
                    entries.append(f"- command: \"{ep.get('command', '')}\"")
                    if ep.get("usage"):
                        entries.append(f"  usage: \"{ep['usage']}\"")
            sections.append("### kernel.surfaces\n\n```yaml\n" + "\n".join(entries) + "\n```")

        # modules
        modules = self.build_yaml.get("modules", [])
        if modules:
            entries = []
            for m in modules[:10]:  # Limit to 10
                entries.append(f"- name: {m.get('name')}")
                entries.append(f"  provides: {m.get('provides', [])}")
            sections.append("### modules\n\n```yaml\n" + "\n".join(entries) + "\n```")

        # layout
        layout = self.build_yaml.get("layout", [])
        if layout:
            entries = []
            for l in layout[:10]:  # Limit to 10
                entries.append(f"- path: {l.get('path')}")
                if l.get("role"):
                    entries.append(f"  role: \"{l['role']}\"")
            sections.append("### layout\n\n```yaml\n" + "\n".join(entries) + "\n```")

        return "\n\n".join(sections) if sections else "<!-- build.yaml has no kernel/modules/layout -->"
```

### Verification
- `pytest tests/governance/test_spec_scaffolder.py::test_load_build_yaml -v`
- Load specwright.build.yaml → extracts surfaces, modules, layout
- Repo with governor-layout build.yaml → found and loaded
- Repo without build.yaml → returns None, graceful fallback message

---

## Phase 3: Spec scaffolder output

### Objective
Generate complete scaffolded spec markdown from intent + build.yaml.

### Files to Touch
- `src/spec/governance/spec_scaffolder.py` (modify) — add scaffold() and render methods
- `tests/governance/test_spec_scaffolder.py` (create) — full scaffold tests

### Implementation Notes

```python
from datetime import datetime, timezone

def scaffold(self, num_phases: int = 2) -> str:
    """Generate scaffolded spec markdown."""
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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""---
id: {self.intent.id}
title: "{self.intent.title}"
tier: {self.intent.tier or "B"}
owner: {self.intent.owner or "TODO"}
goal: "{self.intent.goal}"
branch: {self.intent.branch or f"feat/{self.intent.id}"}
status: draft
created: {now}
---"""

def _render_header(self) -> str:
    return f"""# {self.intent.id}: {self.intent.title}

**Epic:** {self.intent.epic_id or "TODO"}
**Branch:** `{self.intent.branch or f"feat/{self.intent.id}"}`
**Tier:** {self.intent.tier or "B"}"""

def _render_objective(self) -> str:
    return f"""## Objective

> {self.intent.goal}

<!-- TODO: Expand with 2-3 paragraphs explaining what we're building and why -->"""

def _render_problem(self) -> str:
    return """## Problem

<!-- TODO: List numbered problems with the current state -->
1. ...
2. ..."""

def _render_proposed_build_delta(self) -> str:
    return """## Proposed build_delta

```yaml
adds:
  layout: []
  modules: []
  kernel_surfaces: []
modifies: {}
removes: {}
```

<!-- TODO: Fill in structural changes this spec makes -->"""

def _render_acceptance_criteria(self) -> str:
    criteria = self.intent.expectations or ["TODO: Add acceptance criteria"]
    items = "\n".join(f"- [ ] {c}" for c in criteria)
    return f"## Acceptance Criteria\n\n{items}"

def _render_constraints(self) -> str:
    constraints = self.intent.constraints or ["TODO: Add constraints"]
    items = "\n".join(f"- {c}" for c in constraints)
    return f"## Constraints\n\n{items}"

def _render_phase(self, n: int) -> str:
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
```

### Verification
- `pytest tests/governance/test_spec_scaffolder.py -v`
- Scaffold from intent → has valid YAML frontmatter
- Scaffold includes Current Capabilities from build.yaml
- Scaffold includes Proposed build_delta template
- Scaffold has acceptance criteria from intent.expectations
- Scaffold has constraints from intent.constraints
- Scaffold has N phases with all required subsections

---

## Phase 4: CLI command

### Objective
Wire scaffolder into `spec draft` CLI command.

### Files to Touch
- `src/spec/cli/draft.py` (create) — spec draft command implementation
- `src/spec/cli/spec.py` (modify) — import and register draft command
- `tests/cli/test_draft.py` (create) — CLI integration tests

### Implementation Notes

```python
"""spec draft command: generate scaffolded specs from intents."""

from pathlib import Path
import typer
from rich.console import Console

console = Console()

def spec_draft(
    intent: str = typer.Argument(
        ...,
        help="Path to intent.md OR epic/spec-id (e.g., t005/t005-03)",
    ),
    repo: Path | None = typer.Option(
        None, "--repo", "-r",
        help="Target repository path (auto-detected for epic entries)",
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o",
        help="Output file path (default: stdout)",
    ),
    phases: int = typer.Option(
        2, "--phases",
        help="Number of placeholder phases to generate",
    ),
    llm: bool = typer.Option(
        False, "--llm",
        help="Use LLM to fill in details (requires llm.enabled)",
    ),
) -> None:
    """Draft a spec from an intent document or epic entry.

    Generates a scaffolded spec with:
    - Valid frontmatter (tier, title, owner, goal)
    - Current Capabilities from target build.yaml
    - Proposed build_delta section
    - Acceptance criteria from intent
    - Placeholder phases ready to fill in

    Examples:
        spec draft intent.md --repo /workspace/myproject
        spec draft t005/t005-03
        spec draft t005/t005-03 --output specs/t005-03.md
        spec draft t005/t005-03 --llm
    """
    from spec.governance.intent_parser import IntentParser
    from spec.governance.spec_scaffolder import SpecScaffolder

    # Load intent
    parsed_intent, resolved_repo = _load_intent(intent, repo)

    console.print(f"[bold]Drafting spec:[/] {parsed_intent.title}")
    console.print(f"[bold]Target repo:[/] {resolved_repo}")

    # Scaffold
    scaffolder = SpecScaffolder(parsed_intent, resolved_repo)
    spec_md = scaffolder.scaffold(num_phases=phases)

    # LLM mode
    if llm:
        from spec.governance.spec_drafter import SpecDrafter
        drafter = SpecDrafter(scaffolder, model="claude-sonnet-4-20250514")
        with console.status("Claude Code is exploring and drafting..."):
            spec_md = drafter.draft()

    # Output
    if output:
        output.write_text(spec_md)
        console.print(f"[green]✓[/] Wrote spec to {output}")
    else:
        console.print(spec_md)


def _load_intent(intent_arg: str, repo_override: Path | None) -> tuple:
    """Load intent from file or epic entry."""
    from spec.governance.intent_parser import IntentParser, ParsedIntent
    from spec.governor.resolver import resolve_spec
    from spec.epic.loader import load_epic

    parser = IntentParser()

    # Check if it's a file path
    intent_path = Path(intent_arg)
    if intent_path.exists() and intent_path.suffix == ".md":
        content = intent_path.read_text()
        parsed = parser.parse_markdown(content)
        if repo_override is None:
            raise typer.BadParameter("--repo is required for file-based intents")
        return parsed, repo_override

    # Try to resolve as epic/spec
    try:
        epic_dir, spec_id = resolve_spec(intent_arg)
        epic = load_epic(epic_dir / "epic.yaml")
        parsed = parser.parse_epic_entry(epic, spec_id)

        # Get repo path from epic targets
        spec_entry = next(s for s in epic.specs if s.id == spec_id)
        target = next(t for t in epic.targets if t.id == spec_entry.repo)
        repo_path = Path(target.repo_path).expanduser()

        return parsed, repo_override or repo_path
    except Exception as e:
        raise typer.BadParameter(f"Could not load intent '{intent_arg}': {e}")
```

### Verification
- `spec draft --help` → shows usage
- `spec draft intent.md --repo /workspace/foo` → prints scaffolded spec
- `spec draft t005/t005-03` → loads from epic, auto-resolves repo, prints scaffold
- `spec draft t005/t005-03 --output spec.md` → writes to file
- `spec draft intent.md` (no --repo) → error with helpful message
- `spec draft nonexistent` → error listing how to specify intent

---

## Phase 5: LLM-assisted mode

### Objective
Add `--llm` flag to fill in scaffolded spec using Claude Code exploration.

### Files to Touch
- `src/spec/governance/spec_drafter.py` (create) — LLM drafting logic
- `src/spec/cli/draft.py` (modify) — wire --llm flag (already stubbed in Phase 4)
- `tests/governance/test_spec_drafter.py` (create) — LLM mode tests

### Implementation Notes

Two-stage drafting: scaffold first, then ask LLM to fill TODOs.

```python
"""LLM-assisted spec drafting using Claude Code."""

import subprocess
import os
import signal
from pathlib import Path

DRAFTING_ALLOWLIST = [
    "Read", "Glob", "Grep",
    "Bash(ls:*)", "Bash(find:*)", "Bash(tree:*)",
    "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)",
    "Bash(wc:*)",
    "Bash(git status:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(git diff:*)", "Bash(git ls-files:*)",
]

class SpecDrafter:
    """LLM-assisted spec drafting."""

    def __init__(
        self,
        scaffolder: "SpecScaffolder",
        model: str = "claude-sonnet-4-20250514",
        timeout_s: int = 600,
        max_turns: int = 50,
    ):
        self.scaffolder = scaffolder
        self.model = model
        self.timeout_s = timeout_s
        self.max_turns = max_turns

    def draft(self) -> str:
        """Generate full spec with LLM assistance."""
        # Stage 1: Generate scaffold
        scaffold = self.scaffolder.scaffold()

        # Stage 2: Ask LLM to fill in TODOs
        prompt = self._build_prompt(scaffold)
        filled = self._call_claude_code(prompt)

        return filled

    def _build_prompt(self, scaffold: str) -> str:
        return f"""You have a scaffolded spec that needs to be completed.
Your job is to explore the codebase and fill in the TODO sections.

## Scaffolded Spec

{scaffold}

## Your Task

1. Explore the repository to understand the current state
2. Fill in the Problem section with real issues you discover
3. Fill in each Phase with:
   - Concrete objective
   - Real file paths (files_to_touch)
   - Implementation notes based on existing patterns
   - Verification commands from the repo (pytest, ruff, etc.)
4. Propose build_delta changes if the spec adds new structure

Output the complete, filled-in spec. Keep all the scaffolded content
that's already correct (frontmatter, acceptance criteria, constraints).
Replace TODO comments with real content.

Output ONLY the spec markdown, nothing else."""

    def _call_claude_code(self, prompt: str) -> str:
        """Call Claude Code in headless mode with read-only tools."""
        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--output-format", "text",
            "--allowedTools", ",".join(DRAFTING_ALLOWLIST),
            "--max-turns", str(self.max_turns),
            "--model", self.model,
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=self.scaffolder.repo_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        try:
            stdout, stderr = proc.communicate(input=prompt, timeout=self.timeout_s)
            if proc.returncode != 0:
                raise RuntimeError(f"Claude Code failed: {stderr}")
            return stdout
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait()
            raise RuntimeError(f"Claude Code timed out after {self.timeout_s}s")
```

### Verification
- `spec draft t005/t005-03 --llm` → launches Claude Code, returns filled spec
- LLM can read files (Read, Glob, Grep) but not write
- LLM can run read-only bash commands
- Timeout kills runaway sessions after 600s
- `--llm` without claude CLI → helpful error message
- `ruff check src/spec/governance/` → clean
- `pytest tests/governance/test_spec_drafter.py -v` → passes
