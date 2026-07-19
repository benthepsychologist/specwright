# STATUS — specwright

As of **2026-07-19** (`main` at `575ae57`, pushed to origin).

## Current state

- **Run records are governed rows** (e040-07d, merged to main at `f1ac228`):
  every `spec run` emits `run` / `run_step` / `run_report` objects through the
  storacle gate (lorchestra `object.create`, in-process) to `ops__base` at
  finalize, with row-count + policy-stamp verification. Bulk artifacts
  (consolidated YAML, stdout/stderr, patches) go to local scratch
  `~/.local/specwright/runs/` (`SPECWRIGHT_SCRATCH_ROOT` override).
- **No silent legacy fallback.** Gate refusals fail the run loudly (exit 1,
  scratch remains as evidence). `--legacy-output` is the only, explicit
  tree-writing escape hatch. The old silent fallback to epic-folder trees
  (projection repo unconfigured → legacy writer) is dead.
- **Scope:** specwright runs, validates, and records/traces specs. It does
  not author epics/specs — authoring lives cloud-governor-side (t013-02
  removed the authoring surface; `life create` is the authoring path).
- **Suite:** 1065 passed / 4 skipped (post-merge, 2026-07-17).

## Recent changes

- 2026-07-18 — `HOTFIXES.md` gained the projection-config update procedure
  (lorchestra `object.update`, superseding hand-built plans); repo-level
  `AGENTS.md`/`STATUS.md` added; all pushed to origin.
- 2026-07-17 — e040-07d merged: `spec.executor.gate_emission` (gated
  emission), silent-fallback removal, repo-wide test guards (emission
  stubbed + scratch redirected in tests). Historical run trees (87) were
  ingested to `ops__base` and `runs/` retired from cloud-governor the same
  day (post-op; see cloud-governor's FREEZE-CHAIN-STATUS.md).
- 2026-06-25 — t013 batch: colocated agent context (`refs.sync` →
  `.claude/AGENTS.md` + skills), authoring removal, `chat-1` free-range
  harness. See `HOTFIXES.md`.

## Known follow-ups

- Jobdef deploy convention: the loader prefers
  `~/.local/local-governor/jobdefs/specwright/` over bundled source —
  jobdef edits require a re-sync (or `spec init --force`).
- `interactive-1` runs produce no stdout capture for the agent step by
  design ("interactive session — no stdout capture").

## Conventions

- Direct (run-record-less) changes are logged in `HOTFIXES.md`.
- Spec branches: `spec/<spec-id>` (harness-created); feature work: `feat/*`.
- Do not push (sandbox rule).
