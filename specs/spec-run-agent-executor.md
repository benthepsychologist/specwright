---
version: "0.1"
tier: B
title: Spec-Run Agent Executor
owner: benthepsychologist
goal: Implement autonomous step execution with end-gate-only approval, scope enforcement, and a Codex-first agent adapter
labels: [executor, agent, automation, core]
project_slug: spec-run-executor
spec_version: 1.0.0
created: 2024-12-13T00:00:00Z
updated: 2024-12-13T00:00:00Z
orchestrator_contract: "standard"
repo:
  working_branch: "feat/spec-run-agent-executor"
---

# Spec-Run Agent Executor

## Objective

> Implement `spec run --step N` as a fully autonomous execution loop:
>
> **Extract step → Build contract → Run agent (black box) → Apply patch (runner) → Scope check → Verify (runner) → Iterate (within limits) → Present final gate package for human approval.**
>
> No human interaction inside the step loop. Scope/policy violations fail fast.

---

## v1 Scope Boundary

### Non-negotiables (v1)

- **Agent never mutates repo.** Agent proposes `patch.diff` only.
- **Runner applies patch** via `git apply`. Runner owns the working tree.
- **Agent may run commands** during analysis, but sandbox enforcement prevents repo mutation.
- **Runner verification is authoritative** (tests/lint/build).
- **No context packing.** Agent crawls repo itself.
- **Baseline = branch HEAD** at step start. Runner never commits. Human commits after gate approval.
- **First adapter: Codex CLI** (`codex exec`) only.

### Deferred to v2

- AdapterCapabilities negotiation
- `spec adapter-test` CLI
- Full escalation taxonomy (beyond the two triggers below)
- Worktrees / parallel execution
- Auto-commit after gate approval
- Context packing / manifest generation

---

## Acceptance Criteria

### Functional Requirements

- [ ] `spec run --step N` executes the full step lifecycle autonomously
- [ ] Step Contract generated from step definition + autogov policies
- [ ] Codex adapter interface defined with strict input/output contract
- [ ] Scope enforcement runs BEFORE verification (fail fast on violations)
- [ ] Retry loop respects `max_iterations` + retry rules
- [ ] Gate package presented only at step completion (end-gate-only)
- [ ] All artifacts written to `runs/<aip_id>/<timestamp>/step-N/`
- [ ] Termination reason captured in `result.json`

### Agent Protocol Contract

- [ ] File bundle IO: `input/` written by runner, `output/` written by agent adapter
- [ ] Required inputs: `contract.yaml`, `prompt.md`, `repo_state.json`
- [ ] Required outputs: `patch.diff`, `agent.json`
- [ ] Required output from adapter: `cmdlog.txt` (normalized command log)
- [ ] Optional outputs: `summary.md` (missing = ok)
- [ ] `agent.json` schema validated
- [ ] Runner-applies-patch: `git apply --check` then `git apply`
- [ ] `failure_context.json` provided on retry (iteration > 0)

### Baseline & Isolation

- [ ] Baseline = branch HEAD at step start
- [ ] Fail fast if working tree dirty (unless `--allow-dirty`)
- [ ] Each iteration: `git reset --hard <baseline>`
- [ ] All iteration patches preserved in `iter-N/`
- [ ] Runner never commits. Human commits after gate approval.

### Scope Enforcement

- [ ] Touched files computed by runner: `git diff --name-only` (authoritative)
- [ ] Check touched files against `allowed_paths` + `forbidden_paths` globs
- [ ] Autogov integration: forbidden globs merged into contract (v1: merge only)
- [ ] Scope violation = immediate failure (no retry)
- [ ] `policy_report.json` written

### Iteration Semantics

- [ ] `max_iterations` default = 3
- [ ] Retry only on runner verification failure (tests/lint/build)
- [ ] Hard fail (no retry): scope violation, patch apply failure, adapter protocol error, dirty worktree
- [ ] Escalate only:
  - `agent.json.needs_human == true`
  - cannot derive `allowed_paths` AND fallback is disabled (see contract rules)

### CLI

- [ ] Add `--dry-run`:
  - Builds contract
  - Writes input bundle
  - Prints adapter invocation plan
  - Exits without calling adapter

### Quality Gates

- [ ] CI green (lint + unit + integration)
- [ ] Ruff passes
- [ ] Mypy passes
- [ ] ≥80% coverage for new executor code
- [ ] No changes to `src/spec/compiler/` (read-only dependency)

---

## Core Design: Codex CLI Is Real, Use Its Native Controls

### Codex Exec: Non-interactive + sandbox + schema'd output

Codex CLI provides:

- `codex exec` for scripted, non-interactive runs
- `--sandbox read-only|workspace-write|danger-full-access`
- `--cd` to set workspace root
- `--output-schema` to validate the final response shape
- `--output-last-message` to write final assistant message to a file
- `--json` to emit newline-delimited JSON events (used to build `cmdlog.txt`)

That's enough to make v1 deterministic without inventing "mock adapters".

---

## Command Policy

### The only enforcement that matters in v1

**Enforced by Codex sandbox mode** (`--sandbox read-only` by default).

- In v1 we default Codex to `--sandbox read-only`.
- This makes "agent never mutates repo" true even if the agent tries to write.
- Runner still verifies post-factum by checking the working tree and only applying the proposed patch.

### Secondary policy: allow/deny list (for logging + fail-fast on obvious nonsense)

Because Codex can emit JSON events (`--json`), the adapter must extract shell/tool commands and write `cmdlog.txt`.

The runner then applies simple rules:

**Allowed commands (v1)**

Read-only navigation + inspection:
- `cd`, `pwd`
- `ls`
- `find` (no `-delete`)
- `rg` / `grep`
- `cat`, `sed` (NO `-i`), `awk`, `head`, `tail`, `wc`
- `python -c` / `python -m` only if contract `allowed_ops` includes `read`

Git inspection only:
- `git status`, `git diff`, `git show`, `git log`

**Forbidden patterns (v1)**

Anything that writes or mutates:
- redirections: `>`, `>>`, `2>`, `| tee`
- editors: `vim`, `nano`, `emacs`
- mutation git: `git commit`, `git add`, `git checkout`, `git reset`, `git clean`, `git apply`
- build/install: `pip install`, `uv pip install`, `npm install`, `brew`, `apt`
- deletion: `rm`, `mv`, `cp` (yes, even `cp`; v1 is strict)
- network: `curl`, `wget`

**Termination behavior:**
- If forbidden pattern appears in `cmdlog.txt` → `FAIL_ADAPTER_PROTOCOL` (adapter allowed something it shouldn't)

(This is intentionally harsh in v1.)

---

## Data Structures

### StepContract (v1)

```yaml
step_id: step-003
aip_id: AIP-myproject-2024-12-13-001
repo_root: /workspace/myproject

# Scope
allowed_paths:
  - "src/**"
  - "tests/**"
  - "docs/**"
forbidden_paths:
  - "**/*.lock"
  - "pyproject.toml"
  - ".env*"

# Ops
allowed_ops:
  - read
  - write
  - test

# Iteration
max_iterations: 3

# Codex execution policy
codex:
  sandbox: "read-only"   # v1 default
  emit_json_events: true # adapter must call codex exec --json
  output_schema: "artifacts/schemas/codex_output.schema.json"
```

### Allowed paths derivation rules (FIXED)

Contract builder derives `allowed_paths` in this priority order:

1. **If step explicitly declares `allowed_paths`:** use it (plus policy forbiddens merged in).
2. **Else if step declares `outputs`:** derive from output directories AND add safe defaults:
   - always include: `src/**`, `tests/**`
   - include output parents: e.g., `artifacts/**` if output is `artifacts/foo.md`
3. **Else if spec has `repo.paths`:** use them + safe defaults.
4. **Else:**
   - v1 default behavior: use safe defaults (`src/**`, `tests/**`, `docs/**`)
   - optional strict mode: if `--strict-contract` later exists, escalate instead

**Escalation trigger (v1):**
- `ESCALATE_AMBIGUOUS` only if `allowed_paths` resolves to empty after all rules (which should basically never happen unless the spec is malformed).

### repo_state.json (required)

```json
{
  "commit": "abc123def456",
  "branch": "feat/spec-run-agent-executor",
  "dirty": false,
  "baseline": "abc123def456"
}
```

### failure_context.json (required on retry, defined now)

```json
{
  "iteration": 1,
  "failure_category": "verify_fail",
  "failed_commands": [
    {
      "command": "pytest -q",
      "exit_code": 1,
      "stderr_tail": "FAILED tests/test_example.py::test_x - AssertionError"
    }
  ],
  "previous_patch_path": "iter-0/patch.diff",
  "previous_verification_report_path": "iter-0/verification_report.json"
}
```

### agent.json (required, simplified for v1)

```json
{
  "status": "success",
  "needs_human": false,
  "notes": "Implemented executor contract builder; tests pass."
}
```

Valid `status`: `success` | `failure` | `needs_human`

---

## TerminationReason (v1 minimal)

```
PASS

FAIL_VERIFY_RETRYABLE
FAIL_SCOPE
FAIL_PATCH_APPLY
FAIL_ADAPTER_PROTOCOL
FAIL_DIRTY_WORKTREE

ESCALATE_NEEDS_HUMAN
ESCALATE_AMBIGUOUS

GATE_REJECTED
GATE_DEFERRED
```

---

## Agent Protocol: File Bundle IO

### Input bundle (runner → adapter)

```
input/
├── contract.yaml
├── prompt.md
├── repo_state.json
└── failure_context.json   # only on retry
```

### Output bundle (adapter → runner)

```
output/
├── patch.diff             # REQUIRED
├── agent.json             # REQUIRED
├── cmdlog.txt             # REQUIRED (normalized from Codex JSON events)
└── summary.md             # OPTIONAL
```

---

## Codex Adapter Contract (v1 pinned)

### Codex execution (required behavior)

Adapter MUST invoke non-interactively:

- Use `codex exec` (or `codex e`)
- Set workspace root: `--cd <repo_root>`
- Enforce sandbox: `--sandbox read-only` (default)
- Emit JSON events for log extraction: `--json`
- Provide an output schema file: `--output-schema <schema_path>`
- Write final assistant message to file: `--output-last-message <tmp_last_message_path>`
- Prompt comes from stdin: `PROMPT = -`

### Output schema requirement (how we get deterministic patch+agent.json)

Runner writes `artifacts/schemas/codex_output.schema.json` like:

```json
{
  "type": "object",
  "required": ["patch_diff", "agent"],
  "properties": {
    "patch_diff": {"type": "string"},
    "agent": {
      "type": "object",
      "required": ["status", "needs_human", "notes"],
      "properties": {
        "status": {"type": "string"},
        "needs_human": {"type": "boolean"},
        "notes": {"type": "string"}
      }
    }
  }
}
```

Prompt instructs Codex: *"Your final output MUST be valid JSON matching the provided schema. `patch_diff` MUST be a unified diff against baseline."*

Adapter reads `<tmp_last_message_path>`, parses JSON:
- writes `output/patch.diff` = `patch_diff`
- writes `output/agent.json` = `agent`
- writes `output/cmdlog.txt` by extracting command events from Codex `--json` stream

### Errors

- `ToolNotFoundError` if `codex` binary missing
- `ProtocolError` if:
  - last message missing / invalid JSON
  - missing required fields per schema
  - cannot write required outputs

---

## Runner Phases (v1)

### 1. Extract

- parse AIP → step N prompt/commands/outputs/gate checklist
- load autogov policy (optional; merge forbiddens)
- build `contract.yaml` + schema file
- write input bundle

### 2. Loop (max_iterations)

- reset baseline: `git reset --hard <baseline>`
- invoke adapter (Codex)
- validate outputs exist + `agent.json` schema
- apply patch:
  - `git apply --check`
  - `git apply`
- compute touched files: `git diff --name-only <baseline>`
- scope check (fail fast)
- verify (runner runs commands from step/spec)
- if pass: stop
- if verify fail and iterations remain: write `failure_context.json` and retry
- else: terminate with `FAIL_VERIFY_RETRYABLE`

### 3. Gate

- render `gate.md` including:
  - final patch diff (truncate if huge)
  - touched files
  - verification summary
  - policy report summary
  - termination reason
- human approves/rejects/defers
- runner never commits

---

## CLI Changes (v1)

`spec run --step N` new flags:

- `--adapter codex` (default)
- `--max-iterations 3`
- `--allow-dirty`
- `--observe`
- `--dry-run` (new)

### `--dry-run` behavior

- builds contract + schema
- writes `runs/.../step-N/input/`
- prints the exact `codex` invocation it would run
- exits 0

---

## Plan

### Step 1: Data structures + schemas [G0: Plan Approval]

**Prompt:**

Design and document the core data structures:

1. **StepContract** - Machine-readable contract per step
   - Define YAML schema
   - Document derivation rules (with fixed allowed_paths logic)
   - Define defaults

2. **Codex output schema**
   - `codex_output.schema.json` for `--output-schema`

3. **Agent IO schemas**
   - `repo_state.json` schema
   - `failure_context.json` schema
   - `agent.json` schema

4. **TerminationReason enum**

**Outputs:**

- `artifacts/plan/step-contract-schema.yaml`
- `artifacts/schemas/codex_output.schema.json`
- `artifacts/plan/agent-io-schemas.md`
- `artifacts/plan/termination-reasons.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Design Completeness
- [ ] StepContract schema covers allowed/forbidden paths + codex config
- [ ] Codex output schema forces patch_diff + agent structure
- [ ] Agent IO schemas are minimal and complete
- [ ] Termination reasons match v1 set exactly
- [ ] `failure_context.json` schema defined

##### Integration
- [ ] Allowed paths derivation rules documented with fallback defaults
- [ ] Autogov path-level constraint loading documented

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 2: Implement Step Contract Builder [G1: Code Readiness]

**Prompt:**

Implement `src/spec/executor/contract.py`:

1. **`StepContract` dataclass**
2. **`build_contract(aip: dict, step_idx: int, autogov_policy: dict | None) -> StepContract`**
   - Derive `allowed_paths` using fixed priority rules:
     1. Explicit step declaration
     2. Step outputs + safe defaults (`src/**`, `tests/**`)
     3. Spec `repo.paths` + safe defaults
     4. Fallback to safe defaults
   - Derive `forbidden_paths` from spec + autogov (path-level only)
   - Raise `EscalationRequired` only if `allowed_paths` resolves to empty
3. **`save_contract()` / `load_contract()`**

**Commands:**

```bash
ruff check src/spec/executor/
mypy src/spec/executor/
pytest tests/executor/test_contract.py -v
```

**Outputs:**

- `src/spec/executor/__init__.py`
- `src/spec/executor/contract.py`
- `tests/executor/test_contract.py`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality
- [ ] Contract derivation uses fixed priority rules
- [ ] Safe defaults always included (`src/**`, `tests/**`)
- [ ] Raises `EscalationRequired` only on empty `allowed_paths`
- [ ] Codex config defaults included in contract
- [ ] YAML serialization is deterministic

##### Testing
- [ ] Tests cover derivation from explicit paths
- [ ] Tests cover derivation from outputs
- [ ] Tests cover fallback to safe defaults
- [ ] Tests cover autogov integration

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 3: Implement Scope Checker [G1: Code Readiness]

**Prompt:**

Implement `src/spec/executor/scope.py`:

1. **`check_scope(touched: list[str], contract: StepContract) -> ScopeResult`**
   - Check against `allowed_paths` globs
   - Check against `forbidden_paths` globs

2. **`ScopeResult` dataclass**
   - `passed: bool`
   - `violations: list[ScopeViolation]`

3. **`generate_policy_report(result: ScopeResult) -> dict`**

Note: `touched` files come from runner's `git diff --name-only`, not from parsing patch.

**Commands:**

```bash
ruff check src/spec/executor/
mypy src/spec/executor/
pytest tests/executor/test_scope.py -v
```

**Outputs:**

- `src/spec/executor/scope.py`
- `tests/executor/test_scope.py`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality
- [ ] Glob matching is correct
- [ ] Violations explain which rule failed
- [ ] Policy report structure is machine-readable

##### Testing
- [ ] Tests cover allowed path matching
- [ ] Tests cover forbidden path rejection
- [ ] Tests cover edge cases (root files, nested paths)

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 4: Implement Verification Runner [G1: Code Readiness]

**Prompt:**

Implement `src/spec/executor/verify.py`:

1. **`run_commands(commands: list[str], cwd: Path, timeout: int = 300) -> list[CommandResult]`**

2. **`CommandResult` dataclass**
   - `command`, `exit_code`, `stdout`, `stderr`, `duration_ms`, `timed_out`

3. **`VerificationResult` dataclass**
   - `passed: bool`
   - `commands: list[CommandResult]`
   - `failure_category: str | None`

4. **`generate_verification_report(result: VerificationResult) -> dict`**

**Commands:**

```bash
ruff check src/spec/executor/
mypy src/spec/executor/
pytest tests/executor/test_verify.py -v
```

**Outputs:**

- `src/spec/executor/verify.py`
- `tests/executor/test_verify.py`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality
- [ ] Command execution is safe
- [ ] Timeouts enforced
- [ ] Output captured completely

##### Testing
- [ ] Tests cover success/failure
- [ ] Tests cover timeout
- [ ] Tests use mocked subprocess

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 5: Implement Codex Adapter (Real) [G1: Code Readiness]

**Prompt:**

Implement `src/spec/executor/adapters/`:

1. **`base.py` - Abstract AgentAdapter**:
   ```python
   class AgentAdapter(ABC):
       @abstractmethod
       def execute(self, input_dir: Path, output_dir: Path) -> None:
           """
           Reads input/, writes output/.
           Raises ToolNotFoundError or ProtocolError.
           """
           pass

       @abstractmethod
       def name(self) -> str:
           pass
   ```

2. **`codex.py` - Codex CLI adapter** implementing pinned contract:
   - Invoke `codex exec` with:
     - `--cd <repo_root>`
     - `--sandbox read-only`
     - `--output-schema <schema_path>`
     - `--output-last-message <tmp_path>`
     - `--json`
   - Parse last message JSON → `patch.diff` + `agent.json`
   - Parse JSON event stream → `cmdlog.txt`
   - Apply forbidden command check on `cmdlog.txt`

3. **Error types**: `ToolNotFoundError`, `ProtocolError`

4. **Registry**: `get_adapter(name: str) -> AgentAdapter`

**Commands:**

```bash
ruff check src/spec/executor/
mypy src/spec/executor/
pytest tests/executor/test_adapters.py -v
```

**Outputs:**

- `src/spec/executor/adapters/__init__.py`
- `src/spec/executor/adapters/base.py`
- `src/spec/executor/adapters/codex.py`
- `tests/executor/test_adapters.py`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Interface
- [ ] Minimal interface (execute + name)
- [ ] IO via directories
- [ ] Error types defined

##### Codex Adapter
- [ ] Invokes `codex exec` with all required flags
- [ ] Parses `--output-last-message` JSON correctly
- [ ] Extracts `patch_diff` → `patch.diff`
- [ ] Extracts `agent` → `agent.json`
- [ ] Parses `--json` stream → `cmdlog.txt`
- [ ] Applies forbidden command check
- [ ] Raises `ToolNotFoundError` if `codex` missing
- [ ] Raises `ProtocolError` on schema validation failure

##### Testing
- [ ] Mocked subprocess
- [ ] Success path with valid JSON
- [ ] Failure on invalid JSON
- [ ] Failure on forbidden command in log

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 6: Implement Execution Runner (Orchestrator) [G1: Code Readiness]

**Prompt:**

Implement `src/spec/executor/runner.py`:

1. **`StepRunner` class**:
   ```python
   class StepRunner:
       def run_step(self, aip: dict, step_idx: int, dry_run: bool = False) -> StepResult:
           """Full step lifecycle. Returns only when complete."""
   ```

2. **Execution loop** (three phases):
   - **Extract**: build contract, write input bundle
   - **Loop**: reset → invoke → apply → scope → verify → retry/stop
   - **Gate**: render gate package

3. **`StepResult` dataclass**

4. **`--dry-run` support**: stops after writing input bundle, prints codex invocation

**Commands:**

```bash
ruff check src/spec/executor/
mypy src/spec/executor/
pytest tests/executor/test_runner.py -v
```

**Outputs:**

- `src/spec/executor/runner.py`
- `tests/executor/test_runner.py`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Orchestration
- [ ] Baseline reset before each iteration
- [ ] Patch applied by runner (not agent)
- [ ] Scope check before verification
- [ ] Correct termination reasons
- [ ] `--dry-run` exits after input bundle

##### Testing
- [ ] Full success path
- [ ] Scope violation (no retry)
- [ ] Retry on verify failure
- [ ] Max iterations
- [ ] Dry run path

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 7: Implement Artifact Writer [G1: Code Readiness]

**Prompt:**

Implement `src/spec/executor/artifacts.py`:

1. **`ArtifactWriter` class**
   - `runs/<aip_id>/<timestamp>/step-N/` structure
   - Write all required artifacts
   - Handle iteration subdirectories
   - Preserve `input/` and `output/` snapshots per iteration

2. **Directory layout**:
   ```
   runs/
     AIP-.../
       2024-12-13T10-30-00/
         step-03/
           contract.yaml
           prompt.md
           repo_state.json
           iter-0/
             input/
             output/
             patch.diff
             agent.json
             cmdlog.txt
             verification_report.json
           policy_report.json
           gate.md
           result.json
   ```

**Commands:**

```bash
ruff check src/spec/executor/
mypy src/spec/executor/
pytest tests/executor/test_artifacts.py -v
```

**Outputs:**

- `src/spec/executor/artifacts.py`
- `tests/executor/test_artifacts.py`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Structure
- [ ] Directory layout matches spec
- [ ] Timestamps filesystem-safe
- [ ] Iteration subdirs include input/output snapshots

##### Content
- [ ] All required artifacts written
- [ ] JSON/YAML valid

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 8: Integrate into CLI + --dry-run [G2: Pre-Release]

**Prompt:**

Update `src/spec/cli/spec.py`:

1. **Update `spec run` command**:
   ```python
   @app.command()
   def run(
       step: int = typer.Option(None, "--step", "-s"),
       adapter: str = typer.Option("codex", "--adapter", "-a"),
       max_iterations: int = typer.Option(3, "--max-iterations"),
       allow_dirty: bool = typer.Option(False, "--allow-dirty"),
       dry_run: bool = typer.Option(False, "--dry-run"),
   ):
   ```

2. **`--dry-run` behavior**:
   - Builds contract + schema
   - Writes `runs/.../step-N/input/`
   - Prints exact `codex` invocation
   - Exits 0

3. **Gate presentation**:
   - Show final patch diff
   - Show touched files
   - Show verification summary
   - Show termination reason
   - Prompt: approve / reject / defer

4. **Backward compatible**: no `--step` = existing interactive mode

**Commands:**

```bash
ruff check src/
mypy src/
pytest tests/ -v
```

**Outputs:**

- Updated `src/spec/cli/spec.py`
- `tests/cli/test_run_autonomous.py`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### CLI
- [ ] `--step` triggers autonomous mode
- [ ] `--dry-run` prints invocation and exits
- [ ] `--allow-dirty` works
- [ ] Backward compatible

##### Gate Presentation
- [ ] Diff readable
- [ ] Termination reason clear

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 9: Full Integration Testing [G2: Pre-Release]

**Prompt:**

Create integration tests:

1. **E2E with mocked Codex subprocess**
2. **Scope violation test** (no retry)
3. **Retry behavior test**
4. **Max iterations test**
5. **Dirty worktree test**
6. **Dry run test**
7. **Forbidden command in cmdlog test**

**Commands:**

```bash
pytest tests/integration/test_executor_e2e.py -v
pytest tests/ -v --cov=src/spec/executor --cov-report=term-missing
```

**Outputs:**

- `tests/integration/test_executor_e2e.py`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Coverage
- [ ] All execution paths tested
- [ ] ≥80% coverage
- [ ] No flaky tests
- [ ] Forbidden command detection tested

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 10: Documentation & Finalization [G3: Deployment Approval]

**Prompt:**

1. **Update README.md** with `spec run --step N` usage including `--dry-run`
2. **Create docs/EXECUTOR.md** with:
   - Architecture overview
   - Codex adapter contract
   - Command policy (allowed/forbidden)
   - Troubleshooting guide
3. **Final checks**: all tests pass, lint clean, coverage met

**Commands:**

```bash
ruff check .
mypy src/
pytest tests/ -v --cov=src/spec --cov-fail-under=80
```

**Outputs:**

- Updated `README.md`
- `docs/EXECUTOR.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Documentation
- [ ] README accurate
- [ ] EXECUTOR.md covers Codex contract
- [ ] Command policy documented

##### Quality
- [ ] All tests pass
- [ ] Lint clean
- [ ] Coverage ≥80%

#### Approval Decision
- [ ] APPROVED FOR MERGE
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

---

## Models & Tools

**Tools:** bash, pytest, ruff, mypy, git, codex

**Models:** claude-sonnet-4-5 (implementation), codex (execution target)

## Repository

**Branch:** `feat/spec-run-agent-executor`

**Merge Strategy:** squash
