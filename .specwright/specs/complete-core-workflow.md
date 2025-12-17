---
tier: C
title: Complete core Specwright workflow
owner: benthepsychologist
goal: Implement missing CLI commands to enable full Markdown-first workflow
labels: [core, cli, workflow]
---

# Complete core Specwright workflow

## Objective

> Implement the complete Markdown-first workflow: spec init (config), spec create (default MD), spec compile (MD→YAML), spec validate (check YAML), spec run (execute). Currently create generates YAML directly; change it to generate MD by default with optional --yaml flag.

## Acceptance Criteria

### Functional Requirements
- [ ] CI green (lint + unit tests + integration tests)
- [ ] `spec init` creates `.specwright.yaml` config with sensible defaults
- [ ] `spec config` displays current effective configuration with discovery path
- [ ] `spec create` generates Markdown by default in `specs/` directory
- [ ] `spec create --yaml` generates YAML directly in `aips/` directory (legacy mode)
- [ ] `spec compile` converts MD→YAML using existing compiler code
- [ ] `spec validate` validates compiled YAML against schema
- [ ] `spec run` executes validated YAML in guided mode
- [ ] Config auto-discovery walks up directory tree to find `.specwright.yaml`
- [ ] All commands gracefully fall back to defaults if no config found

### Test Coverage
- [ ] Unit tests for config discovery (walk-up behavior)
- [ ] Unit tests for `spec init` (file creation, defaults)
- [ ] Unit tests for `spec config` (display, discovery path)
- [ ] Unit tests for `spec create` (MD output, Jinja2 rendering)
- [ ] Unit tests for `spec create --yaml` (legacy YAML output)
- [ ] Unit tests for `spec compile` (wrapper around compiler)
- [ ] Integration test: Full workflow (init → create → compile → validate → run)
- [ ] Integration test: Nested directory usage (config discovery)
- [ ] Integration test: No config fallback behavior

### Quality Gates
- [ ] Ruff lint passes with no errors
- [ ] Mypy type checking passes
- [ ] Test coverage ≥ 70% for new code
- [ ] No changes to protected paths (`src/spec/compiler/`, `src/spec/core/`)
- [ ] Total diff ≤ 250 lines (Tier C constraint)
- [ ] Backward compatible: existing `spec validate` and `spec run` still work

### Documentation
- [ ] README.md updated with new workflow examples
- [ ] DEVELOPMENT.md dogfooding examples updated
- [ ] Each command has clear `--help` text with examples
- [ ] `.specwright.yaml` schema documented in help text

## Context

### Background

Specwright claims to be "Markdown-first" but the current CLI workflow is broken:
- `spec create` generates YAML directly instead of Markdown
- No `spec compile` command to convert MD→YAML
- No `spec init` to set up repo-aware configuration
- Commands assume config files exist in `./config/` (only works from specwright repo)

The promised workflow from README.md should be:
```bash
spec create --tier B --title "Feature" --owner alice --goal "Do thing"
# Edit specs/feature.md (created by default)
spec compile specs/feature.md
spec validate aips/feature.yaml
spec run aips/feature.yaml
```

Or for power users who want YAML directly:
```bash
spec create --tier B --title "Feature" --owner alice --goal "Do thing" --yaml
# Edit aips/feature.yaml directly
spec validate aips/feature.yaml
spec run aips/feature.yaml
```

But currently only the YAML workflow exists. We need MD-first as default.

### Constraints

- Keep changes small and focused (Tier C)
- No changes to `src/spec/compiler/` or `src/spec/core/` (those already exist and work)
- Focus on CLI commands and config discovery only
- Must maintain backward compatibility with existing YAML files

## Plan

### Step 1: Planning [G0: Plan Approval]

**Prompt:**

Analyze the existing codebase to understand:
1. What compiler/parser code already exists that we can reuse
2. Current CLI structure in `src/spec/cli/spec.py`
3. Template system in `config/templates/`
4. What's the minimal set of files to touch

Produce a one-paragraph plan and list of files to modify (<= 6 files).

**Outputs:**

- `artifacts/plan/plan-01.md`

### Step 2: Prompt Engineering [G0: Plan Approval]

**Prompt:**

Create implementation prompts for each command:
1. `spec init` - Create `.specwright.yaml` with sensible defaults
2. `spec config` - Read/display/update config
3. Config discovery - Walk up directory tree to find `.specwright.yaml`
4. Update `spec create` - Default to MD output, add `--yaml` flag for direct YAML generation
5. `spec compile` - MD→YAML using existing compiler code

**Outputs:**

- `artifacts/prompts/coding-prompts.md`

### Step 3: Implementation [G1: Code Readiness]

**Prompt:**

Implement the CLI commands in `src/spec/cli/spec.py`:

1. Add config loader that walks up directory tree to find `.specwright.yaml`
2. Add `spec init` command to create config file
3. Add `spec config` command to display/update config
4. Update `spec create` to generate MD by default, add `--yaml` flag for direct YAML
5. Add `spec compile` command that converts MD→YAML using existing compiler code

Keep each command simple and focused. Total diff should be < 250 lines.

**Commands:**

```bash
ruff check src/
pytest -q tests/
```

**Outputs:**

- `artifacts/code/implementation-notes.md`

### Step 4: Testing [G2: Pre-Release]

**Prompt:**

Write comprehensive tests covering all new functionality:

#### Unit Tests (`tests/cli/test_cli_workflow.py`):

1. **Test config discovery**:
   - Creates nested temp dir structure
   - Places `.specwright.yaml` at various levels
   - Verifies walk-up finds correct config
   - Tests fallback when no config exists

2. **Test `spec init`**:
   - Creates `.specwright.yaml` with defaults
   - Verifies YAML structure and required keys
   - Tests overwrite prevention
   - Tests `--force` flag for overwrite

3. **Test `spec config`**:
   - Displays effective config correctly
   - Shows discovery path
   - Tests in various directory locations

4. **Test `spec create` (MD mode)**:
   - Generates MD file in `specs/` directory
   - Renders Jinja2 variables correctly
   - Creates proper frontmatter
   - Slugifies title properly

5. **Test `spec create --yaml`**:
   - Generates YAML in `aips/` directory (legacy)
   - Maintains backward compatibility
   - Matches previous output format

6. **Test `spec compile`**:
   - Calls underlying compiler correctly
   - Passes flags properly
   - Handles errors gracefully

#### Integration Tests (`tests/integration/test_full_workflow.py`):

1. **Full workflow test**:
   ```bash
   # Setup
   cd /tmp/test-project
   spec init

   # Create and compile
   spec create --tier C --title "Test Feature" --owner alice --goal "Test it"
   spec compile specs/test-feature.md

   # Validate and run
   spec validate aips/test-feature.yaml
   spec run aips/test-feature.yaml --dry-run

   # Verify all files exist and are valid
   assert specs/test-feature.md exists
   assert aips/test-feature.yaml exists
   assert YAML is valid against schema
   ```

2. **Nested directory test**:
   ```bash
   # Create config at project root
   cd /tmp/test-project
   spec init

   # Work from nested subdirectory
   mkdir -p src/features
   cd src/features
   spec create --tier C --title "Nested" --owner bob --goal "Test discovery"

   # Verify config was discovered
   # Verify output went to project-root/specs/
   ```

3. **No config fallback test**:
   ```bash
   # No .specwright.yaml exists
   cd /tmp/no-config-project

   # Commands should work with sensible defaults
   spec create --tier C --title "Default" --owner charlie --goal "Use defaults"

   # Verify defaults were used
   assert specs/default.md exists  # default specs dir
   ```

#### Manual Verification:

```bash
# Test init and config
cd /tmp/manual-test
spec init
spec config

# Test create (default MD) + compile
spec create --tier C --title "Manual Test" --owner alice --goal "Manual testing"
cat specs/manual-test.md  # Verify Jinja2 rendered correctly
spec compile specs/manual-test.md
cat aips/manual-test.yaml  # Verify compilation worked

# Test create with --yaml flag
spec create --tier C --title "Direct YAML" --owner alice --goal "Direct mode" --yaml
cat aips/direct-yaml.yaml  # Verify legacy mode works

# Test validate and run
spec validate aips/manual-test.yaml
spec run aips/manual-test.yaml --dry-run
```

**Commands:**

```bash
# Run all tests with coverage
pytest tests/ -v --cov=src/spec/cli --cov-report=term-missing --cov-report=xml

# Check coverage threshold
coverage report --fail-under=70

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

**Outputs:**

- `artifacts/test/test-results.xml` (pytest output)
- `artifacts/test/coverage.xml` (coverage report)
- `artifacts/test/manual-test-results.md` (manual verification notes)

### Step 5: Governance [G4: Post-Implementation]

**Prompt:**

Update documentation:
- README.md: Ensure workflow examples match implementation
- DEVELOPMENT.md: Update dogfooding examples
- Add simple usage examples to each command's help text

**Outputs:**

- `artifacts/governance/docs-updated.md`

## Models & Tools

**Tools:** bash, pytest, ruff, typer (CLI framework)

**Models:** claude-sonnet-4-5 (for implementation)

## Repository

**Branch:** `feat/complete-core-workflow`

**Merge Strategy:** squash
