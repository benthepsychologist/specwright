# HOTFIXES

Changes applied **directly** to specwright, outside its own governed `spec run`
flow — so they have **no governor run record**. specwright cannot govern changes to
itself (running `spec` on specwright would operate on the tool mid-change), so this
work is implemented by hand/agent on a branch and logged here for traceability.

Each entry: date · what · commits · related spec (authored in cloud-governor, where
specs/epics live).

---

## 2026-07-20 — gate-emission env hardening + lorchestra as a declared dep

Incident: lorchestra got installed NON-editable into this venv at 18:41 (ad
hoc, unblocking an earlier import failure), so `lorchestra.__file__` resolved
into site-packages, `gate_emission`'s `.env` lookup silently missed
`/workspace/lorchestra/.env`, and BOTH e045 runs' finalize emissions failed —
e045-02's silently earlier the same day (proven missing at re-emit), e045-02b's
loudly on the six bare `STORACLE_*` vars. Recovered by reinstalling editable
and re-running `emit_run_records` for both runs (9 + 9 rows verified in
`ops__base`). Two hardening fixes so it can't recur silently:

- **`gate_emission._require_storacle_env`** — pre-submit check of the six
  storacle-required vars (mirrors storacle config.py); refusal names the
  resolved `.env` path and, when it doesn't exist, diagnoses the
  non-editable-install cause with the fix command. The silent
  `if env_path.exists()` skip is what made this a two-run mystery.
- **lorchestra declared in pyproject** (`[tool.uv.sources]` editable path
  dep) so venv rebuilds keep the editable install; `requires-python` bumped
  to `>=3.14` to match lorchestra's. `uv lock`/`uv sync` resolved the full
  path-dep chain and pruned a stale `workman` install. Goes away when the
  job executor lifts out of lorchestra.

Observed while verifying, not fixed here: a full re-emit of an
already-landed run re-submits all 9 objects instead of skipping (the
`_row_exists` precheck didn't fire); the gate's append-once semantics
deduped silently so row counts stay correct, but that's §6b failure-mode-1
territory — worth a look next time someone's in this file. Also note: with
lorchestra's e045-02b two-phase write-back live, every emission's
`object.create` execution now writes its own governed claim+terminal run
rows — by design (every execution is a run), relevant to e040-12's
retention math.

Related: e045-02b (cloud-governor); lorchestra `c409f23`; suite green under
`NO_COLOR=1` except two pre-existing environmental failures (rich-styled
help assertion; retired local-governor tree).

**Same-incident addendum (2026-07-20, found at e045-04 launch):** the
`uv sync` above also pruned the ad-hoc-installed `llm` provider plugins
(`llm-gemini`, `llm-azure`) — they were never declared either, so the
LLM preflight lost both the primary (`gemini-3.1-pro-preview`) and
fallback (`azure-gpt52`) models, leaving only stock OpenAI ids visible.
Fixed the same way as lorchestra: `uv add llm-gemini llm-azure` — both
now declared in pyproject, both model ids verified resolving. Lesson
generalized: everything this venv needs must be declared; ad-hoc pip
state does not survive a sync.

---

## 2026-06-25 — t013 skills layer, authoring removal, free-range chat harness

All implemented directly (bootstrap) and merged to `develop`.

### t013-01 — colocated agent context (AGENTS.md pointer + sync)
- Runtime `agent.sync_refs`: materialize an epic's `AGENTS.md` + `CLAUDE.md` stub into
  the target repo's `.claude/` and copy the named shared-library skills into
  `.claude/skills/` (SKILL.yaml-aware, non-clobbering, graceful degrade).
- Enabled `refs.sync` in all three jobdefs (`skip_sync: false` + `epic_dir`):
  `aip-1`, `aip-1-lite`, `interactive-1`.
- Commits: `cf2a2a2`, `1905094`.
- Spec: `cloud-governor: epics/t/t013-skills-layer/specs/t013-01-colocated-agent-context.yaml`.

### t013-02 — remove epic/spec creation from specwright
- specwright now **runs + validates + records/traces** specs; it no longer creates or
  authors epics/specs. Removed: `spec epic create/add-target/add-spec/set-current`,
  `spec draft`, `spec refine`, the LLM drafters, the `SpecScaffolder` + AGENTS.md
  authoring helpers, and `create_epic`. Kept the full run package + validators +
  runtime `agent.sync_refs`. Authoring lives cloud-governor-side.
- Also fixed README + `docs/epic-context-convention.md` and scrubbed `CLAUDE.md`.
- Commits: `68bd31d`, `6aca0be`, `0830ee1`.
- Spec: `cloud-governor: epics/t/t013-skills-layer/specs/t013-02-remove-spec-authoring-from-specwright.yaml`.

### chat-1 — free-range chat harness (run-side meta-harness; no spec)
- New `chat-1` jobdef + `spec run --free-range` (specless): launches interactive Claude
  Code, not repo-locked, and captures the Claude session transcript + summary into
  `~/.local/local-governor/sessions/<run_id>/`. No multi-repo diff yet.
- Commit: `a6f9064`. No spec (run-side harness).

### Deploy note (outside the repo)
- The jobdefs were re-synced to `~/.local/local-governor/jobdefs/specwright/`
  (`aip-1`, `aip-1-lite`, `interactive-1` now `skip_sync: false`; new `chat-1`). The
  loader prefers the `~/.local` install over the bundled source, so jobdef edits require
  this re-sync (or `spec init --force`).

---

## 2026-07-18 — projection-config updates: use lorchestra's `object.update` (deploy note, outside the repo)

The projection config (`cloud-governor-projection-config`, the DB row behind
`.projection.yaml`) has no rendered source in its own `sources:` list, so the
repo_sync push loop cannot update it. An earlier session drafted a hand-built
`document.updated` plan for this — **superseded, do not hand-build plans**.
The sanctioned path is lorchestra's `object.update` job (CAS + rendered-surface
refusal; lorchestra `937c3a4`):

```python
# venv with storacle importable (e.g. specwright's .venv)
from pathlib import Path
import lorchestra
from lorchestra import execute
from spec.executor.gate_emission import _load_lorchestra_env
_load_lorchestra_env(lorchestra)

execute({
    "job_id": "object.update",
    "payload": {
        "kind": "document", "schema_ref": None,
        "name": "cloud-governor-projection-config",
        "expected_version": "<current version — read it first>",
        "object_params": {
            "version": "<next patch>",
            "content": {"text": Path(".projection.yaml").read_text(),
                        "format": "markdown"},
        },
        "projection_config": None,
    },
    "definitions_dir": Path(lorchestra.__file__).parent / "jobs" / "definitions",
})
```

Then verify by counting rows (never trust the success status), and re-run the
wipe drill (`projection.bootstrap` into an empty dir + pull) to prove the DB
copy round-trips. First use: config 1.0.0 → 1.0.1, drill PASS 0/632.
