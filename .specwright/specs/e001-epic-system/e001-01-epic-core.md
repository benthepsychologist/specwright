---
title: Epic Core - Schema, DAG, and CRUD
id: e001-01-epic-core
version: "0.1"
status: draft
tier: B
owner: benthepsychologist
epic: e001-epic-system
repo:
  working_branch: feat/epic-system
goal: "Implement epic dataclasses, schema validation, DAG cycle detection, persistence, and core CLI commands"
created: 2025-12-26T00:00:00+00:00
updated: 2025-12-26T00:00:00+00:00
orchestrator_contract: "standard"
---

# Epic Core - Schema, DAG, and CRUD

## Goal

Implement the foundational epic system: dataclasses, schema validation, DAG cycle detection, persistence, and core CLI commands. **No LLM integration in this spec.**

## Non-Goals

- LLM check execution (e001-02-epic-checks)
- LLM client integration (e001-04-epic-llm-integration)
- Autogov context injection (e001-04-epic-llm-integration)

---

## Exit Codes

Use `SpecwrightError(exit_code)` pattern:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Generic error |
| 2 | Not found (epic, spec, check, target) |
| 3 | Validation error (schema, DAG cycle, ref mismatch) |

---

## Epic Schema (v0.1)

```yaml
version: "0.1"
kind: epic
id: e001-epic-system
title: "string"
owner: "string"
created: "ISO8601"
updated: "ISO8601"  # managed by tooling

intent:
  goal: "string"
  narrative: "string"

run_context:
  governor_root: "path"           # default ~/.local/local-governor
  env_override: "string"          # env var to override governor_root
  cli_bin: "string"
  cwd_policy: "governor | repo | any"

defaults:
  model: "string"                 # default llm model alias for checks

governance:  # optional
  enabled: bool
  source: "org | patterns"
  project: "string"
  include: ["policy", "arch", "patterns"]

targets:
  - id: "string"         # unique within epic
    repo_path: "abspath"
    default_branch: "string"
    governor_project: "string"  # optional

specs:
  - id: "e001-01-epic-core"       # unique within epic
    repo: "string"               # must match targets[*].id
    branch: "string"
    path: "string"               # relative to governor_root
    status: "planned | active | blocked | done | abandoned"
    depends_on: ["e001-02-epic-checks"]  # must be valid spec IDs, DAG
    expectations: ["string"]
    checks: ["CHECK-xxx"]              # must be valid check IDs

checks:
  - id: "CHECK-xxx"
    name: "string"
    scope: "spec | epic"
    default_spec: "string"       # for spec-scoped checks
    model: "string"              # llm model alias (optional, uses defaults.model)
    prompt_ref: "string"
    response_contract:
      verdicts: ["PASS", "WARN", "FAIL", "ERROR"]
      required_sections: ["string"]
    inputs:                      # typed union - each type has specific fields
      - type: epic
        path: "string"
      - type: spec
        path: "string"
      - type: file
        target: "string"
        path: "string"
      - type: git_diff
        target: "string"
        range: "string"
      - type: cli_output
        args: ["string"]         # joined with cli_bin, shell=False
      - type: governance_pack
        include: ["string"]      # optional, defaults to epic.governance.include

state:
  status: "planned | active | blocked | done | abandoned"
  current_spec: "e001-01-epic-core"  # optional, must be active
  history:
    - id: "EVT-xxxx"
      at: "ISO8601"
      event: "epic.created | spec.activated | spec.done | ..."
      actor: "human | specwright | llm"
      spec_id: "string"
      check_id: "string"
      verdict: "PASS | WARN | FAIL | ERROR | NOT_RUN"
      report: "string"
      note: "string"
```

---

## Validation Rules

1. **Target refs**: `specs[*].repo` must match `targets[*].id`
2. **DAG integrity**: `depends_on` must form acyclic graph
3. **Check refs**: `specs[*].checks[*]` must exist in `checks[*].id`
4. **Current spec**: If set, must reference spec with `status: active`
5. **Status enum**: Only allowed values
6. **Event types**: Only allowed values

---

## Plan

### Step 1: Epic Dataclasses

**Prompt:**

Create `src/spec/epic/schema.py` with dataclasses for the epic model.

Define these enums:
- `SpecStatus`: planned, active, blocked, done, abandoned
- `EventType`: epic.created, epic.updated, spec.activated, spec.blocked, spec.done, spec.abandoned, check.completed, check.failed, step.started, step.completed, step.failed
- `Actor`: human, specwright, llm
- `CheckScope`: spec, epic

Define these dataclasses:
- `Target`: id, repo_path, default_branch, governor_project (optional)
- `CheckInput`: type, path (optional), args (optional list), target (optional), range (optional), include (optional list)
- `ResponseContract`: verdicts list, required_sections list
- `Check`: id, name, scope, prompt_ref, model (optional), default_spec (optional), response_contract (optional), inputs list
- `SpecRef`: id, repo, branch, path, status, depends_on list, expectations list, checks list
- `HistoryEvent`: id, at, event, actor, spec_id (optional), check_id (optional), verdict (optional), report (optional), note (optional), step (optional int), plan_artifact (optional str), commit (optional str), verification (optional object with commands list and status str)
- `EpicState`: status, current_spec (optional), history list
- `Intent`: goal, narrative
- `RunContext`: governor_root, env_override (optional), cli_bin, cwd_policy
- `GovernanceConfig`: enabled, source, project, include list
- `Defaults`: model (optional)
- `Epic`: version, kind, id, title, owner, created, updated, intent, targets, specs, checks, state, run_context (optional), governance (optional), defaults (optional)

Add validation methods to Epic:
- `validate() -> list[str]`: Run all validations, return list of errors
- `_validate_target_refs()`: Check specs[].repo exists in targets
- `_validate_dag()`: Check no cycles in depends_on
- `_validate_check_refs()`: Check specs[].checks exist
- `_validate_current_spec()`: Check current_spec is active if set

Add helper methods to Epic:
- `get_spec(spec_id) -> SpecRef | None`
- `get_check(check_id) -> Check | None`
- `get_target(target_id) -> Target | None`
- `topological_order() -> list[SpecRef]`

Use `dacite` for YAML → dataclass conversion.

**Allowed Paths:** `src/spec/epic/**`

**Verification:** `ruff check src/spec/epic/ && pytest tests/epic/test_schema.py -v`

---

### Step 2: DAG Utilities

**Prompt:**

Create `src/spec/epic/dag.py` with topological sort and cycle detection.

Define `DAGError` exception with `message` and `cycle` (optional list of spec IDs).

Implement:
- `topological_sort(specs: list[SpecRef]) -> list[SpecRef]`: Return specs in dependency order. Raise DAGError if cycle detected.
- `detect_cycle(specs: list[SpecRef]) -> list[str] | None`: Return cycle path if found, else None.
- `get_ready_specs(specs: list[SpecRef]) -> list[SpecRef]`: Return specs whose dependencies are all done.

Use Kahn's algorithm or DFS for topological sort. On cycle detection, return the full cycle path for clear error messages.

**Allowed Paths:** `src/spec/epic/**`

**Verification:** `pytest tests/epic/test_dag.py -v`

---

### Step 3: Epic Loader

**Prompt:**

Create `src/spec/epic/loader.py` for loading epics from YAML.

Define exceptions:
- `EpicNotFoundError(SpecwrightError)`: exit_code = 2
- `EpicValidationError(SpecwrightError)`: exit_code = 3

Implement:
- `get_governor_root() -> Path`: Check `SPECWRIGHT_GOVERNOR_ROOT` env var first, else use `~/.local/local-governor`. Always expand and resolve.
- `get_epic_path(epic_id: str) -> Path`: Return path to epic directory
- `load_epic(epic_id: str) -> Epic`: Load epic from governor. Raise EpicNotFoundError if not found.
- `load_epic_from_path(path: Path) -> Epic`: Load and validate epic from YAML file. Use dacite for deserialization. Run validation and raise EpicValidationError with clear message on failure.
- `list_epics() -> list[str]`: Return list of epic IDs in governor.

Use `ruamel.yaml` for better error messages with line numbers if available, else `pyyaml`.

**Allowed Paths:** `src/spec/epic/**`

**Verification:** `pytest tests/epic/test_loader.py -v`

---

### Step 4: Epic Writer

**Prompt:**

Create `src/spec/epic/writer.py` for creating and updating epics.

Implement:
- `create_epic(id, title, owner, goal, narrative="") -> Epic`: Create new epic with directory structure (`checks/`, `reports/`, `artifacts/snapshots/`), stub `notes.md`, and `epic.yaml`. Return loaded Epic.
- `save_epic(epic: Epic, update_timestamp: bool = True)`: Write epic.yaml. Update `updated` field if update_timestamp=True.
- `add_target(epic: Epic, target: Target)`: Add target and save.
- `add_spec(epic: Epic, spec: SpecRef)`: Validate repo ref and DAG, add spec, save. Raise on invalid.
- `update_spec_status(epic: Epic, spec_id: str, status: SpecStatus, note: str | None = None)`: Update status and append history event.
- `set_current_spec(epic: Epic, spec_id: str)`: Set current spec, mark it active, append history.
- `mark_spec_done(epic: Epic, spec_id: str, note: str | None = None)`: Mark spec done, append history, suggest next spec.
- `append_history(epic: Epic, event: HistoryEvent)`: Append event and save.
- `generate_event_id(epic: Epic) -> str`: Generate next EVT-XXXX id. Must be monotonic: `next = max(existing numeric IDs) + 1`. Format as EVT-0001, EVT-0002, etc.

Use `ruamel.yaml` for round-trip YAML preservation if available.

**Allowed Paths:** `src/spec/epic/**`

**Verification:** `pytest tests/epic/test_writer.py -v`

---

### Step 5: Epic CLI Commands

**Prompt:**

Create `src/spec/cli/epic.py` with Typer commands for epic management.

Create Typer app: `epic_app = typer.Typer(help="Epic management commands")`

Implement commands:

```python
@epic_app.command()
def create(
    title: str = typer.Argument(..., help="Epic title"),
    id: str = typer.Option(None, "--id", help="Epic ID (auto-generated if not provided)"),
    goal: str = typer.Option(..., "--goal", "-g", help="One-line goal statement"),
    owner: str = typer.Option(None, "--owner", help="Owner username"),
): ...

@epic_app.command("add-target")
def add_target(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    target_id: str = typer.Option(..., "--id", help="Target ID"),
    repo_path: str = typer.Option(..., "--repo-path", help="Absolute path to repo"),
    default_branch: str = typer.Option("main", "--branch", help="Default branch"),
    governor_project: str = typer.Option(None, "--governor-project", help="Link to governor project"),
): ...

@epic_app.command("add-spec")
def add_spec(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    spec_id: str = typer.Option(..., "--id", help="Spec ID"),
    repo: str = typer.Option(..., "--repo", help="Target repo ID"),
    branch: str = typer.Option(..., "--branch", help="Working branch"),
    path: str = typer.Option(..., "--path", help="Spec path relative to governor"),
    depends_on: List[str] = typer.Option([], "--depends-on", help="Dependency spec IDs"),
    expectation: List[str] = typer.Option([], "--expectation", "-e", help="Expectations"),
): ...

@epic_app.command("set-current")
def set_current(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    spec_id: str = typer.Option(..., "--spec", "-s", help="Spec ID to set as current"),
): ...

@epic_app.command("mark-done")
def mark_done(
    epic_id: str = typer.Argument(..., help="Epic ID"),
    spec_id: str = typer.Option(..., "--spec", "-s", help="Spec ID to mark done"),
    note: str = typer.Option(None, "--note", "-n", help="Completion note"),
): ...

@epic_app.command()
def status(epic_id: str = typer.Argument(..., help="Epic ID")): ...

@epic_app.command("list")
def list_epics(): ...

@epic_app.command()
def validate(epic_id: str = typer.Argument(..., help="Epic ID")): ...
```

Status output should show:
- Epic title and overall status
- Current spec indicator (→)
- DAG visualization with status icons: ✓ done, → active, ○ planned, ✗ blocked, ⊘ abandoned
- Check summary

Add placeholder for `check` command that returns exit 4 with message about LLM integration.

Register in main CLI (`src/spec/cli/spec.py`): `app.add_typer(epic_app, name="epic")`

**Allowed Paths:** `src/spec/cli/**`

**Verification:** `spec epic --help && spec epic create --help && pytest tests/cli/test_epic.py -v`

---

### Step 6: Comprehensive Test Suite for Epic Core

**Prompt:**

Create comprehensive tests for the epic core module.

Create test files:
- `tests/epic/__init__.py`
- `tests/epic/test_schema.py`: Dataclass validation tests
- `tests/epic/test_dag.py`: Cycle detection, topological sort
- `tests/epic/test_loader.py`: Load/parse tests, error cases
- `tests/epic/test_writer.py`: Create/update tests
- `tests/cli/test_epic.py`: CLI integration tests

Test cases:
- Valid epic loads successfully
- Invalid target ref raises EpicValidationError (exit 3)
- DAG cycle detected and reported with cycle path
- Unknown check ref detected
- current_spec must be active
- create produces correct directory structure
- add-spec validates before adding
- status renders correctly with icons
- validate returns correct exit codes (0 or 3)

Use pytest fixtures for sample epics.

**Allowed Paths:** `tests/**`

**Verification:** `pytest tests/epic/ tests/cli/test_epic.py -v --cov=src/spec/epic --cov=src/spec/cli/epic`

---

## Acceptance Criteria

- [ ] All dataclasses defined with proper types
- [ ] Validation methods raise SpecwrightError with correct exit codes
- [ ] DAG cycle detection works and reports cycle path
- [ ] Epic create produces correct directory structure
- [ ] All CLI commands respond to --help
- [ ] Status command renders readable DAG with icons
- [ ] Validate command returns exit 0 or 3
- [ ] Unit tests pass with >80% coverage

## Constraints

- No LLM calls in this spec
- No report writing in this spec
- Use existing SpecwrightError pattern
- Governor root is always `~/.local/local-governor`
