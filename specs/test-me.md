---
tier: C
title: Test Me
owner: ben@mensiomentalhealth.com

goal: test spec
labels: []
---

# Test Me

## Objective

> test spec

## Acceptance Criteria

- [ ] CI green (lint + unit)
- [ ] No protected paths modified
- [ ] 70% test coverage achieved

## Context

### Background

> Describe the current state and why this work is needed now.

### Constraints

- No edits under protected paths (`src/core/**`, `infra/**`)

## Plan

### Step 1: Planning [G0: Plan Approval]

**Prompt:**

Outline minimal file-touch set and quick test plan.
Produce a one-paragraph plan and list of files to touch (<= 5).

**Outputs:**

- `artifacts/plan/plan-01.md`

### Step 2: Prompt Engineering [G0: Plan Approval]

**Prompt:**

Generate basic prompts for implementation (auto-approved for Tier C).
Create simple, direct prompts for the implementation tasks.

**Outputs:**

- `artifacts/prompts/coding-prompts.md`

### Step 3: Implementation [G1: Code Readiness]

**Prompt:**

Implement small change; keep diff small and isolated.

**Commands:**

```bash
ruff check .
pytest -q
```

**Outputs:**

- `artifacts/code/quick-release-note.md`

### Step 4: Testing [G2: Pre-Release]

**Prompt:**

Run quick validation suite.

**Commands:**

```bash
pytest -q --tb=short
```

**Outputs:**

- `arti