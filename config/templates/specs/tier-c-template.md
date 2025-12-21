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

> Governance Guidance (autogov, non-enforced in v1)

**Policy:** {{ autogov_policy_name }} v{{ autogov_policy_version }}
**Architecture:** {{ autogov_arch_name }} v{{ autogov_arch_version }}
{% if autogov_arch_decisions %}

#### Architecture Decisions
{% for decision in autogov_arch_decisions %}
- **{{ decision.id }}**: {{ decision.title }}{% if decision.summary %} - {{ decision.summary }}{% endif %}

{% endfor %}
{% endif %}
{% if autogov_policy_rules %}

#### Policy Rules (Error Severity)
{% for rule in autogov_policy_rules %}
- **{{ rule.id }}**: {{ rule.name }}{% if rule.description %} - {{ rule.description }}{% endif %}

{% endfor %}
{% endif %}
{% if autogov_forbidden_paths %}

#### Forbidden Paths
{% for fp in autogov_forbidden_paths %}
- `{{ fp.path }}` - {{ fp.reason }}
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
