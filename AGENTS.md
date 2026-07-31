# AGENTS.md — specwright

Repo-level agent onramp. For the current epic/spec context synced by the
harness, see `.claude/AGENTS.md` (materialized by `refs.sync` at run start;
gitignored — its source of truth is the cloud-governor projection).

## What this repo is

Spec execution engine: compiles job definitions against specs and executes
step sequences via pluggable backends (claude-code, copilot, cmd, python,
llm, codex). It **runs, validates, and records/traces** specs — it does not
author them (authoring lives cloud-governor-side via `life create`).

## Contract (see CLAUDE.md for the full version)

- Spine: `compile(job_def, envelope) -> JobInstance`, then execute fixed
  steps. The executor never mutates the step list.
- Never swallow errors; capture them into StepOutcome/StepCapture with
  context before aborting.
- **Run records are governed rows**: emission through the storacle gate at
  finalize (`src/spec/executor/gate_emission.py`); bulk to local scratch
  `~/.local/specwright/runs/`; the projection repo receives nothing;
  `--legacy-output` is the only tree-writing escape hatch.

## Self-hosting rules (this repo IS the harness)

- The in-flight orchestrator will not pick up mid-run edits — prove changes
  with a nested `spec` CLI run (fresh subprocess = new code).
- Commit the working tree promptly and keep the suite green — the tree is
  the live harness for the next run.
- Direct (run-record-less) changes get logged in `HOTFIXES.md`.

## Commands

```bash
pytest tests/ -x -q                 # tests (baseline: 1083 passed / 4 skipped,
                                     #   1 pre-existing unrelated failure —
                                     #   test_python_backend.py needs `governor init`)
ruff check src/ tests/              # lint before committing
mypy src/spec/executor/             # types, if touching schemas
.venv/bin/spec --help               # CLI surface
```

## Pointers

- `CLAUDE.md` — contract, naming, storage, git discipline
- `STATUS.md` — current state + recent changes
- `HOTFIXES.md` — direct-change log
- `docs/EXECUTOR.md` — execution model detail
- Epics/specs (cloud-governor side, dual-root since t018-01/t018-04): most
  render at `canon/initiatives/<initiative>/epics/<epic>/` (70 of 72); the
  2 genuinely unassigned ones stay at the old flat `epics/e/<epic>/`. This
  repo's own `resolver.py`/`loader.py` search both roots.
