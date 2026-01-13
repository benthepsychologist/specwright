# Spec-Run Agent Executor

The executor orchestrates agentic step execution with strict scope enforcement, verification gating, and full audit trails.

## Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         spec run --step N                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  EXTRACT PHASE                                                          │
│  ├── Load AIP, build StepContract                                       │
│  ├── Check worktree clean (or --allow-dirty)                            │
│  ├── Record baseline SHA                                                │
│  └── Write input bundle: contract.yaml, prompt.md, repo_state.json      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                     ┌──────────────┴──────────────┐
                     │       --dry-run?            │
                     └──────────────┬──────────────┘
                            yes │         │ no
                                ▼         ▼
                          EXIT(0)    ENTER LOOP
                                          │
┌─────────────────────────────────────────┴───────────────────────────────┐
│  ITERATION LOOP (max_iterations times)                                  │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  1. RESET to baseline (git reset --hard)                        │    │
│  │  2. INVOKE adapter → patch.diff, agent.json, cmdlog.txt         │    │
│  │  3. APPLY patch (git apply)                                     │    │
│  │  4. SCOPE CHECK                                                 │    │
│  │     └── touched = git diff --name-only ∪ git ls-files --others  │    │
│  │     └── filter out artifact root (runs/)                        │    │
│  │     └── check against allowed_paths, forbidden_paths            │    │
│  │  5. VERIFY (run verification_commands)                          │    │
│  │  6. DECIDE termination                                          │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  Termination:                                                           │
│  ├── PASS                    → exit loop, finalize                      │
│  ├── FAIL_SCOPE              → exit immediately (no retry)              │
│  ├── FAIL_PATCH_APPLY        → exit immediately (no retry)              │
│  ├── FAIL_ADAPTER_PROTOCOL   → exit immediately (no retry)              │
│  ├── ESCALATE_NEEDS_HUMAN    → exit immediately (no retry)              │
│  └── FAIL_VERIFY_RETRYABLE   → retry (or exhaust iterations)            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  GATE PHASE                                                             │
│  ├── Write result.json (machine-readable outcome)                       │
│  ├── Write gate.md (human-readable summary)                             │
│  └── Exit with code: 0=PASS, 1=FAIL_*, 2=ESCALATE_*                     │
└─────────────────────────────────────────────────────────────────────────┘
```

## Invariants

These are non-negotiable. Violations are bugs.

### 1. Runner Owns the Working Tree

The runner exclusively controls `git reset`, `git apply`, and working tree state. The agent **must not**:
- Run `git commit`, `git push`, `git checkout`
- Modify `.git/` directly
- Run destructive commands (`rm -rf`, etc.)

### 2. Agent Outputs Patch Only

The agent produces exactly three files:
- `patch.diff` — unified diff to apply
- `agent.json` — status, needs_human flag, notes
- `cmdlog.txt` — commands executed (for audit/tripwire)

The agent does **not** apply the patch. The runner applies it.

### 3. Scope Check Before Verify

Scope enforcement happens **after** patch apply, **before** verification:
```
apply patch → scope check → verify
```
If scope fails, verification never runs. No retry on scope violations.

### 4. Baseline Reset Every Iteration

At the **start** of each iteration (including iter-0), the runner resets to baseline:
```
git reset --hard <baseline_sha>
```
This ensures each iteration starts from a clean, known state.

### 5. Touched Files = Tracked Diff ∪ Untracked, Minus Artifact Root

```python
touched = git_diff_name_only(baseline) ∪ git_ls_files_others()
touched = touched - artifact_root_prefix  # exact configured path
```

- **Tracked diff**: Files modified/deleted since baseline
- **Untracked**: New files created by patch (not in index)
- **Artifact exclusion**: Uses exact `runs_dir` path, not glob pattern

This prevents:
- Agents bypassing scope by "adding" files (untracked detection)
- False positives from executor artifacts (exact prefix exclusion)

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

## Troubleshooting by Termination Reason

**FAIL_SCOPE** — Check `step_summary.yaml` scope section:
- Look at `scope.violations[].file_path` to see what was touched
- Compare against `input/contract.yaml` `allowed_paths`
- Agent likely created/modified a file outside scope

**FAIL_PATCH_APPLY** — Check `patch.diff`:
- Malformed diff syntax (missing headers, bad line counts)
- Patch conflicts with current file state
- Try `git apply --check patch.diff` manually

**FAIL_VERIFY_RETRYABLE** — Check `step_summary.yaml` verification section:
- See which command failed
- Check error output in the summary
- Ran `max_iterations` times without passing

**FAIL_ADAPTER_PROTOCOL** — Check adapter output in the run directory:
- Agent ran forbidden command (rm -rf, git commit, pip install)
- Missing required output files (patch.diff, agent.json)
- Check error message in `result.json`

**ESCALATE_NEEDS_HUMAN** — Check agent output:
- Agent set `needs_human: true`
- Read `notes` field for what's blocking
- Human decision required before retry

**FAIL_DIRTY_WORKTREE** — Run `git status`:
- Uncommitted changes present at step start
- Either commit/stash changes or use `--allow-dirty`

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
