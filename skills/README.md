# Skills Store Conventions

This directory is the repository copy of the governed skills store using the
Agent Skills standard format.

## Canonical store path

The machine-level canonical store is:

`~/.local/local-governor/skills/`

This repository copy should be mirrored there when updating skills.

## Projection

Global skills from `skills.yaml` `global:` must be projected to personal agent
discovery paths:

- `~/.claude/skills/<name>/SKILL.md`
- `~/.agents/skills/<name>/SKILL.md`

Projection is a copy (or symlink where supported). The canonical source remains
the governor store.

## Git convention for projected repo paths

Projected repo-local paths are derived content and should not be committed:

- `.claude/skills/`
- `.agents/skills/`

These are ignored by the repository `.gitignore`.
