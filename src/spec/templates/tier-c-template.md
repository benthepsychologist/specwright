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

- [ ] CI green (lint + unit)
- [ ] No protected paths modified
- [ ] 70% test coverage achieved

## Context

### Background

> Describe the current state and why this work is needed now.

### Constraints

- No edits under protected paths (`src/core/**`, `infra/**`)
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

### Step 1: Implementation [G1: Code Readiness]

**Role:** agentic

**Prompt:**

Implement the required changes. Keep diff small and isolated.

**Allowed Paths:**

- `src/**`
- `tests/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`

**Verification Commands:**

```bash
ruff check .
pytest -q
```

**Outputs:**

- `src/` (modified files)
- `tests/` (test files)

## Models & Tools

**Tools:** bash, pytest, ruff

**Models:** (to be filled by defaults)

## Repository

**Branch:** `{{ branch }}`

**Merge Strategy:** squash
