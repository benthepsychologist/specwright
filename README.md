# Specwright

**The architect of agentic workflows.**

Specwright defines, validates, and executes **Agentic Implementation Plans (AIPs)** — human-in-the-loop governance for AI-assisted software development.

---

## LLM Orientation

> This section helps AI assistants understand this codebase quickly.

### What This Repo Does

Specwright is a **CLI tool** that governs AI-assisted development through structured specs:

1. **`spec create`** - Create a Markdown spec from a template (Tier A/B/C)
2. **`spec compile`** - Parse Markdown to validated YAML AIP
3. **`spec validate`** - Schema-validate the compiled AIP
4. **`spec run`** - Execute steps with agent adapters (Claude, Codex)

### Key Architecture

```
src/spec/
├── cli/spec.py              # Typer CLI - all commands defined here
├── compiler/                # Markdown → YAML compilation
│   ├── parser.py            # Token-based MD parser (markdown-it-py)
│   └── compiler.py          # Deterministic YAML generator
├── executor/                # Step execution engine
│   ├── executor.py          # Main executor loop
│   ├── contract.py          # StepContract dataclass
│   └── adapters/            # Agent adapters
│       ├── base.py          # AdapterResult, BaseAdapter
│       ├── claude_adapter.py # Claude CLI integration
│       └── codex_adapter.py # OpenAI Codex (legacy)
├── autogov/                 # Governance integration
│   ├── loader.py            # Loads project.build.yaml from local-governor
│   ├── context_builder.py   # Builds template context from governance
│   └── exceptions.py        # AutogovNotInstalledError, etc.
├── templates/               # Jinja2 spec templates (tier-a/b/c-template.md)
└── core/                    # Shared utilities
    └── loader.py            # YAML loading + defaults merging
```

### Core Data Flows

**Spec Creation with Autogov:**
```
spec create "Feature" --autogov <project> --tier B
    ↓
GovernanceLoader.load_all(project)
    ↓ reads ~/.local/local-governor/projects/<project>/<project>.build.yaml
GovernanceBundle (decisions, rules, policies, patterns, invariants, frozen_paths)
    ↓
SpecContextBuilder.merge_with_template_context()
    ↓
Jinja2 renders tier-b-template.md with governance context
    ↓
.specwright/specs/<slug>.md (with governance section)
```

**Step Execution:**
```
spec run aips/my-aip.yaml --step 1
    ↓
StepExecutor loads AIP + creates StepContract
    ↓
Adapter.execute(contract, workspace) → runs agent
    ↓
PolicyChecker validates scope (allowed_paths, forbidden_paths)
    ↓
Verification commands run (ruff, mypy, pytest)
    ↓
AdapterResult (PASS/FAIL_SCOPE/FAIL_VERIFY/...)
```

### Key Types

```python
# src/spec/autogov/loader.py
@dataclass
class GovernanceBundle:
    project: str              # e.g., "injest"
    source: str               # e.g., "patterns"
    version: str              # e.g., "0.1.0"
    description: str          # Kernel description
    decisions: list[Decision] # ADRs from decisions section
    rules: list[Rule]         # Placement/semantic rules
    policies: list[AppliedPolicy]   # From applies.policies
    patterns: list[AppliedPattern]  # From applies.patterns
    invariants: list[str]     # Kernel invariants
    frozen_paths: list[str]   # Files that shouldn't be modified

# src/spec/executor/contract.py
@dataclass
class StepContract:
    aip_id: str
    step_id: str
    step_index: int
    allowed_paths: list[str]
    forbidden_paths: list[str]
    verification_commands: list[str]
    adapter: AdapterConfig
    max_iterations: int
    governance: GovernanceContext | None

# src/spec/executor/adapters/base.py
@dataclass
class AdapterResult:
    status: str  # PASS, FAIL_SCOPE, FAIL_VERIFY, FAIL_ADAPTER, etc.
    iterations: int
    changed_files: list[str]
    verification_output: str
    error: str | None
```

### Configuration

**`.specwright.yaml`** in project root:
```yaml
version: "0.1"
paths:
  specs: .specwright/specs
  aips: .specwright/aips
user:
  default_owner: myname
  default_tier: B
autogov:
  enabled: true
  source: patterns  # or "org"
```

**Governance Source:** Project build files are loaded from:
- `$LOCAL_GOVERNOR_HOME/projects/<project>/<project>.build.yaml`
- Default: `~/.local/local-governor/projects/...`

### Exit Codes

| Code | Meaning | Exception |
|------|---------|-----------|
| 0 | Success | - |
| 1 | Autogov not installed | `AutogovNotInstalledError` |
| 2 | Governance not found | `GovernanceNotFoundError` |
| 3 | Invalid governance | `GovernanceInvalidError` |
| 4 | Missing config | `RegistryConfigError` |
| 5 | CLI usage error | `CLIUsageError` |

### Testing

```bash
# Run all tests
pytest tests/ -q

# Run specific test files
pytest tests/autogov/test_loader.py -v
pytest tests/cli/test_spec_create.py -v
pytest tests/integration/ -v

# Linting and type checking
ruff check src tests
mypy src --ignore-missing-imports
```

---

## Quick Start

```bash
# Install
pip install uv
uv pip install specwright

# Initialize config in your project
cd /path/to/your/project
spec init

# Create a new spec
spec create "Add OAuth login" --tier B

# With governance from local-governor project
spec create "Add Feature" --autogov myproject --tier B

# Edit the generated Markdown spec, then:
spec compile .specwright/specs/add-oauth-login.md
spec validate .specwright/aips/add-oauth-login.yaml
spec run .specwright/aips/add-oauth-login.yaml
```

---

## Core Concepts

### Three Risk Tiers

| Tier | Risk | Gates | Coverage | Use Cases |
|------|------|-------|----------|-----------|
| **A** | High | 5 formal | 90%+ | Security, architecture |
| **B** | Moderate | 5 standard | 85%+ | Features, refactoring |
| **C** | Low | 5 fast-lane | 70%+ | Docs, minor fixes |

### 5-Gate Model

All tiers follow the same workflow with different rigor:

1. **G0: Plan Approval** - WBS, file-touch map
2. **G1: Code Readiness** - Implementation prompts
3. **G2: Pre-Release** - Test coverage, verification
4. **G3: Deployment Approval** - Release readiness
5. **G4: Post-Implementation** - Decision log, compliance

### Autogov Integration

When `--autogov <project>` is specified, Specwright loads governance from `~/.local/local-governor/projects/<project>/<project>.build.yaml` and injects it into the spec:

- **Applied Policies** - Organization security policies
- **Applied Patterns** - Architectural patterns to follow
- **Architecture Decisions** - ADRs with rationale
- **Rules** - Placement and semantic constraints
- **Invariants** - Kernel invariants that must hold
- **Frozen Paths** - Files that should not be modified

This creates a governance-enriched spec that guides AI agents toward compliant implementations.

---

## CLI Commands

### `spec init`

Initialize specwright in a project:

```bash
spec init                    # Create .specwright.yaml
spec init --autogov          # Enable autogov (prompts for source)
spec init --no-claude        # Skip Claude slash command installation
```

### `spec create`

Create a new spec from template:

```bash
spec create "Feature Title"                    # Uses defaults
spec create "Feature" --tier C --owner alice
spec create "Feature" --autogov myproject      # With governance
```

### `spec compile`

Compile Markdown spec to YAML AIP:

```bash
spec compile .specwright/specs/my-feature.md
spec compile specs/*.md                        # Batch compile
```

### `spec validate`

Validate AIP against schema:

```bash
spec validate .specwright/aips/my-feature.yaml
```

### `spec run`

Execute an AIP:

```bash
spec run                          # Run current AIP
spec run --step 1                 # Run specific step
spec run --step 1 --dry-run       # Preview without executing
spec run --step 1 --allow-dirty   # Allow dirty worktree
```

### `spec set`

Set current spec/AIP:

```bash
spec set spec .specwright/specs/my-feature.md
spec set aip .specwright/aips/my-feature.yaml
```

---

## Project Structure

```
specwright/
├── src/spec/                    # Core implementation
│   ├── cli/spec.py             # CLI commands (Typer)
│   ├── compiler/               # Markdown→YAML compiler
│   ├── executor/               # Step execution engine
│   │   ├── executor.py         # Main loop
│   │   ├── contract.py         # StepContract
│   │   └── adapters/           # Claude, Codex adapters
│   ├── autogov/                # Governance integration
│   │   ├── loader.py           # Loads project.build.yaml
│   │   ├── context_builder.py  # Template context
│   │   └── exceptions.py       # Error types
│   └── templates/              # Jinja2 templates
│
├── config/                      # Configuration
│   ├── templates/              # Tier templates
│   ├── defaults/               # Tier defaults
│   └── schemas/                # JSON Schema
│
├── tests/                       # Test suite
│   ├── autogov/                # Loader, context tests
│   ├── cli/                    # CLI command tests
│   ├── compiler/               # Parser, compiler tests
│   ├── executor/               # Executor tests
│   └── integration/            # E2E tests
│
└── docs/                        # Documentation
```

---

## Development

```bash
# Setup
git clone <repo>
cd specwright
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Test
pytest tests/ -q
ruff check src tests
mypy src --ignore-missing-imports

# Run CLI
spec --help
```

---

## Related Projects

| Project | Purpose |
|---------|---------|
| **local-governor** | Governance registry (project.build.yaml files) |
| **autogov** | Governance SDK (patterns, policies, contracts) |
| **life** | CLI orchestrator using specwright |
| **injest** | Data ingestion with specwright governance |

---

## License

MIT License - see [LICENSE](LICENSE) file.

---

**Built for rigorous, traceable, human-in-the-loop AI-assisted development.**
