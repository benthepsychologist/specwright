# STATUS — specwright

As of **2026-07-31** (`main` at `161b053`, pushed to origin — t018-04 and
t019-04 both merged since the last sync of this file).

## Current state

- **Run records are governed rows** (e040-07d, merged to main at `f1ac228`):
  every `spec run` emits `run` / `run_step` / `run_report` objects through the
  storacle gate (lorchestra `object.create`, in-process) to `ops__base` at
  finalize, with row-count + policy-stamp verification. Bulk artifacts
  (consolidated YAML, stdout/stderr, patches) go to local scratch
  `~/.local/specwright/runs/` (`SPECWRIGHT_SCRATCH_ROOT` override).
- **Run records now carry a claim/supersede lifecycle** (t019-04, merged
  `5619bf9` → `eb27da6`): a `run` row is written as a CLAIM at start,
  superseded to its terminal state at finalize — same content-hash-folded
  `row_id` mechanism lorchestra's own two-phase runs use, idempotent under
  retry (proven with a real double-invocation against prod: exactly 1
  physical row from 2 identical calls).
- **Epic resolution is dual-root** (t018-04, merged `3df316a` → `161b053`):
  `governor/resolver.py` and `epic/loader.py` now search both
  `canon/initiatives/*/epics/*/` (70 of 72 epics) and the old flat
  `epics/*/*/` (the 2 genuinely unassigned ones) — this repo's consumer
  side of cloud-governor's t018-01 layout split.
- **No silent legacy fallback.** Gate refusals fail the run loudly (exit 1,
  scratch remains as evidence). `--legacy-output` is the only, explicit
  tree-writing escape hatch. The old silent fallback to epic-folder trees
  (projection repo unconfigured → legacy writer) is dead.
- **Scope:** specwright runs, validates, and records/traces specs. It does
  not author epics/specs — authoring lives cloud-governor-side (t013-02
  removed the authoring surface; `life create` is the authoring path).
- **Suite:** 1083 passed / 4 skipped / 1 pre-existing unrelated failure
  (`test_python_backend.py::test_validate_build_returns_report` — needs a
  real `governor init`'d tree at `~/.local/local-governor`; confirmed
  pre-existing via a base-branch worktree comparison during t019-04's
  postflight, not a new regression).

## Recent changes

- 2026-07-31 — t018-04 and t019-04 executed, independently POSTFLIGHTed,
  and merged to `main` (details above).
- 2026-07-27 — dependency pinning swept repo-wide: `lorchestra` (and this
  machine's sibling repos — storacle, egret, life) moved from a local
  `editable = true` path dep to a fixed `git+rev` pin (`efa5114`). See
  Known follow-ups below — this changes what a plain `uv sync` gives you.
- 2026-07-20/21 — gate-emission hardening: a pre-submit check of the six
  required storacle env vars (diagnoses a non-editable lorchestra install
  by name instead of silently starving the gate mid-submit), plus
  `llm-gemini`/`llm-azure` declared after an ad-hoc `uv sync` pruned them
  — both logged in `HOTFIXES.md`'s 2026-07-20 entry.
- 2026-07-20 — two small direct fixes: dead `--epic`/`--spec` shortcut
  examples dropped from docs (confirmed unused — resolves against a path
  with no epics since authoring moved to cloud-governor), and `spec init`
  stopped propagating five dead v1 slash commands into new repos'
  `.claude/commands/`.
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

- **Local dev against unreleased lorchestra changes needs a manual
  editable reinstall.** Since the 2026-07-27 pinning sweep, `pyproject.toml`
  points `lorchestra` at a fixed `git+rev` SHA — a plain `uv sync` on this
  machine now silently resolves that pinned commit, not this machine's
  live `/workspace/lorchestra` working tree. Same footgun class as the
  2026-07-20 incident this repo already hardened against (see HOTFIXES.md)
  — override with an editable install when testing against local
  lorchestra changes, and expect `uv sync` to evict it again.
- Jobdef deploy convention: the loader prefers
  `~/.local/local-governor/jobdefs/specwright/` over bundled source —
  jobdef edits require a re-sync (or `spec init --force`).
- `interactive-1` runs produce no stdout capture for the agent step by
  design ("interactive session — no stdout capture").

## Conventions

- Direct (run-record-less) changes are logged in `HOTFIXES.md`.
- Spec branches: `spec/<spec-id>` (harness-created); feature work: `feat/*`.
- Do not push (sandbox rule).
