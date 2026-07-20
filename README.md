# Specwright

**The architect of agentic workflows.**

Specwright defines, validates, and executes **Agentic Implementation Plans (AIPs)** — human-in-the-loop governance for AI-assisted software development.

Specs are authored on the governor side (cloud-governor, as `.md` or `.yaml`); specwright compiles and executes them through pluggable agent backends (Claude Code, GitHub Copilot, shell commands, Python callables, LLMs). Every step is captured; run records are emitted as governed rows through the storacle gate, and bulk artifacts stay in local scratch — never in the target repo.

---

## Quick Start

```bash
# Install
pip install uv
uv pip install specwright

# Initialize in your project
cd /path/to/your/project
spec init

# Compile and run a spec (specwright runs specs; it does not author them)
spec compile aip-1 ./my-feature.md
spec run aip-1 ./my-feature.md --repo . --agent claude-code
```

---

## What It Does

Specwright manages the full lifecycle of AI-assisted development:

1. **Compile** — Parse specs (Markdown or YAML, authored governor-side), then compile against job definitions
2. **Execute** — Run materialized steps through pluggable backends with policy enforcement
3. **Capture** — Record git state, agent output, and assessments for every step
4. **Record** — Emit run/run_step/run_report as governed rows through the storacle gate at finalize
5. **Govern** — Epic-level dependency tracking, LLM checks, and build delta management

### Three Risk Tiers

| Tier | Risk | Gates | Coverage | Use Cases |
|------|------|-------|----------|-----------|
| **A** | High | 5 formal | 90%+ | Security, architecture |
| **B** | Moderate | 5 standard | 85%+ | Features, refactoring |
| **C** | Low | 5 fast-lane | 70%+ | Docs, minor fixes |

### 5-Gate Model

All tiers follow the same workflow with different rigor:

1. **G0: Plan Approval** — WBS, file-touch map
2. **G1: Code Readiness** — Implementation prompts
3. **G2: Pre-Release** — Test coverage, verification
4. **G3: Deployment Approval** — Release readiness
5. **G4: Post-Implementation** — Decision log, compliance

---

## CLI Reference

### Core Workflow

```bash
spec init                                     # Initialize .specwright.yaml + JobDefs
  --force                                     #   overwrite existing
  --no-claude                                 #   skip Claude slash commands
  --governor ~/.local/local-governor          #   custom governor path

spec compile aip-1 ./spec.md                  # Compile JobDef + spec to JobInstance
  --repo /path --branch main                  #   target repo and branch
  --agent claude-code                         #   agent backend
  --models gpt-5.3-codex                      #   model priority list
  --output ./instance.yaml                    #   output path

spec run aip-1 ./spec.md                      # Compile and execute in one step
  --repo /path --branch main                  #   target repo and branch
  --agent copilot --models gpt-5.3-codex      #   agent and model selection
  --dry-run                                   #   preview without executing
  --run-id custom-run-id                      #   custom run identifier

spec execute ./instance.yaml                  # Execute a pre-compiled JobInstance
  --run-id custom-run-id

spec status                                   # Show recent run statuses
  --limit 10

spec logs <run_id>                            # Show run logs
  --patch                                     #   show patch diffs
  --stderr                                    #   show stderr output

spec config --show                            # Display current config
```

### Spec Lifecycle

```bash
spec finish t004-01                           # Apply build delta and close lifecycle
  --dry-run --json                            #   preview in JSON format

spec delta generate t004-01                   # Generate build delta via LLM
  --model gemini-3-pro-preview --yes          #   auto-approve
```

### Epic Management

Epics/specs are authored on the cloud-governor side, not via specwright. The epic
commands below operate on existing epics (status/lifecycle/validation):

```bash
spec epic mark-done e008 --spec e008-01       # Mark spec complete
spec epic status e008                         # Show status with DAG
spec epic list                                # List all epics
spec epic validate e008                       # Validate structure
spec epic check e008                          # Run LLM checks
  --check CHK-001                             #   run specific check
```

### Validation

```bash
spec validate spec ./my-feature.md            # Validate spec structure
  --check --strict

spec validate build myproject                 # Validate build.yaml vs filesystem
  --json --fix                                #   output JSON, auto-fix issues

spec validate epic e008                       # Validate epic consistency
  --json

spec validate contracts                       # Validate op-catalog vs code
  --json
```

---

## Execution Backends

| Backend | Description | Use Case |
|---------|-------------|----------|
| **claude-code** | Claude Code CLI (headless or interactive) | Primary agent for code generation |
| **copilot** | GitHub Copilot CLI (headless or interactive) | Alternative agent backend |
| **cmd** | Shell command execution with sandbox enforcement | Build steps, verification commands |
| **python** | In-process Python callable execution | Validators, assessments, custom logic |
| **llm** | LLM API calls via `llm` package (multi-provider) | Checks, verification, drafting |
| **codex** | OpenAI Codex CLI | Experimental agent backend |

---

## Architecture

### Four-Layer Model

```
L3: Ephemeral     → Claude/Copilot sessions, temporary workspaces
L2: Target Repos  → Multiple repos receiving AIP execution
L1: Specwright    → CLI, compiler, executor, backends
L0: Governed DB   → Run records as rows via the storacle gate (ops__base);
                    bulk in local scratch (~/.local/specwright/runs/);
                    jobdefs synced to ~/.local/local-governor/jobdefs/
```

### Execution Model

```
spec run aip-1 ./my-feature.md
    ↓
compile(JobDef, envelope) → JobInstance
    ↓
execute(JobInstance) → runs steps via backends
    ↓
StepCapture records git state, agent output
    ↓
RunRecord (completed/failed/partial)
    ↓
gated emission at finalize → run/run_step/run_report rows in ops__base
```

### Source Layout

```
src/spec/
├── cli/                   # Typer CLI
│   ├── spec.py            # Main commands (init, compile, run, execute, status, logs)
│   ├── epic.py            # Epic management subcommands
│   ├── finish.py          # Spec lifecycle completion
│   ├── delta.py           # Build delta management
│   ├── governance.py      # Governance commands
│   └── interactive.py     # Interactive UI components
├── compiler/              # Markdown → YAML compilation
│   ├── parser.py          # Token-based MD parser (markdown-it-py)
│   └── compiler.py        # Deterministic YAML generator
├── executor/              # v2 job-based executor
│   ├── engine.py          # Main execution loop
│   ├── jobdefs.py         # Built-in job definitions (aip-1)
│   ├── store.py           # Run artifact storage
│   ├── backends/          # Pluggable backends
│   │   ├── claude_code.py # Claude Code CLI adapter
│   │   ├── copilot.py     # GitHub Copilot CLI adapter
│   │   ├── cmd.py         # Shell command backend
│   │   ├── python.py      # In-process callable backend
│   │   ├── llm.py         # LLM API backend (multi-provider)
│   │   └── codex.py       # OpenAI Codex adapter
│   ├── schemas/           # Pydantic models
│   │   ├── job_def.py     # JobDef, StepTemplate
│   │   ├── job_instance.py # JobInstance, Step, Common
│   │   ├── capture.py     # StepCapture, GitCapture, AgentCapture
│   │   ├── outcome.py     # StepOutcome, OutcomeStatus
│   │   ├── run.py         # RunRecord
│   │   └── manifest.py    # StepManifest
│   └── sandbox/           # Policy enforcement
│       ├── capture.py     # Git state capture
│       └── enforcer.py    # Sandbox policy enforcer
├── governance/            # Governance operations
│   ├── spec_validator.py  # Spec structure validation
│   ├── delta_generator.py # Build delta generation
│   ├── delta_applicator.py # Build delta application
│   ├── epic_updater.py    # Epic updates
│   ├── epic_validator.py  # Epic validation
│   ├── build_validator.py # Build.yaml validation
│   └── contract_validator.py # Contract validation
├── governor/              # L0 local-governor integration
│   ├── locator.py         # Find/validate governor path
│   ├── reader.py          # Read specs/AIPs from governor
│   ├── writer.py          # Write specs, errors, provenance
│   ├── materializer.py    # Copy AIPs to repo workspace
│   ├── targets.py         # Multi-repo target resolution
│   ├── splitter.py        # Split specs into repo-scoped AIPs
│   └── coordinator.py     # Cross-repo execution
├── epic/                  # Epic management
│   ├── schema.py          # Epic, SpecRef, Check dataclasses
│   ├── loader.py          # Load/validate epics
│   ├── writer.py          # Update epics (save, status, history)
│   └── dag.py             # Dependency graph utilities
├── checks/                # LLM-powered checks
│   ├── executor.py        # Check execution engine
│   ├── inputs.py          # Check input resolution
│   └── resolver.py        # Check file resolution
├── llm/                   # LLM integration
│   ├── client.py          # LLM client wrapper
│   ├── config.py          # LLM configuration
│   ├── prompts.py         # Prompt templates
│   └── reporter.py        # LLM output reporting
├── audit/                 # Execution logging
├── runner/                # Background and interactive runners
├── core/                  # Config, exceptions, YAML loading
└── templates/             # Jinja2 spec templates (tier-a/b/c)
```

### Configuration

**`.specwright.yaml`** in project root:
```yaml
version: "0.6"
governor:
  path: ~/.local/local-governor
```

### Storage

Run records are **governed rows**: at finalize, `run`, `run_step`, and
`run_report` objects are emitted through the storacle gate (lorchestra
`object.create`, in-process) to the `ops__base` table, with row-count and
policy-stamp verification. Bulk artifacts never become rows — they live in
local scratch, outside the target repo:

```
~/.local/specwright/runs/{epic_id}/{run_id}/     # SPECWRIGHT_SCRATCH_ROOT override
├── run.yaml               # Consolidated RunRecord
├── run_report.yaml        # Structured report
├── stdout.txt / stderr.txt / changes_final.patch
└── steps/
    ├── step-001.yaml      # Consolidated per-step YAML
    └── step-001/          # Bulk: stdout, stderr, changes.patch
```

There is no silent fallback: if the gate refuses an emission the run fails
loudly (scratch files remain as evidence). `--legacy-output` is the only,
explicit escape hatch that writes the old multi-file tree format instead.

---

<details>
<summary><strong>LLM Orientation</strong></summary>

> This section helps AI assistants understand this codebase quickly.

### Key Types (v2 Executor)

```python
# src/spec/executor/schemas/job_def.py
class JobDef(BaseModel):
    job_id: str               # e.g., "aip-1"
    version: str              # Template version
    steps: list[StepTemplate] # Step templates with @ref expressions
    defaults: dict[str, Any]  # Default values for @payload.* refs

# src/spec/executor/schemas/job_instance.py
class JobInstance(BaseModel):
    job_id: str               # Template this was compiled from
    job_hash: str             # Instance hash for deduplication
    steps: list[Step]         # Materialized steps (no @refs remain)

class Step(BaseModel):
    step_n: int               # Step number (1-indexed)
    step_id: str              # Unique identifier
    backend: Backend          # claude-code, copilot, cmd, python, llm, codex
    common: Common            # repo_path, branch, base_commit, timeout_s
    payload: dict[str, Any]   # Backend-specific payload (fully resolved)

# src/spec/executor/schemas/capture.py
class StepCapture(BaseModel):
    step_n: int
    step_id: str
    git: GitCapture | None    # base_commit, patch_file, changed_files
    agent: AgentCapture | None # stdout_file, stderr_file, exit_code
    assessments: list[dict]   # Structured LLM assessments

# src/spec/executor/schemas/outcome.py
class StepOutcome(BaseModel):
    step_n: int
    step_id: str
    outcome: OutcomeStatus    # completed, failed, timeout, cancelled, skipped
    duration_ms: int
    error: str | None
```

### Core Data Flow

```
spec run aip-1 ./my-feature.md --repo /path --agent claude-code
    ↓
1. Load JobDef template ("aip-1") from jobdefs.py
2. Build envelope from spec file + CLI args
3. compile(JobDef, envelope) → resolve @aip.* and @payload.* refs
4. Produce JobInstance with materialized Steps
    ↓
5. For each Step in JobInstance:
   a. Build StepManifest (step_n, backend, payload, common)
   b. Dispatch to backend (claude_code, copilot, cmd, python, llm)
   c. Capture results (git state, stdout/stderr, exit code)
   d. Record StepOutcome + StepCapture
   e. Check continue_on_failure policy
    ↓
6. Write RunRecord to local scratch store
7. Emit run/run_step/run_report rows through the storacle gate (verified)
8. Exit: 0=completed, 1=failed, 2=partial
```

### Testing

```bash
pytest tests/ -q                    # All tests
pytest tests/executor/ -v           # Executor tests
pytest tests/integration/ -v        # E2E tests
ruff check src/ tests/              # Lint
mypy src/ --ignore-missing-imports  # Type check
```

</details>

---

## Development

```bash
# Setup
git clone https://github.com/benthepsychologist/specwright.git
cd specwright
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Test
pytest tests/ -q
ruff check src/ tests/
mypy src/ --ignore-missing-imports

# Run CLI
spec --help
```

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) file.

---

**Built for rigorous, traceable, human-in-the-loop AI-assisted development.**
