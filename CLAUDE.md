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

<!-- BEGIN SYNCED: SPEC: sw-01-02-execution-surface-honesty -->
## Current Spec: sw-01-02-execution-surface-honesty

(No acceptance criteria section found in spec)
<!-- END SYNCED: SPEC: sw-01-02-execution-surface-honesty -->

<!-- BEGIN SYNCED: SPEC: hf-03-01-silent-completion-detection -->
## Current Spec: hf-03-01-silent-completion-detection

## Acceptance Criteria

- SUBSTANTIVE-DIFF HELPER EXISTS: a reusable function computes whether a target-repo diff contains real change, correctly excluding content between BEGIN/END SYNCED marker pairs (both markdown and hash-comment marker forms) -- unit-tested directly, not just exercised indirectly.
- STATUS REFLECTS REALITY: when an agent step exits 0 but produces no substantive change under that definition, its OutcomeStatus is NOT completed, and the overall RunStatus is NOT completed -- verified by a real test that exercises engine.py's actual status computation, not a mock of it.
- CASCADE VERIFIED, NOT ASSUMED: when the above triggers, the generated run report's issues list is non-empty with real, accurate content, and recommendation differs from the plain-success default -- proven by an integration test through the real report-generation path, confirming whether the existing cascade already handles this or needed a direct fix (record whichever is true).
- HISTORICAL INCIDENTS CAUGHT: replayed against frozen fixtures snapshotted from the two real incident runs named in the objective, the new logic classifies both as non-clean.
- REAL SUCCESSES UNAFFECTED: replayed against frozen fixtures snapshotted from the two real successful runs named in the objective, the new logic does not flag either -- zero behavior change for the common case.
- NO REGRESSION: the full existing specwright test suite passes clean after this change -- this is shared core executor logic.
<!-- END SYNCED: SPEC: hf-03-01-silent-completion-detection -->
