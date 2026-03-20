---
name: registrar-bootstrap
description: Bootstrap registrar-managed environments using registrar CLI, verify provisioned cloud resources, and capture reproducible evidence for dev, stage, and prod setup.
metadata:
  author: benthepsychologist
  version: "1.0"
allowed-tools: bash registrar gcloud bq
---

# Registrar Bootstrap

Use this skill when provisioning or repairing environments managed by registrar.

## Bootstrap command

```bash
registrar bootstrap --env <dev|stage|prod> --project <project-id>
```

## Workflow

1. Verify active account and selected project.
2. Run bootstrap for the target env.
3. Validate required artifacts.
4. Capture output for audit trail.

```bash
gcloud config get-value account
gcloud config get-value project
registrar bootstrap --env dev --project "$PROJECT_ID"
```

## Post-checks

```bash
bq ls --project_id "$PROJECT_ID"
gcloud secrets list --project "$PROJECT_ID" --format="value(name)"
```

See `references/env-configs.md` for expected baseline per environment.
