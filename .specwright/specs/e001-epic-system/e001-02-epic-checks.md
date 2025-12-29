---
title: Epic Checks - Input Gathering and Reports
id: e001-02-epic-checks
version: "0.1"
status: draft
tier: B
owner: benthepsychologist
epic: e001-epic-system
repo:
  working_branch: feat/epic-system
goal: "Implement check subsystem: prompt resolution, input gathering, report writing, and stub executor"
created: 2025-12-26T00:00:00+00:00
updated: 2025-12-26T00:00:00+00:00
orchestrator_contract: "standard"
depends_on:
  - e001-01-epic-core
---

# Epic Checks - Input Gathering and Reports

## Goal

Implement the check subsystem: prompt resolution, input gathering, report writing, and history recording. **This spec does NOT include actual LLM execution** - it creates a stub executor that writes "NOT_RUN" reports. e001-03-epic-llm-integration wires up the actual LLM.

## Non-Goals

- Actual LLM calls (stub only)
- Autogov context injection (that's e001-03-epic-llm-integration)

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

This spec primarily raises codes 1-2. Codes 4-5 are used by e001-03-epic-llm-integration.

---

## Plan

### Step 1: Prompt Resolver

**Prompt:**

Create `src/spec/checks/resolver.py` for resolving check prompts.

Define `PromptNotFoundError(SpecwrightError)` with exit_code = 2.

Implement:
- `resolve_prompt(prompt_ref: str, epic_path: Path) -> str`: Read prompt file from `<epic_path>/<prompt_ref>`. Return markdown content. Raise PromptNotFoundError if file doesn't exist with clear error message including the path.

**Allowed Paths:** `src/spec/checks/**`

**Verification:** `pytest tests/checks/test_resolver.py -v`

---

### Step 2: Input Gathering

**Prompt:**

Create `src/spec/checks/inputs.py` for gathering check inputs.

Define `InputGatherError(SpecwrightError)` with exit_code = 1.

Define dataclass:
```python
@dataclass
class GatheredInput:
    type: str       # epic, spec, file, git_diff, cli_output, governance_pack
    source: str     # path, command, or description
    content: str    # the actual content
```

Implement:
- `gather_inputs(check: Check, epic: Epic, epic_path: Path) -> list[GatheredInput]`: Gather all inputs defined for a check. Iterate through check.inputs and call _gather_single for each.

- `_gather_single(input_def: CheckInput, epic: Epic, epic_path: Path) -> GatheredInput`: Dispatch based on input_def.type.

Support these input types:
- `type: epic` → Read epic.yaml from epic_path
- `type: spec` → Read spec file from governor (path relative to governor root)
- `type: file` → Read file from target repo (resolve target from input_def.target or first target)
- `type: git_diff` → Run `git diff <range>` in target repo, capture output
- `type: cli_output` → Execute command using args-based invocation (see below)
- `type: governance_pack` → Load governance context (see precedence rules below)

For git_diff, use subprocess.run with cwd set to target.repo_path. Default range to "HEAD~1..HEAD" if not specified.

For cli_output:
- Build argv as `[epic.run_context.cli_bin] + input_def.args`
- Set cwd based on `epic.run_context.cwd_policy`: governor → governor_root, repo → target.repo_path
- Use `subprocess.run(argv, shell=False, capture_output=True, timeout=30)`
- Never use shell=True unless input_def.tool == "shell" (escape hatch, not recommended)

For governance_pack precedence:
- If input_def.include is set → use it
- Else if epic.governance.include is set → use that
- Else → include all available (policy, arch, patterns)

Raise InputGatherError on failures with descriptive message.

**Allowed Paths:** `src/spec/checks/**`

**Verification:** `pytest tests/checks/test_inputs.py -v`

---

### Step 3: Report Writer

**Prompt:**

Create `src/spec/llm/reporter.py` for writing check reports.

Define dataclass:
```python
@dataclass
class CheckReport:
    check_id: str
    epic_id: str
    spec_id: str | None
    model: str                # llm model alias used (or "stub" if no LLM)
    timestamp: datetime
    inputs: list[str]         # list of input source descriptions
    verdict: str              # PASS, WARN, FAIL, ERROR, NOT_RUN
    content: str              # markdown body
```

Implement:
- `write_report(report: CheckReport, epic_path: Path) -> Path`: Write report to `reports/` directory. Filename format: `YYYYMMDD-HHMM-<check_id>.md`. Include YAML frontmatter with check_id, epic_id, spec_id (if present), model, timestamp, inputs, verdict. Return path to written report.

- `parse_verdict(response: str, is_stub: bool = False) -> str`: Parse verdict from LLM response. Look for line starting with "VERDICT:". Accept PASS, WARN, FAIL, ERROR, NOT_RUN. If not found and is_stub=True, return NOT_RUN. If not found and is_stub=False (real LLM response), return ERROR (malformed output is an error, not a warning).

Report format:
```markdown
---
check_id: CHECK-xxx
epic_id: e001-epic-system
spec_id: e001-01-epic-core  # if applicable
model: gpt-4o
timestamp: 2025-12-26T14:30:00Z
inputs:
  - epic.yaml
  - projects/specwright/specs/spec.md
verdict: WARN
---

<markdown body from response>
```

**Allowed Paths:** `src/spec/llm/**`

**Verification:** `pytest tests/llm/test_reporter.py -v`

---

### Step 4: Stub Executor

**Prompt:**

Create `src/spec/checks/executor.py` for executing checks.

Implement `CheckExecutor` class:

```python
class CheckExecutor:
    def __init__(self, llm_client=None):
        """
        Initialize executor.
        llm_client: Optional LLM client. If None, uses stub.
        """
        self.llm_client = llm_client

    def execute(
        self,
        epic: Epic,
        check_id: str,
        epic_path: Path,
        spec_id: str | None = None,
    ) -> CheckReport:
        """
        Execute a check and return report (does not save).

        1. Find check by ID (raise ValueError if not found)
        2. Resolve prompt from prompt_ref
        3. Gather inputs
        4. Assemble full prompt (template + inputs)
        5. Call LLM (or stub if no client)
        6. Parse verdict from response
        7. Return CheckReport
        """
        ...

    def run_and_save(
        self,
        epic: Epic,
        check_id: str,
        epic_path: Path,
        spec_id: str | None = None,
    ) -> tuple[CheckReport, Path]:
        """
        Execute check, write report, update history.
        Returns (report, report_path).
        """
        ...

    def _assemble_prompt(self, template: str, inputs: list[GatheredInput]) -> str:
        """Assemble full prompt with inputs section."""
        # Add inputs under "# Inputs" header with type and source
        ...

    def _stub_response(self, check: Check) -> str:
        """Generate stub response when no LLM client."""
        # Return formatted response with VERDICT: NOT_RUN
        ...
```

When no LLM client is provided, `_stub_response` should return:
```
VERDICT: NOT_RUN
SUMMARY: LLM integration not configured

# Check Report: {check.name}

## Status

This check was not executed because LLM integration is not configured.

To enable LLM checks:
1. Install llm package: `pip install llm`
2. Configure a model: `llm keys set openai`
3. Enable in config: `~/.local/local-governor/config.yaml` → `llm.enabled: true`
4. Re-run this check

## Inputs

{number} inputs were gathered successfully.
```

Note: If input gathering fails, that's a different code path - exit 1 with VERDICT: ERROR, not NOT_RUN. NOT_RUN is only for "LLM disabled but everything else worked."

For `run_and_save`, after writing report, append history event:
- Generate event ID with `generate_event_id(epic)`
- event type: `check.completed`
- actor: `specwright` (always - CLI execution means specwright is the actor)
- Include check_id, verdict, report path relative to epic_path

**Allowed Paths:** `src/spec/checks/**`

**Verification:** `pytest tests/checks/test_executor.py -v`

---

### Step 5: Tests

**Prompt:**

Create comprehensive tests for the check subsystem.

Create test files:
- `tests/checks/__init__.py`
- `tests/checks/test_resolver.py`: Prompt resolution tests
- `tests/checks/test_inputs.py`: Input gathering tests
- `tests/checks/test_executor.py`: Executor tests with stub
- `tests/llm/__init__.py`
- `tests/llm/test_reporter.py`: Report writing tests

Test cases:
- Prompt resolved from checks/ directory
- Missing prompt raises PromptNotFoundError (exit 2)
- All input types gather correctly
- git_diff runs in correct directory with correct range
- cli_output captures stdout and stderr
- Unknown input type raises InputGatherError
- Report written with correct YAML frontmatter
- Verdict parsed correctly from response (PASS, WARN, FAIL)
- Default to WARN when verdict not found
- Stub executor produces NOT_RUN verdict
- History event appended on run_and_save

Use pytest fixtures and mocks for git/subprocess calls.

**Allowed Paths:** `tests/**`

**Verification:** `pytest tests/checks/ tests/llm/ -v --cov=src/spec/checks --cov=src/spec/llm`

---

## Acceptance Criteria

- [ ] Prompts resolved from epic checks/ directory
- [ ] All 5 input types gathered correctly (governance_pack returns placeholder)
- [ ] Reports written with YAML frontmatter and correct format
- [ ] Verdict parsing handles all cases
- [ ] Stub executor works without LLM client
- [ ] History events appended correctly
- [ ] Unit tests pass with >80% coverage

## Constraints

- No actual LLM calls - stub only
- governance_pack input returns placeholder text
- Use existing SpecwrightError pattern
