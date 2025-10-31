# Spec vs. Forge: Architectural Separation

**TL;DR:** Spec is the meta-engineering orchestration layer. Forge is the Python builder. They're separate, complementary tools.

---

## The Two-Layer Architecture

```
┌─────────────────────────────────────────┐
│         SPEC (Meta-Engineering)         │
│  Creates, validates, and orchestrates   │
│    implementation specifications        │
│  Output: AIPs, execution state, logs    │
└──────────────┬──────────────────────────┘
               │ AIPs
               ▼
┌─────────────────────────────────────────┐
│            ADAPTERS                     │
│  Convert AIPs to builder-specific       │
│      work instructions                  │
└──────────────┬──────────────────────────┘
               │ Build Instructions
               ▼
┌─────────────────────────────────────────┐
│      BUILDERS (Forge, etc.)             │
│  Execute actual code generation,        │
│  testing, deployment                    │
│  Output: Running software               │
└─────────────────────────────────────────┘
```

---

## Spec: The Meta-Engineering Layer

**Purpose:** Create and orchestrate implementation plans

**What it does:**
1. **Creates AIPs** from templates (Tier A/B/C)
2. **Validates AIPs** against JSON schema
3. **Runs AIPs** through state machine orchestration
4. **Tracks execution** (state, logs, metrics)
5. **Manages gates** (human approvals, checkpoints)

**What it outputs:**
- Agentic Implementation Plans (AIPs)
- Execution state (state.json)
- Audit logs (JSONL)
- Metrics (coverage, cost, time)

**What it doesn't do:**
- Generate code
- Run tests
- Deploy infrastructure
- Execute builds

**Tech stack:**
- Python 3.12+
- YAML (AIP format)
- JSON Schema (validation)
- Typer (CLI)
- State machine (orchestration)

**Key files:**
- `spec.py` - CLI (create, validate, run)
- `loader.py` - Defaults merging
- `aip.schema.json` - AIP structure definition
- `templates/` - Tier templates
- `defaults/` - Hierarchical defaults

---

## Forge: The Python Builder

**Purpose:** Build and deploy Python projects

**What it does:**
1. **Generates Python code** from specifications
2. **Runs tests** (pytest, coverage)
3. **Lints and formats** (ruff, mypy)
4. **Builds packages** (setuptools, poetry)
5. **Deploys** (Docker, K8s, cloud platforms)

**What it consumes:**
- Build instructions from adapters
- Configuration from AIPs (via adapter translation)

**What it outputs:**
- Python source code
- Test results
- Built packages (wheels, sdists)
- Deployment artifacts

**Tech stack:**
- Python 3.12+
- pytest, ruff, mypy
- setuptools/poetry
- Docker, K8s (optional)

**Key patterns:**
- Convention over configuration
- Sensible defaults for Python projects
- Multi-environment support (dev, staging, prod)

---

## The Adapter Layer

**Purpose:** Translate AIPs into builder-specific instructions

**Example: Forge Adapter**

**Input (AIP excerpt):**
```yaml
plan:
  - type: "agent"
    name: "Implementation"
    models: ["claude-3-5-sonnet"]
    tools: ["pytest", "ruff", "mypy"]
    output_artifacts: ["src/**/*.py", "tests/**/*.py"]
```

**Output (Forge instructions):**
```json
{
  "action": "generate_code",
  "model": "claude-3-5-sonnet",
  "quality_checks": ["pytest", "ruff", "mypy"],
  "output_paths": {
    "source": "src/",
    "tests": "tests/"
  },
  "validation": {
    "min_coverage": 0.80,
    "lint_severity": "error"
  }
}
```

**Responsibilities:**
- Parse AIP structure
- Extract relevant fields for builder
- Apply builder-specific defaults
- Handle builder-specific quirks

**Adapter types:**
- `ForgeAdapter` - Python projects
- `NextAdapter` - Next.js projects (future)
- `ViteAdapter` - Vite projects (future)
- `TerraformAdapter` - Infrastructure (future)

---

## Why Separate?

### 1. Single Responsibility
- **Spec:** Orchestration, governance, workflow
- **Forge:** Code generation, testing, building

### 2. Technology Independence
- Spec can orchestrate any builder (Python, JS, Go, Rust)
- Forge can be used standalone or via Spec
- Adapters handle impedance matching

### 3. Evolution Speed
- Spec evolves with methodology (Agentsway, governance)
- Forge evolves with Python ecosystem (tools, frameworks)
- Decoupled release cycles

### 4. Composition
- One Spec instance can orchestrate multiple builders
- One AIP can span multiple builders (e.g., Python backend + Next.js frontend)

### 5. Testing & Validation
- Spec tested for orchestration correctness
- Forge tested for build quality
- Clear boundaries = easier testing

---

## Interaction Patterns

### Pattern 1: Spec Orchestrates Forge

**User workflow:**
```bash
# Create AIP
spec create --tier B --title "Add search API"

# Edit AIP (add details, customize)
vim aip.yaml

# Validate AIP
spec validate aip.yaml

# Run AIP (Spec orchestrates, calls Forge via adapter)
spec run aip.yaml
```

**Behind the scenes:**
1. Spec loads and validates AIP
2. Spec merges with defaults
3. Spec executes step 1: Planning (agent)
4. Spec executes step 2: Gate (human approval)
5. Spec executes step 3: Implementation (agent)
   - Spec calls ForgeAdapter with step details
   - ForgeAdapter translates to Forge instructions
   - Forge generates code, runs tests
   - Forge returns results to adapter
   - Adapter returns results to Spec
6. Spec logs results, updates state
7. Spec executes step 4: Testing (agent)
   - Similar flow via adapter
8. Spec marks AIP as succeeded

### Pattern 2: Forge Standalone

**User workflow:**
```bash
# Use Forge directly without Spec
forge init my-project --template fastapi
cd my-project
forge generate model User
forge test
forge build
```

**Use case:** Developers who want a Python builder without full orchestration

### Pattern 3: Hybrid

**User workflow:**
```bash
# Use Spec for high-risk work (orchestration)
spec run production-deploy.yaml

# Use Forge standalone for quick iteration
forge generate endpoint /api/search
forge test tests/test_search.py
```

---

## When to Use Which?

### Use Spec When:
- ✅ Multi-step workflows with gates
- ✅ High-risk or compliance-critical work
- ✅ Need audit trails and governance
- ✅ Coordinating multiple builders/tools
- ✅ Budget tracking and cost control
- ✅ Team collaboration with approvals

### Use Forge When:
- ✅ Building Python projects (standalone)
- ✅ Quick prototypes or experiments
- ✅ Local development iteration
- ✅ CI/CD pipelines (direct integration)

### Use Both When:
- ✅ Production systems with governance needs
- ✅ Mix of high-risk and low-risk work
- ✅ Want orchestration for some work, speed for others

---

## Future: Multi-Builder AIPs

**Example: Full-stack AIP**
```yaml
metadata:
  title: "User authentication system"
  risk: "high"

plan:
  - type: "agent"
    name: "Backend API"
    builder: "forge"  # Use Forge for Python
    output_artifacts: ["backend/src/**/*.py"]
  
  - type: "agent"
    name: "Frontend UI"
    builder: "next"  # Use Next.js builder
    output_artifacts: ["frontend/src/**/*.tsx"]
  
  - type: "agent"
    name: "Infrastructure"
    builder: "terraform"  # Use Terraform builder
    output_artifacts: ["infra/**/*.tf"]
  
  - type: "gate"
    approver: "devops-lead"
    description: "Review full stack before deployment"
```

Spec orchestrates all three builders via their respective adapters.

---

## Summary

| Aspect | Spec | Forge |
|--------|------|-------|
| **Purpose** | Orchestration | Building |
| **Input** | User intent, methodology | Build instructions |
| **Output** | AIPs, state, logs | Code, tests, packages |
| **Scope** | Meta-engineering | Python projects |
| **Users** | Teams, governance roles | Developers |
| **Standalone?** | Yes (orchestrates others) | Yes (can be used alone) |
| **Integration** | Via adapters | Via CLI or API |

**Key insight:** Spec doesn't build software—it creates and orchestrates the plans for building software. Forge (and other builders) do the actual building.

This separation allows Spec to be language-agnostic while Forge specializes in Python excellence.
