---
id: t008-04-copilot-backend-adapter
title: "t008-04-copilot-backend-adapter"
tier: B
owner: benthepsychologist
goal: "Implement CopilotBackend class following BackendBase interface"
branch: feat/copilot-backend
status: draft
created: 2026-02-05T18:23:41Z
---

# t008-04-copilot-backend-adapter: t008-04-copilot-backend-adapter

**Epic:** t008-agent-reference-syncing-and-continuous-improvement
**Branch:** `feat/copilot-backend`
**Tier:** B

## Objective

> Implement CopilotBackend class to execute agent steps using GitHub Copilot CLI with deterministic model selection and preflight validation

Create a GitHub Copilot backend that allows specwright to execute agent steps with GPT-5.2, Claude via Copilot, or other Copilot-supported models. The backend will:

- **Validate availability upfront** via deterministic preflight checks before dispatch
- **Support model arrays** — try models in priority order, fail if none work
- **Follow claude-code patterns** for consistency (headless + interactive modes, git capture, timeouts)
- **Integrate with t008-03** agent parameterization to enable multi-agent workflows

The Copilot backend is a **first-class agent backend**, equivalent in capability to claude-code, not a fallback.

## Problem

1. **Limited agent access**: No way to use GPT-5.2 via Copilot within specwright workflows
2. **No Copilot integration**: Copilot CLI available but not integrated as a backend
3. **Model selection uncertainty**: When specifying models, unclear whether they're available, installed, or properly configured
4. **No environment validation**: Can't verify agent availability before expensive job compilation/dispatch

## Current Capabilities

### kernel.surfaces

```yaml
- command: "spec compile"
  usage: "spec compile aip-1 ./my-feature.md"
- command: "spec execute"
  usage: "spec execute ./job_instance.yaml"
- command: "spec run"
  usage: "spec run aip-1 ./my-feature.md --repo /workspace/target"
- command: "spec status"
  usage: "spec status [run-id]"
- command: "spec logs"
  usage: "spec logs <run-id>"
- command: "spec create"
  usage: "spec create 'feature name' --tier C"
- command: "spec init"
  usage: "spec init"
- command: "spec config"
  usage: "spec config current.spec ./my-feature.md"
- command: "spec epic"
  usage: "spec epic status e011"
- command: "spec validate spec"
  usage: "spec validate spec ./my-feature.md"
- command: "spec validate build"
  usage: "spec validate build specwright [--json] [--fix]"
- command: "spec validate epic"
  usage: "spec validate epic t004 [--json]"
- command: "spec validate contracts"
  usage: "spec validate contracts [--json]"
```

### modules

```yaml
- name: cli
  provides: ['spec command-line interface']
- name: executor
  provides: ['job compilation', 'step execution', 'run tracking']
- name: backends
  provides: ['claude-code backend', 'cmd backend', 'python backend', 'llm backend', 'codex backend']
- name: executor_schemas
  provides: ['StepTemplate', 'JobDef', 'JobInstance', 'StepOutcome', 'StepCapture']
- name: epic
  provides: ['epic loading', 'epic schema', 'DAG validation', 'epic writing']
- name: governor
  provides: ['governor locator', 'epic/spec resolver', 'spec reader', 'materializer']
- name: governance
  provides: ['build validation', 'epic validation', 'contract validation']
- name: checks
  provides: ['LLM check execution', 'check input resolution']
- name: llm
  provides: ['LLM client', 'prompt rendering', 'report generation']
- name: compiler
  provides: ['spec markdown parsing', 'v1 YAML compilation']
```

### layout

```yaml
- path: src/spec/cli/
  role: "Typer CLI commands and subcommand registration"
- path: src/spec/executor/
  role: "v2 job engine: compile, dispatch, step execution, run tracking"
- path: src/spec/executor/backends/
  role: "Pluggable execution backends (claude-code, cmd, python, llm, codex)"
- path: src/spec/executor/schemas/
  role: "Step, job, and capture dataclasses"
- path: src/spec/epic/
  role: "Epic loading, schema dataclasses, DAG validation, writer"
- path: src/spec/governor/
  role: "Local-governor integration: locator, reader, resolver, materializer, targets"
- path: src/spec/governance/
  role: "Build, epic, and contract validation"
- path: src/spec/checks/
  role: "LLM check execution and input resolution"
- path: src/spec/llm/
  role: "LLM client, config, prompts, and report generation"
- path: src/spec/compiler/
  role: "Spec markdown parser and v1 compiler (legacy)"
```

## Proposed build_delta

```yaml
target: "projects/specwright/specwright.build.yaml"
summary: "Add copilot backend for GitHub Copilot CLI integration"

adds:
  layout:
    - module: copilot_backend
      kind: backend_implementation
      path: src/spec/executor/backends/copilot.py
    - module: backend_enum_update
      kind: schema_update
      path: src/spec/executor/schemas/shared.py
      note: "Add Backend.copilot = 'copilot' enum value"
  modules: []
  kernel_surfaces: []
modifies:
  backends:
    provides: ["claude-code backend", "cmd backend", "python backend", "llm backend", "codex backend", "copilot backend"]
  layout:
    - path: src/spec/executor/backends/registry.py
      note: "Register CopilotBackend in _auto_register()"
removes: {}
```

## Acceptance Criteria

**Core implementation:**
- [ ] Implement CopilotBackend class following BackendBase interface
- [ ] Register in backend registry with ID `"copilot"`
- [ ] Follow `claude_code.py` structure and patterns exactly

**Preflight validation (verify method):**
- [ ] Implement `verify()` method in CopilotBackend (override from BackendBase)
- [ ] Check CLI installed: `shutil.which("copilot")` succeeds
- [ ] Check auth valid: `copilot -p "test" --model claude-sonnet-4.5` returns 0 (5s timeout)
- [ ] Check CLI version/flag support: Verify `--deny-tool` flag exists via `copilot --help`
- [ ] Raise `BackendError` with helpful context if any check fails
- [ ] Error messages guide user: "Install copilot CLI", "Set GH_TOKEN", "Upgrade copilot CLI to X.Y"

**Model handling:**
- [ ] Support `models` array in payload (ordered, deterministic)
- [ ] Try models in order during dispatch
- [ ] Fail step (not fallback) if no models work
- [ ] If no models specified, use "claude-sonnet-4.5" as default
- [ ] Pass `--model <name>` to copilot CLI

**Execution modes:**
- [ ] Headless mode: `copilot -p "<prompt>" --model <model> --deny-tool 'shell(git*)'`
- [ ] Interactive mode: Launch copilot CLI with same deny-tool flags, user sees prompt
- [ ] Both modes handle timeouts via subprocess
- [ ] Both modes capture stdout/stderr/exit code

**Tool safety (agent stays in file-change lane):**
- [ ] Deny all git operations: git add, git commit, git push, git merge, git restore, etc.
- [ ] Allow: file read/write/edit, tests, builds, dev tools, etc.
- [ ] Job handles commits as separate step (after agent completes)
- [ ] User can reset if job fails; agent's lane is file changes only

**Git and artifacts:**
- [ ] Support git state capture before/after (match claude-code)
- [ ] Create StepCapture with stdout, stderr, patches (match claude-code)
- [ ] Respect `capture_git` and `capture_patch` flags

**Error handling:**
- [ ] Clear messages: CLI not found, auth failure, model unavailable
- [ ] Parse Copilot error messages for user guidance
- [ ] Timeout handling (default 1800s, user-configurable)

**Integration:**
- [ ] Works with t008-03 agent parameterization (backend: "@payload.agent")
- [ ] Integrates with t008-03 preflight validation framework

**Testing:**
- [ ] Unit tests for verify() method (CLI check, auth check, flag support)
- [ ] Unit tests for dispatch with multiple models (success, no models work, failure)
- [ ] Integration tests with actual Copilot CLI (if available in test env)
- [ ] Mock tests for missing CLI, failed auth, unsupported flags, timeout scenarios
- [ ] Preflight integration: Verify called exactly once per unique backend in job
- [ ] Linting passes: `ruff check src/`
- [ ] Type checking passes: `mypy src/spec/executor/backends/copilot.py`

## Constraints

- Must follow same interface as claude-code backend
- Use official Copilot CLI surface (discover at implementation)
- No modifications to existing backend interfaces
- Preflight validation is **deterministic** — fails if requirements not met, succeeds if all validated
- Model selection is **deterministic** — tries models in order, fails if none available
- Error clearly when Copilot CLI unavailable or authentication fails

---

## Preflight Checks

Before dispatch, the Copilot backend validates in `is_available()`:

1. **CLI installed**: `shutil.which("copilot")` finds the binary
   - Error: "Copilot CLI not found. Install from: https://github.com/github/copilot-cli"

2. **Authentication valid**: Test with `copilot -p "test" --model <model>` (5s timeout)
   - Check exit code 0 = authenticated
   - Non-zero = auth failure (missing GH_TOKEN, expired token, subscription lapsed)
   - Error: "Copilot authentication failed. Set GH_TOKEN or GITHUB_TOKEN environment variable with valid Copilot access token"

3. **Model availability**: Test model with same `copilot -p` command
   - Model error patterns: "unknown model", "not available", "not supported"
   - If no models specified in payload, use default (Claude Sonnet 4.5)
   - Error: "Requested models not available: gpt-5.2, claude-opus-4.6. Available via your subscription: [detected or generic list]"

**Failure behavior**: If ANY check fails, `is_available()` returns `False` and compilation fails with clear error message.

**Success behavior**: If ALL checks pass, backend is ready for execution.

### Model Array Support

The `models` parameter (in step payload) is an **ordered array** of model preferences:

```yaml
payload:
  models:
    - "gpt-5.2"
    - "claude-3.5"
    - "gpt-4"
```

**Execution**:
1. Try `gpt-5.2` first
2. If not available, try `claude-3.5`
3. If not available, try `gpt-4`
4. If none available, **fail the step** (not fallback to default)

If `models` is not provided, use backend default model (e.g., Copilot's default model).

---

## Phase 1: Core Backend Implementation

### Objective
Implement the CopilotBackend class with basic dispatch functionality, following the same patterns as claude-code and codex backends.

### Files to Touch
- `src/spec/executor/backends/copilot.py` (create) — Main CopilotBackend implementation with dispatch logic
- `src/spec/executor/backends/registry.py` (modify) — Register copilot backend in _auto_register()

### Implementation Notes

**Preflight checks** (in `is_available()` method):
```python
def is_available(self) -> bool:
    """Check if Copilot CLI backend is ready for execution."""
    # 1. Check CLI exists
    if not shutil.which("copilot"):
        self._error = "Copilot CLI not installed. See: https://github.com/github/copilot-cli"
        return False

    # 2. Check authentication via test command (5s timeout)
    try:
        result = subprocess.run(
            ["copilot", "-p", "test", "--model", self._get_first_model()],
            capture_output=True,
            timeout=5,
            env={**os.environ, "GH_TOKEN": os.getenv("GH_TOKEN", "")}
        )
        if result.returncode != 0:
            self._error = "Copilot auth failed. Set GH_TOKEN or GITHUB_TOKEN environment variable."
            return False
    except subprocess.TimeoutExpired:
        self._error = "Copilot auth check timed out (5s). Network or auth issue."
        return False

    return True

def availability_error(self) -> str:
    """Return helpful error message from last is_available() check."""
    return self._error or "Unknown error"
```

**Model selection** (during dispatch):
```python
def dispatch(self, step: Step) -> StepOutcome:
    models = self.payload.get("models") or [self._get_default_model()]

    for model in models:
        try:
            result = self._run_copilot(step.payload.get("prompt"), model)
            if result.returncode == 0:
                return StepOutcome(passed=True, ...)
            # Model not available, try next
        except Exception:
            continue

    # All models failed
    return StepOutcome(
        passed=False,
        error=f"No models available: {models}. Check subscription and token."
    )
```

**Invocation mechanism**:
- Primary: `copilot -p "<prompt>" --model <model> --deny-tool 'shell(git*)'`
  - Agent stays in file-change lane: read, write, edit, test, build
  - All git operations blocked (add, commit, push, merge, restore, etc.)
  - Job handles commits as separate step; user can reset if needed
- NO fallback to deprecated `gh copilot`
- Interactive mode: `copilot` with same deny-tool flags

**Payload schema** (match claude-code):
- `prompt` — agent task description (required)
- `repo_path` — target repository path (required)
- `models` — array of preferred models, ordered (optional, default: claude-sonnet-4.5)
- `capture_git` — capture git state before/after (optional, default: true)
- `interactive` — interactive mode flag (optional, default: false)
- `timeout_s` — step timeout in seconds (optional, default: 1800)

**Code patterns**:
- Follow `claude_code.py` structure exactly
- Use same git capture logic from claude-code
- **Tool safety**: Agent stays out of git entirely via deny-tool flags
  - Deny ALL git operations: `git add`, `git commit`, `git push`, `git merge`, `git restore`, etc.
  - Agent only reads/writes files; job handles commits as separate step
  - User can reset if something goes wrong; agent's lane is file changes only
  - Command: `copilot -p "<prompt>" --model <model> --deny-tool 'shell(git*)'`
  - This blocks any git command while allowing file ops, tests, builds, etc.
- Headless: `copilot -p ...` captures stdout/stderr
- Interactive: Launch `copilot` in subprocess, user sees prompt in terminal

### Verification
- `pytest tests/executor/backends/` → new tests pass
- `ruff check src/` → clean
- `python -c "from spec.executor.backends import get_backend; print(get_backend('copilot'))"` → CopilotBackend instance

## Phase 2: Integration and Testing

### Objective
Complete backend registration, add comprehensive error handling, and ensure integration with the broader specwright ecosystem.

### Files to Touch
- `tests/executor/backends/test_copilot.py` (create) — Test suite for CopilotBackend
- `src/spec/executor/backends/__init__.py` (modify) — Update docstring to include copilot backend

### Implementation Notes
- Write comprehensive tests covering both available and unavailable CLI scenarios
- Test both headless and interactive mode execution paths
- Verify git capture and artifact handling work correctly
- Test timeout scenarios and process management
- Ensure error messages are helpful when Copilot CLI is unavailable or auth fails
- Follow the same test patterns as existing backend tests

### Verification
- `pytest tests/executor/backends/test_copilot.py -v` → all tests pass
- `pytest tests/executor/ -k backend` → all backend tests pass
- `spec run --backend copilot` → shows helpful error if copilot unavailable
- Backend shows up in `list_backends()` output

## Discovery Findings

### CLI Interface ✓ RESEARCHED

**Command invocation**:
- Standalone `copilot` CLI (recommended, under active development)
- ~~`gh copilot` extension (DEPRECATED as of Oct 25, 2025)~~ — do NOT use
- Headless mode: `copilot -p "prompt text"` or `copilot --prompt "prompt text"`
- Interactive mode: `copilot` (default, launches interactive session)

**Model selection**:
- Headless: `copilot -p "prompt" --model gpt-5.2`
- Interactive: `/model` slash command to switch models
- Default model: Claude Sonnet 4.5

**Tool control** (for safety):
- `--allow-all-tools` — allow any shell command
- `--allow-tool shell` — allow any shell command with approval
- `--deny-tool 'shell(rm)'` — deny specific commands

**Other flags**:
- `--experimental` — enable experimental features
- `--banner` — show animated banner
- `--allow-all-paths` — disable path verification

Sources: [GitHub Copilot CLI Docs](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli), [CLI Reference](https://docs.github.com/en/copilot/reference/cli-command-reference)

### Available Models ✓ RESEARCHED

Supported in Copilot CLI:
- **Claude models**: Haiku 4.5, Sonnet 4.5, Sonnet 4, Opus 4.5, Opus 4.6
- **Gemini models**: 2.5 Pro, 3 Pro, 3 Flash
- **GPT models**: GPT-5, GPT-5.1, GPT-5.2, GPT-5.2-Codex

Model naming in `--model` flag: Use model identifiers directly (e.g., `gpt-5.2`, `claude-sonnet-4.5`)

⚠️ **Note**: Available models may vary by region and subscription. CLI uses what's available in your account.

Sources: [Supported Models](https://docs.github.com/en/copilot/reference/ai-models/supported-models)

### Authentication ✓ RESEARCHED

**Requirement**: GitHub token with Copilot access
- Environment variable: `GH_TOKEN` or `GITHUB_TOKEN`
- Token type: Fine-grained personal access token recommended
- Required permission: "Copilot Requests" scope
- Scope: OAuth-like access (full account authentication)

**Verification**:
- `copilot --version` succeeds with valid token
- Interactive mode shows login prompt if token missing/invalid
- Can test auth with: `copilot -p "test" --model claude-sonnet-4.5` (fails if no auth)

**Important**: `gh copilot` extension required OAuth via browser and is deprecated. Use standalone `copilot` CLI only.

Sources: [Installation Guide](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli), [Auth Discussion](https://github.com/orgs/community/discussions/167158)

### Implementation Implications

1. **No fallback to `gh copilot`** — just use standalone `copilot` CLI
2. **Model availability not queryable** — no built-in `list-models` command; assume what's in user's token
3. **Auth validation**: Run `copilot -p "test" --model <model>` with timeout to validate environment
4. **Tool safety**: Use `--allow-all-tools` or `--allow-tool shell` for agent execution

---

## Critical Constraint: build_delta First

The build_delta is the REAL constraint. Everything else derives from it:
- **adds.layout** → drives Files to Touch (what paths to create/modify)
- **adds.kernel_surfaces** → drives Acceptance Criteria (what commands are exposed)
- **adds.modules** → drives what functionality is added and how to verify it

Start by defining the build_delta, then derive everything else from it.