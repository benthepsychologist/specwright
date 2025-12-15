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

## Artifact Directory Structure

```
runs/
└── <aip_id>/
    └── <timestamp>/
        └── step-<N>/
            ├── result.json          # Machine-readable outcome
            ├── gate.md              # Human-readable summary
            ├── input/
            │   ├── contract.yaml    # Step contract
            │   ├── prompt.md        # Agent prompt
            │   └── repo_state.json  # Baseline SHA, sandbox mode
            └── iter-<N>/
                ├── input/           # (retry iterations only)
                │   ├── prompt.md
                │   ├── repo_state.json
                │   └── failure_context.json
                ├── output/
                │   ├── patch.diff
                │   ├── agent.json
                │   └── cmdlog.txt
                ├── policy_report.json
                └── verification_report.json
```

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

**FAIL_SCOPE** — Check `iter-N/policy_report.json`:
- Look at `violations[].file_path` to see what was touched
- Compare against `input/contract.yaml` `allowed_paths`
- Agent likely created/modified a file outside scope

**FAIL_PATCH_APPLY** — Check `iter-N/output/patch.diff`:
- Malformed diff syntax (missing headers, bad line counts)
- Patch conflicts with current file state
- Try `git apply --check patch.diff` manually

**FAIL_VERIFY_RETRYABLE** — Check `iter-N/verification_report.json`:
- See which command failed (`commands[].exit_code`)
- Check `stdout_tail`/`stderr_tail` for error output
- Ran `max_iterations` times without passing

**FAIL_ADAPTER_PROTOCOL** — Check `iter-N/output/cmdlog.txt`:
- Agent ran forbidden command (rm -rf, git commit, pip install)
- Missing required output files (patch.diff, agent.json)
- Check adapter error message in `result.json`

**ESCALATE_NEEDS_HUMAN** — Check `iter-N/output/agent.json`:
- Agent set `needs_human: true`
- Read `notes` field for what's blocking
- Human decision required before retry

**FAIL_DIRTY_WORKTREE** — Run `git status`:
- Uncommitted changes present at step start
- Either commit/stash changes or use `--allow-dirty`

## Policy Report Fields

The `policy_report.json` includes touched file breakdown:

```json
{
  "passed": false,
  "timestamp": "2024-12-15T10:30:00Z",
  "summary": {
    "total_files": 3,
    "violations_count": 1,
    "touched_tracked": 2,
    "touched_untracked": 1,
    "touched_excluded_artifacts": 5
  },
  "checked_files": ["src/main.py", "src/utils.py", "config/new.yaml"],
  "violations": [
    {
      "file_path": "config/new.yaml",
      "violation_type": "not_allowed",
      "matched_pattern": null,
      "message": "File 'config/new.yaml' is not in any allowed path pattern"
    }
  ]
}
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
