# Step: step-001

## Objective
Create a Claude adapter for specwright that implements the AgentAdapter interface with dual-mode support.
**File: `src/spec/executor/adapters/claude.py`**
```python
# Required structure - implement these
class ClaudeAdapter(AgentAdapter):
    def __init__(self) -> None:
        self._verified = False
        self._script_available = False  # Set in verify()
    @property
    def name(self) -> str:
        return "claude"
    def verify(self) -> None:
        # 1. Check `claude` CLI exists (shutil.which)
        # 2. Check `script` exists for transcript recording
        #    - If missing, set self._script_available = False (will use PTY fallback)
        # 3. Set self._verified = True
    def execute(self, input_dir, output_dir, repo_root, timeout=600) -> None:
        # 1. Ensure verified
        # 2. Read contract.yaml from input_dir, extract adapter.mode (default: "interactive")
        # 3. Dispatch to _execute_interactive or _execute_oneshot
    def _execute_interactive(self, input_dir, output_dir, repo_root, timeout) -> None:
        # 1. Capture repo_state_before.json
        # 2. Build prompt with artifact instructions (include SPEC_OUTPUT_DIR path)
        # 3. Launch claude via script or PTY fallback
        #    - Set env: SPEC_OUTPUT_DIR=str(output_dir)
        #    - Command: claude --dangerously-skip-permissions -p "<prompt>"
        # 4. Wait for exit (timeout is advisory - just log warning if exceeded)
        # 5. Capture repo_state_after.json
        # 6. Validate artifacts exist; backfill missing ones
        # 7. Validate agent.json has required keys
    def _execute_oneshot(self, input_dir, output_dir, repo_root, timeout) -> None:
        # 1. Build prompt from prompt.md
        # 2. Run: claude --print --output-format json --json-schema <path> --dangerously-skip-permissions "<prompt>"
        # 3. Parse JSON output
        # 4. Extract and write patch.diff, agent.json, cmdlog.txt
        # 5. Hard timeout enforcement
    def _capture_repo_state(self, repo_root) -> dict:
        # Returns {"commit": "<sha>", "status": "<porcelain>"}
    def _backfill_artifacts(self, output_dir, repo_root) -> list[str]:
        # Returns list of warnings for backfilled artifacts
    def _validate_agent_json(self, agent_json_path) -> None:
        # Parse JSON, check required keys exist
        # Raise ProtocolError if invalid
```
**Prompt construction for interactive mode:**
```python
INTERACTIVE_PROMPT_TEMPLATE = '''
{task_prompt}

## Scope Constraints

### Allowed Paths
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
