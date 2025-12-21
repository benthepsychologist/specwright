---
version: "0.1"
tier: {{ tier }}
title: {{ title }}
owner: {{ owner }}
goal: {{ goal }}
labels: []
project_slug: {{ project_slug }}
spec_version: 1.0.0
created: {{ created }}
updated: {{ updated }}
orchestrator_contract: "standard"
repo:
  working_branch: "{{ branch }}"
{% if autogov %}
autogov:
  project: {{ autogov.project }}
  source: {{ autogov.source }}
  captured_at: {{ autogov.captured_at }}
{% endif %}
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
{% if autogov %}

### Governance

> Governance Guidance from {{ autogov.project }} (v{{ autogov.version }})

{{ autogov_description }}
{% if autogov_policies %}

#### Applied Policies
{% for policy in autogov_policies %}
- **{{ policy.name }}** v{{ policy.version }}
{% endfor %}
{% endif %}
{% if autogov_patterns %}

#### Applied Patterns
{% for pattern in autogov_patterns %}
- **{{ pattern.name }}** v{{ pattern.version }}
{% endfor %}
{% endif %}
{% if autogov_decisions %}

#### Architecture Decisions
{% for decision in autogov_decisions %}
- **{{ decision.id }}**: {{ decision.title }}{% if decision.rationale %} - {{ decision.rationale }}{% endif %}

{% endfor %}
{% endif %}
{% if autogov_rules %}

#### Rules
{% for rule in autogov_rules %}
- **{{ rule.id }}** ({{ rule.severity }}): {{ rule.message }}
{% endfor %}
{% endif %}
{% if autogov_invariants %}

#### Invariants
{% for invariant in autogov_invariants %}
- {{ invariant }}
{% endfor %}
{% endif %}
{% if autogov_frozen_paths %}

#### Frozen Paths (Do Not Modify)
{% for path in autogov_frozen_paths %}
- `{{ path }}`
{% endfor %}
{% endif %}
{% endif %}

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

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Architecture Review
- [ ] Work breakdown structure is complete and accurate
- [ ] File touch map identifies all affected components
- [ ] Dependencies and interfaces are clearly defined
- [ ] No circular dependencies introduced

##### Risk Assessment
- [ ] Risk analysis completed for proposed changes
- [ ] Mitigation strategies identified
- [ ] Rollback plan documented

##### Resource Planning
- [ ] Effort estimates are reasonable
- [ ] Timeline is achievable
- [ ] Required skills/tools identified

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

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

**Role:** agentic

**Prompt:**

Implement feature per plan with standard best practices.

**Allowed Paths:**

- `src/**`
- `tests/**`
- `docs/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`
- `infra/**`

**Verification Commands:**

```bash
ruff check .
mypy .
pytest -q
```

**Outputs:**

- `artifacts/code/release-notes.md`
- `artifacts/code/runbook.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality
- [ ] Code follows project style guide
- [ ] No linting errors (ruff check passes)
- [ ] Type hints complete (mypy passes)
- [ ] No hardcoded secrets or credentials

##### Testing
- [ ] Unit tests written for new code
- [ ] Quick test suite passes (pytest -q)
- [ ] Edge cases covered
- [ ] Test coverage meets minimum threshold

##### Documentation
- [ ] Release notes updated
- [ ] Runbook documented
- [ ] API changes documented
- [ ] Breaking changes highlighted

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

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

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Test Coverage
- [ ] Full test suite passes
- [ ] Test coverage ≥ 85%
- [ ] No flaky tests identified
- [ ] Performance tests pass

##### Integration Testing
- [ ] End-to-end workflows tested
- [ ] Integration points validated
- [ ] Error handling verified
- [ ] Rollback tested

##### Quality Metrics
- [ ] Defect density ≤ 1.5
- [ ] No critical bugs
- [ ] No high-severity security issues
- [ ] Code review feedback addressed

#### Approval Decision
- [ ] APPROVED
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

### Step 5: Governance [G3: Deployment Approval]

**Prompt:**

Document decisions and verify compliance.

**Outputs:**

- `artifacts/governance/decision-log.md`
- `artifacts/governance/compliance-checklist.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Compliance
- [ ] Decision log complete and accurate
- [ ] Compliance checklist validated
- [ ] Regulatory requirements met
- [ ] Audit trail documented

##### Deployment Readiness
- [ ] Deployment plan reviewed
- [ ] Rollback procedure validated
- [ ] Monitoring and alerting configured
- [ ] Runbook complete

##### Stakeholder Approval
- [ ] Technical lead approval obtained
- [ ] Product owner approval obtained
- [ ] Security review complete
- [ ] Final signoff received

#### Approval Decision
- [ ] APPROVED FOR DEPLOYMENT
- [ ] APPROVED WITH CONDITIONS: ___
- [ ] REJECTED: ___
- [ ] DEFERRED: ___

**Approval Metadata:**
- Reviewer: ___
- Date: ___
- Rationale: ___
<!-- GATE_REVIEW_END -->

## Models & Tools

**Tools:** bash, pytest, ruff, mypy

**Models:** (to be filled by defaults)

## Repository

**Branch:** `{{ branch }}`

**Merge Strategy:** squash
