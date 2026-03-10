# CLAUDE.md — Specwright v2 Epic (e008)

## Core Contract
- **Entry point:** `specwright.execute(envelope)` is the only public API
- **Spine:** `compile(job_def, envelope) -> JobInstance` then execute fixed steps
- **Job template:** `aip-1` compiles to exactly 5 wrapper steps with ONE agent step that receives the ENTIRE AIP payload
- **No phase expansion:** AIP phases are payload structure, not executor steps

## Naming (non-negotiable)
| Thing | Name |
|-------|------|
| Machine-readable feature spec | AIP (YAML) |
| Internal AIP sub-units | Phases (not "steps") |
| Job template | JobDef |
| Materialized step list | JobInstance |
| Executor dispatch unit | Step (job-step) |
| Summary record | StepOutcome |
| Evidence bundle | StepCapture |

## Error Handling
- **Never swallow errors.** Surface them with context (step_n, step_id, backend).
- **Fail fast on policy violations** (push, merge, branch switch).
- **Capture errors into StepOutcome/StepCapture** before aborting.

## Storage
- **Run sink:** `~/.local/local-governor/runs/{run_id}/`
- **Never write artifacts into the target repo** (no `.aip_artifacts/`).
- **Index artifacts via refs** in StepCapture (relocatable storage).

## Execution Rules
- **Retries rerun the same step** — do not reset worktree between attempts by default.
- **Executor never mutates the step list** — it runs exactly what compile() produced.
- **@run.* refs** are resolved at step dispatch time, not at compile time.

## Testing
- Run tests after each logical change: `pytest tests/ -x -q`
- Run lints before committing: `ruff check src/ tests/`
- Check types if touching schemas: `mypy src/spec/executor/`

## Documentation Sources
- Epic: `~/.local/local-governor/epics/e008-specwright-v2/epic.yaml`
- Notes + aip-1 template: `~/.local/local-governor/epics/e008-specwright-v2/notes.md`
- Checks: `~/.local/local-governor/epics/e008-specwright-v2/checks/CHK-*.md`
- AIP schema: `~/.local/local-governor/contracts/schemas/aip-v2.0.schema.json`
- lorchestra pattern (reference): same spine, different handlers

## Git Discipline
- Feature branches: `feat/v2-executor-*`
- Commit often with clear messages
- Do not push (sandbox rule applies to you too)

## When Stuck
1. Re-read the relevant check file (CHK-001 through CHK-006)
2. Re-read notes.md for the aip-1 JobDef template
3. Ask — don't guess at contracts

<!-- BEGIN SYNCED: specwright -->
# Specwright Project Context

## Description

Spec execution engine. Compiles job definitions against spec markdown, executes step sequences via pluggable backends (claude-code, cmd, python, llm), and tracks runs with artifact capture.

## Invariants

- Job-based execution: specs compile to JobInstances with fixed step sequences.
- Executor never mutates the step list — it runs exactly what compile() produced.
- Run artifacts stored in ~/.local/local-governor/runs/, never in the target repo.

## Boundaries

### cli
- Type: inbound
- Contract: spec <command> [options]
- Consumers: developers, agentic workflows

### governor_fs
- Type: dependency
- Contract: ~/.local/local-governor/ filesystem layout
- Requires: epics/, projects/, runs/, contracts/ directories

### claude_code
- Type: dependency
- Contract: claude CLI binary
- Requires: claude CLI for claude-code backend execution

### llm_lib
- Type: dependency
- Contract: llm Python library (simon willison)
- Requires: llm>=0.19.0 for LLM check execution

## Architecture Decisions

### adr-001: Job-based execution model
**Status:** accepted

**Rationale:** Decouples spec authoring from execution. JobDefs are reusable templates. Specs are payload.

**Decision:** Specs compile to JobInstances via JobDef templates. Executor runs JobInstances.

### adr-002: Pluggable backends
**Status:** accepted

**Rationale:** Different step types need different execution strategies.

**Decision:** Backend registry dispatches steps to claude-code, cmd, python, llm, or codex backends.

### adr-003: Governor-based storage
**Status:** accepted

**Rationale:** Artifacts, runs, and config live outside target repos.

**Decision:** All specwright state in ~/.local/local-governor/. Target repos are never polluted.

<!-- END SYNCED: specwright -->

<!-- BEGIN SPEC: e101-04d-specwright-output-format -->
## Current Spec: e101-04d-specwright-output-format

---
id: e101-04d-specwright-output-format
tier: C
title: "Specwright Consolidated Output Format + JobDef Registrar Fields"
owner: benthepsychologist
goal: Update specwright run output to consolidated YAML format. Add registrar fields to JobDef model.
validated: false
version: '3.0'
labels:
- specwright
- jobs
- runs
- output
epic: e101-lifeos-cloud-registrar
repo:
  name: specwright
  working_branch: feat/consolidated-output
created: '2026-03-05T00:00:00Z'
updated: '2026-03-09T00:00:00Z'
---

## Objective

Update specwright to:

1. Add registrar fields (`kind`, `artifact_id`, `name`) to `JobDef` model
2. Write consolidated YAML output that registrar sync can ingest directly
3. Preserve legacy output mode behind `--legacy-output` flag

After this spec, specwright's run output matches the file shapes 04c's
sync expects.

## Preconditions

- e101-04b complete: JSON schemas for `jobdef`, `run`, `run_step`, `run_report`
  exist in registrar
- e101-04c complete: sync routing for job/run kinds works end-to-end

## Changes

### 1. JobDef Model

Add fields to specwright's `JobDef` pydantic model
(`/workspace/specwright/src/spec/executor/schemas/job_def.py`):

```python
class JobDef(BaseModel):
    # ...existing fields...
    kind: str = Field(default="jobdef", description="Artifact kind for registrar")
    artifact_id: str = Field(default="", description="Registrar artifact UUID")
    name: str = Field(default="", description="Registrar artifact name")
```

Update all three bundled jobdef YAMLs with registrar fields:

- `aip-1.yaml` — `kind: jobdef`, `artifact_id: <uuid>`, `name: aip-1`
- `interactive-1.yaml` — `kind: jobdef`, `artifact_id: <uuid>`, `name: interactive-1`
- `harness-probe-1.yaml` — `kind: jobdef`, `artifact_id: <uuid>`, `name: harness-probe-1`

Generate stable UUIDs once.

### 2. ConsolidatedRunWriter

New writer class that produces the layout registrar sync expects:

```
runs/{epic_id}/{run_id}/
  run.yaml              — kind: run
  run_report.yaml       — kind: run_report
  steps/
    step-001.yaml       — kind: run_step
    step-002.yaml
    ...
```

Each file includes `kind` at top level for registrar sync routing.

vs. legacy layout:

```
<epic_dir>/runs/{run_id}/
  run.yaml, job_def.yaml, job_instance.yaml, run_report.md,
  stdout.txt, stderr.txt, changes_final.patch,
  attempts/attempt-001.yaml,
  steps/step-001/{manifest,outcome,capture}.yaml + txt files
```

### 3. File Shapes

**`run.yaml` (kind: run):**

No `version` field — run records are immutable logs.

```yaml
kind: run
artifact_id: <uuid>
name: run-{epic_id}-{spec_id}-{timestamp}-{hash}
run_id: <same as name>
job_id: aip-1
status: completed
epic_id: e016-local-prompt-eng
spec_id: e016-02-lorchestra-job-migration
repo: { repo_path, branch, base_commit }
policy: { profile, allow_commit, allow_push }
created_at: "2026-03-03T19:40:44Z"
updated_at: "2026-03-03T19:55:42Z"
envelope:
  job_def: { ... }     # absorbed from job_def.yaml
  payload: { ... }
  ctx: { ... }
attempts:              # absorbed from attempts/attempt-NNN.yaml
  - attempt_n: 1
    started_at: ...
    ended_at: ...
    status: completed
    final_step_n: 13
stdout: |              # absorbed from stdout.txt
  <run-level stdout>
stderr: |              # absorbed from stderr.txt
  <run-level stderr>
changes_final: |       # absorbed from changes_final.patch
  <aggregate unified diff>
```

**`steps/step-NNN.yaml` (kind: run_step):**

```yaml
kind: run_step
artifact_id: <uuid>
name: run-abc123/step-003
run_id: run-abc123
step_n: 3
step_id: agent.run_spec
backend: copilot
started_at: "2026-03-03T19:42:00Z"
payload: { ... }
# --- appended at step end ---
outcome: completed
duration_ms: 458486
ended_at: "2026-03-03T19:49:38Z"
error: null
capture: { git: { base_commit, changed_files } }
stdout: |
  <full stdout>
stderr: |
  <full stderr>
patch: |
  <unified diff>
```

**`run_report.yaml` (kind: run_report):**

```yaml
kind: run_report
artifact_id: <uuid>
name: run-abc123/report
run_id: run-abc123
generated_at: "2026-03-03T19:56:00Z"
status: completed
job_id: aip-1
summary: |
  ...
assessment: |
  ...
issues:
  - description: "..."
    severity: warning
recommendation: |
  ...
```

### 4. Step Write-Then-Append Pattern

Steps are written twice:

1. **At step start:** manifest fields (step_number, tool, started_at). File
   is valid YAML if step crashes.
2. **At step end:** outcome, capture, text blobs, completed_at, duration.
   Overwrites the file.

Partial runs are always recoverable — every step file is valid YAML at all
times.

### 5. Output Mode Switch

```python
if legacy_output:
    writer = LegacyRunWriter(run_dir=epic_dir / "runs" / run_id)
else:
    writer = ConsolidatedRunWriter(run_dir=projection_repo / "runs" / epic_id / run_id)
```

- Default: consolidated YAML to projection repo path from `config.yaml`
- `--legacy-output`: old multi-file format in governor filesystem

### 6. Config

```yaml
jobdefs:
  path: /workspace/cloud-codex/jobdefs
  fallback: bundled
```

`load_job_def()` checks `jobdefs.path` first, falls back to bundled YAML
templates if not found.

## Acceptance Criteria

1. `specwright run` writes consolidated YAML to projection repo path
2. Each output file has a `kind` field matching registrar's expected kinds
3. `--legacy-output` produces the old multi-file format
4. Partial runs (step crashes) produce valid YAML for all completed steps
5. `load_job_def()` loads from `jobdefs.path` when available, falls back to bundled
6. All three bundled jobdefs include `kind`, `artifact_id`, `name` fields
7. Step files zero-padded: `step-001.yaml`, `step-003.yaml`
8. run.yaml embeds job_def, attempts, stdout, stderr, changes_final
9. run_report.yaml replaces run_report.md (structured YAML)
10. Existing tests pass
11. Legacy output identical to current behavior

## Known Issues / Deferred

- `job_instance.yaml` not included (compiled artifact → GCS, future)
- Migration of existing governor FS runs to new format (separate task)
- `result.json` — embed in step YAML or skip (TBD)

## Constraints

- Legacy format must remain fully functional (`--legacy-output`)
- No changes to step execution logic — only the file writer changes
- `artifact_id` is a UUID; `name` is deterministic from run_id + step
- YAML multi-line strings must preserve content exactly (use `|` block scalar)

## Dependencies

- e101-04b-foundation-rename-and-ddl (JSON schemas for all kinds)
- e101-04c-registrar-job-routing (sync routing, file shape contracts)

<!-- END SPEC: e101-04d-specwright-output-format -->
