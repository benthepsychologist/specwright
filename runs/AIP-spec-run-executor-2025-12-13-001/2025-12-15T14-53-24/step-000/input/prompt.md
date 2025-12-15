# Step: unknown

## Objective
Design and document the core data structures:
1. **StepContract** - Machine-readable contract per step
   - Define YAML schema
   - Document derivation rules (with fixed allowed_paths logic)
   - Define defaults
2. **Codex output schema**
   - `codex_output.schema.json` for `--output-schema`
3. **Agent IO schemas**
   - `repo_state.json` schema
   - `failure_context.json` schema
   - `agent.json` schema
4. **TerminationReason enum**

## Scope Constraints

### Allowed Paths
- `artifacts/**`
- `src/**`
- `tests/**`

### Forbidden Paths
- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`

## Verification Commands

Your changes will be verified by running:

```bash
ruff check .
```
```bash
mypy .
```
```bash
pytest
```

## Output Requirements

Your final output MUST be valid JSON matching the provided schema.
`patch_diff` MUST be a unified diff against the current baseline.
