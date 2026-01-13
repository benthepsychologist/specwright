# LLM-Powered Spec Execution Workflow

This document describes the complete workflow for LLM-powered spec execution in specwright.

## Overview

The LLM workflow extends the standard executor with two key capabilities:

1. **LLM SEP Generation**: Generate richer Step Execution Plans using LLM
2. **LLM Patch Verification**: Verify patches against SEP constraints post-execution

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Human-in-the-Loop LLM Workflow                           │
└─────────────────────────────────────────────────────────────────────────────┘

         ┌───────────────┐
         │   AIP + Step  │
         └───────┬───────┘
                 │
                 ▼
    ┌────────────────────────┐
    │   --model provided?    │
    └────────────┬───────────┘
           yes   │    no
                 │     └──────────▶ Deterministic SEPBuilder
                 ▼
    ┌────────────────────────┐
    │  LLM SEP Generation    │
    │  (with fallback)       │
    └────────────┬───────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │  Human Reviews SEP     │──────▶ (optional: --skip-sep-review)
    └────────────┬───────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │   Agent Execution      │
    └────────────┬───────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │  LLM Patch Verification│
    └────────────┬───────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │  Human Reviews Gate    │
    └────────────────────────┘
```

## Workflow Phases

### Phase 1: SEP Generation

**Command:**
```bash
spec run --step 1 --plan-only --model gpt-4o
```

**What happens:**
1. AIP and step contract are loaded
2. If `--model` is provided:
   - Prompt is rendered using `~/.local/local-governor/prompts.yaml`
   - LLM generates SEP based on AIP context, step index, and contract
   - Response is parsed as YAML and validated
   - On success: SEP has `provenance.generator: llm`
   - On failure: Falls back to deterministic builder with warning
3. SEP is saved to `runs/<aip_id>/<timestamp>/step-N/sep.yaml`
4. With `--plan-only`: Execution stops here for human review

**SEP Provenance:**
```yaml
provenance:
  generator: llm      # or "deterministic"
  model: gpt-4o       # only present for LLM-generated SEPs
```

### Phase 2: Human SEP Review

After SEP generation, humans can review:
- `sep.yaml` - The full execution plan
- Files to touch, verification commands, allowed/forbidden paths
- LLM provenance (was it LLM-generated or fallback?)

To continue from reviewed SEP:
```bash
spec run --step 1 --from-sep .specwright/runs/test-aip/2024-01-01T00-00-00/step-001/sep.yaml
```

### Phase 3: Execution

**Command:**
```bash
spec run --step 1 --model gpt-4o
```

Execution proceeds through the standard lifecycle:
1. Extract phase (contract, prompt, repo state)
2. Iteration loop (agent invocation, patch apply, scope check, verify)
3. Gate phase (write artifacts)

### Phase 4: LLM Patch Verification

After execution completes (if `--model` provided):

1. Load `patch.diff` from run directory
2. If patch is missing or empty: `status: skipped`
3. Otherwise:
   - Render verification prompt with SEP and patch
   - Send to LLM
   - Parse response as JSON

**Verification Result:**
```yaml
llm_verification:
  status: pass      # pass | fail | skipped
  rationale: "..."  # LLM explanation
  model: gpt-4o
```

**Important:** LLM verification failure does NOT fail the step. It's informational for human review.

### Phase 5: Re-verification (Optional)

Re-run verification on existing artifacts without execution:

```bash
spec run --verify-only .specwright/runs/test-aip/2024-01-01T00-00-00/step-001 --model claude-sonnet
```

This:
- Loads existing SEP and patch
- Runs LLM verification
- Updates `step_summary.yaml` with new `llm_verification` block

Use cases:
- Re-verify with different model
- Verify after manual patch modifications
- Add verification to runs that didn't use `--model` originally

## Configuration

### LLM Enable

`~/.local/local-governor/config.yaml`:
```yaml
llm:
  enabled: true
  timeout_s: 120
```

### Custom Prompts

`~/.local/local-governor/prompts.yaml`:
```yaml
sep_generation: |
  You are a spec execution planner...

  ## AIP Context
  {aip_context}

  ## Step Index
  {step_index}

  ## Contract
  {contract_text}

  Generate YAML SEP with: objective, files_to_touch, verification_steps,
  allowed_paths, forbidden_paths, estimated_complexity, requires_human_review

patch_verification: |
  You are a code review assistant...

  ## SEP
  {sep_yaml}

  ## Patch
  {patch_content}

  Respond with JSON: {"status": "pass|fail", "rationale": "..."}
```

## Command Reference

| Command | Description |
|---------|-------------|
| `spec run --step N --plan-only --model X` | Generate LLM SEP, stop for review |
| `spec run --step N --model X` | Execute with LLM verification |
| `spec run --step N --from-sep FILE --model X` | Execute from SEP with verification |
| `spec run --verify-only DIR --model X` | Re-verify existing run |

## Fallback Behavior

The system is designed to be resilient:

| Scenario | Behavior |
|----------|----------|
| LLM disabled in config | Error: must enable LLM |
| LLM returns invalid YAML | Fall back to deterministic SEP |
| LLM times out | Fall back to deterministic SEP |
| LLM verification fails to parse | Record as `fail` with error |
| patch.diff missing/empty | Record as `skipped` |

## Artifacts

After LLM-powered execution, find these in the run directory:

```
step-001/
├── sep.yaml            # SEP with provenance
├── step_summary.yaml   # Includes llm_verification block
├── patch.diff          # Agent output (if any changes)
├── input/
│   ├── contract.yaml
│   └── prompt.md
└── iter-N/
    └── output/
        ├── agent.json
        └── cmdlog.txt
```

## Example Session

```bash
# 1. Generate SEP with LLM
$ spec run --step 1 --plan-only --model gpt-4o
Using LLM (gpt-4o) for SEP generation...
✓ SEP generated via LLM (gpt-4o)
  Source: LLM (gpt-4o)
✓ Generated SEP: .specwright/runs/my-aip/2024-01-01T12-00-00/step-001/sep.yaml

# 2. Review and execute
$ spec run --step 1 --from-sep .specwright/runs/my-aip/2024-01-01T12-00-00/step-001/sep.yaml --model gpt-4o
...
Running LLM patch verification...
  LLM Verification: ✓ PASS
  Rationale: Patch correctly implements the objective and stays within allowed paths.
  Model: gpt-4o

# 3. Re-verify with different model
$ spec run --verify-only .specwright/runs/my-aip/2024-01-01T12-00-00/step-001 --model claude-sonnet
Verify-Only Mode
  Run directory: .specwright/runs/my-aip/2024-01-01T12-00-00/step-001
Running LLM patch verification...
  LLM Verification: ✓ PASS
  Rationale: Changes align with the SEP contract.
  Model: claude-sonnet
✓ Updated .specwright/runs/my-aip/2024-01-01T12-00-00/step-001/step_summary.yaml
```
