# Spec-Run Agent Executor (v2)

The v2 executor uses a job-based architecture: `compile(JobDef, envelope) → JobInstance → execute()`. This document describes the execution model and artifact structure.

## Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    spec run aip-1 ./my-feature.aip.yaml                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  COMPILE PHASE                                                          │
│  ├── Load JobDef template (e.g., "aip-1")                               │
│  ├── Build envelope from AIP file                                       │
│  ├── Resolve @aip.* and @run.* variable references                      │
│  └── Produce JobInstance with materialized steps                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                     ┌──────────────┴──────────────┐
                     │       --dry-run?            │
                     └──────────────┬──────────────┘
                            yes │         │ no
                                ▼         ▼
                          EXIT(0)    ENTER EXECUTION
                                          │
┌─────────────────────────────────────────┴───────────────────────────────┐
│  STEP EXECUTION (for each step in JobInstance)                          │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  1. BUILD StepManifest (step_n, backend, payload, common)       │    │
│  │  2. DISPATCH to backend (cmd, claude-code, codex, copilot, llm) │    │
│  │  3. CAPTURE results (git state, stdout/stderr, exit code)       │    │
│  │  4. RECORD StepOutcome + StepCapture                            │    │
│  │  5. CHECK continue_on_failure policy                            │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  Step Outcomes:                                                         │
│  ├── success    → continue to next step                                 │
│  ├── failed     → stop (unless continue_on_failure)                     │
│  └── skipped    → continue to next step                                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FINALIZE PHASE                                                         │
│  ├── Write RunRecord to store                                           │
│  ├── Set run status (completed, failed, partial)                        │
│  └── Exit with code: 0=completed, 1=failed, 2=partial                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Invariants

These are non-negotiable. Violations are bugs.

### 1. Executor Never Mutates Step List

The executor runs exactly what `compile_job()` produced. It does not add, remove, or reorder steps.

### 2. Git Capture After Each Step

After each step completes, the executor captures:
- Git diff from base commit
- List of changed files
- Patch file (for reproducibility)

### 3. Artifacts Stored Outside Target Repo

Run artifacts are stored under `~/.local/local-governor/runs/`, never inside the target repository.

### 4. Backend Dispatches Are Isolated

Each backend (cmd, claude-code, codex, copilot, llm) is responsible for:
- Executing its payload
- Capturing stdout/stderr
- Returning exit code and any agent-specific data

### 5. Policy Enforcement via Tool Allowlist

The `claude-code` backend uses a tool allowlist to prevent dangerous operations:
- Blocks `git push`, `git merge` by default
- Allows `git commit` only if `policy.allow_commit` is true
- Note: This is defense-in-depth, not a hard sandbox

## Artifact Storage Location

Starting with v0.6, run artifacts are stored under local-governor by default:

```
~/.local/local-governor/projects/<project_slug>/runs/
```

The `project_slug` is read from `.specwright.yaml`. This prevents polluting target repos with `.specwright/` directories.

For tests and CI, the artifact root can be overridden programmatically via `get_artifact_root(override_path=...)`.

## Artifact Directory Structure (Audit-Essential Set)

```
<artifact_root>/
└── <aip_id>/
    └── <timestamp>/
        └── step-<N>/
            ├── sep.yaml             # Step Execution Plan (canonical)
            ├── patch.diff           # Changes made (may be empty)
            ├── step_summary.yaml    # Comprehensive execution record
            ├── result.json          # Machine-readable outcome
            └── input/
                ├── sep.yaml         # SEP bundle for adapter
                ├── contract.yaml    # Step contract
                ├── prompt.md        # Agent prompt
                └── repo_state.json  # Baseline SHA, sandbox mode
```

The artifact set is intentionally minimal for auditability:
- `sep.yaml` — The Step Execution Plan used for execution
- `patch.diff` — The diff of changes made (empty if no changes)
- `step_summary.yaml` — Comprehensive summary including inputs, verification, scope, and LLM verification
- `result.json` — Machine-readable execution outcome

Note: `gate.md`, `policy_report.json`, and `verification_report.json` are no longer written as separate files. Their information is consolidated into `step_summary.yaml`.

## Exit Codes

| Code | Meaning | Termination Reasons |
|------|---------|---------------------|
| 0 | Success | `PASS` |
| 1 | Failure | `FAIL_SCOPE`, `FAIL_PATCH_APPLY`, `FAIL_VERIFY_RETRYABLE`, `FAIL_ADAPTER_PROTOCOL`, `FAIL_DIRTY_WORKTREE`, `GATE_REJECTED` |
| 2 | Escalation | `ESCALATE_NEEDS_HUMAN`, `ESCALATE_AMBIGUOUS`, `GATE_DEFERRED` |

## Termination Reasons

| Reason | Description | Retryable |
|--------|-------------|-----------|
| `PASS` | All checks passed | N/A |
| `FAIL_SCOPE` | Patch touched files outside allowed paths or in forbidden paths | No |
| `FAIL_PATCH_APPLY` | `git apply` failed (malformed patch, conflicts) | No |
| `FAIL_VERIFY_RETRYABLE` | Verification commands failed, max iterations exhausted | Yes |
| `FAIL_ADAPTER_PROTOCOL` | Agent violated protocol (forbidden command, missing output) | No |
| `FAIL_DIRTY_WORKTREE` | Working tree not clean at start (without --allow-dirty) | No |
| `ESCALATE_NEEDS_HUMAN` | Agent requested human review | No |
| `ESCALATE_AMBIGUOUS` | Contract could not be resolved | No |
| `GATE_REJECTED` | Human rejected at gate | No |
| `GATE_DEFERRED` | Human deferred decision | No |

## Troubleshooting

**Step failed with non-zero exit code**:
- Check `stdout.txt` and `stderr.txt` in the step artifacts directory
- Look at `StepOutcome.error` in the run record

**Git capture shows unexpected changes**:
- Verify `base_commit` in JobInstance matches expected state
- Check if prior steps modified files unexpectedly

**Backend dispatch error**:
- Verify backend is available (`claude` CLI for claude-code)
- Check payload format matches backend expectations
- Look at stderr for specific error messages

### Copilot Backend (Headless)

The `copilot` backend runs GitHub Copilot CLI in **non-interactive** mode.

**Payload requirements (headless):**
- Provide one of: `prompt`, `prompt_type`, or `spec_md`.
  - `prompt_type` is used for drift passes (`drift_fix`, `drift_verify`) to build a prompt dynamically.
  - If `prompt` is omitted, `spec_md` is used as the prompt by default.
- Provide `models` (optional) as a priority-ordered list, e.g. from CLI `--models`.

**Common failure mode:**
- Error like "copilot backend requires 'prompt' ..." indicates the step payload did not include `prompt`, `prompt_type`, or `spec_md`.

**Recommended CLI usage:**
```bash
spec run aip-1 ./my-spec.md --repo /path/to/repo --agent copilot --models gpt-5.3-codex
```

**JobDef note:**
- Ensure your JobDef passes `models: @payload.models` into agent steps if you want `--models` to apply to `copilot`.

## Step Summary Format

The `step_summary.yaml` consolidates execution metadata:

```yaml
aip_id: AIP-test-2024-12-15-001
step_id: step-001
step_index: 1
termination_reason: PASS
iterations: 1
dry_run: false

inputs:
  sep:
    sha256: abc123...
    outline: "Step objective summary"
  contract:
    sha256: def456...
  prompt:
    sha256: ghi789...

scope:
  passed: true
  files_checked: ["src/main.py", "src/utils.py"]
  violations: []

verification:
  passed: true
  commands_run: 2
  commands_passed: 2

patch:
  sha256: jkl012...
  stats:
    files_changed: 2
    insertions: 15
    deletions: 3

llm_verification:  # Only present if --model was used
  status: pass
  rationale: "Changes align with SEP constraints"
  model: gpt-4o
```

## Forbidden Command Policy

The adapter enforces a tripwire policy on commands in `cmdlog.txt`:

**Hard violations** (FAIL_ADAPTER_PROTOCOL):
- `rm` with dangerous flags (`-r`, `-f`, `--recursive`, `--force`)
- `git commit`, `git push`, `git checkout`, `git reset`
- Package managers (`pip install`, `npm install`, `cargo install`)
- Unusual shells (`zsh`, `fish`, `powershell`)

**Escalation violations** (ESCALATE_NEEDS_HUMAN):
- Compound shell operators (`&&`, `||`, `;`)
- Requires human review before proceeding

**Allowed**:
- Read-only commands (`ls`, `cat`, `git status`, `git diff`)
- Standard shell wrappers (`bash -c`, `sh -c` with safe inner command)

## LLM-Powered Features

The executor supports optional LLM integration for enhanced SEP generation and patch verification.

### Model Flag

Use `--model <alias>` to enable LLM features:

```bash
# Generate SEP via LLM instead of deterministic builder
spec run --step 1 --plan-only --model gpt-4o

# Execute with LLM verification after completion
spec run --step 1 --model claude-sonnet
```

Without `--model`, the executor uses the deterministic `SEPBuilder` - no LLM calls are made.

### SEP Generation

When `--model` is provided with `--plan-only`:
- Uses LLM to generate a richer SEP based on AIP context
- Falls back to deterministic builder if LLM fails
- SEP includes `provenance` field recording generator and model

```yaml
# SEP provenance (LLM-generated)
provenance:
  generator: llm
  model: gpt-4o

# SEP provenance (deterministic)
provenance:
  generator: deterministic
```

### Patch Verification

When `--model` is provided (without `--plan-only`):
- After step execution, LLM verifies patch against SEP constraints
- Results recorded in `step_summary.yaml`:

```yaml
llm_verification:
  status: pass  # pass | fail | skipped
  rationale: "Patch correctly implements the objective..."
  model: gpt-4o
```

Verification status:
- `pass`: Patch aligns with SEP constraints
- `fail`: Patch violates SEP constraints (does not fail the step)
- `skipped`: No patch to verify (empty or missing patch.diff)

### Verify-Only Mode

Re-run verification on existing artifacts without execution:

```bash
# Using local-governor path (default for v0.6)
spec run --verify-only ~/.local/local-governor/projects/myproject/runs/AIP-test/2024-01-01T00-00-00/step-001 --model gpt-4o
```

Requirements:
- `--model` is required
- Run directory must contain `sep.yaml`
- `patch.diff` is optional (verification skipped if missing/empty)

### Configuration

LLM features require configuration in `~/.local/local-governor/config.yaml`:

```yaml
llm:
  enabled: true
  timeout_s: 120  # optional, defaults to 120
```

Prompts are configurable via `~/.local/local-governor/prompts.yaml`:

```yaml
sep_generation: |
  Your custom SEP generation prompt...
  Variables: {aip_context}, {step_index}, {contract_text}

patch_verification: |
  Your custom verification prompt...
  Variables: {sep_yaml}, {patch_content}
```
