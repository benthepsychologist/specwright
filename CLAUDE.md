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

<!-- BEGIN SYNCED: specwright -->
# Specwright Project Context

## Description

Spec execution engine. Compiles job definitions against spec markdown, executes step sequences via pluggable backends (claude-code, cmd, python, llm), and tracks runs with artifact capture.

## Invariants

- Job-based execution: specs compile to JobInstances with fixed step sequences.
- Executor never mutates the step list — it runs exactly what compile() produced.
- Run artifacts stored in ~/.local/local-governor/runs/, never in the target repo.

## Boundaries

### cli
- Type: inbound
- Contract: spec <command> [options]
- Consumers: developers, agentic workflows

### governor_fs
- Type: dependency
- Contract: ~/.local/local-governor/ filesystem layout
- Requires: epics/, projects/, runs/, contracts/ directories

### claude_code
- Type: dependency
- Contract: claude CLI binary
- Requires: claude CLI for claude-code backend execution

### llm_lib
- Type: dependency
- Contract: llm Python library (simon willison)
- Requires: llm>=0.19.0 for LLM check execution

## Architecture Decisions

### adr-001: Job-based execution model
**Status:** accepted

**Rationale:** Decouples spec authoring from execution. JobDefs are reusable templates. Specs are payload.

**Decision:** Specs compile to JobInstances via JobDef templates. Executor runs JobInstances.

### adr-002: Pluggable backends
**Status:** accepted

**Rationale:** Different step types need different execution strategies.

**Decision:** Backend registry dispatches steps to claude-code, cmd, python, llm, or codex backends.

### adr-003: Governor-based storage
**Status:** accepted

**Rationale:** Artifacts, runs, and config live outside target repos.

**Decision:** All specwright state in ~/.local/local-governor/. Target repos are never polluted.

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
goal: Convert specwright to YAML as the native spec format. Read, write, scaffold, validate, and resolve .yaml specs. .md remains readable but .yaml is the default.
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
YAML as its native spec format — read, write, scaffold, validate, resolve.

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

### Scaffolder Outputs spec-v2.1 YAML

`SpecScaffolder.scaffold()` currently emits markdown with frontmatter + prose
sections. Change it to emit a spec-v2.1 YAML dict (dumped to string). The
same fields exist — they just live in structured YAML instead of markdown
sections. The scaffolder already has all the data (intent, build_delta,
constraints, expectations); it just needs to emit it as YAML.

`SpecDrafter` (LLM mode) wraps the scaffolder. Its prompt changes from
"fill in the TODO sections of this markdown" to "fill in the TODO fields
of this YAML spec". The LLM can edit YAML as well as markdown.

### `draft.py` Default Extension Changes

`spec draft` defaults to writing `{spec_id}.yaml` instead of `{spec_id}.md`.
If the epic's `spec.path` field says `.md`, honor it (backward compat). But
the computed default changes.

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

### 9. `SpecScaffolder` — `spec_scaffolder.py`

Replace `scaffold()` to emit spec-v2.1 YAML instead of markdown.

The scaffolder already has all the structured data (from `ParsedIntent`):
tier, title, owner, goal, constraints, expectations, branch, epic_id. It
just needs to assemble a spec-v2.1 dict and dump it.

```python
def scaffold(self, num_phases: int = 2) -> str:
    """Generate scaffolded spec as YAML (spec-v2.1 format)."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    branch = self.intent.branch or f"feat/{self.intent.id}"

    spec = {
        "artifact_id": "",  # filled by registrar on registration
        "name": self.intent.id,
        "version": "0.1.0",
        "kind": "spec",
        "title": self.intent.title,
        "epic_artifact_id": "",  # filled by registrar
        "tier": self.intent.tier or "B",
        "owner": self.intent.owner or "TODO",
        "goal": self.intent.goal,
        "objective": "TODO: describe the objective",
        "key_decisions": [],
        "phases": [
            {
                "phase_number": i,
                "title": "TODO",
                "objective": "TODO",
                "files_to_touch": [],
                "notes": "",
                "verification": [],
            }
            for i in range(1, num_phases + 1)
        ],
        "acceptance_criteria": [
            {"text": c, "status": "pending"}
            for c in (self.intent.expectations or ["TODO"])
        ],
        "constraints": self.intent.constraints or ["TODO"],
        "dependencies": [],
        "labels": [],
        "repo": {
            "name": self.repo_path.name,
            "url": str(self.repo_path),
            "working_branch": branch,
        },
        "created": now,
        "updated": now,
        "metadata": {},
    }
    return yaml.dump(spec, default_flow_style=False,
                     allow_unicode=True, sort_keys=False)
```

The old markdown rendering methods (`_render_frontmatter`,
`_render_header`, `_render_objective`, `_render_phase`, etc.) become dead
code. Delete them.

### 10. `SpecDrafter` — `spec_drafter.py`

Update the prompt in `_build_prompt()` (~line 111). Change from:

> "You have a scaffolded spec that needs to be completed..."
> "...output the complete filled-in spec markdown."

To:

> "You have a scaffolded spec in YAML (spec-v2.1 format)..."
> "...output the complete filled-in spec YAML."

The LLM fills in TODO fields in the YAML instead of markdown sections.

### 11. `draft.py` — Default Extension

**Default output path** (~line 106):
```python
# Before:
    output_path = epic_dir / "specs" / f"{spec_entry.id}.md"
# After:
    output_path = epic_dir / "specs" / f"{spec_entry.id}.yaml"
```

If `spec_entry.path` is set, it's used as-is (may be `.md` for old epics).

### 12. `epic.py` — Default Spec Path in Refs

**Default path in spec refs** (~lines 254, 410):
```python
# Before:
    path=s.get("path", f"specs/{s['id']}.md"),
# After:
    path=s.get("path", f"specs/{s['id']}.yaml"),
```

### 13. `epic_validator.py` — Default Spec Path Lookup

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

### 14. LLM Prompt Templates — `epic_drafter.py`, `spec_entry_drafter.py`

Both files contain YAML templates shown to the LLM when drafting epics or
spec entries. The templates include `path: specs/<spec-id>.md` — the LLM
copies this pattern into its output, so new epics/specs would get `.md`
default paths.

**`epic_drafter.py`** (~line 142):
```python
# Before:
      path: specs/<spec-id>.md
# After:
      path: specs/<spec-id>.yaml
```

**`spec_entry_drafter.py`** (~line 181):
```python
# Before:
    path: specs/<spec-id>.md
# After:
    path: specs/<spec-id>.yaml
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
- `refine.py` — `help=` at ~L21

These are non-functional but should be updated for a clean grep.

## Files to Touch

| File | Action |
|------|--------|
| `src/spec/cli/exec_commands.py` | modify — add `_load_spec`, update `_get_spec_path`, `compile_command`, `run_command`, `validate_command` |
| `src/spec/cli/governance.py` | modify — update `validate_spec` to accept `.yaml` |
| `src/spec/cli/draft.py` | modify — default output extension `.md` → `.yaml` |
| `src/spec/cli/epic.py` | modify — default spec path extension `.md` → `.yaml` |
| `src/spec/governor/resolver.py` | modify — `.yaml`/`.yml` in `resolve_spec`, `list_specs_in_epic` |
| `src/spec/governor/reader.py` | modify — `.yaml`/`.yml` in `_resolve_spec_path`, `list_specs`, `get_spec_path` |
| `src/spec/governor/writer.py` | modify — `write_spec` emits `.yaml`, `delete_spec` checks both |
| `src/spec/governance/spec_scaffolder.py` | modify — `scaffold()` emits spec-v2.1 YAML, delete old markdown renderers |
| `src/spec/governance/spec_drafter.py` | modify — update LLM prompt for YAML output |
| `src/spec/governance/epic_validator.py` | modify — default spec path `.md` → `.yaml`, accept both extensions |
| `src/spec/governance/epic_drafter.py` | modify — LLM template `path:` default `.md` → `.yaml` |
| `src/spec/governance/spec_entry_drafter.py` | modify — LLM template `path:` default `.md` → `.yaml` |
| `src/spec/cli/refine.py` | modify — help text `.md` → `.yaml / .md` |

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
- [ ] `spec draft` outputs `.yaml` by default
- [ ] `SpecScaffolder.scaffold()` returns spec-v2.1 YAML string
- [ ] `spec epic create` / `spec epic add-spec` default path is `.yaml`
- [ ] No changes to LLM backends — they still receive `spec_md` string
- [ ] `epic_validator._check_spec_files()` defaults to `.yaml`, falls back to `.md`
- [ ] `epic_drafter` LLM template uses `.yaml` default path
- [ ] `spec_entry_drafter` LLM template uses `.yaml` default path
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
