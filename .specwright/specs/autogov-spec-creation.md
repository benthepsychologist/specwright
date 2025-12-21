---
version: "0.1"
tier: B
title: Autogov Integration for Spec Creation and Execution
owner: benthepsychologist
goal: Make --autogov <project> required for spec create and spec run, loading governance artifacts to enrich specs and execution contracts with policy constraints and architecture context
labels: [integration, governance]
project_slug: specwright
spec_version: 1.0.0
created: 2025-12-19T16:02:37.675950+00:00
updated: 2025-12-19T19:00:00.000000+00:00
orchestrator_contract: "standard"
repo:
  working_branch: "feat/autogov-integration"
---

# Autogov Integration for Spec Creation and Execution

## Objective

> When `autogov.enabled: true` in config, require `--autogov <project>` for `spec create` and `spec run` that:
> 1. Validates the named project exists in the autogov registry (fails fast if not)
> 2. Loads governance artifacts (policy, arch required; state optional with warning)
> 3. Injects `policy.constraints.deny.paths` as additive guidance into Forbidden Paths
> 4. Injects `arch.decisions` summaries into spec Context
> 5. Enriches agent prompts with exported governance text during execution

## Acceptance Criteria

- [ ] `spec create --autogov specwright --tier B --title "Test" --goal "Test goal"` produces `.specwright/specs/test.md` with governance sections populated
- [ ] `spec create --tier B --title "Test" --goal "Test"` (without --autogov) fails when `autogov.enabled: true` in config
- [ ] Generated spec's governance guidance labeled: "Governance Guidance (autogov, non-enforced in v1)"
- [ ] Generated spec's `Context > Governance` section includes ADR summaries from `arch.decisions`
- [ ] Generated spec frontmatter includes `autogov: { project, source, captured_at }` for audit
- [ ] Execution contract includes `governance.guidance.forbidden_paths` (separate from `forbidden_paths`)
- [ ] Old contracts without `governance` field still deserialize and run (backward compat)
- [ ] Agent prompt begins with deterministic header: `=== GOVERNANCE (AUTOGOV) ===` with policy name + version
- [ ] `spec run --autogov specwright --step 1` injects governance export into agent prompt
- [ ] Registry source resolved from `.specwright.yaml` only (no `--source` CLI flag)
- [ ] New module `src/spec/autogov/` exists with loader.py, context_builder.py
- [ ] Autogov imports are lazy (inside loader methods), with `TYPE_CHECKING` imports for type hints
- [ ] Base `SpecwrightError(exit_code)` exception with centralized CLI handling
- [ ] `pytest tests/autogov/ --cov=spec.autogov --cov-fail-under=85` passes
- [ ] `ruff check src/spec/autogov/` passes
- [ ] `mypy src/spec/autogov/` passes

### Failure Precedence (deterministic ordering)

1. Config error (missing `autogov.source` when enabled) → exit 4
2. CLI usage error (missing `--autogov` when enabled) → exit 5
3. Autogov enabled but import fails → exit 1 with message: "This repo is configured to use autogov, but autogov failed to load. Install or fix the environment."
4. Autogov project not found in registry → exit 2
5. Governance artifact malformed/invalid → exit 3

## Context

### Background

Specwright executes specs through gated steps with scope constraints (allowed/forbidden paths). Currently, these constraints are manually specified in each spec. The autogov project provides a governance registry with policies, architecture decisions, and project state that should inform these constraints.

The autogov Python API exposes:
- `load_artifact(name, kind, source)` - Load policy/arch/state artifacts
- `export_pack(artifact, role, format)` - Export for LLM consumption
- `PolicyPack.constraints.deny.paths` - Forbidden paths from policy
- `ArchPack.decisions` - Architecture Decision Records
- `StatePack.maturity` - Project maturity level

Specwright specs are governed by default, not opt-in. This integration makes governance mandatory.

### Constraints

- Must not modify existing spec parsing conventions (frontmatter + section headers)
- Autogov is required only when enabled by repo config (`autogov.enabled: true`), not globally
- Specwright may consume autogov types directly (PolicyPack, ArchPack, etc.) - no over-abstraction
- Must use autogov Python API directly, not subprocess CLI calls
- Autogov imports must be lazy (inside loader methods only); use `TYPE_CHECKING` for type hints
- Single template per tier with conditional governance block, not parallel template files
- CLI must provide a single centralized handler that catches `SpecwrightError` and exits with `e.exit_code`, printing `Error: {message}` to stderr

### Governance Semantics (v1)

- Autogov deny paths are rendered into spec text with explicit label: "Governance Guidance (autogov, non-enforced in v1)"
- Autogov deny paths are injected into execution contract as `governance.guidance.forbidden_paths` (NOT `StepContract.forbidden_paths`)
- StepContract.governance is optional; old contracts without it still deserialize and run
- Agent prompt begins with deterministic header: `=== GOVERNANCE (AUTOGOV) ===` including policy name + version
- Scope enforcer does NOT block on governance guidance paths in v1
- Hard enforcement will be introduced in a later spec (v2) via scope enforcer integration

### Provenance & Audit

- Frontmatter `autogov` block is an audit snapshot, not source of truth for execution
- Includes: `project`, `source`, `captured_at` (ISO timestamp), `captured_from` (config path)
- Execution always uses current config + CLI args, not frontmatter values

## Interface Specification

### CLI: `spec create`

```
spec create --autogov <project> --title <title> [options...]

Required Options (when autogov.enabled: true):
  --autogov TEXT     Autogov project name
  --title TEXT       Spec title

Options:
  --tier TEXT        Risk tier A/B/C
  --goal TEXT        Objective
  --owner TEXT       GitHub username
  --branch TEXT      Working branch
  --output PATH      Output file path
  --set-current      Set as current working spec

Config (.specwright.yaml):
  autogov:
    enabled: true     # Autogov required when true
    source: org       # or "patterns"

Behavior:
  1. Check config: if autogov.enabled but missing autogov.source → exit 4
  2. If autogov.enabled but --autogov not provided → exit 5
  3. If autogov.enabled: import autogov (exit 1 if fails with message)
  4. Load <project>.policy.yaml (exit 2 if project not found)
  5. Load <project>.arch.yaml (exit 2 if not found)
  6. Load <project>.state.yaml (warn if missing, continue)
  7. Validate artifacts (exit 3 if malformed)
  8. Render template with governance context + captured_at timestamp
  9. Write spec to output path

Exit codes:
  0  Success
  1  Autogov enabled but failed to load
  2  Autogov project not found in registry
  3  Invalid/malformed governance artifact
  4  Config error (missing source when enabled)
  5  CLI usage error (missing --autogov when enabled)
```

### CLI: `spec run`

```
spec run --autogov <project> [existing flags...]

Required Options (when autogov.enabled: true):
  --autogov TEXT     Autogov project name

Behavior:
  1. Check config: if autogov.enabled but missing autogov.source → exit 4
  2. If autogov.enabled but --autogov not provided → exit 5
  3. Load governance artifacts (same validation + exit codes as create)
  4. Inject deny paths into contract.governance.guidance.forbidden_paths
  5. Prepend governance to agent prompt with header: === GOVERNANCE (AUTOGOV) ===
  6. Proceed with normal execution

Exit codes:
  Same as spec create
```

### Generated Spec Structure

All specs created via `spec create` include governance. Template supports conditional governance for backward compatibility with manual/legacy specs.

**Frontmatter (audit snapshot, not source of truth):**
```yaml
autogov:
  project: specwright
  source: org
  captured_at: 2025-12-19T19:30:00+00:00
  captured_from: .specwright.yaml
```

**Template structure:**
```markdown
## Context

### Background
> [User-provided or default background]

{% if autogov %}
### Governance

> Governance: {{ autogov.project }} (policy v{{ autogov_policy_version }})

**Policy:** {{ autogov_policy_name }} v{{ autogov_policy_version }}
**Architecture:** {{ autogov_arch_name }} v{{ autogov_arch_version }}

#### Architecture Decisions
{% for decision in autogov_arch_decisions %}
- **{{ decision.id }}**: {{ decision.title }} ({{ decision.status }})
  > {{ decision.decision }}
{% endfor %}

### Constraints
{% for rule in autogov_policy_rules %}
- {{ rule.description }}
{% endfor %}
{% endif %}

## Plan

### Step N: Implementation [G1: Code Readiness]

**Forbidden Paths:**
- `.git/**`
- `*.lock`
- `.env*`

{% if autogov %}
**Governance Guidance (autogov, non-enforced in v1):**
{% for path in autogov_forbidden_paths %}
- `{{ path.path }}`  # {{ path.reason }}
{% endfor %}
{% endif %}
```

### Configuration

`.specwright.yaml` autogov section:

```yaml
version: '0.5'
paths:
  specs: .specwright/specs
  aips: .specwright/aips
autogov:
  enabled: true           # Autogov required when true
  source: org             # patterns | org - no CLI override
```

## Plan

### Step 1: Create autogov module with loader and centralized exceptions [G0: Plan Approval]

**Prompt:**

Create the `src/spec/autogov/` module with:

1. `__init__.py` - Minimal, NO autogov imports at top level
   - Only export exception classes and lazy loader
   - This keeps `spec list`, `spec validate` etc working if autogov env is broken

2. `exceptions.py` - Centralized exit-code handling:
   ```python
   class SpecwrightError(Exception):
       """Base exception with exit code for centralized CLI handling."""
       exit_code: int = 1

       def __init__(self, message: str, exit_code: int | None = None):
           super().__init__(message)
           if exit_code is not None:
               self.exit_code = exit_code

   class AutogovNotInstalledError(SpecwrightError):
       exit_code = 1

   class GovernanceNotFoundError(SpecwrightError):
       exit_code = 2

   class GovernanceInvalidError(SpecwrightError):
       exit_code = 3

   class RegistryConfigError(SpecwrightError):
       exit_code = 4

   class CLIUsageError(SpecwrightError):
       exit_code = 5
   ```

3. `loader.py` - GovernanceLoader class with LAZY imports + TYPE_CHECKING:
   ```python
   from typing import TYPE_CHECKING

   if TYPE_CHECKING:
       from autogov.models import PolicyPack, ArchPack, StatePack

   class GovernanceLoader:
       def load_policy(self, project: str, source: str) -> "PolicyPack":
           try:
               from autogov import load_artifact
           except ImportError:
               raise AutogovNotInstalledError(
                   "This repo is configured to use autogov, but autogov failed to load. "
                   "Install or fix the environment."
               )
           # ... load logic
   ```
   - `load_policy(project, source) -> PolicyPack` (raises if missing)
   - `load_arch(project, source) -> ArchPack` (raises if missing)
   - `load_state(project, source) -> StatePack | None` (warns if missing)
   - `load_all(project, source) -> GovernanceBundle`
   - Use autogov types directly - no wrapper types

Write tests in `tests/autogov/test_loader.py`:
- Test successful load of each artifact type
- Test missing policy raises GovernanceNotFoundError (exit_code=2)
- Test missing arch raises GovernanceNotFoundError (exit_code=2)
- Test missing state returns None with warning
- Test missing autogov package raises AutogovNotInstalledError (exit_code=1)

**Allowed Paths:**

- `src/spec/autogov/**`
- `tests/autogov/**`

**Forbidden Paths:**

- `src/spec/cli/**`
- `src/spec/compiler/**`
- `src/spec/executor/**`
- `.git/**`

**Verification Commands:**

```bash
ruff check src/spec/autogov/
mypy src/spec/autogov/
pytest tests/autogov/test_loader.py -v
```

**Outputs:**

- `src/spec/autogov/__init__.py`
- `src/spec/autogov/loader.py`
- `src/spec/autogov/exceptions.py`
- `tests/autogov/__init__.py`
- `tests/autogov/test_loader.py`

### Step 2: Create context builder [G0: Plan Approval]

**Prompt:**

Create `src/spec/autogov/context_builder.py` with SpecContextBuilder class:

1. `build_forbidden_paths(policy: PolicyPack) -> list[dict]`
   - Extract paths from `policy.constraints.deny.paths`
   - Return list of `{"path": str, "reason": str}` dicts
   - Format as glob patterns (append `/**` if needed)

2. `build_governance_context(bundle: GovernanceBundle, project: str, source: str) -> dict`
   - Return dict with all template variables:
     - `autogov` dict: `{"project": str, "source": str, "captured_at": ISO timestamp}`
     - `autogov_policy_name`, `autogov_policy_version`
     - `autogov_arch_name`, `autogov_arch_version`
     - `autogov_arch_decisions` (list of decision dicts)
     - `autogov_policy_rules` (list of rule dicts, severity=error only)
     - `autogov_forbidden_paths` (from build_forbidden_paths)

3. `build_prompt_header(policy: PolicyPack) -> str`
   - Return deterministic header for agent prompt:
     ```
     === GOVERNANCE (AUTOGOV) ===
     Policy: {name} v{version}
     ```

4. `merge_with_template_context(bundle: GovernanceBundle, base_context: dict, project: str, source: str) -> dict`
   - Merge governance context into base Jinja2 context
   - Include `captured_at` timestamp

Write tests in `tests/autogov/test_context_builder.py`:
- Test each builder method with realistic fixtures
- Test with missing optional fields in artifacts
- Test prompt header format is deterministic
- Standard assertion-based tests (no snapshots)

**Allowed Paths:**

- `src/spec/autogov/**`
- `tests/autogov/**`

**Forbidden Paths:**

- `src/spec/cli/**`
- `src/spec/compiler/**`
- `src/spec/executor/**`
- `.git/**`

**Verification Commands:**

```bash
ruff check src/spec/autogov/
mypy src/spec/autogov/
pytest tests/autogov/ -v
```

**Outputs:**

- `src/spec/autogov/context_builder.py`
- `tests/autogov/test_context_builder.py`
- `tests/autogov/fixtures/sample_policy.yaml`
- `tests/autogov/fixtures/sample_arch.yaml`

### Step 3: Add governance blocks to existing templates [G0: Plan Approval]

**Prompt:**

Modify existing tier templates to include conditional governance blocks:

1. Edit `config/templates/specs/tier-a-template.md`:
   - Add `autogov` frontmatter field (structured: `project`, `source`, `captured_at`)
   - Add `{% if autogov %}` governance section under Context
   - Add separate section labeled: "Governance Guidance (autogov, non-enforced in v1)"

2. Edit `config/templates/specs/tier-b-template.md`:
   - Same changes as tier-a

3. Edit `config/templates/specs/tier-c-template.md`:
   - Same changes as tier-a

Single template per tier. No parallel *-autogov-template.md files.

Template variables to support:
- `autogov` - Dict with `project`, `source`, `captured_at` keys (or None)
- `autogov_policy_name`, `autogov_policy_version`
- `autogov_arch_name`, `autogov_arch_version`
- `autogov_arch_decisions` - List of decision dicts
- `autogov_policy_rules` - List of rule dicts
- `autogov_forbidden_paths` - List of path dicts with `path` and `reason`

Write template tests in `tests/autogov/test_template.py`:
- Test rendering with governance context populated
- Test governance section appears in output
- Test label is exactly: "Governance Guidance (autogov, non-enforced in v1)"
- Standard assertion-based tests (no snapshots)

**Allowed Paths:**

- `config/templates/specs/**`
- `tests/autogov/**`
- `src/spec/autogov/**`

**Forbidden Paths:**

- `src/spec/cli/**`
- `src/spec/compiler/**`
- `.git/**`

**Verification Commands:**

```bash
pytest tests/autogov/test_template.py -v
```

**Outputs:**

- Modified `config/templates/specs/tier-a-template.md`
- Modified `config/templates/specs/tier-b-template.md`
- Modified `config/templates/specs/tier-c-template.md`
- `tests/autogov/test_template.py`

### Step 4: Make --autogov required on spec create (when enabled) [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Modify `src/spec/cli/spec.py` `create()` function:

1. Change `title` from positional argument to required option:
   ```python
   title: str = typer.Option(..., "--title", "-t", help="Spec title (required)")
   ```

2. Add `--autogov` option (required when autogov.enabled):
   ```python
   autogov_project: str | None = typer.Option(None, "--autogov", help="Autogov project name")
   ```

3. Check config and validate (failure precedence):
   ```python
   autogov_cfg = cfg.get("autogov", {})
   autogov_enabled = autogov_cfg.get("enabled", False)

   if autogov_enabled:
       if "source" not in autogov_cfg:
           raise RegistryConfigError("Missing autogov.source in .specwright.yaml")
       if not autogov_project:
           raise CLIUsageError("--autogov is required when autogov.enabled: true")
   ```

4. CLI must provide centralized exception handler that catches `SpecwrightError` and exits with `e.exit_code`, printing `Error: {message}` to stderr. (Implementation mechanism left to implementer.)

5. Load governance (lazy import, exceptions bubble up to handler):
   ```python
   if autogov_enabled:
       from spec.autogov.loader import GovernanceLoader
       loader = GovernanceLoader()
       bundle = loader.load_all(autogov_project, autogov_cfg["source"])
   ```

6. Use SpecContextBuilder to merge governance into template context with captured_at

7. Use same tier template (with governance conditional block)

Write/update tests in `tests/cli/test_spec_create.py`:
- Test `--autogov` with valid project produces spec with governance
- Test missing `--autogov` when enabled fails with exit code 5 (CLIUsageError)
- Test missing config autogov.source when enabled fails with exit code 4
- Test autogov import failure when enabled fails with exit code 1
- Test `--autogov nonexistent` fails with exit code 2
- Test invalid artifact fails with exit code 3

**Allowed Paths:**

- `src/spec/cli/spec.py`
- `src/spec/autogov/**`
- `tests/cli/test_spec_create.py`
- `tests/autogov/**`

**Forbidden Paths:**

- `src/spec/compiler/**`
- `src/spec/executor/**`
- `.git/**`
- `*.lock`

**Verification Commands:**

```bash
ruff check src/spec/cli/spec.py src/spec/autogov/
mypy src/spec/cli/spec.py src/spec/autogov/
pytest tests/cli/test_spec_create.py tests/autogov/ -v
```

**Outputs:**

- Modified `src/spec/cli/spec.py`
- `tests/cli/test_spec_create.py` (new or updated)

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality
- [ ] `ruff check .` passes
- [ ] `mypy src/spec/cli/ src/spec/autogov/` passes
- [ ] No `--source` CLI flag exists
- [ ] Exit codes match spec (1/2/3/4/5)
- [ ] Error messages include actionable guidance

##### Testing
- [ ] Test: create with valid autogov produces governance section
- [ ] Test: missing --autogov when enabled exits 5
- [ ] Test: missing source when enabled exits 4
- [ ] Test: nonexistent project exits 2
- [ ] Test: invalid artifact exits 3

##### Integration
- [ ] Works with real autogov registry (manual verification)
- [ ] Generated spec compiles successfully

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
<!-- GATE_REVIEW_END -->

### Step 5: Make --autogov required on spec run (when enabled) [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Modify `src/spec/cli/spec.py` `run()` and `_run_autonomous_step()`:

1. Add `--autogov` option (required when autogov.enabled):
   ```python
   autogov_project: str | None = typer.Option(None, "--autogov", help="Autogov project name")
   ```

2. Same config validation as create (uses centralized exception handler)

3. Load governance once at run() level, pass bundle to _run_autonomous_step()

4. Modify StepContract dataclass in `src/spec/executor/contract.py`:
   ```python
   @dataclass
   class StepContract:
       # ... existing fields ...
       governance: dict | None = None  # NEW: optional for backward compat
   ```

5. In contract builder, populate governance guidance (NOT forbidden_paths):
   ```python
   if bundle:
       contract.governance = {
           "guidance": {
               "forbidden_paths": [
                   {"path": p.path, "reason": p.reason}
                   for p in bundle.policy.constraints.deny.paths
               ]
           }
       }
   ```

6. Modify prompt building in StepRunner:
   - Use `build_prompt_header(bundle.policy)` from context_builder
   - Prepend: `=== GOVERNANCE (AUTOGOV) ===\nPolicy: {name} v{version}\n`
   - Then include full governance export

7. Ensure contract serialization handles optional governance field (backward compat)

Write tests in `tests/cli/test_spec_run.py`:
- Test contract has `governance.guidance.forbidden_paths` (separate from forbidden_paths)
- Test old contracts without governance field still load
- Test prompt begins with `=== GOVERNANCE (AUTOGOV) ===`
- Test missing --autogov when enabled fails with exit code 5 (CLIUsageError)
- Test nonexistent project exits 2

**Allowed Paths:**

- `src/spec/cli/spec.py`
- `src/spec/executor/runner.py`
- `src/spec/executor/contract.py`
- `src/spec/autogov/**`
- `tests/cli/test_spec_run.py`
- `tests/executor/test_runner.py`
- `tests/executor/test_contract.py`

**Forbidden Paths:**

- `src/spec/compiler/**`
- `.git/**`
- `*.lock`

**Verification Commands:**

```bash
ruff check src/spec/cli/ src/spec/executor/ src/spec/autogov/
mypy src/spec/cli/ src/spec/executor/ src/spec/autogov/
pytest tests/cli/test_spec_run.py tests/executor/test_runner.py tests/executor/test_contract.py -v
```

**Outputs:**

- Modified `src/spec/cli/spec.py`
- Modified `src/spec/executor/runner.py`
- Modified `src/spec/executor/contract.py`
- `tests/cli/test_spec_run.py`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality
- [ ] `ruff check .` passes
- [ ] `mypy .` passes
- [ ] Governance loaded once at run() level, not per-step
- [ ] No `--source` CLI flag exists
- [ ] Centralized exception handler catches SpecwrightError

##### Governance Semantics
- [ ] Contract has optional `governance.guidance.forbidden_paths` field
- [ ] Contract `forbidden_paths` does NOT contain autogov paths
- [ ] Agent prompt begins with `=== GOVERNANCE (AUTOGOV) ===`
- [ ] Old contracts without governance field still deserialize

##### Testing
- [ ] Missing --autogov when enabled fails with exit 5
- [ ] Exit codes match spec (1/2/3/4/5)

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
<!-- GATE_REVIEW_END -->

### Step 6: Add autogov config section [G1: Code Readiness]

**Prompt:**

Extend `.specwright.yaml` schema and loader:

1. Update `src/spec/core/loader.py` to recognize `autogov` section:
   ```yaml
   autogov:
     enabled: true   # Autogov required when true
     source: org     # patterns | org
   ```

2. Update `spec init` to prompt for autogov config:
   - Ask: "Enable autogov governance? (y/n)"
   - If yes, ask: "Registry source? (org/patterns)"
   - Write autogov section to config

3. Validation rules (handled by RegistryConfigError):
   - If `autogov.enabled` missing → default to `false` (backward compat)
   - If `autogov.enabled: false` → `source` is optional/ignored
   - If `autogov.enabled: true` but `autogov.source` missing → exit 4

Write tests:
- Test config loading with autogov section
- Test config loading without autogov section (enabled defaults to false)
- Test autogov.enabled: true but missing source raises RegistryConfigError
- Test spec init creates autogov section when enabled

**Allowed Paths:**

- `src/spec/core/loader.py`
- `src/spec/cli/spec.py`
- `tests/core/test_loader.py`
- `tests/cli/test_spec_create.py`

**Forbidden Paths:**

- `src/spec/compiler/**`
- `src/spec/executor/**`
- `.git/**`

**Verification Commands:**

```bash
ruff check src/spec/core/ src/spec/cli/
mypy src/spec/core/ src/spec/cli/
pytest tests/core/test_loader.py tests/cli/test_spec_create.py -v
```

**Outputs:**

- Modified `src/spec/core/loader.py`
- Modified `src/spec/cli/spec.py`
- Updated tests

### Step 7: Full integration test [G2: Pre-Release]

**Prompt:**

1. Create integration test in `tests/integration/test_autogov_integration.py`:
   - End-to-end: create spec with autogov, compile, validate
   - End-to-end: run step with autogov, verify contract has governance paths
   - Test with mock autogov registry fixtures
   - Standard assertion-based tests (no snapshots)

2. Add autogov as required dependency to `pyproject.toml`:
   ```toml
   dependencies = [
       # ... existing deps
       "autogov>=0.1.0",
   ]
   ```

3. Update CLI help text to indicate --autogov is required

**Verification Commands:**

```bash
pytest tests/integration/test_autogov_integration.py -v
pytest --cov=spec.autogov --cov-fail-under=85
ruff check .
mypy .
```

**Outputs:**

- `tests/integration/test_autogov_integration.py`
- Modified `pyproject.toml`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Test Coverage
- [ ] `pytest --cov=spec.autogov --cov-fail-under=85` passes
- [ ] Integration tests pass
- [ ] No regressions in existing tests

##### Quality
- [ ] `ruff check .` passes
- [ ] `mypy .` passes
- [ ] CLI help shows --autogov as required

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
<!-- GATE_REVIEW_END -->

## Models & Tools

**Tools:** bash, pytest, ruff, mypy

**Models:** claude-sonnet-4-20250514 (implementation), claude-opus-4-20250514 (review)

## Repository

**Branch:** `feat/autogov-integration`

**Merge Strategy:** squash

## Dependencies

**Runtime:**
- autogov>=0.1.0 (required when `autogov.enabled: true`; if enabled and import fails → exit 1)

**Dev:**
- pytest-cov
