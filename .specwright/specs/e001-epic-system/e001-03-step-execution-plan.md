---
title: Step Execution Plan (SEP)
id: e001-03-step-execution-plan
aip_id: AIP-specwright-2025-12-29-001
version: "0.1"
status: draft
tier: B
owner: benthepsychologist
epic: e001-epic-system
repo:
  working_branch: feat/epic-system
goal: "Add Step Execution Plan (SEP) generation and an advisory human gate before Claude execution"
created: 2025-12-29T00:00:00+00:00
updated: 2025-12-29T00:00:00+00:00
orchestrator_contract: "standard"
depends_on:
  - e001-02-epic-checks
---

# Step Execution Plan (SEP)

## Goal

Add a deterministic Step Execution Plan (SEP) artifact that can be generated and reviewed before execution, then optionally used as the source of truth for executing a step.

## Non-Goals

- Any LLM integration changes (moved to `e001-04-epic-llm-integration`)
- Changing the existing step runner semantics beyond adding optional planning/review support

---

## Exit Codes

This spec extends the existing exit code taxonomy:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Generic error |
| 2 | Not found (AIP, step, SEP file) |
| 3 | Validation error (schema, DAG cycle, ref mismatch) |
| 6 | SEP load error (file missing, malformed YAML, schema invalid) |
| 7 | SEP validation mismatch (identity mismatch or constraint widening) |

Codes 4-5 are reserved for LLM config/execution errors (see `e001-04-epic-llm-integration`).

---

## Plan

### Step 1: SEP Schema

**Prompt:**

Create `src/spec/executor/sep.py` with the Step Execution Plan schema.

Define dataclasses:
```python
@dataclass
class FileChange:
    path: str                    # relative path in repo
    action: str                  # create, modify, delete
    description: str             # what will change
    estimated_lines: int | None  # rough estimate

@dataclass
class VerificationStep:
    command: str                 # command to run
    expected_outcome: str        # what success looks like
    required: bool = True        # fail step if this fails

@dataclass
class StepExecutionPlan:
    aip_id: str
    step_id: str
    step_index: int
    created_at: str              # ISO timestamp

    # What the step will do
    objective: str               # from AIP step prompt, summarized
    files_to_touch: list[FileChange]
    verification_steps: list[VerificationStep]

    allowed_paths: list[str]
    forbidden_paths: list[str]

    # Metadata
    estimated_complexity: str    # low, medium, high
    requires_human_review: bool  # true if touching sensitive paths
```

Implement:
- `save_sep(sep: StepExecutionPlan, path: Path) -> None`: Write SEP to YAML
- `load_sep(path: Path) -> StepExecutionPlan`: Load SEP from YAML

**Allowed Paths:** `src/spec/executor/**`

---

### Step 2: SEP Materializer

**Prompt:**

Create `src/spec/executor/sep_builder.py` for materializing SEPs from AIP steps.

Implement `SEPBuilder` class:
```python
class SEPBuilder:
  def build(
    self,
    aip: dict[str, Any],
    step_idx: int,
    contract: StepContract,
  ) -> StepExecutionPlan:
    """
    Build a Step Execution Plan from AIP step and contract.

    This is deterministic - no LLM calls. It parses the step prompt
    to extract:
    - Files mentioned (Create `path`, Update `path`, etc.)
    - Actions per file (create, modify, delete)
    - Verification commands from contract

    Returns a SEP that can be reviewed before execution.
    """
    ...

  def _extract_files_from_prompt(self, prompt: str) -> list[FileChange]:
    """Parse prompt to find file references."""
    ...

  def _estimate_complexity(self, files: list[FileChange]) -> str:
    """Estimate complexity based on number of files and actions."""
    ...

  def _check_sensitive_paths(
    self,
    files: list[FileChange],
    forbidden: list[str],
  ) -> bool:
    """Return True if human review recommended."""
    ...
```

Extraction patterns to match:
- "Create `path/to/file.py`" -> create
- "Update `path/to/file.py`" -> modify
- "Modify `path/to/file.py`" -> modify
- "Delete `path/to/file.py`" -> delete
- "Add to `path/to/file.py`" -> modify

**Allowed Paths:** `src/spec/executor/**`

---

### Step 3: CLI Integration

**Prompt:**

Update `src/spec/cli/spec.py` to add SEP workflow flags.

Add to the `run` command:
```python
plan_only: bool = typer.Option(
  False,
  "--plan-only",
  help="Generate SEP and stop. Do not execute.",
),
from_sep: str | None = typer.Option(
  None,
  "--from-sep",
  help="Execute from approved SEP file instead of generating new one.",
),
skip_sep_review: bool = typer.Option(
  False,
  "--skip-sep-review",
  help="Skip SEP review gate (use with caution).",
),
```

Workflow:
1. If `--from-sep` provided:
   - Load SEP from file (exit 6 if file missing, malformed, or schema-invalid)
   - Validate SEP matches current AIP/step (exit 7 if mismatch):
     - `sep.aip_id == aip.aip_id`
     - `sep.step_id == plan[step_idx].step_id`
     - `sep.step_index == step_idx + 1`
   - Enforce contract safety (exit 7 if widening detected):
     - `sep.allowed_paths` must be equal to (or a subset of) contract allowed paths
     - `sep.forbidden_paths` must be equal to (or a superset of) contract forbidden paths
   - Execute directly (skip generation)
2. Else:
   - Build contract (existing)
   - Build SEP from contract + AIP
   - Save SEP to `runs/<aip_id>/<timestamp>/step-N/sep.yaml`
   - If `--plan-only`: print SEP path and exit
   - Else if not `--skip-sep-review`: print SEP path, prompt for continue
   - Execute step

Update output to show SEP path in results.

**Allowed Paths:** `src/spec/cli/**`

---

### Step 4: Runner Integration

**Prompt:**

Update `src/spec/executor/runner.py` to integrate SEP workflow.

Add to `StepRunner.run_step()`:
- Accept `sep: StepExecutionPlan | None` parameter
- If sep provided, use it; else build from contract
- Write SEP to `runs/<aip_id>/<timestamp>/step-N/sep.yaml` (canonical location)
- Pass SEP to adapter for context (optional use)

Update artifact writing:
- Write `sep.yaml` to the step run dir (canonical): `runs/<aip_id>/<timestamp>/step-N/sep.yaml`
- Include SEP summary in gate.md

Post-execution:
- Materialize the staged diff to `runs/<aip_id>/<timestamp>/step-N/patch.diff` using `git diff --cached`
- Always write the file, even if empty (absence of `patch.diff` means step didn't run to completion)

Add method:
```python
def build_sep(
  self,
  aip: dict[str, Any],
  step_idx: int,
  contract: StepContract,
) -> StepExecutionPlan:
  """Build SEP for the step."""
  builder = SEPBuilder()
  return builder.build(aip, step_idx, contract)
```

**Allowed Paths:** `src/spec/executor/**`

---

### Step 5: Test Suite

**Prompt:**

Create comprehensive tests for SEP functionality.

Create `tests/executor/test_sep.py`:
- SEP dataclass serialization/deserialization
- File extraction from various prompt patterns
- Complexity estimation
- Sensitive path detection

Create `tests/executor/test_sep_builder.py`:
- Building SEP from sample AIPs
- Edge cases (no files mentioned, deletes, etc.)

Update `tests/cli/test_spec_run.py`:
- `--plan-only` generates SEP and exits
- `--from-sep` loads and validates SEP
- `--skip-sep-review` bypasses gate

**Allowed Paths:** `tests/**`

---

### Step 6: SEP Check Prompt

**Prompt:**

Create the epic check prompt referenced by `CHECK-e001-sep`:

- Create `~/.local/local-governor/epics/e001-epic-system/checks/check-sep.md`

It should verify (at minimum):
- `src/spec/executor/sep.py` exists and matches the SEP schema expectations
- `spec run --help` mentions the SEP flags
- SEP is written to `runs/<aip_id>/<timestamp>/step-N/sep.yaml`
- `--from-sep` enforces the SEP/AIP identity match and does not widen contract constraints
- `patch.diff` is written from `git diff --cached`

**Allowed Paths:** `~/.local/local-governor/epics/e001-epic-system/checks/**`

---

## Acceptance Criteria

- SEP includes: `files_to_touch` with per-file changes (via `FileChange.action` + `FileChange.description`) and `verification_steps`
- SEP materializer parses AIP step and generates deterministic plan
- `--plan-only` flag generates SEP without execution
- `--from-sep` flag executes from approved SEP
- SEP saved to `runs/<aip_id>/<timestamp>/step-N/sep.yaml`
- Post-execution: `git diff --cached` materialized to `runs/<aip_id>/<timestamp>/step-N/patch.diff`
- `CHECK-e001-sep` validates SEP behavior against epic intent
- Unit tests pass with >80% coverage
