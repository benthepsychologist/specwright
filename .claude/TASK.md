---
id: t008-03
title: JobDef Integration for Agent-Parameterized Workflows
tier: B
owner: benthepsychologist
goal: Enable JobDef templates to parameterize agent selection at compile time
status: planned
branch: feat/jobdef-agent-param
repo:
  name: specwright
  url: https://github.com/workspace/specwright
created: 2026-02-05T00:00:00Z
updated: 2026-02-12T00:00:00Z
---

# t008-03: JobDef Integration for Agent-Parameterized Workflows

**Epic**: t008-agent-reference-syncing-and-continuous-improvement
**Status**: planned
**Branch**: feat/jobdef-agent-param
**Target**: specwright
**Depends on**: t008-01-agent-sync-refs

---

## Summary

Add `refs.sync` step and agent parameterization to JobDef templates (aip-1.yaml, interactive-1.yaml), enabling the same workflow to execute with different coding agents. Agent selection is **required at compile time** via `@payload.agent` variable reference.

## Context

JobDefs currently hardcode `backend: claude-code` for agent execution. With t008-01 providing agent-agnostic reference syncing, we can now parameterize JobDefs via `backend: "@payload.agent"` to support multiple agents while keeping workflow logic unified. Variable resolution happens at compile time (not runtime), so the resolved backend is known before dispatch.

## Problem Statement

1. JobDefs hardcode agent to Claude Code — can't execute with other agents
2. Adding new agents requires duplicating entire JobDef templates
3. No reference syncing before agent execution
4. Can't mix agents in a single workflow (e.g., claude-code → gpt-5.2 → claude-code)

## Solution

1. Add `agent` as a **required** parameter in JobDef payload
2. Add `refs.sync` step to synchronize agent reference files before execution
3. Use `@payload.agent` variable reference in `backend` field (resolved at compile time)
4. Update JobDef templates (aip-1.yaml, interactive-1.yaml) with agent parameterization

## Constraints

- **NO backward compatibility** — `agent` parameter is REQUIRED in payload
- Agent parameter is a string (e.g., "claude-code", "copilot") — not an object
- Variable resolution happens at **compile time**, not runtime
- BackendBase API unchanged (schema changes only in StepTemplate)

## Prerequisites

### Schema Changes Required

The `backend` field in `StepTemplate` is currently typed as `Backend` (enum only).
To support `backend: "@payload.agent"`, allow strings for variable references:

**Files requiring changes:**
- `src/spec/executor/schemas/shared.py` — Update Backend enum if adding new backends (e.g., `COPILOT = "copilot"` for t008-04)
- `src/spec/executor/schemas/job_def.py` — Change `StepTemplate.backend: Backend | str`
- `src/spec/executor/schemas/job_instance.py` — Keep `Step.backend: Backend` (enum only — receives resolved value)
- `src/spec/executor/schemas/manifest.py` — Keep `StepManifest.backend: Backend` (enum only)

**Pattern**: JobDef templates allow `str` for variable references; after compilation, Step and StepManifest always receive resolved `Backend` enum values.
**Note**: Backend enum uses snake_case in code (`claude_code`) but kebab-case in value (`"claude-code"`).

### Engine Modification Required

The `compile_job()` function in `src/spec/executor/engine.py` must be extended for:

#### 1. Backend Variable Resolution

For each `StepTemplate.backend`:
- If it's a string like `"@payload.agent"`, extract the variable name
- Resolve against the provided payload dict
- Validate the resolved value is a valid Backend enum name (case-insensitive)
- Convert to Backend enum and assign to `Step.backend`

**Validation rules**:
- If `backend` is `"@payload.agent"` but payload doesn't have `agent` key → **compilation error**
- If resolved value is not a valid backend name → **compilation error**
- No fallback defaults — all must be explicit in payload

**Example**:
```python
# JobDef template:
step: {step_id: "agent.run", backend: "@payload.agent"}

# Payload:
{agent: "claude-code", ...}

# After compile():
step: {step_id: "agent.run", backend: Backend.CLAUDE_CODE}  # enum, resolved
```

#### 2. Preflight Agent Validation (New)

After resolving backend variables, validate agent availability using existing `verify()` method:
```python
def _preflight_backend_checks(job_instance: JobInstance) -> None:
    """Validate backends are available — once per unique backend, not per-step."""
    # Collect unique backends used in the job (efficient verification)
    unique_backends = {step.backend for step in job_instance.steps}

    # Verify each backend ONCE
    for backend_enum in unique_backends:
        backend_instance = get_backend(backend_enum)
        try:
            backend_instance.verify()
        except BackendError as e:
            raise CompilationError(
                f"Backend '{backend_enum.value}' is not available.\n"
                f"Details: {str(e)}\n"
                f"Check your environment: CLI installed? Authenticated? Models available?"
            ) from e

def compile_job(job_def, payload):
    ...
    # Resolve variables and build steps
    job_instance = JobInstance(...)

    # Run preflight checks for all backends (NEW)
    _preflight_backend_checks(job_instance)

    return job_instance
```

**What verify() checks** (backend-specific):
- **claude-code**: Claude Code CLI installed via `shutil.which("claude")`
- **copilot**: Copilot CLI installed, authenticated, model availability
- **cmd/python**: Default verify() does nothing (always available)
- Each backend raises `BackendError` with helpful context if unavailable

**Timing**: Preflight checks run after compilation but before dispatch, following existing `_require_llm_preflight()` pattern.

## Expectations

1. **Agent parameter is REQUIRED** in all JobDef payloads:
   ```yaml
   payload:
     spec_md: "..."
     repo_path: "/workspace/specwright"
     agent: "claude-code"  # REQUIRED — no defaults
     project: "specwright" # Project to locate build.yaml for refs.sync
   ```

2. `refs.sync` step added after branch creation in aip-1.yaml and interactive-1.yaml:
   ```yaml
   steps:
     - step_id: branch.create
       backend: cmd
       description: Create or switch to feature branch
       payload:
         command: "git checkout @payload.feature_branch 2>/dev/null || git checkout -b @payload.feature_branch"
         capture_git: true
       continue_on_failure: false

     # NEW: Sync reference files before agent execution
     # Note: Depends on agent.sync_refs callable from t008-01
     - step_id: refs.sync
       backend: python
       description: Sync agent reference files from build.yaml
       payload:
         callable: "agent.sync_refs"
         agent: "@payload.agent"
         project: "@payload.project"
         sync_task: true
         spec_md: "@payload.spec_md"
       continue_on_failure: true  # Don't block agent if sync fails (build.yaml not found, etc.)

     - step_id: agent.run_spec
       backend: "@payload.agent"  # Resolved at compile time to Backend enum
       description: "Run 1: Execute spec with agent"
       payload:
         spec_md: "@payload.spec_md"
         repo_path: "@payload.repo_path"
         capture_git: true
       timeout_s: 1800
       ...
   ```

   **refs.sync behavior**:
   - Step runs immediately after branch.create (files synced before agent starts)
   - Continues to agent step even if sync fails (continue_on_failure: true)
   - Failure modes: build.yaml not found, project not specified, write errors
   - Agent continues with any partial sync or no sync (graceful degradation)

3. **Compile-time variable resolution**: When `compile(job_def, payload)` is called, `@payload.agent` resolves to the backend enum. Example:
   - Payload: `{agent: "claude-code", ...}`
   - Result: Step has `backend: Backend.CLAUDE_CODE` (enum value, not string)

4. **Multi-agent workflows supported**: Different steps can target different agents:
   ```yaml
   steps:
     - step_id: agent.run_spec
       backend: "@payload.agent"  # Use first agent
     - step_id: agent.refine
       backend: "@payload.copilot_agent"  # Use second agent (if provided)
     - step_id: agent.verify
       backend: "@payload.agent"  # Back to first agent
   ```

5. **Compilation fails if agent is missing or invalid**:
   - Missing `agent` in payload → compilation error
   - Invalid backend name → compilation error
   - No fallback defaults

## Implementation Notes

### Updated aip-1.yaml Structure

```yaml
job_id: aip-1
version: "0.3"  # Bump for refs.sync addition
description: Execute a spec with 3-pass agent verification

steps:
  # Step 1: Create or switch to feature branch - must succeed
  - step_id: branch.create
    backend: cmd
    description: Create or switch to feature branch
    payload:
      command: "git checkout @payload.feature_branch 2>/dev/null || git checkout -b @payload.feature_branch"
      capture_git: true
    continue_on_failure: false

  # Step 2: Sync agent reference files - best effort
  - step_id: refs.sync
    backend: python
    description: Sync reference files from build.yaml
    payload:
      callable: "agent.sync_refs"
      agent: "@payload.agent"
      project: "@payload.project"
      sync_task: true
      spec_md: "@payload.spec_md"
    continue_on_failure: true

  # Step 3: Run 1 - Execute spec
  - step_id: agent.run_spec
    backend: "@payload.agent"  # Dynamic backend selection
    description: "Run 1: Execute spec with agent"
    payload:
      spec_md: "@payload.spec_md"
      repo_path: "@payload.repo_path"
      capture_git: true
    timeout_s: 1800
    on_failure_skip_to: capture.bundle
    capture_patch: true

  # ... remaining steps unchanged
```

### Agent Backend Mapping

For non-Claude agents, specwright will need backend adapters:

| Agent | Backend ID | Notes |
|---|---|---|
| Claude Code | `claude-code` | Existing backend |
| Cursor | `cursor` | Future: MCP or CLI |
| Aider | `aider` | Future: CLI wrapper |
| Roo Code | `roo-code` | Future: Extension API |
| Goose | `goose` | Future: CLI wrapper |
| OpenCode | `opencode` | Future: CLI wrapper |

For now, only `claude-code` has a working backend. Other agents will require
separate backend implementations (out of scope for this spec).

### Compile-Time Variable Resolution

Variables in the `backend` field resolve at compile time:
```python
def resolve_backend_variable(template: str, payload: dict) -> Backend:
    """Resolve @payload.X references to Backend enum values."""
    if isinstance(template, Backend):
        return template  # Already enum

    if not isinstance(template, str):
        raise ValueError(f"backend must be Backend enum or string, got {type(template)}")

    if template.startswith("@payload."):
        key = template[9:]  # Strip "@payload."
        value = payload.get(key)
        if value is None:
            raise ValueError(f"Required payload key not found: {key}")
        # Convert string to Backend enum
        try:
            return Backend[value.upper()]
        except KeyError:
            raise ValueError(f"Unknown backend: {value}")

    # Direct backend name
    try:
        return Backend[template.upper()]
    except KeyError:
        raise ValueError(f"Unknown backend: {template}")
```

### Project Parameter for refs.sync

The `@payload.project` is used by `refs.sync` to locate the build.yaml:

1. **Explicit**: User provides in payload → use it directly
2. **Inferred from repo**: Use the target repo directory name as project ID

If refs.sync cannot resolve the project, it fails gracefully (with `continue_on_failure: true`, execution continues to agent step):
```python
# Inside refs.sync callable:
project = payload.get("project") or Path(repo_path).name
# If build.yaml not found for project → passed=False, error in data
```

## Test Cases

**Variable resolution:**
1. **Missing agent in payload** → compilation error with clear message
2. **agent=unknown_backend** → compilation error: "Unknown backend: unknown_backend"
3. **agent=claude-code** → resolves to Backend.CLAUDE_CODE, preflight checks pass, compilation succeeds
4. **agent=copilot** → resolves to Backend.COPILOT, preflight checks pass, compilation succeeds

**Preflight validation (NEW):**
5. **Backend unavailable** (e.g., claude-code CLI not installed) → compilation error with helpful message
6. **Backend requires auth** (e.g., copilot not authenticated) → compilation error with auth guidance
7. **Models specified but unavailable** (e.g., requested model not supported) → compilation error
8. **Backend available** → compilation succeeds, preflight checks cached for dispatch

**Template execution:**
9. **refs.sync failure** → continues to agent step (due to `continue_on_failure: true`)
10. **refs.sync success** → reference files synced before agent step runs
11. **Agent step executes** → with synced reference files and resolved backend

**Multi-agent workflows:**
12. **Multiple agent parameters** (agent, copilot_agent) → different steps use different backends
13. **Same agent in multiple steps** → all steps execute with same backend

## Build Delta

```yaml
target: projects/specwright/specwright.build.yaml
summary: "JobDef support for agent-parameterized workflows"
modifies:
  layout:
    - module: jobdefs
      kind: templates
      path: src/spec/templates/jobdefs/
      note: "Updated aip-1.yaml and interactive-1.yaml with refs.sync step"
```

## Acceptance Criteria

**Schema changes:**
- [ ] `StepTemplate.backend` accepts `str | Backend` union type
- [ ] `Step.backend` and `StepManifest.backend` remain `Backend` enum only

**Compilation and resolution:**
- [ ] `compile_job()` resolves `@payload.agent` variables to Backend enum
- [ ] Compilation fails with clear error if agent is missing from payload
- [ ] Compilation fails with clear error if agent backend name is invalid
- [ ] Compilation fails with clear error if backend is unavailable (not installed, not authenticated)

**Preflight validation:**
- [ ] `compile_job()` calls `backend.verify()` for each agent step after compilation
- [ ] Helpful error messages when agent unavailable (from BackendError exceptions)
- [ ] Preflight checks fail fast at compile time, before dispatch
- [ ] Works with single-agent and multi-agent workflows
- [ ] Follows existing `_require_llm_preflight()` pattern in engine.py

**Templates and integration:**
- [ ] `refs.sync` step added to aip-1.yaml template (after branch.create)
- [ ] `refs.sync` step added to interactive-1.yaml template (after branch.create)
- [ ] Agent parameter is REQUIRED in JobDef payloads (no defaults)
- [ ] Multi-agent workflows supported (different agents per step)

**Testing:**
- [ ] All test cases passing (missing agent, invalid backend, unavailable agent, multi-agent)
- [ ] Preflight validation tests for claude-code backend
- [ ] Future backends (copilot, etc.) plug in without engine changes
- [ ] Documentation updated with agent parameterization examples

## Future Work (Out of Scope)

- Backend adapters for Cursor, Aider, Roo, Goose, OpenCode (t008-04 starts with Copilot)
- Agent capability detection (what each agent can do, prerequisites)
- Agent-specific timeout tuning based on backend
- Conditional step execution based on agent (e.g., skip steps for certain backends)
