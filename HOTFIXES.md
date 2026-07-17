# HOTFIXES

Changes applied **directly** to specwright, outside its own governed `spec run`
flow — so they have **no governor run record**. specwright cannot govern changes to
itself (running `spec` on specwright would operate on the tool mid-change), so this
work is implemented by hand/agent on a branch and logged here for traceability.

Each entry: date · what · commits · related spec (authored in cloud-governor, where
specs/epics live).

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
