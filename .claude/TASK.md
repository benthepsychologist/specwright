spec_id: 16cec52b-a634-5575-911a-20443ce721e2
object_schema_ref: iglu:io.lifeos/spec_object/jsonschema/2-1-0
wal_target: development_artifact
kind: spec
name: e040-07d-run-kinds-routing-and-runs-ingestion
version: 0.2.4
epic_id: e77d11f3-fc57-5579-91bc-96af94881680
epic_name: e040-frozen-prod-bigquery-mirror-and-live-parity
epic_series: e
title: run records into the DB — specwright gated producer, historical ingest, full-reprojection
  cutover
tier: B
owner: benthepsychologist
goal: 'Close the last durable-only-on-disk content class and cut cloud-governor over
  to full projection. Three moves: (1) route the already-registered run kinds (run@1-0-0,
  run/run_step@1-0-0, run/run_report@1-0-0) into the frozen topology (candidate: ops
  dataset); (2) flip specwright from writing legacy run trees into epic folders to
  emitting run records THROUGH THE GATE as governed rows — its ConsolidatedRunWriter
  ("registrar-friendly" layout) already exists, adjusted and extended to DB emission;
  (3) ingest the 86 historical run trees (43MB, bulk excluded), then retire runs/
  from the repo entirely. End state (Ben): a fresh pull, and NOTHING we care about
  in the repo that does not survive a FULL REPROJECTION FROM THE DB — plus the life
  commands to create every kind of new material, living the fully projected lifestyle.'
objective: 'REDESIGNED 2026-07-17 (Ben) from the v0.1.0 stub, with specwright investigation
  folded in. Grounded facts: (a) specwright has TWO writers — legacy RunStore (the
  per-step-dir trees: run.yaml, steps/step-NNN/{capture, outcome,stdout,stderr,changes.patch},
  attempts/, run_report.md) and ConsolidatedRunWriter (run_writers.py, "consolidated
  registrar-friendly YAML layout", writes runs/{epic_id}/{run_id} with per-step consolidated
  YAMLs) — and the selection in exec_commands.py (~line 747) prefers consolidated
  but FALLS BACK to legacy when _resolve_projection_repo_path() finds no projection
  repo configured; the config still points at the RETIRED local-governor, which is
  why every freeze-chain run landed as an old-style tree in the epic folder. (b) The
  run kinds are registered (e025 RunL heritage) and specwright''s RunRecord matches
  run@1-0-0 nearly 1:1 (run_id, job_hash, repo, policy, status, envelope, created/updated);
  no routing seed names them; zero run rows exist in any table. (c) Census: 86 run
  trees, 43MB, across 15 epic runs/ dirs. (d) The ops dataset seed exists (seed-dataset-ops.json)
  and ops__base is empty — purpose-fit landing zone. (e) The projected-space residue
  after e040-07c is exactly: runs/ trees (this spec), SHADOW-REPORT json, account-instances.json
  (e031), .sync-history.jsonl + .claude/settings.local (local-by-design, gitignored),
  .pytest_cache (junk) — D4 dispositions each. Open decisions carried into the run
  (recommendations included): the gate emission path for specwright (recommend lorchestra-as-library,
  lorchestra.execute(...) in-process — the same convention life-cli and e045 use —
  over shelling out or a raw storacle client); whether job_request routing lands here
  or waits for e045-02 (recommend: run kinds only here, one coordination note — the
  sweeper''s job_request routing is e045-02''s call); where bulk artifacts live going
  forward (recommend: specwright''s local scratch root ~/.local, never the projection
  repo, never rows).'
phases:
- phase_number: 1
  title: Routing + specwright cutover
  objective: 'D1-D2: run kinds routed into ops via the descriptor-domain fix (jobs
    → ops, validated + published — see AC1); specwright emits run/run_step/run_report
    rows through the gate on a real run, deriving the target from the descriptor,
    writes ZERO files into the projection repo; legacy tree-writing retired behind
    an explicit escape hatch only.'
- phase_number: 2
  title: 'POST-OP (attended, AFTER the run finalizes): migration + cutover'
  objective: 'D3-D5 execute as a post-op in the verification session, never in-run
    (Ben, 2026-07-17 — the run must not migrate around its own live tree): the run
    DELIVERS the ingest mapper + a dry-run; the post-op ingests ALL trees including
    the just-finished run''s own (a frozen set, zero carve-outs), reconciles, removes
    runs/ from the repo, then runs the wipe-equivalent drill and the closing stack-check.'
acceptance_criteria:
- text: 'D1 (reshaped by the 2026-07-17 footgun pass) — the three run kinds'' descriptors
    carry default_data_domain: jobs, a PRE-FREEZE FOSSIL naming a dataset that does
    not exist in the frozen topology. Fix: jobs → ops in run/1-0-0, run/run_step/1-0-0,
    run/run_report/1-0-0 (job_request untouched — e045''s), validated + published;
    the emission then DERIVES its dataset/table from the descriptor (never hardcodes
    — doctrine principle 5). Grounded: schemas already published to governance__schemas
    (no publish gap); stack-check phase J classes governed-kind rows in ops__base
    as runtime-origin info census (its documented class-2 scoping), so D/E/I/J stay
    green; NO new table.'
  status: pending
- text: 'D2 — a real specwright run (the harness run of this very spec qualifies)
    lands its run + run_step + run_report rows through the storacle gate, stamped,
    routed to ops__base — and writes NO run tree into the projection repo. The legacy
    fallback no longer silently activates: absent configuration fails loudly or uses
    local scratch, never the epic folder. Bulk artifacts (stdout/stderr/ patches)
    stay in specwright''s local scratch, not rows, not the repo.'
  status: pending
- text: D3 (run half) — the disposable ingest mapper exists (e040-07 script precedent),
    unit-sane, and a DRY-RUN over all present trees reports per-epic counts with zero
    mapping errors. NO real ingest and NO runs/ removal happens in-run. D3 (post-op
    half) — the attended post-op ingests ALL trees (including this run's own — the
    set is frozen once the run finalizes) through the gate; tree↔row counts reconcile
    per epic; bulk recorded as the accept-lost tier; runs/ directories then removed
    in a normal commit (git history retains the trees).
  status: pending
- text: 'D4 — every file in cloud-governor that is neither DB-rendered nor a bootstrap
    stub is explicitly dispositioned: ingested (e.g. SHADOW-REPORT.md already is;
    decide its .json twin), deleted (junk), or gitignored-local (.sync-history.jsonl,
    .claude/settings.local.json). account-instances.json (e031) gets an explicit call,
    not a silent skip.'
  status: pending
- text: 'D5 (post-op) — THE CUTOVER PROOF, after the post-op migration: the wipe-equivalent
    drill — empty dir + projection_bootstrap + repo_sync pull — produces a space whose
    tracked content diffs EMPTY against the real repo (modulo gitignored local files).
    A fresh pull on the real repo is clean. Recorded as the blessed recovery path:
    cloud-governor survives full reprojection from the DB with nothing of value lost.'
  status: pending
- text: 'D6 — the fully-projected authoring surface is verified live and documented
    as a DB-native doc: life create for spec/epic/skill/prompt/document (with document_type
    + linkage metadata conventions), life run repo.sync (pull/push), life run projection.bootstrap.
    One real life create document round-trips file-ward through a pull.'
  status: pending
- text: (post-op) stack-check 12/12 PASS at close (run on lifeos-registry main, not
    an in-flight spec branch checkout — the known e045-01 B/V false-fail); zero unstamped
    anywhere; version-monotonic and name-uniqueness policies untouched.
  status: pending
constraints:
- Routing lands only via governed seeds + registrar projection + the gate-stamp driver
  — no new tables, no hand DDL. Re-stamping MUST follow any re-projection (the 2026-07-17
  gov-unstamped incident is the cautionary precedent).
- The run kinds are shared with e045-02's sweeper mechanism — this spec routes run/run_step/run_report
  only; job_request routing is e045-02's decision, one coordination note here, no
  unilateral shape changes.
- specwright's gate emission goes through the sanctioned write path (recommend lorchestra-as-library);
  severity=error rejections surface to the operator — NO fallback to tree-writing
  on gate refusal (fail loudly, the run record is the evidence chain).
- Bulk artifacts never become rows and never return to the projection repo — local
  scratch only, accept-lost on machine loss (recorded, not implied).
- Historical ingest is idempotent (create-retry dedup holds for identical content)
  and reconciled per epic before runs/ removal; removal is a normal git commit (recoverable),
  not a purge.
- The version-bump policy covers spec/epic/skill/prompt — run kinds are NOT added
  to it in this spec (runs are append-only event records, not versioned artifacts);
  document auto-bump is already live via 07c.
- PREFLIGHTED 2026-07-17 in the redesign session (writer mechanisms, fallback cause,
  census, seeds, schema fit all grounded live); re-verify against live state if significant
  time passes before the run.
- 'SELF-HOSTING RULES (this run edits the harness running it — grounded: specwright
  orchestrates in-process from its own venv, modules imported at run start; it spawns
  only agent/command backends as subprocesses, never itself). (1) The in-flight orchestrator
  will NOT pick up mid-run edits — do not expect the flip to change THIS run''s behavior;
  prove D2 with a NESTED smoke run (`spec` CLI = fresh subprocess = new code). (2)
  THIS run''s own record lands as one final LEGACY tree — expected, correct, and NOT
  this run''s problem: the entire migration (real ingest + runs/ removal + cutover
  drill) is the attended POST-OP, executed after finalize against a frozen tree set.
  In-run, D3 is mapper + dry-run ONLY; the run never deletes any runs/ directory and
  never ingests for real. (3) Commit the specwright working tree promptly and keep
  the suite green before finalize — the tree IS the live harness for the next run
  (the storacle 2026-07-14 lost-edit lesson applies verbatim).'
- 'FOOTGUN PASS (2026-07-17, pre-launch, all grounded live): (1) run kind descriptors
  are immutable: True — emission is EMIT-ONCE-AT-FINALIZE, one complete record per
  run/step/report; never emit-then-update. (2) lorchestra job defaults do NOT merge
  into @payload refs — pass repo_sync''s projection_tag and projection_bootstrap''s
  db_path/config_name explicitly (bit two prior sessions). (3) The config chain _resolve_projection_repo_path
  actually reads: env SPECWRIGHT_PROJECTION_REPO → workspace .specwright.yaml (projection_repo/projection.path)
  → ~/.local/local-governor/config.yaml → None; today it returns None, which is the
  silent-legacy trigger D2 kills. (4) specwright suite baseline at redesign: 1054
  passed / 4 skipped — a clean bar; regressions are yours. (5) The storacle-client
  silent-noop footgun (lorchestra STATUS.md:108) is UNFIXED — AC2''s row-count verification
  is the guard: never trust a noop/success status without counting rows.'
labels:
- series:e
- runs
- runl
- routing
- ingest
- specwright
- cutover
repo:
  name: specwright
  url: /workspace/specwright
  working_branch: spec/e040-07d-run-kinds-routing-and-runs-ingestion
body: |-
  # e040-07d: run records into the DB + the full-reprojection cutover

  ## Why this exists

  After e040-07c, run trees are the last content class in cloud-governor
  that exists only on disk. The kinds to hold them have existed since e025
  (RunL); specwright already writes WAL-ready shapes and even has a
  registrar-friendly consolidated writer — it just fell back to legacy
  tree-writing because its projection-repo config still points at retired
  local-governor. This spec routes the kinds, cuts specwright over to
  gated emission, ingests history, and finishes with the cutover Ben
  named: nothing of value in the repo that does not survive a full
  reprojection from the DB.

  ## Deliverables

  ### D1 — Routing seeds (ops dataset)

  Table/routing seeds land run@1-0-0, run/run_step@1-0-0,
  run/run_report@1-0-0 in ops (empty, in the BQ mirror). Applied via
  registrar project + gate_stamp_projected.py — projection without
  re-stamping is the known footgun.

  ### D2 — specwright cutover (the producer flip)

  - Fix `_resolve_projection_repo_path()` / config: retire the
    local-governor pointer; absent config fails loudly (no silent legacy
    fallback — that silent fallback is exactly how old-style trees kept
    appearing).
  - Extend the ConsolidatedRunWriter path to EMIT: run + run_step +
    run_report objects through the gate (recommend lorchestra-as-library,
    the life-cli/e045 convention). The consolidated YAML shapes are
    already ~1:1 with the registered schemas.
  - Bulk (stdout/stderr/patches/attempt logs) stays in specwright's local
    scratch root. The projection repo gets NOTHING.
  - `legacy_output` remains only as an explicit, named escape hatch.

  ### D3 — Historical ingest + runs/ retirement

  Disposable mapper (e040-07 precedent, /workspace/scripts) walks the 86
  trees → gated rows; per-epic tree↔row reconciliation; then `runs/`
  directories are removed from the projection repo in a normal commit.

  ### D4 — Residue disposition (nothing silent)

  Enumerate every non-projected, non-stub file and disposition it:
  ingest / delete / gitignore-local. Known list at redesign time:
  SHADOW-REPORT-*.json twin, account-instances.json (e031),
  .sync-history.jsonl (gitignored), .claude/settings.local.json (local),
  .pytest_cache (junk).

  ### D5 — The cutover proof

  Wipe-equivalent drill: empty dir + projection_bootstrap + pull, tracked
  content diffs empty against the real repo. Recorded as the blessed
  recovery path. This is the epic-level definition of done for the
  projected-repo story.

  ### D6 — The fully projected lifestyle (authoring surface)

  Verify live + document as a DB-native doc: `life create` for all five
  kinds + document conventions (document_type, epic_id/project_label
  linkage), `life run repo.sync`, `life run projection.bootstrap`. One
  real `life create document` round-trip.

  ## Anti-patterns

  - Do NOT let gate refusals fall back to tree-writing — fail loudly;
    a silently-degraded run record is worse than a failed run.
  - Do NOT ingest bulk artifacts as rows or leave them in the repo.
  - Do NOT touch job_request routing/semantics — e045-02's territory.
  - Do NOT hand-run CREATE/ALTER anything — seeds + registrar + stamp
    driver only, re-stamp after every projection.
  - Do NOT purge runs/ history from git — removal is a commit, recovery
    stays possible.
