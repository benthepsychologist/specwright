---
version: "0.1"
tier: C
title: Soft determinism slim down
owner: benthepsychologist
goal: Refactor step execution for Claude interactive mode with soft determinism and remove Codex
labels: [refactor, claude, breaking-change]
project_slug: specwright
spec_version: 1.0.0
created: 2025-12-17T19:23:01.239143+00:00
updated: 2025-12-17T19:30:00.000000+00:00
orchestrator_contract: "standard"
repo:
  working_branch: "feat/soft-determinism-slim-down"
---

# Soft determinism slim down

## Objective

> Refactor the step execution flow for Claude's interactive babysitting mode with "softer determinism": keep human changes (no git reset on iteration 0 for Claude interactive only), still run scope checking and verification, print commit commands after verification (don't auto-commit), and **remove Codex completely** from the codebase.

## Acceptance Criteria

### Core Behavior
- [ ] Skip git reset on iter-0 **only** for Claude adapter in interactive mode
- [ ] Other adapters/modes still reset on iter-0 (unchanged behavior)
- [ ] Claude interactive returns normally on success (no unconditional EscalationRequired)
- [ ] Runner handles escalation decisions (scope fail → escalate, verify fail → escalate)

### Codex Removal
- [ ] `src/spec/executor/adapters/codex.py` deleted
- [ ] `CodexConfig` dataclass removed from `contract.py`
- [ ] `codex_config` field removed from `StepContract`
- [ ] All Codex test classes removed from `test_adapters.py`
- [ ] `grep -r "codex" src/ tests/` returns no results

### Contract Simplification
- [ ] `StepContract` has new `adapter: dict[str, Any]` field (default: `{"name": "claude", "mode": "interactive"}`)
- [ ] `verification_commands` defaults to empty list (not hardcoded commands)
- [ ] `repo_state.json` uses `adapter` field instead of codex-specific fields

### CLI Improvements
- [ ] After step completion, CLI prints git status and suggested commit commands
- [ ] CLI does NOT auto-commit (prints commands for user to run)

### Artifacts
- [ ] `step.summary.json` **always** written (even on ProtocolError/Escalation) for drift visibility

### Testing
- [ ] CI green (ruff + mypy + pytest)
- [ ] `test_adapters.py` asserts "claude" exists and "codex" does NOT exist

## Context

### Background

The current execution flow has Codex-specific assumptions baked in:
1. **Git reset on every iteration** - This destroys human changes made during babysitting
2. **Codex-typed config** - `CodexConfig` and `codex_config` field are unused with Claude adapter
3. **Unconditional escalation** - Claude interactive raises `EscalationRequired` even on normal exit

For Claude interactive babysitting to work properly:
- Human changes during the session must be preserved (no reset on iter-0)
- Normal session exit should proceed to scope check + verification
- Escalation should only happen when something is actually wrong

### Key Design Decisions

**Termination Semantics (Clean Separation)**

| Component | Responsibility |
|-----------|---------------|
| Claude Adapter | "Dumb and reliable" - ProtocolError on session failure, return normally on success |
| Runner | Policy/quality gating - EscalationRequired on scope/verify failures |

**Reset Rule (Soft Determinism)**

```python
is_soft_determinism = (adapter_name == "claude" and mode == "interactive")

for iteration in range(max_iterations):
    should_reset = True
    if iteration == 0 and is_soft_determinism:
        should_reset = False  # Preserve human changes
    if should_reset:
        self._reset_to_baseline(baseline)
```

### Constraints

- This is Pass 1 (engine running). Pass 2 (repo.build.yaml, spec.resolve.json) is out of scope.
- No auto-commit - always print commands for user to run
- Keep adapter "dumb" - policy decisions stay in runner

## Plan

### Step 1: Remove Codex Adapter [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Delete the Codex adapter and remove all references from the codebase.

1. **Delete** `src/spec/executor/adapters/codex.py`

2. **Update** `src/spec/executor/adapters/__init__.py`:
   - Remove `CodexAdapter` import
   - Remove from `_ADAPTERS` registry
   - Remove from `__all__`

3. **Update** `src/spec/executor/contract.py`:
   - Delete `CodexConfig` dataclass
   - Delete `CODEX_ALLOWED_COMMANDS` constant
   - Delete `CODEX_FORBIDDEN_COMMANDS` constant
   - Remove `codex_config` field from `StepContract`
   - Add `adapter: dict[str, Any] = field(default_factory=lambda: {"name": "claude", "mode": "interactive"})`
   - Change `verification_commands` default to `field(default_factory=list)`

4. **Update** `tests/executor/test_adapters.py`:
   - Delete all `TestCodexAdapter*` classes
   - Delete `TestForbiddenCommands`, `TestTokenAwareMatching`, etc.
   - Update `TestAdapterRegistry` to assert "claude" exists and "codex" does NOT exist

5. **Verify** with `grep -r "codex" src/ tests/` - should return no results

**Allowed Paths:**

- `src/spec/executor/adapters/**`
- `src/spec/executor/contract.py`
- `tests/executor/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`

**Verification Commands:**

```bash
ruff check src/spec/executor/adapters/ src/spec/executor/contract.py tests/executor/
mypy src/spec/executor/adapters/ src/spec/executor/contract.py
pytest tests/executor/test_adapters.py -v
```

**Outputs:**

- `src/spec/executor/adapters/codex.py` (deleted)
- `src/spec/executor/adapters/__init__.py` (modified)
- `src/spec/executor/contract.py` (modified)
- `tests/executor/test_adapters.py` (modified)

---

### Step 2: Update Runner for Soft Determinism [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Update the step runner to implement soft determinism and remove Codex-specific code.

1. **Update** `src/spec/executor/runner.py`:

   a. **Skip reset for Claude interactive iter-0** (around line 269):
   ```python
   # Compute soft determinism flag once (before loop)
   is_soft_determinism = (
       self.adapter_name == "claude"
       and contract.adapter.get("mode") == "interactive"
   )

   for iteration in range(max_iterations):
       should_reset = True
       if iteration == 0 and is_soft_determinism:
           should_reset = False
       if should_reset:
           self._reset_to_baseline(baseline)
   ```

   b. **Update repo_state.json** (around line 245):
   ```python
   # OLD: "codex_sandbox_mode": contract.codex_config.sandbox_mode,
   # NEW:
   "adapter": contract.adapter,
   ```

   c. **Delete `_build_codex_command` method** (around line 715)

   d. **Change default adapter** from "codex" to "claude" (line 115)

   e. **Add step.summary.json** in `_finalize_artifacts` (this already runs on ALL paths including errors):

   Note: `_finalize_artifacts` is called in a finalization path that runs even on ProtocolError/Escalation,
   so step.summary.json will always be written for drift visibility.

   ```python
   # Write step.summary.json - ALWAYS written for drift visibility
   step_summary = {
       "adapter": self.adapter_name,
       "mode": contract.adapter.get("mode", "unknown"),
       "baseline_commit": result.baseline_sha,
       "changed_files": result.touched_files,
       "verification_passed": result.verification_report.get("passed", False) if result.verification_report else None,
       "scope_ok": result.policy_report.get("passed", False) if result.policy_report else None,
       "termination_reason": result.termination_reason.value,
       "error": result.error,  # Include error message for failed runs
   }
   (run_dir / "step.summary.json").write_text(json.dumps(step_summary, indent=2))
   ```

**Allowed Paths:**

- `src/spec/executor/runner.py`
- `tests/executor/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`

**Verification Commands:**

```bash
ruff check src/spec/executor/runner.py
mypy src/spec/executor/runner.py
pytest tests/executor/test_runner.py -v
```

**Outputs:**

- `src/spec/executor/runner.py` (modified)

---

### Step 3: Fix Claude Adapter Termination [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Update the Claude adapter to return normally on success instead of always raising EscalationRequired.

1. **Update** `src/spec/executor/adapters/claude.py`:

   Remove the unconditional `EscalationRequired` at the end of `_execute_interactive` (around line 218-221).

   The method should end like this:
   ```python
   # Capture repo state after
   repo_state_after = self._capture_repo_state(repo_root)
   (output_dir / "repo_state_after.json").write_text(
       json.dumps(repo_state_after, indent=2)
   )

   # Backfill missing artifacts
   warnings = self._backfill_artifacts(output_dir, repo_root)
   for warning in warnings:
       logger.warning(f"Artifact backfill: {warning}")

   # Validate agent.json - raises ProtocolError if can't validate
   self._validate_agent_json(output_dir / "agent.json")

   # Normal exit - return cleanly
   # Runner handles scope check + verification + escalation decisions
   ```

   **Do NOT raise EscalationRequired** on normal exit. Only raise:
   - `ProtocolError` if Claude exits non-zero
   - `ProtocolError` if artifacts missing and cannot be backfilled

**Allowed Paths:**

- `src/spec/executor/adapters/claude.py`
- `tests/executor/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`

**Verification Commands:**

```bash
ruff check src/spec/executor/adapters/claude.py
mypy src/spec/executor/adapters/claude.py
pytest tests/executor/test_claude_adapter.py -v
```

**Outputs:**

- `src/spec/executor/adapters/claude.py` (modified)

---

### Step 4: CLI Commit Commands [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Update the CLI to print commit commands after step completion instead of auto-committing.

1. **Update** `src/spec/cli/spec.py`:

   After `runner.run_step()` returns, add:
   ```python
   # After successful execution or escalation with artifacts
   if result.termination_reason in (TerminationReason.PASS, TerminationReason.ESCALATE_NEEDS_HUMAN):
       # Show status
       typer.echo("\n" + "="*60)
       if result.verification_report:
           status = "PASSED" if result.verification_report.get("passed") else "FAILED"
           typer.echo(f"Verification: {status}")

       # Show git status
       subprocess.run(["git", "status", "--short"], cwd=project_root)

       # Suggest commit
       step_desc = step_def.get("description", f"Step {step_num}")
       commit_msg = f"feat: {step_desc}"

       typer.echo(f"\nSuggested commit message: {commit_msg}")
       typer.echo("\nTo commit these changes:")
       typer.echo(f'  git add -A')
       typer.echo(f'  git commit -m "{commit_msg}"')
       typer.echo("\nIf you want to keep working, don't commit yet.")
   ```

2. **Ensure default adapter is "claude"** (should already be set, verify around line 883)

**Allowed Paths:**

- `src/spec/cli/spec.py`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`

**Verification Commands:**

```bash
ruff check src/spec/cli/spec.py
mypy src/spec/cli/spec.py
```

**Outputs:**

- `src/spec/cli/spec.py` (modified)

---

### Step 5: Integration Testing [G2: Verification]

**Role:** agentic

**Prompt:**

Run full test suite and fix any remaining issues.

1. Run `pytest` and fix any failures
2. Run `ruff check .` and fix any lint errors
3. Run `mypy .` and fix any type errors
4. Verify `grep -r "codex" src/ tests/` returns no results

**Allowed Paths:**

- `src/**`
- `tests/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`

**Verification Commands:**

```bash
ruff check .
mypy .
pytest -v
```

**Outputs:**

- Any files that needed fixes

## Models & Tools

**Tools:** bash, pytest, ruff, mypy

**Models:** claude

## Repository

**Branch:** `feat/soft-determinism-slim-down`

**Merge Strategy:** squash