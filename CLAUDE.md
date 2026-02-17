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
