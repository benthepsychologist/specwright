# Artifact Storage Migration Guide

## Summary

Starting with v0.6, specwright stores run artifacts under local-governor by default:

```
~/.local/local-governor/projects/<project_slug>/runs/
```

This change prevents polluting target repositories with `.specwright/` directories.

## Legacy `.specwright/` Runs Are Not Supported

**Important:** Legacy run directories under `.specwright/runs/` are not automatically migrated or supported by the new executor. The executor will not read from or write to `.specwright/` directories.

If you have existing runs under `.specwright/runs/`, they remain readable as static files but cannot be used with `--verify-only` or other executor commands that expect runs under the new location.

## One-Way Copy Procedure (Optional)

If you need to preserve historical runs for reference, you can manually copy them to local-governor:

```bash
# 1. Ensure project_slug is set in .specwright.yaml
grep project_slug .specwright.yaml

# 2. Create the runs directory under local-governor
mkdir -p ~/.local/local-governor/projects/<project_slug>/runs

# 3. Copy existing runs (one-way, no sync)
cp -r .specwright/runs/* ~/.local/local-governor/projects/<project_slug>/runs/

# 4. Optionally remove the old directory
rm -rf .specwright/runs
```

**Note:** This is a one-way copy. The old `.specwright/runs/` directory should be deleted or ignored after migration to avoid confusion.

## Verification

After migration, you can verify the new location is being used:

```bash
# Run any step with plan-only to see the artifact path
spec run --step 1 --plan-only

# Output will show:
# ✓ Generated SEP: ~/.local/local-governor/projects/<project_slug>/runs/<aip_id>/<timestamp>/step-001/sep.yaml
```

## Configuration

The artifact root is determined by:

1. `project_slug` in `.specwright.yaml` (required for v0.6)
2. `governor.path` in `.specwright.yaml` (optional, defaults to `~/.local/local-governor`)

Example v0.6 configuration:

```yaml
version: '0.6'
project_slug: my-project
governor:
  path: ~/.local/local-governor
```

## Tests and CI

For tests and CI environments, the artifact root can be overridden programmatically:

```python
from spec.executor.artifacts import get_artifact_root

# Use a custom path for tests
runs_dir = get_artifact_root(override_path=tmp_path / "runs")
```

This ensures tests don't write to the real local-governor directory.
