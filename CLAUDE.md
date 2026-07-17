# CLAUDE.md — Specwright v2 Epic (e008)

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

<!-- END SYNCED: specwright -->

<!-- BEGIN SPEC: e101-04d-specwright-output-format -->
## Current Spec: e101-04d-specwright-output-format

---
id: e101-04d-specwright-output-format
tier: C
title: "Specwright Consolidated Output Format + JobDef Registrar Fields"
owner: benthepsychologist
goal: Update specwright run output to consolidated YAML format. Add registrar fields to JobDef model.
validated: true
version: '3.0'
labels:
- specwright
- jobs
- runs
- output
epic: e101-lifeos-cloud-registrar
repo:
  name: specwright
  working_branch: feat/consolidated-output
created: '2026-03-05T00:00:00Z'
updated: '2026-03-09T00:00:00Z'
---

## Objective

Update specwright to:

1. Add registrar fields (`kind`, `artifact_id`, `name`) to `JobDef` model
2. Write consolidated YAML output that registrar sync can ingest directly
3. Preserve legacy output mode behind `--legacy-output` flag

After this spec, specwright's run output matches the file shapes 04c's
sync expects.

## Preconditions

- e101-04b complete: JSON schemas for `jobdef`, `run`, `run_step`, `run_report`
  exist in registrar
- e101-04c complete: sync routing for job/run kinds works end-to-end

## Changes

### 1. JobDef Model

Add fields to specwright's `JobDef` pydantic model
(`/workspace/specwright/src/spec/executor/schemas/job_def.py`):

```python
class JobDef(BaseModel):
    # ...existing fields...
    kind: str = Field(default="jobdef", description="Artifact kind for registrar")
    artifact_id: str = Field(default="", description="Registrar artifact UUID")
    name: str = Field(default="", description="Registrar artifact name")
```

Update all three bundled jobdef YAMLs with registrar fields:

- `aip-1.yaml` — `kind: jobdef`, `artifact_id: <uuid>`, `name: aip-1`
- `interactive-1.yaml` — `kind: jobdef`, `artifact_id: <uuid>`, `name: interactive-1`
- `harness-probe-1.yaml` — `kind: jobdef`, `artifact_id: <uuid>`, `name: harness-probe-1`

Generate stable UUIDs once.

### 2. ConsolidatedRunWriter

New writer class that produces the layout registrar sync expects:

```
runs/{epic_id}/{run_id}/
  run.yaml              — kind: run
  run_report.yaml       — kind: run_report
  steps/
    step-001.yaml       — kind: run_step
    step-002.yaml
    ...
```

Each file includes `kind` at top level for registrar sync routing.

vs. legacy layout:

```
<epic_dir>/runs/{run_id}/
  run.yaml, job_def.yaml, job_instance.yaml, run_report.md,
  stdout.txt, stderr.txt, changes_final.patch,
  attempts/attempt-001.yaml,
  steps/step-001/{manifest,outcome,capture}.yaml + txt files
```

### 3. File Shapes

**`run.yaml` (kind: run):**

No `version` field — run records are immutable logs.

```yaml
kind: run
artifact_id: <uuid>
name: run-{epic_id}-{spec_id}-{timestamp}-{hash}
run_id: <same as name>
job_id: aip-1
status: completed
epic_id: e016-local-prompt-eng
spec_id: e016-02-lorchestra-job-migration
repo: { repo_path, branch, base_commit }
policy: { profile, allow_commit, allow_push }
created_at: "2026-03-03T19:40:44Z"
updated_at: "2026-03-03T19:55:42Z"
envelope:
  job_def: { ... }     # absorbed from job_def.yaml
  payload: { ... }
  ctx: { ... }
attempts:              # absorbed from attempts/attempt-NNN.yaml
  - attempt_n: 1
    started_at: ...
    ended_at: ...
    status: completed
    final_step_n: 13
stdout: |              # absorbed from stdout.txt
  <run-level stdout>
stderr: |              # absorbed from stderr.txt
  <run-level stderr>
changes_final: |       # absorbed from changes_final.patch
  <aggregate unified diff>
```

**`steps/step-NNN.yaml` (kind: run_step):**

```yaml
kind: run_step
artifact_id: <uuid>
name: run-abc123/step-003
run_id: run-abc123
step_n: 3
step_id: agent.run_spec
backend: copilot
started_at: "2026-03-03T19:42:00Z"
payload: { ... }
# --- appended at step end ---
outcome: completed
duration_ms: 458486
ended_at: "2026-03-03T19:49:38Z"
error: null
capture: { git: { base_commit, changed_files } }
stdout: |
  <full stdout>
stderr: |
  <full stderr>
patch: |
  <unified diff>
```

**`run_report.yaml` (kind: run_report):**

```yaml
kind: run_report
artifact_id: <uuid>
name: run-abc123/report
run_id: run-abc123
generated_at: "2026-03-03T19:56:00Z"
status: completed
job_id: aip-1
summary: |
  ...
assessment: |
  ...
issues:
  - description: "..."
    severity: warning
recommendation: |
  ...
```

### 4. Step Write-Then-Append Pattern

Steps are written twice:

1. **At step start:** manifest fields (step_number, tool, started_at). File
   is valid YAML if step crashes.
2. **At step end:** outcome, capture, text blobs, completed_at, duration.
   Overwrites the file.

Partial runs are always recoverable — every step file is valid YAML at all
times.

### 5. Output Mode Switch

```python
if legacy_output:
    writer = LegacyRunWriter(run_dir=epic_dir / "runs" / run_id)
else:
    writer = ConsolidatedRunWriter(run_dir=projection_repo / "runs" / epic_id / run_id)
```

- Default: consolidated YAML to projection repo path from `config.yaml`
- `--legacy-output`: old multi-file format in governor filesystem

### 6. Config

```yaml
jobdefs:
  path: /workspace/cloud-codex/jobdefs
  fallback: bundled
```

`load_job_def()` checks `jobdefs.path` first, falls back to bundled YAML
templates if not found.

## Acceptance Criteria

1. `specwright run` writes consolidated YAML to projection repo path
2. Each output file has a `kind` field matching registrar's expected kinds
3. `--legacy-output` produces the old multi-file format
4. Partial runs (step crashes) produce valid YAML for all completed steps
5. `load_job_def()` loads from `jobdefs.path` when available, falls back to bundled
6. All three bundled jobdefs include `kind`, `artifact_id`, `name` fields
7. Step files zero-padded: `step-001.yaml`, `step-003.yaml`
8. run.yaml embeds job_def, attempts, stdout, stderr, changes_final
9. run_report.yaml replaces run_report.md (structured YAML)
10. Existing tests pass
11. Legacy output identical to current behavior

## Known Issues / Deferred

- `job_instance.yaml` not included (compiled artifact → GCS, future)
- Migration of existing governor FS runs to new format (separate task)
- `result.json` — embed in step YAML or skip (TBD)

## Constraints

- Legacy format must remain fully functional (`--legacy-output`)
- No changes to step execution logic — only the file writer changes
- `artifact_id` is a UUID; `name` is deterministic from run_id + step
- YAML multi-line strings must preserve content exactly (use `|` block scalar)

## Dependencies

- e101-04b-foundation-rename-and-ddl (JSON schemas for all kinds)
- e101-04c-registrar-job-routing (sync routing, file shape contracts)

<!-- END SPEC: e101-04d-specwright-output-format -->

<!-- BEGIN SPEC: e101-07-specwright-yaml-io -->
## Current Spec: e101-07-specwright-yaml-io

---
id: e101-07-specwright-yaml-io
tier: C
title: "Specwright Full YAML Conversion — Structured IO for Registrar Loop"
owner: benthepsychologist
goal: Convert specwright to YAML as the native spec format. Read, write, validate, and resolve .yaml specs. .md remains readable but .yaml is the default.
validated: false
version: '4.2'
labels:
- specwright
- registrar
- yaml
- io
epic: e101-lifeos-cloud-registrar
repo:
  name: specwright
  url: /workspace/specwright
  working_branch: feat/yaml-spec-io
created: '2026-03-13T00:00:00Z'
updated: '2026-03-13T00:00:00Z'
---

## Objective

Specwright speaks `.md` with YAML frontmatter. Registrar speaks pure `.yaml`
(spec-v2.1 schema). Rather than maintain two formats, convert specwright to
YAML as its native spec format — read, write, validate, resolve.

This closes the registrar round-trip with zero format conversion:

```
registrar create spec → .yaml on disk
    → human/agent edits .yaml
    → specwright reads .yaml → runs → writes run.yaml
    → registrar commit-run → BQ
    → registrar project → cloud-codex/*.yaml
```

`.md` specs remain *readable* (specwright won't refuse them) but `.yaml` is
the default for all new output. No rendering, no format translation — YAML
everywhere.

## Preconditions

- e101-04d complete: ConsolidatedRunWriter exists, run output is YAML
- spec-v2.1 schema registered in BQ (spec-v2.1.schema.json)

## Key Decisions

### Pass YAML Straight Through — No Rendering

LLM backends (`claude_code.py`, `copilot.py`, `llm.py`) all consume `spec_md`
as a string that gets injected into a prompt. The LLM doesn't care whether
that string is markdown or YAML — it can read both. YAML is arguably more
structured and less ambiguous for the model.

So: `_load_spec()` for `.yaml` files does `spec_path.read_text()` and passes
the raw YAML string as `spec_md`. No rendering, no format conversion. The
only work is extracting the fields specwright needs internally (`tier`,
`title`, `owner`, `goal`, `branch`) from the parsed YAML dict.

The same raw YAML string also flows into `sync_refs.py` which injects
`spec_md` into `CLAUDE.md` / `COPILOT.md`. YAML content works fine there —
it's just text between HTML comment markers.

### Prefer .yaml Over .md in Resolver

When both `spec-id.yaml` and `spec-id.md` exist, prefer `.yaml`. This makes
the transition automatic — once a spec is in YAML, specwright picks up the
structured version without any flags or config.

## Changes

### 1. `_load_spec()` Dispatcher — `exec_commands.py`

New function after `_update_frontmatter()` (~line 133). Dispatches on file
extension:

- `.yaml` / `.yml` → `yaml.safe_load()` to extract frontmatter fields,
  `read_text()` as `spec_md`. Return `(frontmatter_dict, raw_yaml_str)`.
- `.md` → existing path: `_parse_spec_frontmatter()` on `read_text()`.

```python
def _load_spec(spec_path: Path) -> tuple[dict[str, Any], str]:
    """Load a spec from either .md or .yaml format.

    Returns (frontmatter_dict, spec_content_str).
    For .yaml: frontmatter is extracted from the YAML dict,
               spec_content_str is the raw YAML text (passed straight to LLM).
    For .md:   frontmatter is parsed from --- fences,
               spec_content_str is the full markdown.
    """
    content = spec_path.read_text(encoding="utf-8")

    if spec_path.suffix in (".yaml", ".yml"):
        raw = yaml.safe_load(content) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Expected a YAML mapping in {spec_path}")

        frontmatter = {}
        for key in ("tier", "title", "owner", "goal", "name", "version",
                    "epic_artifact_id", "labels", "constraints", "dependencies"):
            if key in raw:
                frontmatter[key] = raw[key]

        tier = str(frontmatter.get("tier", "")).upper()
        if tier not in VALID_TIERS:
            raise ValueError(f"Invalid tier '{frontmatter.get('tier')}'. "
                             f"Must be one of {VALID_TIERS}")
        frontmatter["tier"] = tier

        missing = REQUIRED_FRONTMATTER - set(frontmatter.keys())
        if missing:
            raise ValueError(f"Missing required fields in YAML spec: {missing}")

        # Carry repo / branch info
        if "repo" in raw and isinstance(raw["repo"], dict):
            frontmatter["repo"] = raw["repo"]
            if raw["repo"].get("working_branch"):
                frontmatter["branch"] = raw["repo"]["working_branch"]

        # Derive epic id from name prefix (e.g. e102-01-foo → e102)
        name = raw.get("name", "")
        if name and "-" in name:
            parts = name.split("-")
            if len(parts) >= 2 and parts[0][0] in "est":
                frontmatter["epic"] = parts[0]

        return frontmatter, content  # raw YAML passed straight through
    else:
        frontmatter = _parse_spec_frontmatter(content)
        return frontmatter, content
```

### 2. Callers of `_load_spec()` — `exec_commands.py`

Two call sites replace the inline `read_text()` + `_parse_spec_frontmatter()`:

**`compile_command`** (~line 270):
```python
# Before:
    spec_md = spec_path.read_text()
    frontmatter = _parse_spec_frontmatter(spec_md)
# After:
    frontmatter, spec_md = _load_spec(spec_path)
```

**`run_command`** (~line 527):
```python
# Before:
    spec_md = spec_path.read_text()
    frontmatter = _parse_spec_frontmatter(spec_md)
# After:
    frontmatter, spec_md = _load_spec(spec_path)
```

### 3. `_get_spec_path()` — `exec_commands.py` (~line 136)

Update to search `.yaml` then `.md`:

```python
def _get_spec_path(epic_id: str, spec_id: str) -> Path:
    governor_root = Path.home() / ".local/local-governor/projects"
    if not governor_root.exists():
        raise FileNotFoundError(f"Governor root not found: {governor_root}")

    for ext in (".yaml", ".md"):
        for project_dir in governor_root.iterdir():
            if not project_dir.is_dir():
                continue
            specs_dir = project_dir / "specs" / epic_id
            if specs_dir.exists():
                spec_file = specs_dir / f"{spec_id}{ext}"
                if spec_file.exists():
                    return spec_file

    raise FileNotFoundError(
        f"Spec not found: {epic_id}/{spec_id} (.yaml or .md)")
```

### 4. `validate_command` — `exec_commands.py` (~line 1085)

Add `.yaml`/`.yml` branch before the `.md`-only check:

- YAML specs: validate via `_load_spec()` (checks required fields, tier).
  No `validated: true` flag written — structured YAML specs are validated
  externally by registrar schema validation.
- `.md` specs: existing `SpecParser` path unchanged.
- Other extensions: reject with error.

### 5. `validate_spec` — `governance.py` (~line 259)

Same treatment as `validate_command`: add `.yaml`/`.yml` before the `.md`
guard:

```python
# Before:
    if spec_path.suffix != ".md":
        typer.secho(f"Error: Spec must be a .md file ...")
# After:
    if spec_path.suffix in (".yaml", ".yml"):
        # YAML validation via _load_spec
        ...
        return
    if spec_path.suffix != ".md":
        typer.secho(f"Error: Spec must be a .md or .yaml file ...")
```

### 6. Resolver — `resolver.py`

Three changes in `src/spec/governor/resolver.py`:

**`resolve_spec()`** (~line 191): match files with suffix in
`(".md", ".yaml", ".yml")` instead of only `".md"`:
```python
if f.is_file() and f.suffix in (".md", ".yaml", ".yml") and f.stem.startswith(query):
```

**Available-specs error message** (~line 196):
```python
available = [f.stem for f in sorted(specs_dir.iterdir())
             if f.is_file() and f.suffix in (".md", ".yaml", ".yml")
             and f.stem != "README"]
```

**`list_specs_in_epic()`** (~line 239) — deduplicate with `set()`:
```python
return sorted({
    f.stem for f in specs_dir.iterdir()
    if f.is_file() and f.suffix in (".md", ".yaml", ".yml")
    and f.stem != "README"
})
```

### 7. `GovernorReader` — `reader.py`

**`_resolve_spec_path()`** (~line 86): try `.yaml` then `.md`:
```python
for ext in (".yaml", ".md"):
    direct = self._paths.specs / f"{slug}{ext}"
    if direct.exists():
        return direct
```

**`list_specs()`** (~line 155): add `.yaml`/`.yml` alongside `.md`:
```python
if p.suffix in (".md", ".yaml", ".yml"):
    slugs.add(p.stem)
```

**`get_spec_path()`** (~line 208) fallback: default to `.yaml`:
```python
return self._paths.specs / f"{slug}.yaml"
```

### 8. `GovernorWriter` — `writer.py`

**`write_spec()`** (~line 45): change default extension to `.yaml`:
```python
# Before:
    spec_path = self._paths.specs / f"{slug}.md"
# After:
    spec_path = self._paths.specs / f"{slug}.yaml"
```

**`delete_spec()`** (~line 140): try both extensions:
```python
# Before:
    spec_path = self._paths.specs / f"{slug}.md"
# After:
    for ext in (".yaml", ".md"):
        spec_path = self._paths.specs / f"{slug}{ext}"
        if spec_path.exists():
            spec_path.unlink()
            return True
    return False
```

### 9. `epic.py` — Default Spec Path in Refs

**Default path in spec refs** (~lines 254, 410):
```python
# Before:
    path=s.get("path", f"specs/{s['id']}.md"),
# After:
    path=s.get("path", f"specs/{s['id']}.yaml"),
```

### 10. `epic_validator.py` — Default Spec Path Lookup

**`_check_spec_files()`** (~line 82): the default path uses `.md` and feeds
into a real file-existence check. If specs are `.yaml`, the default would
produce false "spec file not found" warnings.

```python
# Before:
    spec_path = spec.get("path", f"specs/{spec_id}.md")
    full_path = self.epic_dir / spec_path
    if not full_path.exists():
        ...
# After — only the default changes; explicit path still honoured:
    explicit = spec.get("path")
    if explicit:
        spec_path = explicit
    else:
        # Default to .yaml, fall back to .md
        yaml_path = f"specs/{spec_id}.yaml"
        md_path   = f"specs/{spec_id}.md"
        if (self.epic_dir / yaml_path).exists():
            spec_path = yaml_path
        elif (self.epic_dir / md_path).exists():
            spec_path = md_path
        else:
            spec_path = yaml_path  # preferred default for the warning message
    full_path = self.epic_dir / spec_path
    if not full_path.exists():
        ...
```

### Cosmetic: Help Text & Docstrings

Several already-touched files have help strings, docstring examples, and CLI
usage lines that say `.md` (e.g. `help="Path to spec .md file"`,
example lines like `spec compile aip-1 ./my-feature.md`). Update these to
say `.yaml` (or `.yaml / .md`) for consistency. Affected files:

- `exec_commands.py` — `help=` params at ~L218, L411, L1047; docstring
  examples at ~L244-246, L451-453, L838, L1062-1063, L1075
- `governance.py` — `help=` at ~L225; docstring examples at ~L213, L239-241, L250
- `epic.py` — docstring examples at ~L341-342

These are non-functional but should be updated for a clean grep.

## Files to Touch

| File | Action |
|------|--------|
| `src/spec/cli/exec_commands.py` | modify — add `_load_spec`, update `_get_spec_path`, `compile_command`, `run_command`, `validate_command` |
| `src/spec/cli/governance.py` | modify — update `validate_spec` to accept `.yaml` |
| `src/spec/cli/epic.py` | modify — default spec path extension `.md` → `.yaml` |
| `src/spec/governor/resolver.py` | modify — `.yaml`/`.yml` in `resolve_spec`, `list_specs_in_epic` |
| `src/spec/governor/reader.py` | modify — `.yaml`/`.yml` in `_resolve_spec_path`, `list_specs`, `get_spec_path` |
| `src/spec/governor/writer.py` | modify — `write_spec` emits `.yaml`, `delete_spec` checks both |
| `src/spec/governance/epic_validator.py` | modify — default spec path `.md` → `.yaml`, accept both extensions |

### Not Touched (and why)

| File | Reason |
|------|--------|
| `src/spec/executor/backends/*.py` | Receive `spec_md` as string — format-agnostic |
| `src/spec/governance/sync_refs.py` | Injects `spec_md` into CLAUDE.md — string, works with YAML |
| `src/spec/compiler/parser.py` | `SpecParser` validates `.md` structure — still needed for legacy .md |
| `src/spec/compiler/compiler.py` | Only a docstring reference |

## Acceptance Criteria

- [ ] `spec compile aip-1 some-spec.yaml --repo /workspace/foo` works
- [ ] `spec run aip-1 some-spec.yaml --repo /workspace/foo` works
- [ ] `spec run aip-1 --epic e101 --spec e101-01` resolves `.yaml` before `.md`
- [ ] `spec validate some-spec.yaml` validates required fields (exec_commands)
- [ ] `spec validate spec some-spec.yaml` validates (governance.py)
- [ ] `spec validate some-spec.md` still works unchanged
- [ ] `resolver.resolve_spec()` finds `.yaml` specs in epic directories
- [ ] `list_specs_in_epic()` returns specs regardless of extension, deduped
- [ ] `GovernorReader.read_spec()` reads `.yaml` specs
- [ ] `GovernorReader.list_specs()` includes `.yaml` specs
- [ ] `GovernorWriter.write_spec()` creates `.yaml` files
- [ ] `GovernorWriter.delete_spec()` handles both `.yaml` and `.md`
- [ ] No changes to LLM backends — they still receive `spec_md` string
- [ ] `epic_validator._check_spec_files()` defaults to `.yaml`, falls back to `.md`
- [ ] Help text and docstring examples updated to mention `.yaml`
- [ ] Existing `.md` specs remain loadable (backward compat)

## Constraints

- No new dependencies.
- No rendering or format conversion — YAML goes straight to the LLM as-is.
- No changes to LLM backends (claude_code, copilot, llm).
- No changes to ConsolidatedRunWriter or run output format.
- No changes to registrar.
- `.md` specs remain loadable — reader/resolver accept both.
- `SpecParser` kept for legacy `.md` validation — not deleted.

<!-- END SPEC: e101-07-specwright-yaml-io -->

<!-- BEGIN SPEC: t013-01-skills-schema-and-store -->
## Current Spec: t013-01-skills-schema-and-store

---
id: t013-01-skills-schema-and-store
tier: B
title: "Skills Schema, Store, and Seed Skills"
owner: benthepsychologist
goal: Create the governed skills store using the Agent Skills open standard format, establish lifecycle conventions, project global skills to native agent discovery paths, and author seed skills.
validated: true
version: "2.0"
labels:
  - specwright
  - skills
  - governance
  - agent-skills-standard
epic: t013-skills-layer
repo:
  name: specwright
  url: /workspace/specwright
  working_branch: feat/skills-schema
depends_on: []
created: "2026-03-20T00:00:00Z"
updated: "2026-03-20T00:00:00Z"
---

# t013-01: Skills Schema, Store, and Seed Skills

**Epic:** t013-skills-layer
**Branch:** `feat/skills-schema`
**Tier:** B

## Objective

Create the governed skills store using the Agent Skills open standard format
(agentskills.io). Author at least 3 seed skills. Project global skills to
native agent discovery paths. This spec produces **conventions and files
only** — no specwright code changes.

## Problem

Agent sessions lack reusable operational knowledge. Today:

1. Hard-won procedural knowledge gets buried in improvement files or manually
   copy-pasted into CLAUDE.md as static context.
2. When an agent encounters a task it has done before, it has no structured,
   conditionally-loaded reference to consult.
3. CLAUDE.md is always loaded at session start — it is context, not skills.
   As it grows, it wastes context window on knowledge irrelevant to the
   current task.

## Agent Skills Open Standard

The Agent Skills standard (agentskills.io) defines a portable format for
giving agents on-demand capabilities. Key properties:

- A skill is a **directory** containing a required `SKILL.md` file
- `SKILL.md` has YAML frontmatter with `name` (required) and `description`
  (required), plus optional `license`, `compatibility`, `metadata`,
  `allowed-tools`
- Agents use **progressive disclosure**: only `name` and `description` are
  loaded at session start; full `SKILL.md` loads only when the agent
  determines the skill is relevant or the user invokes `/skill-name`
- Supported by: Claude Code, Codex, Copilot, VS Code, Cursor, Goose,
  Junie, TRAE, and others

### How agents discover skills

| Agent | Project Path | Personal Path |
|-------|-------------|---------------|
| Claude Code | `.claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>/SKILL.md` |
| Codex | `.agents/skills/<name>/SKILL.md` | `~/.agents/skills/<name>/SKILL.md` |
| Copilot | reads `.claude/skills/` natively | unconfirmed (project-level confirmed only) |

### How skills differ from context

| | Context (CLAUDE.md) | Skills (SKILL.md) |
|---|---|---|
| Loading | Always, at session start | On demand, when relevant |
| Format | Freeform markdown | Frontmatter + instructions |
| Scope | Entire session | Specific task |
| Cost | Permanent context window use | Loaded only when needed |
| Discovery | Fixed path, always read | Progressive: name+description first |

## Skill Directory Format

Per the Agent Skills specification:

```
skill-name/
├── SKILL.md          # Required: frontmatter + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: reference documentation
└── assets/           # Optional: templates, resources
```

### SKILL.md Frontmatter

Standard fields (these go in the SKILL.md file):

| Field | Required | Constraint |
|-------|----------|------------|
| `name` | Yes | Lowercase alphanumeric (a-z, 0-9) and hyphens, 1-64 chars, must not start/end with hyphen, no consecutive hyphens, must match directory name |
| `description` | Yes | What it does and when to use it, max 1024 chars |
| `license` | No | License name or reference |
| `compatibility` | No | Environment requirements, max 500 chars |
| `metadata` | No | Arbitrary key-value map |
| `allowed-tools` | No | Space-delimited pre-approved tools |

Example:

```yaml
---
name: registrar-bootstrap
description: Bootstrap a registrar-managed environment with BigQuery DDL,
  schemas, and seed data. Use when setting up dev, stage, or prod environments
  for a registrar-governed project.
metadata:
  author: benthepsychologist
  version: "1.0"
---
```

### What does NOT go in SKILL.md frontmatter

Non-standard **top-level** frontmatter fields (`status`, `retired_at`,
`scope`, `source_run` as top-level keys, etc.) do NOT go in the SKILL.md
file. That would violate the standard and could confuse agents.

Governor lifecycle metadata lives in `skills.yaml`.

The standard `metadata:` field (an arbitrary key-value map) IS a valid
place for supplementary information like `author` or `version`. Draft
skills may also use `metadata:` for `source_run` and `source_spec` since
these are sub-keys of a standard field, not non-standard top-level fields.

## Store Layout

```
~/.local/local-governor/
  skills/
    skills.yaml                         # Manifest: global list + governor metadata
    git-branching-workflow/             # Each skill is a directory
      SKILL.md
    specwright-spec-authoring/
      SKILL.md
    idempotent-shell-scripts/
      SKILL.md
    registrar-bootstrap/
      SKILL.md
      references/
        env-configs.md
    local-http-smoke-test/
      SKILL.md
    drafts/                             # Draft skills awaiting review
      some-extracted-skill/
        SKILL.md
```

## skills.yaml Manifest

The manifest declares global skills, tracks lifecycle state, and holds
governor-specific metadata that does not belong in standard SKILL.md
frontmatter.

```yaml
# Skills manifest — governor lifecycle metadata + global declarations
version: "1.0"

# Global skills: projected to ~/.claude/skills/ and ~/.agents/skills/
# for every agent session on this machine. Keep small (3-5 max).
global:
  - git-branching-workflow
  - specwright-spec-authoring

# Governor metadata per skill (not in SKILL.md files)
registry:
  git-branching-workflow:
    status: active
    scope: global
    created: "2026-03-20"
    author: benthepsychologist

  specwright-spec-authoring:
    status: active
    scope: global
    created: "2026-03-20"
    author: benthepsychologist

  idempotent-shell-scripts:
    status: active
    scope: project
    created: "2026-03-20"
    author: benthepsychologist

  registrar-bootstrap:
    status: active
    scope: project
    created: "2026-03-20"
    author: benthepsychologist

  local-http-smoke-test:
    status: active
    scope: domain
    created: "2026-03-20"
    author: benthepsychologist

# Drafts are tracked here too when staged by the improvement pipeline
drafts:
  some-extracted-skill:
    status: draft
    source_run: run-e103-03-...-20260320
    source_spec: e103-03-http-listener
    created: "2026-03-20"
    author: ai
```

### Why separate from SKILL.md?

1. **Standard compliance.** SKILL.md frontmatter must only contain fields
   defined by the Agent Skills spec. `status: retired` is not a standard
   field.
2. **Single source of truth.** Governor metadata lives in one manifest,
   not scattered across 50 SKILL.md files.
3. **Agent safety.** Agents parse SKILL.md frontmatter to decide when to
   load skills. Non-standard fields could confuse them.

## Selection Mechanism

### Three-Tier Declaration

Skills are named at three tiers. The governor resolves which skills to
project. The agent handles on-demand loading natively.

| Tier | Source | Projected To |
|------|--------|--------------|
| **Global** | `skills.yaml` → `global:` | `~/.claude/skills/` + `~/.agents/skills/` |
| **Project** | `{project}.build.yaml` → `skills:` | `{repo}/.claude/skills/` + `{repo}/.agents/skills/` |
| **Spec** | Spec payload → `skills:` | `{repo}/.claude/skills/` + `{repo}/.agents/skills/` |

### build.yaml Integration

```yaml
# In {project}.build.yaml
kernel:
  description: "..."
  invariants: [...]

skills:
  - registrar-bootstrap
  - idempotent-shell-scripts
```

### Spec Frontmatter Integration

```yaml
---
id: e103-03-http-listener
title: "HTTP Listener Service"
skills:
  - local-http-smoke-test
---
```

### What Does NOT Happen

- **No auto-selection.** The governor does not choose skills based on task.
  The human names them. The agent decides when to load based on its own
  progressive disclosure.
- **No "project everything."** Only named skills are projected. The store
  may grow large; projecting all of them would defeat progressive disclosure.
- **No tag-based matching.** Tags/scope are for human CLI listing, not
  automatic projection.

## Global Skills Projection

Global skills are projected to personal agent discovery paths. This is a
one-time setup (or re-run on skill changes):

```
~/.local/local-governor/skills/git-branching-workflow/SKILL.md
  → ~/.claude/skills/git-branching-workflow/SKILL.md
  → ~/.agents/skills/git-branching-workflow/SKILL.md
```

Projection is a **copy** (or symlink if the platform supports it). The
canonical source remains in the governor store. Spec 02 automates this
as part of `refs.sync`.

## .gitignore Convention

Projected skill directories in repos are copies from the governor store.
They should be gitignored to avoid committing derived content:

```gitignore
# Projected agent skills (canonical source: ~/.local/local-governor/skills/)
.claude/skills/
.agents/skills/
```

This convention should be documented in skills store README and applied
to repos that receive projected skills. Spec 02 should note this but
not auto-modify .gitignore.

## Lifecycle

```
draft  ──promote──▶  active  ──retire──▶  retired
  ▲                                          │
  └────────────reactivate───────────────────┘
```

| State | Where | Projected? | Governor Metadata |
|-------|-------|------------|-------------------|
| `draft` | `skills/drafts/<name>/` | Never | `status: draft` in `skills.yaml` → `drafts:` |
| `active` | `skills/<name>/` | When named | `status: active` in `skills.yaml` → `registry:` |
| `retired` | `skills/<name>/` | Never | `status: retired` + `retired_at` + `retired_reason` |

### Promotion (manual)

1. Review draft in `skills/drafts/<name>/SKILL.md`
2. Move directory to `skills/<name>/`
3. Move entry from `drafts:` to `registry:` in `skills.yaml`
4. Set `status: active`, update `author` from `ai` to human

### Retirement

Set `status: retired` in `skills.yaml` → `registry:`. Add `retired_at`
and `retired_reason`. Directory stays in `skills/`. If a build.yaml or
spec still names a retired skill, `refs.sync` warns and skips it.

## Guiding Principles

1. **Standard-compliant SKILL.md.** Every SKILL.md must pass
   `skills-ref validate`. No custom frontmatter fields.

2. **Skills are for agents, not humans.** Write in imperative voice with
   concrete commands, paths, and examples. The description must include
   keywords that match how a task would be described.

3. **One skill, one task.** "How to bootstrap a registrar environment" is
   a skill. "Everything about registrar" is not.

4. **Description is the trigger.** Agents match tasks to skills using the
   description field. Write it to include the exact words a prompt or spec
   would use.

5. **Progressive disclosure.** Keep SKILL.md under 500 lines. Move
   detailed references to `references/`. Move scripts to `scripts/`.

6. **Small global set.** 3-5 global skills max. If it only applies to some
   projects, declare it in build.yaml, not globals.

7. **Named, not magic.** Every projection is traceable to an explicit
   declaration in skills.yaml, build.yaml, or spec frontmatter.

8. **Draft means invisible.** Drafts are never projected, period.

## Seed Skills

Author at least 3 seed skills to validate the format:

| Skill ID | Scope | Description |
|----------|-------|-------------|
| `git-branching-workflow` | global | Branching model: branch naming, commit discipline, merge flow |
| `specwright-spec-authoring` | global | How to write a specwright-compatible spec with proper frontmatter, test plan, and acceptance criteria |
| `idempotent-shell-scripts` | project | How to write re-runnable gcloud/bq infrastructure scripts |
| `registrar-bootstrap` | project | How to use `registrar bootstrap --env` and what it provisions |
| `local-http-smoke-test` | domain | How to start a real HTTP process, send requests, and validate |

The first two are global (declared in `skills.yaml`). The rest are available
for build.yaml or spec-level declaration.

Minimum: 3 seed skills. All 5 are recommended since each validates a
different scope and use case.

## Deliverables

1. `~/.local/local-governor/skills/skills.yaml` — manifest
2. At least 3 skill directories in `~/.local/local-governor/skills/`, each with `SKILL.md`
3. `~/.local/local-governor/skills/drafts/` directory (empty, ready for spec 03)
4. Global skills projected to `~/.claude/skills/` and `~/.agents/skills/`
5. All SKILL.md files pass `skills-ref validate` (or manual frontmatter check)

## Test Plan

| # | Test | Method |
|---|------|--------|
| 1 | SKILL.md frontmatter has `name` and `description` | Manual inspection or skills-ref validate |
| 2 | `name` field matches parent directory name | Check each skill directory |
| 3 | `name` is lowercase alphanumeric + hyphens, 1-64 chars, no leading/trailing/consecutive hyphens | Regex check |
| 4 | `description` is non-empty, max 1024 chars | Length check |
| 5 | No non-standard top-level fields in SKILL.md frontmatter | Frontmatter parse + allowlist check (allowed: name, description, license, compatibility, metadata, allowed-tools) |
| 6 | skills.yaml is valid YAML with `global:` and `registry:` keys | YAML parse |
| 7 | All skills named in `global:` exist as directories | Directory existence check |
| 8 | All skills in `registry:` have `status` field | Key check |
| 9 | Global skills projected to `~/.claude/skills/` | File existence check |
| 10 | Global skills projected to `~/.agents/skills/` | File existence check |
| 11 | `drafts/` directory exists | ls check |
| 12 | No skill in main `skills/` dir has `status: draft` in `skills.yaml` | Manifest check |
| 13 | Seed skills contain concrete procedures, not placeholder stubs | Manual review: each SKILL.md has real commands, paths, and examples |

## Acceptance Criteria

1. `skills/skills.yaml` exists with `version`, `global`, and `registry` keys
2. At least 3 skill directories exist with standard-compliant `SKILL.md` files
3. SKILL.md files contain only standard top-level frontmatter fields (`name`, `description`, and optionally `metadata`, `license`, `compatibility`, `allowed-tools`)
4. Governor lifecycle metadata (`status`, `scope`, `retired_at`, etc.) is in `skills.yaml`, not as top-level SKILL.md keys
5. `skills/drafts/` directory exists
6. Global skills are projected to `~/.claude/skills/` and `~/.agents/skills/`
7. Seed skills are concrete and useful — not placeholder stubs
8. No specwright code changes in this spec

## Boundary

- **In scope:** Conventions, store layout, skills.yaml manifest, seed skills,
  global projection
- **Out of scope:** Code changes to sync_refs.py (spec 02), improvement
  pipeline changes (spec 03), CLI commands (spec 03)

<!-- END SPEC: t013-01-skills-schema-and-store -->

<!-- BEGIN SYNCED: SPEC: e040-07d-run-kinds-routing-and-runs-ingestion -->
## Current Spec: e040-07d-run-kinds-routing-and-runs-ingestion

(No acceptance criteria section found in spec)
<!-- END SYNCED: SPEC: e040-07d-run-kinds-routing-and-runs-ingestion -->
