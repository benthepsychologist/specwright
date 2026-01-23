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
