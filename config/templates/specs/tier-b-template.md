---
tier: {{ tier }}
title: {{ title }}
owner: {{ owner }}
goal: {{ goal }}
labels: []
---

# {{ title }}

## Objective

> {{ goal }}

## Acceptance Criteria

- [ ] TODO: Define measurable outcome 1
- [ ] TODO: Define measurable outcome 2
- [ ] 85% test coverage achieved
- [ ] Defect density ≤ 1.5

## Context

### Background

> Describe the current state and why this work is needed now.

### Constraints

> Add specific constraints here

## Plan

### Step 1: Planning [G0: Plan Approval]

**Prompt:**

Produce detailed work breakdown and file-touch map:
- WBS with task breakdown
- Files to be modified
- Test coverage plan

**Outputs:**

- `artifacts/plan/wbs.md`
- `artifacts/plan/file-touch-map.yaml`

### Step 2: Prompt Engineering [G0: Plan Approval]

**Prompt:**

Generate domain-specific prompts with moderate guardrails:
- Implementation prompts
- Test strategy
- Code review checklist

**Outputs:**

- `artifacts/prompts/coding-prompts.md`
- `artifacts/prompts/test-strategy.md`

### Step 3: Implementation [G1: Code Readiness]

**Prompt:**

Implement feature per plan with standard best practices.

**Commands:**

```bash
ruff check .
mypy .
pytest -q
```

**Outputs:**

- `artifacts/code/release-notes.md`
- `artifacts/code/runbook.md`

### Step 4: Testing [G2: Pre-Release]

**Prompt:**

Run full test suite and generate coverage report.

**Commands:**

```bash
pytest --cov=src --cov-report=xml
```

**Outputs:**

- `artifacts/test/coverage.xml`
- `artifacts/test/test-results.md`

### Step 5: Governance [G3: Deployment Approval]

**Prompt:**

Document decisions and verify compliance.

**Outputs:**

- `artifacts/governance/decision-log.md`
- `artifacts/governance/compliance-checklist.md`

## Models & Tools

**Tools:** bash, pytest, ruff, mypy

**Models:** (to be filled by defaults)

## Repository

**Branch:** `{{ branch }}`

**Merge Strategy:** squash
