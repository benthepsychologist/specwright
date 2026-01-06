# Epics

Multi-spec implementation plans with dependency tracking and status management.

---

## Introduction

Epics are Specwright's mechanism for coordinating complex, multi-spec implementations that span multiple repositories or require ordered execution of dependent specs.

### When to Use Epics

Use epics when your implementation involves:

- **Multiple specs with dependencies**: One feature that requires several ordered implementation steps
- **Cross-repository coordination**: Changes spanning multiple target repositories
- **LLM-based checks**: Automated validation using language models
- **Audit trails**: Tracking who did what, when, and why

For single, isolated specs, the standard `spec create` / `spec compile` / `spec run` workflow is sufficient.

---

## Directory Structure

Epics are stored in the local-governor under:

```
~/.local/local-governor/epics/
└── <epic-id>/
    ├── epic.yaml           # Epic definition (schema below)
    ├── notes.md            # Epic notes and narrative
    ├── checks/             # LLM check prompt files
    │   └── *.md
    ├── reports/            # Optional: check reports (not written by specwright today)
    │   └── *.md
    └── artifacts/
        └── snapshots/      # Artifact snapshots
```

### Example Structure

```
~/.local/local-governor/epics/
├── e001-add-oauth/
│   ├── epic.yaml
│   ├── notes.md
│   ├── checks/
│   │   ├── CHECK-e001-core.md
│   │   └── CHECK-e001-security.md
│   └── reports/
└── e002-db-migration/
    ├── epic.yaml
    └── checks/
```

---

## Epic Schema

The `epic.yaml` file defines the complete epic structure.

### Full Schema Reference

```yaml
# Required metadata
version: "0.1"                    # Schema version
kind: epic                        # Always "epic"
id: e001-add-oauth                # Unique identifier (e###-slug format)
title: "Add OAuth Authentication" # Human-readable title
owner: alice                      # Owner username
created: 2025-01-15T10:30:00Z     # ISO 8601 timestamp
updated: 2025-01-15T10:30:00Z     # ISO 8601 timestamp

# Intent
intent:
  goal: "Implement OAuth2 authentication flow"  # One-line goal (required)
  narrative: |                                   # Extended description
    We need OAuth2 support to enable third-party integrations.
    This epic covers the full implementation from backend to frontend.

# Target repositories
targets:
  - id: backend                        # Target identifier
    repo_path: /workspace/backend      # Absolute path to repository
    default_branch: main               # Branch for PRs
    governor_project: myproject        # Optional: linked governor project

  - id: frontend
    repo_path: /workspace/frontend
    default_branch: main

# Spec references (the DAG)
specs:
  - id: spec-01                        # Spec identifier
    repo: backend                      # Must match a target id
    branch: feat/oauth-backend         # Working branch
    path: specs/oauth-backend.md       # Spec path relative to governor
    status: planned                    # planned | active | blocked | done | abandoned
    depends_on: []                     # List of spec IDs this depends on
    expectations:                      # Expected outcomes
      - "OAuth2 endpoints implemented"
    checks:                            # Checks to run for this spec
      - CHECK-e001-core

  - id: spec-02
    repo: frontend
    branch: feat/oauth-frontend
    path: specs/oauth-frontend.md
    status: planned
    depends_on:
      - spec-01                        # Must complete after spec-01
    expectations:
      - "Login UI with OAuth buttons"

# LLM checks
checks:
  - id: CHECK-e001-core                # Check identifier
    name: "Core Implementation Review" # Human-readable name
    scope: spec                        # spec | epic
    prompt_ref: checks/CHECK-e001-core.md  # Path to prompt file
    model: gpt-4                       # Optional: override default model
    default_spec: spec-01              # Optional: default spec for check
    response_contract:                 # Optional: expected response structure (not enforced today)
      verdicts:
        - PASS
        - FAIL
        - NEEDS_REVISION
      required_sections:
        - summary
        - findings
    inputs:                            # Input specifications
      - type: file
        path: src/auth/oauth.py
      - type: git_diff
        target: backend
        range: main..HEAD

# Current state (managed by CLI)
state:
  status: active                       # Overall epic status
  current_spec: spec-01                # Currently active spec
  history:                             # Audit trail
    - id: evt-001
      at: 2025-01-15T10:30:00Z
      event: epic.created
      actor: human
      note: "Initial epic creation"

# Runtime configuration
run_context:
  governor_root: ~/.local/local-governor
  cli_bin: spec
  cwd_policy: target_repo              # target_repo | governor | spec
  env_override:                        # Environment variables
    DEBUG: "1"

# Governance integration
governance:
  enabled: true
  source: patterns
  project: myproject
  include:
    - policies
    - patterns

# Defaults
defaults:
  model: gpt-4                         # Default LLM model for checks
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string | Yes | Schema version (currently "1.0") |
| `kind` | string | Yes | Always "epic" |
| `id` | string | Yes | Unique ID in `e###-slug` format |
| `title` | string | Yes | Human-readable title |
| `owner` | string | Yes | Owner username |
| `created` | datetime | Yes | Creation timestamp (ISO 8601) |
| `updated` | datetime | Yes | Last update timestamp |
| `intent.goal` | string | Yes | One-line goal statement |
| `intent.narrative` | string | No | Extended description |
| `targets` | array | No | Target repositories |
| `specs` | array | No | Spec references |
| `checks` | array | No | LLM check definitions |
| `state` | object | No | Current epic state (managed by CLI) |
| `run_context` | object | No | Runtime configuration |
| `governance` | object | No | Governance integration settings |
| `defaults` | object | No | Default values |

### Spec Status Values

| Status | Icon | Description |
|--------|------|-------------|
| `planned` | `○` | Not yet started |
| `active` | `→` | Currently in progress |
| `blocked` | `✗` | Blocked by dependencies or issues |
| `done` | `✓` | Completed successfully |
| `abandoned` | `⊘` | Abandoned/cancelled |

### Event Types

| Event | Description |
|-------|-------------|
| `epic.created` | Epic was created |
| `epic.updated` | Epic was updated |
| `spec.activated` | Spec was set as active |
| `spec.blocked` | Spec was blocked |
| `spec.done` | Spec was marked done |
| `spec.abandoned` | Spec was abandoned |
| `check.completed` | LLM check passed |
| `check.failed` | LLM check failed |
| `step.started` | Execution step started |
| `step.completed` | Execution step completed |
| `step.failed` | Execution step failed |

---

## CLI Commands

All epic commands are under `spec epic`.

### Create an Epic

```bash
spec epic create <title> --goal <goal> [--id <id>] [--owner <owner>]
```

**Arguments:**
- `title` (required): Epic title

**Options:**
- `--goal, -g` (required): One-line goal statement
- `--id`: Epic ID (auto-generated if not provided)
- `--owner`: Owner username (uses config default if not provided)

**Examples:**

```bash
# Create with auto-generated ID
spec epic create "Add OAuth" --goal "Implement OAuth2 authentication"

# Create with custom ID
spec epic create "Refactor DB" --id e002-db-refactor --goal "Migrate to PostgreSQL"
```

### Add a Target Repository

```bash
spec epic add-target <epic-id> --id <target-id> --repo-path <path> [options]
```

**Arguments:**
- `epic-id` (required): Epic ID

**Options:**
- `--id` (required): Target identifier
- `--repo-path` (required): Absolute path to repository
- `--branch`: Default branch (default: "main")
- `--governor-project`: Link to governor project

**Examples:**

```bash
spec epic add-target e001-auth --id myrepo --repo-path /workspace/myrepo

spec epic add-target e001-auth --id myrepo --repo-path /workspace/myrepo --branch main
```

### Add a Spec Reference

```bash
spec epic add-spec <epic-id> --id <spec-id> --repo <target> --branch <branch> --path <path> [options]
```

**Arguments:**
- `epic-id` (required): Epic ID

**Options:**
- `--id` (required): Spec identifier
- `--repo` (required): Target repo ID (must exist in targets)
- `--branch` (required): Working branch
- `--path` (required): Spec path relative to governor
- `--depends-on`: Dependency spec IDs (repeatable)
- `--expectation, -e`: Expected outcomes (repeatable)

**Examples:**

```bash
# Add first spec
spec epic add-spec e001-auth --id spec-01 --repo myrepo --branch feat/auth --path specs/auth.md

# Add dependent spec
spec epic add-spec e001-auth --id spec-02 --repo myrepo --branch feat/auth --path specs/tokens.md --depends-on spec-01
```

### Set Current Spec

```bash
spec epic set-current <epic-id> --spec <spec-id>
```

Marks the spec as active and sets it as the current working spec.

**Examples:**

```bash
spec epic set-current e001-auth --spec spec-01
```

### Mark Spec Done

```bash
spec epic mark-done <epic-id> --spec <spec-id> [--note <note>]
```

Updates the spec status to "done" and suggests the next ready spec.

**Examples:**

```bash
spec epic mark-done e001-auth --spec spec-01

spec epic mark-done e001-auth --spec spec-01 --note "OAuth flow implemented"
```

### Show Epic Status

```bash
spec epic status <epic-id>
```

Displays:
- Epic title and overall status
- Current spec indicator (→)
- DAG with status icons
- Check summary
- Recent history

**Example Output:**

```
============================================================
Epic: Add OAuth Authentication
ID: e001-auth
Owner: alice
Status: → active
Current: spec-01
============================================================

Goal: Implement OAuth2 authentication flow

Specs:
  → spec-01 [active]
  (← spec-01) ○ spec-02

Checks (1):
  - CHECK-e001-core: Core Implementation Review

Recent History:
  [evt-001] epic.created - Initial creation
  [evt-002] spec.activated (spec-01)
```

### List All Epics

```bash
spec epic list
```

Lists all epics in the governor with their titles and status.

**Example Output:**

```
Epics (2):
  - e001-auth: Add OAuth Authentication [active]
  - e002-db: Database Migration [planned]
```

### Validate an Epic

```bash
spec epic validate <epic-id>
```

Validates the epic's structure:
- All spec repo references exist in targets
- No cycles in dependency graph
- All check references exist
- Current spec is active (if set)

**Exit Codes:**
- `0`: Valid
- `3`: Validation errors

**Examples:**

```bash
spec epic validate e001-auth
```

### Run LLM Checks

```bash
spec epic check <epic-id> [--check <check-id>]
```

Executes LLM-based checks defined in the epic.

**Options:**
- `--check, -c`: Run a specific check (runs all if not specified)

**Exit Codes:**
- `0`: Success (all checks passed or no checks defined)
- `2`: Epic or check not found
- `4`: LLM config error (not enabled or invalid config)
- `5`: LLM execution error

**Examples:**

```bash
# Run all checks
spec epic check e001-auth

# Run specific check
spec epic check e001-auth --check CHECK-e001-core
```

---

## LLM Checks

Epics support LLM-based validation checks that run against the codebase.

### Configuring LLM

Specwright uses the [llm](https://llm.datasette.io/) Python package for model access. Provider authentication and model configuration are managed entirely by `llm`, not by Specwright.

**Step 1: Install the llm package and provider plugins**

```bash
# Install the llm package (included in specwright dependencies)
pip install llm

# Install provider plugins as needed
llm install llm-anthropic   # For Claude models
llm install llm-gpt4all     # For local models
# etc.
```

**Step 2: Configure API keys via the llm package**

```bash
# Set API keys using llm's key management
llm keys set openai          # Prompts for OPENAI_API_KEY
llm keys set anthropic       # Prompts for ANTHROPIC_API_KEY

# Or use environment variables directly
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-...
```

**Step 3: Verify your setup**

```bash
# List available models
llm models

# Test a model
llm -m gpt-4o "Hello, world"
```

**Step 4: Enable LLM in local-governor config**

Specwright reads only two settings from `~/.local/local-governor/config.yaml`:

```yaml
# ~/.local/local-governor/config.yaml
llm:
  enabled: true      # Required: set to true to enable LLM checks
  timeout_s: 120     # Optional: timeout for LLM calls (default: 120)
```

> **Note:** Specwright does NOT read `provider`, `api_key_env`, or model configuration from this file. Those are handled by the `llm` package. The `model` for each check is specified in the epic's check definition.

> **Response contracts:** `response_contract` is currently stored and validated at schema-load time only. Specwright does not yet enforce verdicts/sections in `spec epic check` output.

### Defining Checks in epic.yaml

```yaml
checks:
  - id: CHECK-e001-core
    name: "Core Implementation Review"
    scope: spec
    prompt_ref: checks/CHECK-e001-core.md
    model: gpt-4
```

3. **Create the prompt file:**

```markdown
<!-- checks/CHECK-e001-core.md -->
# Core Implementation Review

Review the following implementation for:
1. Security best practices
2. Error handling
3. Test coverage

## Files to Review

{{inputs}}

## Response Format

Provide your verdict as one of: PASS, FAIL, NEEDS_REVISION

### Summary
[Brief summary]

### Findings
[Detailed findings]
```

### Check Inputs

Checks can specify various input types:

```yaml
inputs:
  - type: file
    path: src/auth/oauth.py

  - type: git_diff
    target: backend
    range: main..HEAD

  - type: command
    args: ["ruff", "check", "src/"]
```

### Response Contracts

Define expected response structure for validation:

```yaml
response_contract:
  verdicts:
    - PASS
    - FAIL
    - NEEDS_REVISION
  required_sections:
    - summary
    - findings
```

---

## Workflow Walkthrough

### Step 1: Create the Epic

```bash
spec epic create "Add OAuth Authentication" \
  --goal "Implement OAuth2 flow with Google and GitHub providers"
```

Output:
```
✓ Created epic: e001-add-oauth-authentication
  Title: Add OAuth Authentication
  Path: ~/.local/local-governor/epics/e001-add-oauth-authentication

Next steps:
  1. Add targets: spec epic add-target e001-add-oauth-authentication --id myrepo --repo-path /path/to/repo
  2. Add specs: spec epic add-spec e001-add-oauth-authentication --id spec-01 --repo myrepo ...
  3. View status: spec epic status e001-add-oauth-authentication
```

### Step 2: Add Target Repositories

```bash
spec epic add-target e001-add-oauth-authentication \
  --id backend \
  --repo-path /workspace/myapp \
  --branch main
```

### Step 3: Add Specs with Dependencies

```bash
# First spec: Backend OAuth endpoints
spec epic add-spec e001-add-oauth-authentication \
  --id spec-01-backend \
  --repo backend \
  --branch feat/oauth-backend \
  --path specs/oauth-backend.md \
  --expectation "OAuth2 endpoints implemented" \
  --expectation "Token validation working"

# Second spec: Frontend OAuth UI (depends on backend)
spec epic add-spec e001-add-oauth-authentication \
  --id spec-02-frontend \
  --repo backend \
  --branch feat/oauth-frontend \
  --path specs/oauth-frontend.md \
  --depends-on spec-01-backend \
  --expectation "Login UI with OAuth buttons"
```

### Step 4: Check Status

```bash
spec epic status e001-add-oauth-authentication
```

### Step 5: Set Current Spec and Execute

```bash
# Set first spec as current
spec epic set-current e001-add-oauth-authentication --spec spec-01-backend

# Work on the spec (compile, run, etc.)
spec compile ~/.local/local-governor/epics/e001-add-oauth-authentication/specs/oauth-backend.md
spec run
```

### Step 6: Mark Done and Move to Next

```bash
# Mark first spec done
spec epic mark-done e001-add-oauth-authentication \
  --spec spec-01-backend \
  --note "Backend OAuth endpoints complete"

# Set next spec as current
spec epic set-current e001-add-oauth-authentication --spec spec-02-frontend
```

### Step 7: Run Checks

```bash
# Validate structure
spec epic validate e001-add-oauth-authentication

# Run LLM checks
spec epic check e001-add-oauth-authentication
```

### Step 8: Complete the Epic

Continue marking specs done until all are complete. The epic status will reflect overall progress.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Epic or check not found |
| 3 | Validation errors |
| 4 | LLM config error |
| 5 | LLM execution error |

---

## Related Documentation

- [README.md](../README.md) - Main project documentation
- [Integration Guide](integration.md) - Integration patterns
- [Executor Guide](EXECUTOR.md) - Step execution details
