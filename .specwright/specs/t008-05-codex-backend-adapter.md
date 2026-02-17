# t008-05: Codex Backend Adapter

## Context

OpenAI's Codex is a competitor to Claude Code, available through GitHub Enterprise partner agents. The specwright executor has already integrated the Copilot backend (t008-04); now we extend the system to support Codex with feature parity to Copilot.

**Authentication:** GitHub Enterprise partner agents handle auth — no separate API key setup needed.

## Problem Statement

Users with GitHub Enterprise + Codex partner agent enabled cannot use Codex within specwright JobDefs. The executor currently only dispatches to `claude-code`, `cmd`, `python`, `llm`, and `copilot` backends.

## Solution

Implement `CodexBackend` following the same interface as `CopilotBackend`:
- Headless mode: `codex -p "<prompt>" --model <model>`, stdout/stderr captured
- Interactive mode: TUI with `interactive=True` payload flag
- Tool safety: Deny shell(git*) to keep agent in file-change lane
- Model selection: Best-effort (pass through models; use "gpt-5.3-codex" default)

## Acceptance Criteria

### Implementation
- [ ] `CodexBackend` class in `src/spec/executor/backends/codex.py`
- [ ] Implements `BackendBase` interface (verify, dispatch, name property)
- [ ] `verify()` checks: Codex CLI on PATH, `--deny-tool` flag support
- [ ] `dispatch()` supports both headless and interactive modes
- [ ] Model selection tries models in priority order, falls back gracefully
- [ ] Captures pre/post git state and agent output (stdout/stderr)
- [ ] Tool denial: `--deny-tool 'shell(git*)'` to prevent git operations
- [ ] Timeout handling: Respects `timeout_s` in payload/common
- [ ] Error messages guide user to installation and authentication

### Integration
- [ ] `CodexBackend` registered in backend registry
- [ ] Backend discoverable via `backend_registry.get("codex")`
- [ ] Payload schema documented (prompt, repo_path, models, interactive, timeout_s)
- [ ] Works with aip-1 and interactive-1 JobDef templates

### Testing
- [ ] Unit tests in `tests/executor/test_codex_backend.py`
- [ ] Mock Codex CLI execution (no real Codex calls in test suite)
- [ ] Test headless + interactive modes
- [ ] Test model fallback when first model fails
- [ ] Test timeout handling
- [ ] Test missing CLI error message
- [ ] Test git denial prevents shell(git*) invocation

### Documentation
- [ ] Payload schema documented in docstring
- [ ] Installation instructions in code comments
- [ ] Tool safety note (git operations denied)
- [ ] Interactive mode behavior documented

## Payload Schema

```python
{
    "prompt": str,              # Required: task instruction for Codex
    "repo_path": str | None,    # Optional: repo path (default: common.repo_path)
    "models": list[str] | None, # Optional: [gpt-5.3-codex, ...] (default: [gpt-5.3-codex])
    "capture_git": bool,        # Optional: capture pre/post git state (default: True)
    "interactive": bool,        # Optional: launch TUI instead of headless (default: False)
    "timeout_s": int | None,    # Optional: override common.timeout_s
}
```

## Implementation Notes

1. **CLI Command Structure (Headless)**
   ```bash
   codex -p "<prompt>" --model <model> --deny-tool 'shell(git*)'
   ```

2. **CLI Command Structure (Interactive)**
   ```bash
   codex --model <model> --deny-tool 'shell(git*)'
   ```
   Prompt is displayed in TUI; user provides input interactively.

3. **Model Fallback**
   - Try models in order: `payload.models` → `[DEFAULT_MODEL]`
   - Stop on first success (exit_code == 0) OR first non-model-specific error
   - Skip model if stderr contains "unknown model", "not available", etc.

4. **Git State Capture**
   - Pre-step: Call `capture_pre_step_state()` before Codex invocation
   - Post-step: Call `capture_git_state()` after (patch optional via `capture_patch`)
   - Merge pre/post into `GitCapture` for `StepCapture`

5. **Error Handling**
   - CLI not found → BackendError with installation link
   - Missing --deny-tool support → BackendError with upgrade guidance
   - Timeout → exit code 124, stderr message with timeout duration
   - No models available → exit code 1, stderr lists all attempts

6. **Interactive Mode**
   - No stdin/stdout PIPE (inherit terminal)
   - No timeout (human controls exit)
   - Write marker files (stdout/stderr) to signal completion

## Constraints

- Must follow same interface as `CopilotBackend` (for symmetry)
- No modifications to existing backend interfaces
- Backward compatible with existing workflows
- Tool denial is mandatory (same policy as Copilot)
- Graceful error on missing CLI (helpful error message)

## Definition of Done

1. `CodexBackend` implemented and passes all unit tests
2. Backend registered and discoverable
3. Payload schema documented
4. Both headless and interactive modes work
5. Git state capture functional
6. Tool safety (git denial) verified
7. Error messages are helpful (installation links, auth guidance)
8. Code review passes (style, safety, contract compliance)

## Related

- **t008-04**: Copilot backend (reference implementation)
- **Claude Code reference**: `/workspace/specwright/src/spec/executor/backends/claude_code.py`
- **BackendBase interface**: `/workspace/specwright/src/spec/executor/backends/base.py`
- **Codex CLI docs**: https://developers.openai.com/codex/cli/
- **Codex models**: https://developers.openai.com/codex/models/
