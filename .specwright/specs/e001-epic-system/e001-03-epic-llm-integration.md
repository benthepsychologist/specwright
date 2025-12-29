---
title: Epic LLM Integration
id: e001-03-epic-llm-integration
version: "0.1"
status: draft
tier: B
owner: benthepsychologist
epic: e001-epic-system
repo:
  working_branch: feat/epic-system
goal: "Wire up LLM execution for checks: config loading, llm package client, autogov injection, and spec epic check command"
created: 2025-12-26T00:00:00+00:00
updated: 2025-12-26T00:00:00+00:00
orchestrator_contract: "standard"
depends_on:
  - e001-02-epic-checks
---

# Epic LLM Integration

## Goal

Wire up actual LLM execution for checks: config loading from local-governor, `llm` package client wrapper, autogov context injection, and full `spec epic check` command. **After this spec, the epic system is complete.**

## Non-Goals

- Hard gating (checks remain advisory)
- Automatic execution across specs

---

## Prerequisites

- `src/spec/autogov` module must exist with lazy imports (from earlier work)
- `llm` package installed globally (`pip install llm`)
- At least one model configured and working (`llm models` shows it)
- API keys set via `llm keys set <provider>` or environment variables
- Verify setup: `llm -m gpt-4o "test"` should return a response

---

## Exit Codes

All specs in this epic use the same exit code taxonomy:

| Code | Meaning |
|------|---------||
| 0 | Success |
| 1 | Generic error / input gather failure |
| 2 | Not found (epic, spec, check, target, prompt) |
| 3 | Validation error (schema, DAG cycle, ref mismatch) |
| 4 | Config error (LLM disabled, missing config) |
| 5 | LLM execution error (timeout, provider failure) |

This spec primarily raises codes 4-5. Codes 1-3 are defined in earlier specs.

---

## Config Location

LLM **runtime settings only** in local-governor. Model config/auth is managed by the `llm` package itself.

```yaml
# ~/.local/local-governor/config.yaml
specwright:
  default_owner: benthepsychologist

llm:
  enabled: true
  timeout_s: 120           # specwright-level timeout for LLM calls
```

**Model selection is per-check in epic.yaml:**

```yaml
# In epic.yaml
defaults:
  model: gpt-4o            # default model for all checks

checks:
  - id: CHECK-e001-core
    model: gpt-4o          # uses default (explicit)
    ...
  - id: CHECK-e001-llm
    model: claude-3-opus   # override: thorough review
    ...
```

**Auth and model endpoints are NOT configured in specwright.** They are managed by the `llm` package:
- API keys: `llm keys set openai` or `OPENAI_API_KEY` env var
- Model plugins: `llm install llm-anthropic`
- Verify: `llm -m <model> "test"`

---

## Plan

### Step 1: LLM Config

**Prompt:**

Create `src/spec/llm/config.py` for LLM configuration.

Define `LLMConfigError(SpecwrightError)` with exit_code = 4.

Define dataclass:
```python
@dataclass
class LLMConfig:
    enabled: bool = False
    timeout_s: int = 120
    # Note: model is NOT here - it comes from check.model or epic.defaults.model
```

Implement:
- `get_governor_config_path() -> Path`: Return `~/.local/local-governor/config.yaml` expanded.

- `load_llm_config() -> LLMConfig`: Load LLM config from governor config.yaml. If file doesn't exist, return LLMConfig with enabled=False. If file exists but llm section missing, return disabled. Parse llm section into LLMConfig. Raise LLMConfigError on parse error.

- `require_llm_enabled() -> LLMConfig`: Load config and raise LLMConfigError if not enabled. Include helpful message about how to enable.

**Allowed Paths:** `src/spec/llm/**`

**Verification:** `pytest tests/llm/test_config.py -v`

---

### Step 2: LLM Client

**Prompt:**

Create `src/spec/llm/client.py` wrapping the `llm` package.

Define `LLMExecutionError(SpecwrightError)` with exit_code = 5.

Implement `LLMClient` class:

```python
class LLMClient:
    def __init__(self, config: LLMConfig, model_name: str):
        self.config = config
        self.model_name = model_name  # from check.model or epic.defaults.model
        self._model = None

    def _get_model(self):
        """Lazy-load the LLM model."""
        if self._model is None:
            try:
                import llm
                self._model = llm.get_model(self.model_name)
            except ImportError:
                raise LLMExecutionError(
                    "llm package not installed. Run: pip install llm",
                    exit_code=5
                )
            except llm.UnknownModelError:
                raise LLMExecutionError(
                    f"Model '{self.model_name}' not found. "
                    f"Run 'llm models' to see available models, or "
                    f"'llm install llm-<provider>' to add a provider.",
                    exit_code=5
                )
            except Exception as e:
                raise LLMExecutionError(f"Failed to load model {self.model_name}: {e}")
        return self._model

    def prompt(self, text: str) -> str:
        """
        Send prompt to LLM and return response.
        Handles timeouts and translates errors to LLMExecutionError.
        """
        # Use signal.alarm for timeout (self.config.timeout_s)
        # Call model.prompt(text) - use llm package defaults for temperature/tokens
        # Return response.text()
        # Catch exceptions and wrap in LLMExecutionError
        ...

    def prompt_with_system(self, system: str, user: str) -> str:
        """Send prompt with system message."""
        ...
```

Use `signal.SIGALRM` for timeout handling. Clean up alarm in finally block.

Add `llm` to pyproject.toml dependencies.

**Allowed Paths:** `src/spec/llm/**`, `pyproject.toml`

**Verification:** `pytest tests/llm/test_client.py -v`

---

### Step 3: Autogov Context Injection

**Prompt:**

Update `src/spec/checks/inputs.py` to handle governance_pack input type properly.

Replace the placeholder implementation of `_gather_governance_pack`:

```python
def _gather_governance_pack(input_def: CheckInput, epic: Epic) -> GatheredInput:
    """
    Gather governance context from autogov.
    Loads governance bundle and exports to markdown.
    """
    if not epic.governance or not epic.governance.enabled:
        return GatheredInput(
            type="governance_pack",
            source="autogov (disabled)",
            content="[Governance not enabled for this epic]"
        )

    try:
        from spec.autogov.loader import GovernanceLoader
        from spec.autogov.context_builder import SpecContextBuilder

        loader = GovernanceLoader()
        bundle = loader.load_all(
            epic.governance.project,
            epic.governance.source,
        )

        builder = SpecContextBuilder()
        markdown = builder.export_to_markdown(
            bundle,
            include=epic.governance.include,
        )

        return GatheredInput(
            type="governance_pack",
            source=f"autogov:{epic.governance.project}",
            content=markdown,
        )
    except Exception as e:
        return GatheredInput(
            type="governance_pack",
            source="autogov (error)",
            content=f"[Failed to load governance: {e}]"
        )
```

Also add `export_to_markdown` method to `SpecContextBuilder` if not exists.

Handle import errors gracefully - if autogov module not available, return error message in content.

**Allowed Paths:** `src/spec/checks/**`, `src/spec/autogov/**`

**Verification:** `pytest tests/checks/test_inputs.py -v`

---

### Step 4: Wire Check Command

**Prompt:**

Update `src/spec/cli/epic.py` to implement the full `check` command.

Handle all error cases with correct exit codes:
- Exit 2: Epic or check not found
- Exit 4: LLM config error
- Exit 5: LLM execution error

**Allowed Paths:** `src/spec/cli/**`

**Verification:** `spec epic check --help && pytest tests/cli/test_epic_check.py -v`

---

### Step 5: Documentation

**Prompt:**

Create documentation for the epic system.

Create `docs/epics.md`:

1. Introduction - What are epics, when to use them
2. Directory structure - Where epics live
3. Epic schema - Full schema reference
4. CLI commands - All commands with examples
5. LLM checks - How to configure and run
6. Workflow walkthrough - Step-by-step usage

Update `README.md` to add epics to feature list and link to docs/epics.md.

Ensure all CLI commands have clear --help text with examples.

**Allowed Paths:** `docs/**`, `README.md`

**Verification:** Manual review of docs

---

### Step 6: Integration Tests

**Prompt:**

Create end-to-end integration tests for the epic system.

Create `tests/integration/test_epic_e2e.py`:

Test full workflows:
1. Create epic → add target → add spec → set-current → status
2. mark-done → status shows done with checkmark
3. validate detects cycles, missing refs
4. check with LLM disabled returns exit 4 with message
5. check with mock LLM returns report

Use temporary directories for governor root.
Mock LLM calls for deterministic tests.

**Allowed Paths:** `tests/**`

**Verification:** `pytest tests/integration/test_epic_e2e.py -v`

---

## Acceptance Criteria

- [ ] LLM config loads from `~/.local/local-governor/config.yaml`
- [ ] LLM client works with `llm` package
- [ ] Timeout handling works correctly
- [ ] Autogov governance pack injected into prompts
- [ ] `spec epic check` command works end-to-end
- [ ] Exit code 4 on config error
- [ ] Exit code 5 on LLM error
- [ ] Graceful degradation when LLM disabled
- [ ] Documentation complete in docs/epics.md
- [ ] Integration tests pass

## Constraints

- No hard gating - checks remain advisory
- Use `llm` package for provider abstraction
- Config lives in local-governor only
- Existing spec commands unaffected
