---
version: "0.1"
tier: A
title: Local Governance Major Revision
owner: benthepsychologist
goal: Transform Specwright from repo-local spec management to a centralized governance-driven compiler and execution coordinator
labels: [architecture, breaking-change, v0.4.0]
project_slug: specwright
spec_version: 1.0.0
created: 2025-12-22T21:26:59.576438+00:00
updated: 2025-12-22T21:26:59.576438+00:00
orchestrator_contract: "standard"
repo:
  working_branch: "feat/local-governance-major-revision"
---

# Local Governance Major Revision

## Objective

> Transform Specwright from a repo-local spec management tool to a governance-driven compiler and execution coordinator. Under this model, `local-governor` becomes the sole authority for development intent (specs, AIPs, roadmaps, policies), while repos become pure execution targets. Specwright bridges the two—compiling intent into executable plans and materializing them temporarily for execution.

## Acceptance Criteria

- [ ] `spec create` writes specs to `local-governor` by default, not repo-local `.specwright/specs/`
- [ ] `.specwright.yaml` becomes a minimal pointer file (governor path + autogov flags only)
- [ ] AIP compilation reads specs from `local-governor` and validates against governance
- [ ] Execution materializes AIPs temporarily in repos (`.specwright/tmp/`, gitignored)
- [ ] Structured error records are generated and stored in `local-governor/errors/`
- [ ] Provenance snapshots optionally written back to `local-governor/runs/`
- [ ] Repos no longer contain canonical specs or AIPs
- [ ] Multi-repo specs with explicit `targets` declaration work correctly
- [ ] 85% test coverage achieved
- [ ] Defect density ≤ 1.5
- [ ] Migration path documented for existing repo-local specs

## Context

### Background

Specwright currently operates with an implicit model where specs are created "near" repos, repos can advance semi-independently, and governance is advisory rather than authoritative. This causes architectural friction:

1. **Invisible work**: Specs scattered across repos make it hard to answer "what work exists?"
2. **Repo-level drift**: Repos can diverge from governance without detection
3. **Cross-repo awkwardness**: Multi-repo specs have unclear ownership
4. **Silent failures**: Execution errors are lost in CLI output, not tracked structurally

The new model establishes a clear four-layer architecture:

- **L0 (local-governor)**: Intent, governance, specs, AIPs, errors, provenance
- **L1 (Specwright)**: Compilation, validation, orchestration, materialization
- **L2 (Repos)**: Code, tests, tooling—execution only
- **L3 (Ephemeral)**: Temp materialized AIPs, execution logs, agent transcripts

### Constraints

- **Breaking change**: This is a MAJOR version bump (v0.4.0)
- **Migration required**: Existing repo-local specs must be migrated to local-governor
- **local-governor dependency**: Requires local-governor to be installed/configured
- **Backward compatibility**: Provide `--legacy-mode` flag for transition period
- **No repo sovereignty**: Repos MUST NOT contain canonical specs or AIPs

## Plan

### Step 1: Architecture Planning [G0: Plan Approval]

**Prompt:**

Produce detailed work breakdown and file-touch map for the four-layer architecture:

1. **L0 Integration**: How Specwright reads from local-governor
   - Spec location: `~/.local/local-governor/specs/`
   - AIP location: `~/.local/local-governor/aips/`
   - Error records: `~/.local/local-governor/errors/`
   - Provenance: `~/.local/local-governor/runs/`

2. **L1 Compilation Changes**:
   - `spec create` → writes to local-governor
   - `spec compile` → reads from local-governor, validates governance
   - New `spec materialize` command for execution prep

3. **L2 Repo Changes**:
   - `.specwright.yaml` minimal pointer format
   - `.specwright/tmp/` for materialized execution
   - Remove `.specwright/specs/` and `.specwright/aips/`

4. **L3 Ephemeral Handling**:
   - Gitignore patterns for execution residue
   - Cleanup strategies

**Outputs:**

- `artifacts/plan/wbs.md`
- `artifacts/plan/file-touch-map.yaml`
- `artifacts/plan/architecture-layers.md`
- `artifacts/plan/migration-strategy.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Architecture Review
- [ ] Four-layer architecture (L0-L3) clearly defined
- [ ] Data flow between layers documented
- [ ] local-governor integration points identified
- [ ] No circular dependencies introduced
- [ ] Rollback strategy for failed migrations

##### Risk Assessment
- [ ] Breaking change impact assessed
- [ ] Migration complexity estimated
- [ ] Fallback mechanisms defined
- [ ] User communication plan drafted

##### Resource Planning
- [ ] Effort estimates are reasonable (estimate: 3-4 days)
- [ ] Timeline is achievable
- [ ] Required skills/tools identified

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 2: Schema and Data Model Updates [G0: Plan Approval]

**Prompt:**

Design and document the updated data models:

1. **Minimal `.specwright.yaml` schema**:
```yaml
governor:
  path: ~/.local/local-governor  # or absolute path
autogov:
  enabled: true
  source: org  # or "patterns"
```

2. **Multi-repo spec `targets` schema**:
```yaml
targets:
  - repo: storacle
    scope: src/storacle/**
  - repo: injester
    scope: src/injester/**
```

3. **Structured error record schema** (for `local-governor/errors/`):
```yaml
error_id: ERR-2025-12-22-001
spec_ref: specs/feature-x.md
aip_ref: aips/AIP-2025-12-22-001.yaml
repo: specwright
step: 3
error_type: FAIL_VERIFY
message: "pytest failed with 3 errors"
timestamp: 2025-12-22T21:30:00Z
context:
  command: "pytest -q"
  exit_code: 1
  output_snippet: "..."
```

4. **Provenance snapshot schema** (for `local-governor/runs/`):
```yaml
run_id: RUN-2025-12-22-001
aip_ref: aips/AIP-2025-12-22-001.yaml
started_at: 2025-12-22T21:30:00Z
completed_at: 2025-12-22T21:45:00Z
status: COMPLETED
steps_executed: [1, 2, 3]
governance_snapshot:
  commit: abc123
  policies: [...]
```

**Outputs:**

- `artifacts/schemas/specwright-config.schema.json`
- `artifacts/schemas/error-record.schema.json`
- `artifacts/schemas/provenance.schema.json`
- `artifacts/prompts/test-strategy.md`

### Step 3: Core Infrastructure Implementation [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Implement the core infrastructure changes:

1. **Governor Integration Module** (`src/spec/governor/`):
   - `locator.py`: Find and validate local-governor path
   - `reader.py`: Read specs/AIPs from local-governor
   - `writer.py`: Write specs/AIPs/errors to local-governor
   - `materializer.py`: Materialize AIPs into repo workspaces

2. **Updated Config Loading** (`src/spec/core/config.py`):
   - Parse minimal `.specwright.yaml` format
   - Resolve governor path (env var → config → default)
   - Validate governor exists and is accessible

3. **Error Records** (`src/spec/governor/errors.py`):
   - `ErrorRecord` dataclass
   - Write structured errors to `local-governor/errors/`
   - Index by spec, AIP, repo, date

4. **Provenance Tracking** (`src/spec/governor/provenance.py`):
   - `ProvenanceSnapshot` dataclass
   - Capture governance state at execution time
   - Write to `local-governor/runs/`

**Allowed Paths:**

- `src/spec/**`
- `tests/**`
- `docs/**`
- `config/schemas/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`
- `infra/**`

**Verification Commands:**

```bash
ruff check src/spec/governor/
mypy src/spec/governor/
pytest tests/governor/ -q
```

**Outputs:**

- `artifacts/code/governor-module.md` (implementation notes)
- `artifacts/code/runbook.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality
- [ ] Code follows project style guide
- [ ] No linting errors (ruff check passes)
- [ ] Type hints complete (mypy passes)
- [ ] No hardcoded secrets or credentials
- [ ] Error handling is comprehensive

##### Testing
- [ ] Unit tests for all new modules
- [ ] Governor path resolution tested
- [ ] Error record serialization tested
- [ ] Provenance snapshot tested
- [ ] Mock local-governor for tests

##### Documentation
- [ ] Docstrings for all public functions
- [ ] Module-level documentation
- [ ] Usage examples in docstrings

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 4: CLI Command Updates [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Update CLI commands for the new governance model:

1. **`spec init`** changes:
   - Generate minimal `.specwright.yaml` (governor pointer only)
   - Prompt for governor path if not found
   - Create `.specwright/tmp/` (gitignored)
   - Remove `.specwright/specs` and `.specwright/aips` creation
   - Add `--legacy-mode` for backward compatibility

2. **`spec create`** changes:
   - Default output to `local-governor/specs/<slug>.md`
   - Support `--targets` flag for multi-repo specs
   - Remove repo-local spec creation (unless `--legacy-mode`)
   - Validate governance before writing

3. **`spec compile`** changes:
   - Read spec from local-governor
   - Write AIP to `local-governor/aips/`
   - Embed governance snapshot in AIP
   - Validate targets exist

4. **New `spec materialize` command**:
   - Read AIP from local-governor
   - Copy to repo's `.specwright/tmp/`
   - Resolve target repo workspace
   - Return materialization path

5. **`spec run`** changes:
   - Auto-materialize AIP before execution
   - Write errors to local-governor on failure
   - Write provenance on completion
   - Clean up materialized files after run

**Allowed Paths:**

- `src/spec/cli/**`
- `tests/cli/**`
- `docs/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`
- `infra/**`

**Verification Commands:**

```bash
ruff check src/spec/cli/
mypy src/spec/cli/
pytest tests/cli/ -q
```

**Outputs:**

- `artifacts/code/cli-changes.md`
- `artifacts/code/command-reference.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality
- [ ] All CLI commands updated
- [ ] Backward compatibility flags work
- [ ] Error messages are helpful
- [ ] Help text is accurate

##### Testing
- [ ] CLI integration tests pass
- [ ] Legacy mode tested
- [ ] Multi-repo targets tested
- [ ] Materialization tested

##### Documentation
- [ ] CLI help updated
- [ ] Command reference documented
- [ ] Migration guide references CLI changes

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 5: Multi-Repo Spec Support [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Implement multi-repo spec and AIP handling:

1. **Spec Target Resolution**:
   - Parse `targets` block from spec
   - Resolve repo paths (from registry or explicit paths)
   - Validate scopes against repo structure

2. **AIP Splitting**:
   - Compile single spec into multiple repo-scoped AIPs
   - Each AIP references parent spec
   - Each AIP has isolated allowed_paths

3. **Cross-Repo Execution Coordination**:
   - Execute AIPs in target order
   - Aggregate errors across repos
   - Single provenance record for multi-repo run

**Allowed Paths:**

- `src/spec/**`
- `tests/**`
- `docs/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`
- `infra/**`

**Verification Commands:**

```bash
ruff check .
mypy .
pytest tests/ -k "multi_repo or targets" -q
```

**Outputs:**

- `artifacts/code/multi-repo-impl.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality
- [ ] Target resolution handles edge cases
- [ ] AIP splitting is deterministic
- [ ] Cross-repo errors properly aggregated

##### Testing
- [ ] Multi-repo spec creation tested
- [ ] AIP splitting tested
- [ ] Cross-repo execution tested

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 6: Full Test Suite [G2: Pre-Release]

**Prompt:**

Run full test suite and generate coverage report. Focus areas:

1. **Governor module tests** (new)
2. **CLI command tests** (updated)
3. **Integration tests** (new scenarios)
4. **Migration tests** (repo-local → governor)

**Commands:**

```bash
pytest --cov=src --cov-report=xml --cov-report=term-missing
```

**Outputs:**

- `artifacts/test/coverage.xml`
- `artifacts/test/test-results.md`
- `artifacts/test/migration-test-results.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Test Coverage
- [ ] Full test suite passes
- [ ] Test coverage ≥ 85%
- [ ] No flaky tests identified
- [ ] New governor module fully tested

##### Integration Testing
- [ ] End-to-end spec creation workflow tested
- [ ] End-to-end execution workflow tested
- [ ] Error record generation tested
- [ ] Provenance tracking tested
- [ ] Legacy mode tested

##### Quality Metrics
- [ ] Defect density ≤ 1.5
- [ ] No critical bugs
- [ ] No high-severity security issues

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 7: Documentation and Migration Guide [G2: Pre-Release]

**Prompt:**

Update all documentation for the new architecture:

1. **README.md**: Update architecture diagram and data flows
2. **DEVELOPMENT.md**: New development workflow
3. **MIGRATION.md** (new): Step-by-step migration from v0.3 to v0.4
4. **docs/architecture.md** (new): Four-layer architecture deep dive
5. **CHANGELOG.md**: v0.4.0 breaking changes

**Migration Guide Topics:**
- Pre-migration checklist
- Backing up repo-local specs
- Installing/configuring local-governor
- Migrating specs: `spec migrate --from-repo`
- Updating `.specwright.yaml`
- Verifying migration
- Rollback procedure

**Outputs:**

- `artifacts/docs/migration-guide.md`
- `artifacts/docs/architecture-overview.md`

### Step 8: Release Governance [G3: Deployment Approval]

**Prompt:**

Document decisions and verify compliance for v0.4.0 release:

1. **Breaking Change Justification**: Why this architectural change is necessary
2. **Deprecation Schedule**: Legacy mode availability timeline
3. **Communication Plan**: How to notify users
4. **Rollback Plan**: If critical issues discovered post-release

**Outputs:**

- `artifacts/governance/decision-log.md`
- `artifacts/governance/compliance-checklist.md`
- `artifacts/governance/release-notes-v0.4.0.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Compliance
- [ ] Decision log complete and accurate
- [ ] Breaking change documented in CHANGELOG
- [ ] Migration guide reviewed for completeness
- [ ] Deprecation timeline communicated

##### Deployment Readiness
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Version bumped to 0.4.0
- [ ] PyPI release prepared

##### Stakeholder Approval
- [ ] Architecture review complete
- [ ] Migration path validated
- [ ] User communication drafted
- [ ] Final signoff received

#### Approval Decision
- [ ] APPROVED FOR DEPLOYMENT
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

## Models & Tools

**Tools:** bash, pytest, ruff, mypy, git, uv

**Models:** claude-sonnet-4-20250514 (for agentic steps), claude-opus-4-20250514 (for architecture review)

## Repository

**Branch:** `feat/local-governance-major-revision`

**Merge Strategy:** squash

## Appendix: Key File Changes

### Files to Create
- `src/spec/governor/__init__.py`
- `src/spec/governor/locator.py`
- `src/spec/governor/reader.py`
- `src/spec/governor/writer.py`
- `src/spec/governor/materializer.py`
- `src/spec/governor/errors.py`
- `src/spec/governor/provenance.py`
- `tests/governor/` (full test suite)
- `docs/architecture.md`
- `MIGRATION.md`

### Files to Modify
- `src/spec/cli/spec.py` (major updates to init, create, compile, run)
- `src/spec/autogov/loader.py` (integrate with governor)
- `src/spec/executor/runner.py` (materialization + error tracking)
- `src/spec/core/loader.py` (minimal config format)
- `README.md`
- `DEVELOPMENT.md`
- `CHANGELOG.md`
- `VERSION` (→ 0.4.0)

### Files to Deprecate
- `.specwright/specs/` directory pattern (repos)
- `.specwright/aips/` directory pattern (repos)
- Full `.specwright.yaml` format (→ minimal pointer)