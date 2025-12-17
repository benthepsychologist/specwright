---
tier: C
title: Claude Code Integration Acceptance Test
owner: system
goal: Verify Claude Code slash commands work end-to-end
---

# Claude Code Integration Acceptance Test

## Objective

Validate that all four Claude Code slash commands (`/spec-run`, `/spec-status`, `/spec-next`, `/spec-pause`) function correctly and provide the expected user experience.

## Acceptance Criteria

- [ ] `/spec-run` loads AIP and executes steps sequentially
- [ ] `/spec-status` displays current AIP progress accurately
- [ ] `/spec-next` resumes from last completed step
- [ ] `/spec-pause` checkpoints progress correctly
- [ ] Audit trail captures all execution events
- [ ] Gate approvals are triggered and logged

## Context

### Background

We've built Claude Code integration via slash commands in `.claude/commands/`. These commands bridge AI-assisted execution with Specwright's governance framework. We need to verify they work in practice before relying on them for production workflows.

### Constraints

- Must test in actual Claude Code environment (not just unit tests)
- Should use a simple Tier C spec to minimize approval overhead
- Must verify audit trail integrity

## Plan

### Step 1: Create Test Spec [G0: Plan Approval - AUTO]

**Role:** planning

**Prompt:**

Create a minimal Tier C test spec with 3 simple steps:
1. Planning step (create a simple markdown file)
2. Implementation step (create a simple Python script)
3. Testing step (run the script)

Save as `specs/test-claude-integration.md`

**Commands:**

```bash
spec create --tier C --title "Test Claude Integration" --owner "system" --goal "Validate slash commands"
```

**Outputs:**

- `specs/test-claude-integration.md`

#### Gate Review: G0 (Auto-approved for Tier C)

### Step 2: Compile and Validate [G1: Code Readiness - AUTO]

**Role:** compilation

**Prompt:**

Compile the test spec to YAML and validate it against the schema.

**Commands:**

```bash
spec compile specs/test-claude-integration.md
spec validate specs/test-claude-integration.compiled.yaml
```

**Outputs:**

- `specs/test-claude-integration.compiled.yaml`

#### Gate Review: G1 (Auto-approved for Tier C)

### Step 3: Test /spec-status [G3: Deployment Approval - AUTO]

**Role:** testing

**Prompt:**

Run `/spec-status` in Claude Code and verify it shows:
- AIP ID
- Title
- Tier
- Goal
- List of steps
- Current progress (no steps completed yet)

**Expected Output:**

```
╔════════════════════════════════════════════════════════════
║ CURRENT AIP STATUS
╠════════════════════════════════════════════════════════════
║ AIP ID: [generated ID]
║ Title: Test Claude Integration
║ Tier: C
║
║ STEPS:
║  1. [ ] [Step 1 description] ← NEXT
║  2. [ ] [Step 2 description]
║  3. [ ] [Step 3 description]
║
║ GATES: None approved yet
╚════════════════════════════════════════════════════════════
```

#### Gate Review: G3 (Auto-approved for Tier C)

### Step 4: Test /spec-run Execution [G2: Pre-Release]

**Role:** testing

**Prompt:**

Run `/spec-run` in Claude Code and verify:
1. It loads the AIP correctly
2. It displays step 1 details
3. It executes step 1 (creates the markdown file)
4. It triggers gate review (even if auto-approved for Tier C)
5. It proceeds to step 2
6. It continues through all steps

Check audit trail after execution:
```bash
cat .aip_artifacts/execution_history.jsonl | grep "execution_started"
```

**Expected Behavior:**

- All steps execute successfully
- Audit trail contains `execution_started` event
- Generated artifacts exist

#### Gate Review: G2

**Checklist:**

- [ ] `/spec-run` loaded AIP successfully
- [ ] Step execution produced expected outputs
- [ ] Audit trail logged execution_started
- [ ] No errors during execution

### Step 5: Test /spec-pause and /spec-next [G4: Post-Implementation - AUTO]

**Role:** testing

**Prompt:**

Test pause/resume workflow:

1. Create another simple test spec
2. Run `/spec-run` and execute step 1
3. Run `/spec-pause` to checkpoint
4. Verify pause event is logged
5. Run `/spec-next` to resume
6. Verify execution continues from step 2

Check audit trail for pause/resume events.

**Expected Behavior:**

- `/spec-pause` creates checkpoint
- `/spec-next` resumes from correct step
- Audit trail shows pause event (if implemented)

#### Gate Review: G4 (Auto-approved for Tier C)

### Step 6: Verify Audit Trail Integrity [G4: Post-Implementation - AUTO]

**Role:** governance

**Prompt:**

Verify the audit trail captured all key events:

```bash
cat .aip_artifacts/execution_history.jsonl | jq .
spec gate-list
```

**Expected Events:**

- `spec_compiled`
- `execution_started`
- (Optional) `execution_completed`

**Expected Gate Approvals:**

- All Tier C gates should show as auto-approved

#### Gate Review: G4 (Auto-approved for Tier C)

## Models & Tools

**Model:** Claude Sonnet 4.5

**Tools:** Bash, file operations

## Repository

**Branch:** `main`

**Merge Strategy:** Direct commit (Tier C, low risk)

## Metrics

**Estimated Duration:** 30 minutes

**Success Criteria:**
- All 4 slash commands work as documented
- Audit trail is complete and accurate
- No errors or crashes during execution
