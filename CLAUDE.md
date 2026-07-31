# CLAUDE.md — Specwright

## Core Contract
- **Scope:** specwright **runs, validates, and records/traces** specs. It does **not** create or author epics/specs — authoring (epics/specs + their AGENTS.md) lives on the cloud-governor side.
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

## Storage (e040-07d producer flip)
- **Runs are governed rows:** at finalize, run/run_step/run_report objects are
  emitted through the storacle gate (lorchestra `object.create`, in-process) to
  `ops__base` — see `src/spec/executor/gate_emission.py`.
- **Bulk stays local:** consolidated YAML + stdout/stderr/patches go to local
  scratch `~/.local/specwright/runs/{epic}/{run_id}/` (`SPECWRIGHT_SCRATCH_ROOT`
  override). Bulk never becomes rows; rows carry scratch refs.
- **The projection repo receives NOTHING.** No silent legacy fallback —
  `--legacy-output` is the only (explicit) tree-writing escape hatch; gate
  refusals fail the run loudly, scratch remains as evidence.
- **Never write artifacts into the target repo** (no `.aip_artifacts/`).

## Execution Rules
- **Retries rerun the same step** — do not reset worktree between attempts by default.
- **Executor never mutates the step list** — it runs exactly what compile() produced.
- **@run.* refs** are resolved at step dispatch time, not at compile time.

## Testing
- Run tests after each logical change: `pytest tests/ -x -q`
- Run lints before committing: `ruff check src/ tests/`
- Check types if touching schemas: `mypy src/spec/executor/`

## Documentation Sources
- Epics/specs live cloud-governor-side: `/workspace/.projections/cloud-governor/epics/`
  (DB-projected; authored via `life create`, edited via the push/pull loop)
- Direct (run-record-less) changes to this repo are logged in `HOTFIXES.md`
- Jobdef deploy note: the loader prefers `~/.local/local-governor/jobdefs/specwright/`
  over bundled source — jobdef edits need a re-sync (see HOTFIXES.md)
- lorchestra pattern (reference): same spine, different handlers

## Git Discipline
- Spec branches: `spec/<spec-id>` (harness-created); feature work: `feat/*`
- Commit often with clear messages
- Do not push (sandbox rule applies to you too)

## When Stuck
1. Re-read the epic's AGENTS.md (synced into `.claude/AGENTS.md` by refs.sync)
2. Ask — don't guess at contracts

<!-- BEGIN SYNCED: specwright -->

<!-- END SYNCED: specwright -->

<!-- BEGIN SYNCED: SPEC: t019-04-specwright-claim-row -->
## Current Spec: t019-04-specwright-claim-row

(No acceptance criteria section found in spec)
<!-- END SYNCED: SPEC: t019-04-specwright-claim-row -->
