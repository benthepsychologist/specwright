---
name: git-branching-workflow
description: Apply a safe branching model with branch naming, commit discipline, and merge/rebase flow. Use when starting implementation, preparing commits, syncing with main, and opening pull requests.
metadata:
  author: benthepsychologist
  version: "1.0"
allowed-tools: git bash
---

# Git Branching Workflow

Use this skill for repository hygiene from first change to PR creation.

## 1) Start from clean main

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
git checkout -b feat/<ticket>-<short-topic>
```

Branch naming guidelines:

- `feat/<ticket>-<topic>` for features
- `fix/<ticket>-<topic>` for fixes
- `chore/<topic>` for maintenance

## 2) Commit discipline

```bash
git --no-pager status --short
# Run repo checks required by policy
git add -p
git commit -m "feat(scope): concise user-visible change"
```

Rules:

- Keep commits atomic and reviewable.
- Avoid unrelated formatting-only churn unless requested.
- Include test or validation updates when behavior changes.

## 3) Keep branch updated

```bash
git fetch origin
git rebase origin/main
# resolve conflicts, then
git rebase --continue
```

If your team requires merge commits, replace rebase with:

```bash
git merge --no-ff origin/main
```

## 4) Prepare pull request

```bash
git push -u origin <branch-name>
```

In PR description include:

- What changed
- Why it changed
- Validation performed
- Rollback/risk notes

## Safety constraints

- Never commit secrets.
- Do not force-push shared branches without explicit approval.
- Prefer `--ff-only` pulls to avoid accidental merge noise.
