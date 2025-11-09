---
version: "0.1"
tier: {{ tier }}
title: {{ title }}
owner: {{ owner }}
goal: {{ goal }}
labels: []
orchestrator_contract: "standard"
repo:
  working_branch: "{{ branch }}"
---

# {{ title }}

## Objective

> {{ goal }}

## Acceptance Criteria

- [ ] TODO: Define measurable outcome 1
- [ ] TODO: Define measurable outcome 2
- [ ] Security tests passing
- [ ] Privacy impact assessment complete
- [ ] 90% test coverage achieved
- [ ] Defect density ≤ 1.0

## Context

### Background

> Describe the current state and why this work is needed now.

### Constraints

- No PHI exposure
- Threat model reviewed
- Add specific constraints here

## Plan

### Step 1: Planning [G0: Plan Approval]

**Prompt:**

Produce comprehensive plan including:
- Detailed WBS with security/compliance checkpoints
- Threat model analysis
- Risk assessment
- Metrics targets (coverage, defect density)

**Outputs:**

- `artifacts/plan/wbs.md`
- `artifacts/plan/threat-model.md`
- `artifacts/plan/risk-assessment.md`
- `artifacts/plan/metrics-targets.md`

### Step 2: Prompt Engineering [G0: Plan Approval]

**Prompt:**

Create comprehensive prompts with security, privacy, and safety guardrails:
- Implementation prompts for each component
- Test strategy and coverage plan
- Security checklist and review criteria

**Outputs:**

- `artifacts/prompts/coding-prompts.md`
- `artifacts/prompts/safety-constraints.md`
- `artifacts/prompts/test-strategy.md`
- `artifacts/prompts/security-checklist.md`

### Step 3: Implementation [G1: Code Readiness]

**Prompt:**

Implement with security best practices and strict validation.

**Commands:**

```bash
ruff .
mypy .
bandit -r src/
pytest -q
```

**Outputs:**

- `artifacts/code/release-notes.md`
- `artifacts/code/runbook.md`
- `artifacts/code/rollback-plan.md`

### Step 4: Testing [G2: Pre-Release]

**Prompt:**

Run full test suite with security validation and QA sign-off.

**Commands:**

```bash
pytest --cov=src --cov-report=xml --cov-report=html
bandit -r src/ -f json -o artifacts/test/bandit.json
```

**Outputs:**

- `artifacts/test/coverage.xml`
- `artifacts/test/test-results.md`
- `artifacts/test/defect-density-report.md`
- `artifacts/test/bandit.json`

### Step 5: Governance [G3: Deployment Approval]

**Prompt:**

Generate comprehensive governance artifacts and retrospective.

**Outputs:**

- `artifacts/governance/decision-log.md`
- `artifacts/governance/privacy-impact-assessment.md`
- `artifacts/governance/iso42001-evidence-pack.md`
- `artifacts/governance/metrics-dashboard.md`
- `artifacts/governance/retrospective-report.md`
- `artifacts/governance/improvement-actions.md`

## Models & Tools

**Tools:** bash, pytest, ruff, mypy, bandit

**Models:** (to be filled by defaults)

## Repository

**Branch:** `{{ branch }}`

**Merge Strategy:** squash

**Block Paths:** `src/core/**`, `infra/**`
