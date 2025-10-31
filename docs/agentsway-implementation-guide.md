# Agentsway Implementation Guide with Risk-Based Extensions

**Version:** 0.2  
**Status:** Draft  
**Last Updated:** 2025

---

## Purpose

This guide extends the **Agentsway** methodology (October 2024) with risk-based workflow tiering and governance patterns suitable for production AI agent-based development. It builds on Atlassian's **HULA** (Human-in-the-Loop for Agentic Coding) framework for the inner coding loop while providing end-to-end lifecycle guidance.

**Key Extensions:**
- Risk-based tiering (A/B/C) for workflow rigor
- Multi-currency budget support and tracking
- Hierarchical defaults system for AIPs
- Policy pack composition for reusable governance
- Domain-specific overlays (healthcare, finance, etc.)

---

## Core Principles

### 1. Separation of Concerns
Following Agentsway's architecture:
- **Planning**: Decompose work, estimate effort, define acceptance criteria
- **Prompting**: Optimize prompts for agent execution
- **Coding**: Implement solutions via agents or human developers
- **Testing**: Validate functionality and quality
- **Fine-tuning**: Improve agent performance over time
- **Governance**: Ensure compliance, audit trails, and risk management

### 2. Human-in-the-Loop
Critical decision points require human oversight:
- Requirements approval (high-risk work)
- Design reviews (before major implementation)
- Quality gates (before deployment)
- Rollback decisions (incident response)

### 3. Transparency & Auditability
All agent actions must be:
- Logged with full context
- Traceable to requirements
- Reviewable by humans
- Replayable for debugging

### 4. Risk-Proportional Rigor
Different work requires different oversight:
- **Tier A** (High-risk): Full lifecycle, multiple gates, compliance frameworks
- **Tier B** (Moderate): Balanced workflow with key checkpoints
- **Tier C** (Low-risk): Fast-lane, minimal overhead

---

## Risk-Based Workflow Tiers

### Tier A: High-Risk
**Use for:** Security-critical features, regulatory compliance work, production infrastructure changes, AI model deployments

**Lifecycle Scope:** `planning → prompting → coding → testing → fine_tuning → governance`

**Required Gates:**
1. Requirements review (human)
2. Design approval (tech lead)
3. Implementation review (QA lead)
4. Deployment approval (human)

**Metrics:**
- Test coverage ≥ 90%
- Override rate ≤ 5%
- Time to green ≤ 12 hours
- Defect density ≤ 1.0 per KLOC

**Governance:**
- Audit trail required
- Compliance frameworks: ISO42001, NIST AI RMF
- Rollback plan mandatory
- Approval chain documented

**Budget:**
- Default: 2M tokens / $200 USD
- Adjustable per AIP

---

### Tier B: Moderate-Risk
**Use for:** New features, refactoring, API changes, moderate infrastructure updates

**Lifecycle Scope:** `planning → coding → testing`

**Required Gates:**
1. Plan review (senior developer)
2. Implementation checkpoint (optional)

**Metrics:**
- Test coverage ≥ 80%
- Override rate ≤ 10%
- Time to green ≤ 24 hours
- Defect density ≤ 2.0 per KLOC

**Governance:**
- Audit trail required
- Basic approval workflow
- Rollback plan optional

**Budget:**
- Default: 1M tokens / $100 USD
- Adjustable per AIP

---

### Tier C: Low-Risk
**Use for:** Bug fixes, documentation, minor improvements, experimental prototypes

**Lifecycle Scope:** `coding → testing`

**Required Gates:** None (optional checkpoints)

**Metrics:**
- Test coverage ≥ 70%
- Time to green ≤ 48 hours

**Governance:**
- No audit trail required
- No approval required
- Fast-lane execution

**Budget:**
- Default: 500K tokens / $50 USD
- Adjustable per AIP

---

## Domain-Specific Overlays

Some domains require additional considerations beyond base risk tiers.

### Healthcare (PHI/HIPAA)
**Applies to:** Work touching Protected Health Information

**Additional Requirements:**
- Data classification tagging
- PHI containment verification
- HIPAA compliance audit
- Encryption at rest and in transit

**Forced Minimums:**
- Tier B or higher (no Tier C for PHI)
- Coverage ≥ 95% for PHI-handling code
- Zero tolerance for overrides on PHI paths

### Finance (PCI-DSS, SOC2)
**Applies to:** Payment processing, financial data

**Additional Requirements:**
- PCI-DSS compliance checks
- SOC2 controls validation
- Transaction integrity tests
- Fraud detection coverage

### AI/ML Model Development
**Applies to:** Training, deploying, or modifying AI models

**Additional Requirements:**
- Model card documentation
- Bias/fairness evaluation
- Explainability requirements
- Performance benchmarking

---

## Agentic Implementation Plan (AIP) Format

AIPs are executable specifications in YAML format, validated against a JSON schema.

### Minimal AIP (Tier C)
```yaml
metadata:
  title: "Fix typo in README"
  description: "Correct spelling error on line 42"
  owner: "alice"
  created: "2024-01-15T10:00:00Z"
  risk: "low"

budget:
  max_tokens: 50000
  max_usd: 5.00
  currency: "USD"
```

All other fields are inherited from `tier-C.yaml` defaults.

### Full AIP (Tier A)
```yaml
metadata:
  title: "Implement OAuth2 authentication"
  description: "Add OAuth2 provider integration with PKCE flow"
  owner: "security-team"
  created: "2024-01-15T10:00:00Z"
  risk: "high"
  
version: "0.1"
schema_url: "https://specplatform.org/schemas/aip-v0.1.schema.json"

lifecycle_scope: ["planning", "prompting", "coding", "testing", "governance"]

budget:
  max_tokens: 2500000
  max_usd: 250.00
  currency: "USD"

policy_packs: ["security.paths"]

plan:
  - type: "human"
    name: "Security Requirements Review"
    description: "Security team reviews OAuth2 requirements and threat model"
    output_artifacts: ["requirements.md", "threat-model.md"]
  
  - type: "agent"
    name: "Technical Design"
    description: "Agent creates detailed OAuth2 integration design"
    models: ["claude-3-5-sonnet"]
    output_artifacts: ["design.md", "sequence-diagram.svg"]
  
  - type: "gate"
    approver: "security-lead"
    description: "Security lead approves design before implementation"
  
  - type: "agent"
    name: "Implementation"
    description: "Agent implements OAuth2 flow with PKCE"
    models: ["claude-3-5-sonnet"]
    tools: ["pytest", "ruff", "mypy"]
    output_artifacts: ["src/auth/**/*.py", "tests/auth/**/*.py"]
  
  - type: "agent"
    name: "Security Testing"
    description: "Agent runs security test suite and penetration tests"
    models: ["gpt-4"]
    tools: ["pytest", "bandit", "safety"]
    output_artifacts: ["security-report.md", "coverage.xml"]
  
  - type: "gate"
    approver: "security-lead"
    description: "Security lead reviews test results and approves for production"
  
  - type: "human"
    name: "Production Deployment"
    description: "Deploy to production with phased rollout and monitoring"
    output_artifacts: ["deployment-log.txt", "rollback-plan.md"]

metrics:
  targets:
    coverage_min: 0.95
    override_rate_max: 0.0
    time_to_green_hours: 8
    defect_density_max: 0.5
  emit: ["coverage", "override_rate", "time_to_green", "defect_density", "security_score"]

governance:
  privacy:
    touches_phi: false
    touches_pii: true
    notes: "Handles user email and profile data"
  
  data_classification:
    confidentiality: "confidential"
    contains_phi: false
    
  approval_required: true
  compliance_frameworks: ["ISO42001", "SOC2"]
  audit_trail: true
  rollback_plan: true
```

---

## Hierarchical Defaults System

AIPs can be sparse because they inherit from layered defaults.

### Precedence (Highest → Lowest)
1. **AIP file** (highest precedence)
2. **Tier-specific defaults** (`tier-{A,B,C}.yaml`)
3. **Project defaults** (`project.yaml`)
4. **Policy packs** (`policies/*.yaml`)

### Example: Sparse AIP + Defaults
**User writes (sparse):**
```yaml
metadata:
  title: "Add user search API"
  owner: "alice"
  risk: "moderate"
  
budget:
  max_usd: 120.00
```

**System merges with:**
- `tier-B.yaml` (since risk = moderate)
- `project.yaml` (base settings)

**Result (fully resolved):**
- Complete `plan` with 4 steps from Tier B
- `lifecycle_scope: [planning, coding, testing]`
- `metrics.targets.coverage_min: 0.80`
- `repo.url` from project.yaml
- All orchestration contract details

---

## Orchestrator Contract

The orchestrator (Spec engine) manages AIP execution with a state machine.

### States
- `pending`: AIP created, not yet started
- `running`: Currently executing a step
- `awaiting_human`: Paused for human action (gate or human step)
- `failed`: Step failed, intervention required
- `succeeded`: All steps completed successfully
- `rolled_back`: Rolled back due to failure

### Events
- `run_step`: Execute next step
- `await_gate`: Pause for gate approval
- `approve`: Approve gate, continue
- `reject`: Reject gate, stop or rollback
- `retry`: Retry failed step
- `escalate`: Escalate to human intervention
- `complete`: Mark AIP as succeeded

### Logging
All state transitions logged in JSONL format:
```json
{"timestamp": "2024-01-15T10:05:23Z", "event": "run_step", "step": 1, "type": "agent"}
{"timestamp": "2024-01-15T10:12:45Z", "event": "await_gate", "step": 2, "approver": "tech-lead"}
{"timestamp": "2024-01-15T10:15:00Z", "event": "approve", "approver_id": "alice"}
```

### State Persistence
Current state saved to `artifacts/state.json`:
```json
{
  "aip_id": "abc123",
  "current_state": "running",
  "current_step": 3,
  "started_at": "2024-01-15T10:00:00Z",
  "steps_completed": [1, 2],
  "steps_failed": []
}
```

---

## Implementation Maturity Levels

Organizations can adopt this methodology incrementally.

### Level 1: Foundation
**Focus:** Basic AIP creation and manual execution

**Capabilities:**
- Create AIPs from templates
- Validate against schema
- Manual step execution
- Basic logging

**Tools:**
- `spec create` - scaffold AIPs
- `spec validate` - check schemas
- Manual tracking in spreadsheets

### Level 2: Automated Inner Loop
**Focus:** Agent-driven coding with HULA patterns

**Capabilities:**
- Automated agent execution for coding steps
- PR-based workflows
- Continuous testing
- Coverage tracking

**Tools:**
- GitHub Actions integration
- Agent orchestration for coding steps
- Automated test execution

### Level 3: Full Lifecycle Automation
**Focus:** End-to-end orchestration with gates

**Capabilities:**
- Automated planning and prompting
- Human-in-the-loop gates
- Multi-step workflows
- State machine orchestration
- Budget tracking

**Tools:**
- Full orchestrator engine
- Notification system (Slack, email)
- Dashboard for AIP monitoring

### Level 4: Continuous Improvement
**Focus:** Fine-tuning and optimization

**Capabilities:**
- Agent performance analytics
- Prompt optimization
- Cost optimization
- Defect prediction
- Risk scoring

**Tools:**
- ML-based analytics
- A/B testing for prompts
- Anomaly detection

---

## Governance & Compliance

### Audit Trail Requirements

**Tier A & B:**
- All agent prompts logged
- All outputs captured
- Human approvals recorded
- State transitions tracked
- Budget consumption logged

**Tier C:**
- Optional logging

### Compliance Frameworks

**ISO/IEC 42001:2023 (AI Management System):**
- Risk assessment and mitigation
- AI system lifecycle management
- Stakeholder engagement
- Continuous monitoring

**NIST AI RMF 1.0 (AI 100-1):**
- Govern: Policies and oversight
- Map: Context and risks
- Measure: Performance and impacts
- Manage: Incidents and improvements

### Rollback Procedures

**Tier A:**
- Rollback plan required before deployment
- Automated rollback triggers defined
- Post-rollback validation steps
- Incident report template

**Tier B:**
- Rollback plan optional but recommended

**Tier C:**
- No rollback plan required

---

## Metrics & KPIs

### Coverage Metrics
- **Test Coverage:** % of code covered by tests
- **Branch Coverage:** % of branches covered
- **Path Coverage:** % of execution paths covered

### Quality Metrics
- **Defect Density:** Defects per 1000 lines of code
- **Override Rate:** % of agent suggestions overridden by humans
- **Time to Green:** Hours from start to passing tests

### Cost Metrics
- **Token Consumption:** Tokens used vs. budget
- **USD Spent:** Actual cost vs. budget
- **Cost per Feature:** Average cost per completed AIP

### Process Metrics
- **Gate Approval Time:** Time spent awaiting approvals
- **Plan vs. Actual:** Variance in estimated vs. actual effort
- **Rollback Frequency:** # of rollbacks per deployment

---

## Summary

This guide provides a practical, standards-aligned approach to human-agent collaboration in software development. By extending Agentsway with risk-based tiering and building on HULA's inner loop patterns, teams can:

1. **Scale AI agent usage** across different risk profiles
2. **Maintain governance** without stifling innovation
3. **Incrementally adopt** at their own pace
4. **Align with standards** (ISO42001, NIST AI RMF)
5. **Optimize costs** through hierarchical defaults and budgets

The Agentic Implementation Plan (AIP) format serves as an executable contract between humans and agents, ensuring transparency, auditability, and continuous improvement.

---

**References:**
- Agentsway Methodology (October 2024)
- HULA: Human-in-the-Loop for Agentic Coding (Atlassian, November 2024)
- ISO/IEC 42001:2023 - AI Management System
- NIST AI Risk Management Framework 1.0 (AI 100-1)
