---
name: specwright-spec-authoring
description: Author specwright-compatible specs with complete frontmatter, bounded scope, deterministic test plans, and acceptance criteria that map directly to deliverables.
metadata:
  author: benthepsychologist
  version: "1.0"
allowed-tools: bash rg
---

# Specwright Spec Authoring

Use this skill when creating or revising a spec consumed by the Specwright execution flow.

## Required frontmatter

Every spec starts with fully populated YAML frontmatter:

```yaml
---
id: t000-00-example
tier: B
title: "Outcome-focused title"
owner: your-handle
goal: Clear one-sentence objective
validated: true
version: "2.0"
labels:
  - specwright
epic: t000-epic
repo:
  name: project-name
  url: /workspace/project
  working_branch: feat/example
depends_on: []
created: "2026-03-20T00:00:00Z"
updated: "2026-03-20T00:00:00Z"
---
```

## Body structure

Include these sections in order:

1. Objective
2. Problem
3. Deliverables
4. Test Plan
5. Acceptance Criteria
6. Boundary

## Writing rules

- Use explicit paths, commands, and artifacts.
- Avoid ambiguous terms like "handle", "improve", or "cleanup" without measurable criteria.
- Keep in-scope and out-of-scope clearly separated.

## Quick structural check

```bash
rg -n "^## (Objective|Problem|Deliverables|Test Plan|Acceptance Criteria|Boundary)" <spec-file>.md
```

If any required section is missing, revise before handoff.
