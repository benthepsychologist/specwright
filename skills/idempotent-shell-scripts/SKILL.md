---
name: idempotent-shell-scripts
description: Create re-runnable infrastructure shell scripts for gcloud and bq that safely handle existing resources and produce deterministic outcomes across repeated executions.
metadata:
  author: benthepsychologist
  version: "1.0"
compatibility: Requires bash with set -euo pipefail, authenticated gcloud CLI, and bq CLI in PATH.
allowed-tools: bash gcloud bq
---

# Idempotent Shell Scripts

Use this skill for bootstrap/provision scripts that must be safe to run many times.

## Script baseline

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID is required}"
DATASET="${DATASET:-analytics}"

if ! bq --project_id "$PROJECT_ID" show --dataset "$DATASET" >/dev/null 2>&1; then
  bq --project_id "$PROJECT_ID" mk --dataset "$DATASET"
fi
```

## Patterns to apply

- Check-before-create for all resources.
- Prefer update/apply operations over delete/recreate.
- Gate destructive operations behind explicit flags.
- Validate required env vars at script start.

## Verification

```bash
bash scripts/bootstrap.sh
bash scripts/bootstrap.sh
```

Second run must succeed without duplicating resources.
