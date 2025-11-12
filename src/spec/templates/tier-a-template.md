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

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Architecture Review
- [ ] Work breakdown structure is complete and detailed
- [ ] File touch map identifies all affected components
- [ ] Dependencies and interfaces clearly defined
- [ ] No circular dependencies introduced
- [ ] Architecture patterns follow best practices
- [ ] Scalability implications assessed

##### Security & Privacy Assessment
- [ ] Threat model analysis complete
- [ ] Attack surface identified and documented
- [ ] Privacy impact assessment initiated
- [ ] Data classification reviewed
- [ ] Security controls identified
- [ ] No PHI/PII exposure risks

##### Risk Assessment
- [ ] Comprehensive risk analysis completed
- [ ] High-severity risks have mitigation strategies
- [ ] Rollback plan documented and validated
- [ ] Business continuity considered
- [ ] Incident response plan ready

##### Resource Planning
- [ ] Effort estimates are detailed and realistic
- [ ] Timeline includes security review checkpoints
- [ ] Required skills and expertise identified
- [ ] Stakeholder review scheduled

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

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Code Quality & Standards
- [ ] Code follows project style guide and conventions
- [ ] No linting errors (ruff passes clean)
- [ ] Type hints complete and accurate (mypy passes)
- [ ] No hardcoded secrets, API keys, or credentials
- [ ] Code complexity is within acceptable limits
- [ ] Proper error handling and logging implemented

##### Security
- [ ] No security vulnerabilities (bandit scan clean)
- [ ] Input validation implemented for all entry points
- [ ] Authentication and authorization checks in place
- [ ] Sensitive data is encrypted at rest and in transit
- [ ] SQL injection / XSS / CSRF protections verified
- [ ] Security best practices followed (OWASP Top 10)

##### Testing
- [ ] Unit tests written for all new code paths
- [ ] Quick test suite passes (pytest -q)
- [ ] Edge cases and error conditions covered
- [ ] Test coverage meets 90% minimum threshold
- [ ] Security test cases included
- [ ] Integration test stubs created

##### Documentation
- [ ] Release notes comprehensive and accurate
- [ ] Runbook includes all operational procedures
- [ ] Rollback plan tested and validated
- [ ] API changes fully documented
- [ ] Breaking changes clearly highlighted
- [ ] Code comments explain complex logic

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

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Test Coverage & Quality
- [ ] Full test suite passes without failures
- [ ] Test coverage ≥ 90% achieved
- [ ] No flaky or intermittent test failures
- [ ] Performance tests pass all benchmarks
- [ ] Load testing completed successfully
- [ ] Memory leak testing shows no issues

##### Integration & E2E Testing
- [ ] End-to-end workflows tested and validated
- [ ] All integration points verified
- [ ] Error handling and edge cases tested
- [ ] Rollback procedure tested successfully
- [ ] Database migrations tested (up and down)
- [ ] API contract tests pass

##### Security Validation
- [ ] Security scan (bandit) shows no critical issues
- [ ] Penetration testing completed (if applicable)
- [ ] Authentication flows tested
- [ ] Authorization checks validated
- [ ] No sensitive data in logs or errors
- [ ] OWASP Top 10 vulnerabilities checked

##### Quality Metrics
- [ ] Defect density ≤ 1.0 achieved
- [ ] No critical or high-severity bugs remaining
- [ ] No high-severity security issues
- [ ] Code review feedback fully addressed
- [ ] QA sign-off obtained
- [ ] Performance meets SLA requirements

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

Generate comprehensive governance artifacts and retrospective.

**Outputs:**

- `artifacts/governance/decision-log.md`
- `artifacts/governance/privacy-impact-assessment.md`
- `artifacts/governance/iso42001-evidence-pack.md`
- `artifacts/governance/metrics-dashboard.md`
- `artifacts/governance/retrospective-report.md`
- `artifacts/governance/improvement-actions.md`

<!-- GATE_REVIEW_START -->
#### Gate Review Checklist

##### Compliance & Governance
- [ ] Decision log complete, accurate, and auditable
- [ ] Privacy impact assessment completed and approved
- [ ] ISO 42001 / regulatory requirements met
- [ ] Audit trail comprehensive and tamper-proof
- [ ] Data classification verified
- [ ] Compliance evidence pack complete

##### Deployment Readiness
- [ ] Deployment plan reviewed and approved
- [ ] Rollback procedure validated and tested
- [ ] Monitoring and alerting fully configured
- [ ] Runbook complete with all procedures
- [ ] Incident response plan updated
- [ ] On-call rotation and escalation defined
- [ ] Database backups verified

##### Security Final Review
- [ ] Security review completed by CISO/security team
- [ ] Threat model validation completed
- [ ] Security controls tested and operational
- [ ] Access controls properly configured
- [ ] Encryption keys properly managed
- [ ] Security documentation up to date

##### Stakeholder & Executive Approval
- [ ] Technical lead final approval obtained
- [ ] Product owner final approval obtained
- [ ] Security team sign-off received
- [ ] Compliance officer approval (if required)
- [ ] Executive sponsor approval obtained
- [ ] Change Advisory Board approval (if required)

##### Metrics & Retrospective
- [ ] All quality metrics meet targets
- [ ] Lessons learned documented
- [ ] Improvement actions identified
- [ ] Metrics dashboard operational
- [ ] Success criteria defined for monitoring

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

**Tools:** bash, pytest, ruff, mypy, bandit

**Models:** (to be filled by defaults)

## Repository

**Branch:** `{{ branch }}`

**Merge Strategy:** squash

**Block Paths:** `src/core/**`, `infra/**`
