---
id: t004-06-cli-cleanup-llm-drafting
title: "CLI cleanup: LLM-assisted epic/spec drafting, remove legacy commands"
tier: B
owner: benthepsychologist
goal: "Clean CLI with LLM-assisted epic creation and spec addition, remove legacy trash"
branch: feat/cli-cleanup-llm-drafting
status: draft
validated: false
---

# t004-06: CLI cleanup and LLM-assisted epic/spec drafting

**Epic:** t004-specwright-governance
**Branch:** `feat/cli-cleanup-llm-drafting`
**Tier:** B

## Objective

Clean up the specwright CLI by:
1. Adding `--llm` mode to `spec epic create` for LLM-assisted epic drafting
2. Adding `--llm` mode to `spec epic add-spec` for LLM-assisted spec entry drafting (supports multiple specs)
3. Adding a per-spec execution recommendation (`mode: interactive|headless`) to epic entries
4. Removing legacy/unused commands
5. Simplifying `spec init` and `spec config`

## Problem

1. **Epic creation is manual and disconnected from codebase.** `spec epic create` only makes a skeleton. Authors must manually write the narrative, figure out what specs are needed, define expectations/constraints, and understand dependencies. Nothing crawls the repo to understand the problem.

2. **Adding specs to epics requires knowing everything upfront.** `spec epic add-spec` requires all fields (--id, --repo, --branch, --path, --expectation). Authors must manually determine what expectations make sense, what constraints apply, and how specs depend on each other.

3. **CLI is cluttered with legacy commands.** Commands like `spec create`, `spec spec-compile`, `spec gate-list`, `spec gate-report`, `spec materialize`, `spec migrate`, `spec list` are unused or superseded. They confuse users and add maintenance burden.

4. **`spec init` does too much.** Creates directories that aren't used (tmp, runs, artifacts), copies stale GUIDE.md, has legacy mode that should be removed.

## Current Capabilities

### kernel.surfaces (relevant subset)

```yaml
- command: "spec epic create"
  usage: "spec epic create <title> --goal <goal>"
  description: "Create skeleton epic directory and epic.yaml"

- command: "spec epic add-spec"
  usage: "spec epic add-spec <epic-id> --id <spec-id> --repo <repo> --branch <branch> ..."
  description: "Add spec entry to epic (fully manual)"

- command: "spec draft"
  usage: "spec draft <spec-ref> [--llm]"
  description: "Draft full spec.md from epic entry"

- command: "spec init"
  usage: "spec init [--governor <path>] [--claude/--no-claude]"
  description: "Initialize specwright in repo"

- command: "spec config"
  usage: "spec config <key> <value>"
  description: "Set config values (user, tier, current.spec, etc.)"
```

### modules

```yaml
- name: cli
  provides: ['spec command-line interface']
- name: governance
  provides: ['build validation', 'epic validation', 'contract validation', 'spec scaffolding', 'intent parsing', 'LLM-assisted drafting']
- name: epic
  provides: ['epic loading', 'epic schema', 'DAG validation', 'epic writing']
```

## Proposed build_delta

```yaml
build_delta:
  target: "projects/specwright/specwright.build.yaml"
  summary: "Add LLM-assisted epic/spec drafting, remove legacy CLI commands"

  adds:
    layout:
      - path: src/spec/governance/epic_drafter.py
        role: "LLM-assisted epic drafting (crawl repo, generate narrative + specs)"
      - path: src/spec/governance/spec_entry_drafter.py
        role: "LLM-assisted spec entry drafting for epic.yaml"
      - path: tests/governance/test_epic_drafter.py
        role: "Epic drafter tests"
      - path: tests/governance/test_spec_entry_drafter.py
        role: "Spec entry drafter tests"

  modifies:
    modules:
      governance:
        provides:
          - "build validation"
          - "epic validation"
          - "contract validation"
          - "spec scaffolding"
          - "intent parsing"
          - "LLM-assisted spec drafting"
          - "LLM-assisted epic drafting"      # NEW
          - "LLM-assisted spec entry drafting" # NEW

    kernel_surfaces:
      - command: "spec epic create"
        usage: "spec epic create <title> --goal <goal> --owner <owner> [--llm] [--context <file>] [--model <model>]"
        description: "Create epic. Skeleton by default, LLM-assisted with --llm"

      - command: "spec epic add-spec"
        usage: "spec epic add-spec <epic-id> <description> [--llm] [--context <file>] [--target <target-id>]"
        description: "Add spec(s) to epic. --llm crawls repo and drafts expectations/constraints"

    cli:
      - file: src/spec/cli/epic.py
        changes: "Add --llm and --context to create (no --repo); change add-spec to accept description + --llm; add per-spec mode recommendation"
      - file: src/spec/cli/spec.py
        changes: "Remove legacy commands, simplify init"

  removes:
    kernel_surfaces:
      - command: "spec create"
        reason: "Superseded by spec draft"
      - command: "spec spec-compile"
        reason: "v1 authoring, obsolete"
      - command: "spec gate-list"
        reason: "AIP gate tracking, never used"
      - command: "spec gate-report"
        reason: "AIP gate tracking, never used"
      - command: "spec materialize"
        reason: "Governor materialization, rarely used"
      - command: "spec migrate"
        reason: "One-time migration tool, no longer needed"
      - command: "spec list"
        reason: "Confusing (lists specs/AIPs not epics), use spec epic list"

    cli:
      - file: src/spec/cli/spec.py
        removes:
          - "create command"
          - "spec_compile command"
          - "gate_list command"
          - "gate_report command"
          - "materialize command"
          - "migrate command"
          - "list_specs command"
          - "RiskTier enum"
          - "get_next_aip_id function"
          - "get_template_path function"
          - "get_schema_path function"
          - "legacy config helpers"
```

## Acceptance Criteria

**Epic creation with LLM:**
- [ ] `spec epic create "Title" --goal "..." --owner "..."` creates a skeleton epic (no repo-path flags)
- [ ] `spec epic create "Title" --goal "..." --owner "..." --llm` crawls the current working repository (and any already-known targets, if present) and generates:
  - Meaningful `intent.narrative` explaining the problem
  - Initial `specs` list with expectations/constraints
  - Proper `depends_on` relationships between specs
- [ ] Each generated spec entry includes `mode: interactive|headless` recommendation
- [ ] `--context <file>` accepts additional guidance (existing epic to clean up, notes, etc.)
- [ ] Output is valid epic.yaml that passes `spec validate epic`

**Spec entry addition with LLM:**
- [ ] `spec epic add-spec t004 "description of work"` fails without --llm (needs either manual fields or LLM)
- [ ] `spec epic add-spec t004 "description" --llm` crawls repo and generates one or more spec entries:
  - Sensible `id`, `title`, `branch` naming
  - `expectations` derived from codebase understanding
  - `constraints` based on architectural boundaries
  - `depends_on` figured out from existing specs
  - `path` pointing to where spec.md will go
- [ ] Generated spec entries include `mode: interactive|headless` recommendation
- [ ] Can generate multiple specs from one description ("break this feature into specs")
- [ ] Manual mode still works: `spec epic add-spec t004 --id ... --repo ... --branch ... --path ... --mode headless`

**Legacy cleanup:**
- [ ] `spec create` removed
- [ ] `spec spec-compile` removed
- [ ] `spec gate-list` removed
- [ ] `spec gate-report` removed
- [ ] `spec materialize` removed
- [ ] `spec migrate` removed
- [ ] `spec list` removed
- [ ] Associated dead code removed (RiskTier, get_next_aip_id, templates, etc.)

**Init/config simplification:**
- [ ] `spec init --legacy-mode` removed
- [ ] `spec init` only: creates .specwright.yaml, installs the two default JobDefs, optionally installs slash commands
- [ ] No more .specwright/tmp, .specwright/runs, .specwright/artifacts creation
- [ ] `spec config` simplified to essential settings only

## Constraints

- LLM drafting uses read-only tool allowlist (same as spec_drafter.py)
- No backwards compatibility guarantees. Commands/flags/config formats may change or be removed.

---

## Phase 1: Epic drafter implementation

### Objective
Implement LLM-assisted epic drafting that crawls a repo and generates meaningful epic content.

### Files to Touch
- `src/spec/governance/epic_drafter.py` (create) - EpicDrafter class
- `tests/governance/test_epic_drafter.py` (create) - drafter tests

### Implementation Notes

```python
"""LLM-assisted epic drafting using Claude Code."""

from pathlib import Path
from spec.governance.spec_drafter import DRAFTING_ALLOWLIST

class EpicDrafter:
    """Draft epic.yaml content by crawling repository."""

    def __init__(
        self,
        title: str,
        goal: str,
        context: str | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.title = title
        self.goal = goal
        self.context = context
        self.model = model

    def draft(self) -> dict:
        """Generate epic dict by exploring repos.

        Returns:
            Epic dict ready for YAML serialization.
        """
        # Build prompt with goal + context
        prompt = self._build_prompt()

        # Call Claude Code with read-only tools
        result = self._call_claude_code(prompt)

        # Parse YAML from response
        return self._parse_epic(result)

    def _build_prompt(self) -> str:
        """Build prompt for epic drafting."""
        return f"""You are drafting an epic for the specwright system.

## Goal
{self.goal}

## Title
{self.title}

## Target Repositories
- Current working repository (cwd)
- Any repositories registered as epic targets (if available)

{f'## Additional Context\n{self.context}' if self.context else ''}

## Your Task

1. Explore the repository to understand the current state
2. Identify what work needs to be done to achieve the goal
3. Break the work into logical specs with clear boundaries
4. For each spec, determine:
   - A clear title and ID
   - Expectations (what it should deliver)
   - Constraints (boundaries, limitations)
   - Dependencies on other specs

## Output Format

Output YAML for an epic *draft patch* (not a full epic.yaml). The CLI will:
1) create a valid skeleton epic.yaml (with created/updated/state/history), then
2) merge this patch into it, then
3) validate and write the final epic.yaml.

```yaml
patch:
  intent:
    narrative: |
      <Explain the problem and why this epic matters>
  targets:
    - id: <target-id>
      repo_path: <absolute-path>
      default_branch: main
  specs:
    - id: <spec-id>
      title: <spec-title>
      repo: <target-id>
      branch: feat/<slug>
      path: specs/<spec-id>.md
      depends_on: []
      mode: headless  # or interactive
      expectations:
        - <what this spec delivers>
      constraints:
        - <boundaries and limitations>
```

Output ONLY the YAML, nothing else."""
```

### Verification
- `pytest tests/governance/test_epic_drafter.py -v`
- EpicDrafter with mock Claude returns valid epic structure
- Prompt includes all required context

---

## Phase 2: Spec entry drafter implementation

### Objective
Implement LLM-assisted spec entry drafting that adds specs to existing epics.

### Files to Touch
- `src/spec/governance/spec_entry_drafter.py` (create) - SpecEntryDrafter class
- `tests/governance/test_spec_entry_drafter.py` (create) - drafter tests

### Implementation Notes

```python
"""LLM-assisted spec entry drafting for epics."""

from pathlib import Path
from spec.epic.schema import Epic, SpecRef

class SpecEntryDrafter:
    """Draft spec entries for an existing epic."""

    def __init__(
        self,
        epic: Epic,
        description: str,
      target_id: str | None = None,
        context: str | None = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.epic = epic
        self.description = description
      self.target_id = target_id
        self.context = context
        self.model = model

    def draft(self) -> list[SpecRef]:
        """Generate spec entries by exploring repo.

        Returns:
            List of SpecRef objects to add to epic.
        """
        prompt = self._build_prompt()
        result = self._call_claude_code(prompt)
        return self._parse_specs(result)

    def _build_prompt(self) -> str:
        """Build prompt including existing epic context."""
        existing_specs = "\n".join(
            f"- {s.id}: {s.title} (depends_on: {s.depends_on})"
            for s in self.epic.specs
        )

        return f"""You are adding specs to an existing epic.

## Epic: {self.epic.id}
{self.epic.intent.goal}

## Existing Specs
{existing_specs or "(none)"}

## Description of New Work
{self.description}

## Target Repositories (from epic.yaml)
- Use all epic targets as context
- If provided, treat `target_id` as the primary working repo for this spec batch

{f'## Additional Context\n{self.context}' if self.context else ''}

## Your Task

1. Explore the repository to understand the current state
2. Based on the description, determine what spec(s) are needed
3. For each spec, figure out:
   - ID following epic's naming pattern (e.g., {self.epic.id.split('-')[0]}-XX)
   - Clear title
   - Branch name (feat/<slug>)
   - Expectations (what it delivers)
   - Constraints (boundaries)
   - Dependencies on existing or new specs

## Output Format

Output YAML for the new spec entries:

```yaml
specs:
  - id: <spec-id>
    title: <title>
    repo: <target-id>
    branch: feat/<slug>
    path: specs/<spec-id>.md
    status: planned
    depends_on: [<existing-spec-ids-if-any>]
    mode: headless  # or interactive
    expectations:
      - <expectation>
    constraints:
      - <constraint>
```

You may output multiple specs if the work should be broken down.
Output ONLY the YAML, nothing else."""
```

### Verification
- `pytest tests/governance/test_spec_entry_drafter.py -v`
- Drafter respects existing spec naming patterns
- Dependencies reference existing specs correctly
- Can generate multiple specs from one description

---

## Phase 3: CLI integration for epic create --llm

### Objective
Wire EpicDrafter into `spec epic create` command with --llm flag.

### Files to Touch
- `src/spec/cli/epic.py` (modify) - add --llm, --repo, --context to create command
- `src/spec/governance/__init__.py` (modify) - export EpicDrafter
- `tests/cli/test_epic_create_llm.py` (create) - CLI integration tests

### Implementation Notes

Modify `create` command signature:
```python
@epic_app.command()
def create(
    title: str = typer.Argument(..., help="Epic title"),
    id: str | None = typer.Option(None, "--id", help="Epic ID"),
    goal: str = typer.Option(..., "--goal", "-g", help="One-line goal"),
  owner: str = typer.Option(..., "--owner", help="Owner username"),
    llm: bool = typer.Option(False, "--llm", help="Use LLM to draft epic content"),
    context: Path | None = typer.Option(None, "--context", "-c", help="Additional context file"),
    model: str = typer.Option("claude-sonnet-4-20250514", "--model", "-m", help="Model for --llm"),
) -> None:
```

Logic:
- Without --llm: create skeleton epic.yaml only
- With --llm: create skeleton epic.yaml, then use EpicDrafter to generate a patch and merge it into the skeleton

### Verification
- `spec epic create --help` shows new flags
- `spec epic create "Title" --goal "..." --owner "..."` creates skeleton
- `spec epic create "Title" --goal "..." --owner "..." --llm` drafts and writes epic content
- Generated epic passes `spec validate epic`

---

## Phase 4: CLI integration for epic add-spec --llm

### Objective
Wire SpecEntryDrafter into `spec epic add-spec` with --llm flag.

### Files to Touch
- `src/spec/cli/epic.py` (modify) - change add-spec to support description + --llm
- `tests/cli/test_epic_add_spec_llm.py` (create) - CLI integration tests

### Implementation Notes

Change `add-spec` signature to support both modes:
```python
@epic_app.command("add-spec")
def add_spec(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    description: str | None = typer.Argument(None, help="Description of work (for --llm mode)"),
    # Manual mode options (existing)
    spec_id: str | None = typer.Option(None, "--id", help="Spec ID (manual mode)"),
    repo: str | None = typer.Option(None, "--repo", help="Target repo ID"),
    branch: str | None = typer.Option(None, "--branch", help="Working branch"),
    path: str | None = typer.Option(None, "--path", help="Spec path"),
  mode: str = typer.Option("headless", "--mode", help="Recommended mode: interactive|headless"),
    depends_on: list[str] = typer.Option([], "--depends-on", help="Dependencies"),
    expectation: list[str] = typer.Option([], "--expectation", "-e", help="Expectations"),
    # LLM mode options
    llm: bool = typer.Option(False, "--llm", help="Use LLM to draft spec entries"),
  target: str | None = typer.Option(None, "--target", help="Primary target repo ID (LLM mode)"),
    context: Path | None = typer.Option(None, "--context", "-c", help="Additional context"),
    model: str = typer.Option("claude-sonnet-4-20250514", "--model", "-m", help="Model"),
) -> None:
```

Logic:
- With --llm + description: use SpecEntryDrafter, may add multiple specs (and set `mode` for each)
- Without --llm: require manual fields (--id, --repo, --branch, --path)
- Description without --llm: fail with helpful message

### Verification
- `spec epic add-spec t004 "add caching" --llm` drafts spec entry
- Multiple specs can be generated from one description
- Manual mode still works: `spec epic add-spec t004 --id ... --repo ...`
- Generated specs have proper depends_on for existing specs

---

## Phase 5: Legacy command removal

### Objective
Remove unused legacy commands and associated dead code.

### Files to Touch
- `src/spec/cli/spec.py` (modify) - remove commands and helpers
- `tests/cli/test_legacy_removed.py` (create) - verify commands are gone

### Implementation Notes

Remove from spec.py:
1. `create` command (lines 536-732)
2. `spec_compile` command (lines 735-848)
3. `gate_list` command (lines 854-915)
4. `gate_report` command (lines 918-969)
5. `materialize` command (lines 972-1026)
6. `migrate` command (lines 1029-1165)
7. `list_specs` command (lines 1168-1214)

Remove helper functions:
- `RiskTier` enum
- `slugify` function
- `get_next_aip_id` function
- `get_git_remote_url` function
- `get_template_path` function
- `get_schema_path` function
- `get_default_config` legacy mode support
- `is_legacy_config` function
- `get_specs_path` function
- `get_aips_path` function
- `get_user_default` function

### Verification
- `spec create` returns "unknown command"
- `spec spec-compile` returns "unknown command"
- `spec gate-list` returns "unknown command"
- `spec gate-report` returns "unknown command"
- `spec materialize` returns "unknown command"
- `spec migrate` returns "unknown command"
- `spec list` returns "unknown command"
- `ruff check src/spec/cli/spec.py` passes (no unused imports)

---

## Phase 6: Init/config simplification

### Objective
Simplify `spec init` to essentials and remove legacy mode.

### Files to Touch
- `src/spec/cli/spec.py` (modify) - simplify init command
- `tests/cli/test_init_simplified.py` (create) - verify simplified behavior

### Implementation Notes

Simplified init:
```python
@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
    governor: str = typer.Option(
        "~/.local/local-governor",
        "--governor",
        help="Local-governor path"
    ),
    claude: bool = typer.Option(True, "--claude/--no-claude", help="Install slash commands"),
) -> None:
    """Initialize Specwright configuration.

    Creates .specwright.yaml with governor path and installs JobDefs.

    Examples:
        spec init
        spec init --governor /custom/path
        spec init --no-claude
    """
    config_path = Path.cwd() / ".specwright.yaml"

    if config_path.exists() and not force:
        typer.echo(f"Error: {config_path} already exists. Use --force to overwrite.")
        raise typer.Exit(1)

    # Write minimal config (no legacy)
    config = {
      "version": "0.7",
      "governor": {"path": governor},
      "jobdefs": {"path": f"{governor}/jobdefs/specwright"},
      "defaults": {
        "jobs": {
          "headless": "aip-1",
          "interactive": "interactive-1",
        }
      },
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f, sort_keys=False)

    typer.secho(f"Created {config_path}", fg=typer.colors.GREEN)

    # Install the two default JobDefs
    from spec.executor.jobdefs import install_default_jobdefs
    gov_path = Path(governor).expanduser()
    installed = install_default_jobdefs(gov_path, overwrite=force)
    if installed:
        typer.echo(f"Installed {len(installed)} JobDefs to {gov_path}/jobdefs/")

    # Install slash commands
    if claude:
        _install_slash_commands()
```

Remove from init:
- `--legacy-mode` flag
- `.specwright/` directory creation (tmp, runs, artifacts)
- GUIDE.md copying
- Schema copying
- gitignore modification

Simplified config - keep only:
- `spec config --show` to display config
- Remove the key-value setting complexity

### Verification
- `spec init --legacy-mode` fails (unknown option)
- `spec init` creates minimal .specwright.yaml
- No .specwright/ directory created
- JobDefs installed to governor (aip-1 + interactive-1)
- `spec config --show` displays config
