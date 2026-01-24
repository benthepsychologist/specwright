# Specwright v1 → v2 Migration Guide

This document describes breaking changes and migration steps for the v2 executor (Epic e008).

## Overview

Specwright v2 introduces a new job-based executor architecture that replaces the v1 step-based runner. The key changes:

1. **New execution model**: `compile(JobDef, envelope) → JobInstance → execute()`
2. **Removed v1 scope enforcement**: `allowed_paths`, `forbidden_paths`, `verification_commands` removed
3. **New CLI commands**: `spec job-*` commands at top level
4. **Relative capture paths**: StepCapture uses relative filenames, not absolute paths

## Breaking Changes

### 1. Removed Fields

The following v1 fields have been removed from schemas and models:

| Removed Field | Replacement | Notes |
|---------------|-------------|-------|
| `allowed_paths` | `suggested_paths` | Soft guidance only, not enforced |
| `forbidden_paths` | (none) | Removed - v2 philosophy doesn't block paths |
| `verification_commands` | `final_verification` | Per-phase verification in AIP structure |

**Migration**: Replace usage of `allowed_paths` with `suggested_paths` in your AIPs. The v2 executor does not enforce path restrictions - it trusts the agent and captures everything.

### 2. CLI Command Changes

v1 executor commands are now at top level:

| v1 Command | v2 Command |
|------------|------------|
| `spec exec compile` | `spec compile` |
| `spec exec execute` | `spec execute` |
| `spec exec run` | `spec run` |
| `spec exec status` | `spec status` |
| `spec exec logs` | `spec logs` |

**Note**: The v1 `spec compile` command (Markdown → YAML) has been renamed to `spec spec-compile` to avoid conflict with the v2 executor compile command.

### 3. API Changes

The public API is now:

```python
from spec import execute  # Top-level export

# Or from executor module:
from spec.executor import (
    execute,           # Execute from envelope
    execute_instance,  # Execute pre-compiled JobInstance
    compile_job,       # Compile JobDef + envelope → JobInstance
)
```

### 4. Capture Path Format

StepCapture now uses relative filenames instead of absolute paths:

```yaml
# v1 (absolute)
stdout_file: /home/user/.local/local-governor/runs/run-123/steps/step-001/stdout.txt

# v2 (relative filename)
stdout_file: stdout.txt
```

To read capture files, resolve against the step directory:
```python
step_dir = store.get_step_path(run_id, step_n)
stdout_path = step_dir / capture.agent.stdout_file
```

## Known Limitations (v0.1)

### Sandbox Enforcement

The `claude-code` backend uses a tool allowlist approach rather than the `SandboxEnforcer` used by the `cmd` backend. This means:

- The allowlist blocks direct `git push`/`git merge` commands
- However, indirect execution (e.g., via Python subprocess) is not blocked
- For high-security scenarios, use the `cmd` backend with explicit commands

The allowlist provides defense-in-depth but is not a hard sandbox.

### aip-1 JobDef

The built-in `aip-1` job template has these limitations:

1. **Sandbox config not wired**: The sandbox policy fields in JobDef are not passed through to the claude-code backend payload
2. **assess.acceptance is placeholder**: The LLM assessment step doesn't yet reference `@run.*` artifacts

These will be addressed in a future release.

### execute_instance() Feature

The `spec execute` command now uses `execute_instance()` which executes a pre-compiled JobInstance directly without recompiling. This enables:

- Testing JobDef changes without re-running compilation
- Replaying previous runs from saved JobInstance files

## Upgrade Steps

1. **Update AIPs**: Replace `allowed_paths` with `suggested_paths`, remove `forbidden_paths` and `verification_commands`

2. **Update scripts**: Replace `spec exec <cmd>` with `spec <cmd>` (e.g., `spec exec run` → `spec run`)

3. **Update code**: Use relative path resolution for capture files:
   ```python
   # Before
   Path(capture.agent.stdout_file).read_text()

   # After
   (artifacts_dir / capture.agent.stdout_file).read_text()
   ```

4. **Update imports**:
   ```python
   # Now available at package level
   from spec import execute
   ```

## Questions?

See the epic documentation at `~/.local/local-governor/epics/e008-specwright-v2/` or file an issue.
