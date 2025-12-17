---
version: "0.1"
tier: C
title: Claude adapter for specwright
owner: benthepsychologist
goal: Add Claude Code CLI as an alternative agent adapter with interactive babysitting support
labels: []
project_slug: specwright
spec_version: 1.0.0
created: 2025-12-17T10:02:21.023311+00:00
updated: 2025-12-17T13:00:00.000000+00:00
orchestrator_contract: "standard"
repo:
  working_branch: "feat/claude-adapter-for-specwright"
---

# Claude adapter for specwright

## Objective

> Add Claude Code CLI as an alternative agent adapter supporting two execution modes: **interactive** (default, for human babysitting) and **oneshot** (non-interactive, for automation). Both modes produce identical output artifacts for runner compatibility.

## Acceptance Criteria

### Core Interface
- [ ] `ClaudeAdapter` class implements `AgentAdapter` interface (verify, execute, name property)
- [ ] Adapter registered in `_ADAPTERS` registry in `__init__.py`
- [ ] `spec run --adapter claude` selects the Claude adapter

### Dual Mode Support
- [ ] `interactive` (default): Launches Claude TUI, records full transcript
- [ ] `oneshot`: Uses `--print --output-format json` for non-interactive execution
- [ ] Mode is configured via `adapter` section in `contract.yaml`, NOT via CLI flags

### Output Artifacts (Both Modes)
- [ ] `patch.diff` - Unified diff of changes
- [ ] `agent.json` - Agent report (schema below)
- [ ] `cmdlog.txt` - Command execution log

### Interactive Mode Extras
- [ ] `claude.transcript.txt` - Full TUI transcript (via `script` or PTY fallback)
- [ ] `repo_state_before.json` - Git state before execution
- [ ] `repo_state_after.json` - Git state after execution
- [ ] Transcript recording via `script` if available; Python PTY fallback otherwise
- [ ] `SPEC_OUTPUT_DIR` env var set for Claude to know where to write artifacts
- [ ] Adapter backfills missing artifacts from git state (with protocol warning)
- [ ] Timeout is advisory (warning), not a hard kill

### Oneshot Mode Specifics
- [ ] Uses `--json-schema` for structured output enforcement
- [ ] Timeout causes hard kill + `ProtocolError`

### Validation
- [ ] `agent.json` shallow validation: JSON parse + required keys exist
- [ ] CI green (ruff + pytest)
- [ ] Tests cover adapter verification, mode selection, artifact validation, backfill logic

## Context

### Background

The current Codex adapter has reliability issues:
- Timeouts after 600s on straightforward tasks
- Goes off-task, implementing unrelated changes
- Produces changes that don't match the step objective

Claude Code CLI offers better task adherence, but the original spec assumed fully autonomous "oneshot" execution. In practice, **babysitting** (human intervention during execution) is the realistic workflow for now.

### Key Design Decision

**Default mode = `interactive` (babysit)**
**Optional mode = `oneshot` (non-interactive)**

Both modes must end with the same three core artifacts (`patch.diff`, `agent.json`, `cmdlog.txt`) so the runner stays stable.

### agent.json Schema (Minimum Contract)

```json
{
  "completion_status": "success|partial|failed",
  "confidence": 0.0,
  "files_modified": ["path/to/file.py"],
  "commands_executed": ["ruff check ."],
  "notes": "optional string"
}
```

Required fields: `completion_status`, `confidence`, `files_modified`, `commands_executed`
Optional fields: `notes`, `needs_human`

### How Interactive Mode Works

1. **Transcript Recording**:
   - Primary: `script -q -c "claude ..." /output_dir/claude.transcript.txt`
   - Fallback: Python `pty` module if `script` not available
   - `verify()` checks `script` availability; sets internal flag for fallback

2. **Environment Setup**:
   - Set `SPEC_OUTPUT_DIR={output_dir}` so Claude knows where to write
   - Pass output_dir path explicitly in prompt

3. **Artifact Production Contract**:
   - Claude is instructed to write: `patch.diff`, `cmdlog.txt`, `agent.json`
   - On exit, adapter verifies artifacts exist
   - **Backfill behavior** (for velocity during iteration):
     - If `patch.diff` missing: `git diff > patch.diff`
     - If `cmdlog.txt` missing: write stub pointing to transcript
     - If `agent.json` missing: write `{"completion_status": "partial", "confidence": 0.0, "files_modified": [...from git...], "commands_executed": [], "notes": "Backfilled by adapter"}`
   - Backfill triggers a protocol warning in logs, but does NOT raise `ProtocolError`

4. **Repo State Capture**:
   ```json
   {
     "commit": "<sha from git rev-parse HEAD>",
     "status": "<output of git status --porcelain>"
   }
   ```
   Written to `repo_state_before.json` and `repo_state_after.json`

5. **Timeout Behavior**:
   - Timeout is **advisory only** in interactive mode
   - If timeout reached: log warning, do NOT kill process
   - Rationale: human is babysitting, they'll exit when ready

### How Oneshot Mode Works

1. **Execution**:
   ```bash
   claude --print --output-format json --json-schema <schema_path> --dangerously-skip-permissions "<prompt>"
   ```

2. **Schema Enforcement**: Use `--json-schema` pointing to output schema file

3. **Artifact Extraction**: Parse JSON response, write `patch.diff`, `agent.json`, `cmdlog.txt`

4. **Timeout Behavior**: Hard kill on timeout, raise `ProtocolError`

5. **No transcript** (or empty file for consistency)

### Mode Selection via contract.yaml

The adapter reads mode from the `adapter` section in `contract.yaml`:

```yaml
# contract.yaml structure (relevant section)
adapter:
  name: claude
  mode: interactive   # or "oneshot"
  transcript: true    # only relevant for interactive
```

Default if `adapter` section missing: `mode: interactive`, `transcript: true`

This keeps the runner/CLI untouched.

### Existing Architecture

**AgentAdapter ABC** (`src/spec/executor/adapters/base.py`):
```python
class AgentAdapter(ABC):
    @abstractmethod
    def verify(self) -> None:
        """Raises ToolNotFoundError or ProtocolError"""

    @abstractmethod
    def execute(
        self,
        input_dir: Path,
        output_dir: Path,
        repo_root: Path,
        timeout: int = 600,
    ) -> None:
        """Raises ToolNotFoundError, ProtocolError, or EscalationRequired"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return adapter name"""
```

**Exceptions** (`base.py`):
- `AdapterError` - base
- `ToolNotFoundError(tool_name, message)` - tool missing
- `ProtocolError(message, failure_category)` - hard failure
- `EscalationRequired(message, violations)` - needs human review

**Input directory contains**:
- `contract.yaml` - Step contract with scope constraints
- `prompt.md` - Task prompt for the agent
- `repo_state.json` - Baseline repo state

**Output directory must contain**:
- `patch.diff` - Unified diff
- `agent.json` - Structured agent report
- `cmdlog.txt` - Command log

### Constraints

- Must maintain same output artifact format as Codex adapter for runner compatibility
- **Do not modify `runner.py` or CLI** - mode selection via contract.yaml only
- Should not modify `base.py`
- Keep implementation focused - command safety checks are less critical when babysitting
- Interactive mode artifacts are produced by Claude (instructed via prompt) with adapter backfill as safety net

## Plan

### Step 1: Implementation [G1: Code Readiness]

**Role:** agentic

**Prompt:**

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

## Output Requirements

Before exiting, you MUST create these files in the output directory:

Output directory: {output_dir}

1. **patch.diff**: Run `git diff > {output_dir}/patch.diff`

2. **cmdlog.txt**: Create `{output_dir}/cmdlog.txt` with a log of commands you executed

3. **agent.json**: Create `{output_dir}/agent.json` with this structure:
   ```json
   {{
     "completion_status": "success",  // or "partial" or "failed"
     "confidence": 0.85,              // 0.0 to 1.0
     "files_modified": ["path/to/file.py"],
     "commands_executed": ["ruff check ."],
     "notes": "optional notes"
   }}
   ```

The output directory is also available as $SPEC_OUTPUT_DIR environment variable.
'''
```

**Update `src/spec/executor/adapters/__init__.py`:**

```python
from spec.executor.adapters.claude import ClaudeAdapter

_ADAPTERS: dict[str, type[AgentAdapter]] = {
    "codex": CodexAdapter,
    "claude": ClaudeAdapter,
}

__all__ = [
    # ... existing ...
    "ClaudeAdapter",
]
```

**File: `tests/executor/test_claude_adapter.py`**

Test cases to implement:
1. `test_name_property` - returns "claude"
2. `test_verify_claude_exists` - mock shutil.which to return path
3. `test_verify_claude_missing` - mock shutil.which to return None, expect ToolNotFoundError
4. `test_verify_script_fallback` - claude exists, script missing, verify succeeds with fallback flag
5. `test_mode_parsing_default` - no adapter section -> interactive mode
6. `test_mode_parsing_explicit` - adapter.mode: oneshot -> oneshot mode
7. `test_validate_agent_json_valid` - valid JSON with required keys passes
8. `test_validate_agent_json_missing_keys` - missing keys raises ProtocolError
9. `test_backfill_patch_diff` - patch.diff missing, backfill from git diff
10. `test_backfill_agent_json` - agent.json missing, backfill with partial status

**Allowed Paths:**

- `src/spec/executor/adapters/**`
- `tests/executor/**`

**Forbidden Paths:**

- `.git/**`
- `*.lock`
- `.env*`
- `secrets/**`
- `src/spec/executor/runner.py`
- `src/spec/cli/**`

**Verification Commands:**

```bash
ruff check src/spec/executor/adapters/claude.py tests/executor/test_claude_adapter.py
pytest tests/executor/test_claude_adapter.py -v
pytest tests/executor/test_adapters.py -v
```

**Outputs:**

- `src/spec/executor/adapters/claude.py`
- `src/spec/executor/adapters/__init__.py` (modified)
- `tests/executor/test_claude_adapter.py`

## Models & Tools

**Tools:** bash, pytest, ruff

**Models:** claude

## Repository

**Branch:** `feat/claude-adapter-for-specwright`

**Merge Strategy:** squash
