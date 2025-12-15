# Specwright

**The architect of agentic workflows.**

Specwright defines, validates, and executes **Agentic Implementation Plans (AIPs)** — human-in-the-loop governance for AI-assisted software development.

> _Specwright defines. Dogfold builds. Gorch orchestrates. LifeOS lives._

---

## What is Specwright?

Specwright is a **meta-engineering orchestration layer** that ensures AI-driven development is:
- **Traceable**: Every decision logged, every gate validated
- **Tiered**: Governance scales with risk (Tier A/B/C)
- **Human-friendly**: Write specs in Markdown, execute validated YAML
- **Compliant**: Aligned with ISO 42001 and NIST AI RMF

**You write the plan. Specwright ensures it's rigorous.**

---

## 🎯 Quick Start

```bash
# Install
pip install uv
uv pip install specwright

# Initialize config in your project
cd /path/to/your/project
spec init

# Create a new spec (generates Markdown by default)
spec create --tier B --title "Add OAuth login" --owner alice --goal "Implement secure authentication"

# Edit the generated Markdown spec
# specs/add-oauth-login.md

# Compile Markdown to validated YAML
spec compile specs/add-oauth-login.md

# Validate the compiled AIP
spec validate aips/add-oauth-login.yaml

# Execute the plan in guided mode with interactive gate approvals
spec run aips/add-oauth-login.yaml

# View gate approvals
spec gate-list          # List all approvals
spec gate-report        # Summary statistics
```

**Power users:** Use `--yaml` flag to generate YAML directly:
```bash
spec create --tier B --title "Quick Fix" --owner bob --goal "Hotfix production bug" --yaml
# Edits aips/quick-fix.yaml directly, skipping Markdown
```

---

## 🌟 The Ecosystem

Specwright is part of a larger experimental toolchain:

| Tool | Purpose | Status |
|------|---------|--------|
| **Specwright** | Defines AIPs, enforces governance | Alpha (v0.5.0) |
| **Dogfold** | Recursive Python scaffolding | Experimental |
| **Gorch** | Google Cloud orchestration | Future |
| **LifeOS** | Personal operating system | Future |

> **Note:** All tools in this ecosystem are early-stage and actively evolving. Specwright is functional but should be considered alpha software.

---

## 📚 Core Concepts

### Why Specwright?

**The problem**: AI tools generate code fast, but lack governance, traceability, and risk management.

**The solution**: Specwright introduces **tiered governance**:

### Three Risk Tiers

All work follows the same workflow, but governance rigor scales with risk:

| Tier | Risk Level | Gates | SLA | Coverage | Use Cases |
|------|-----------|-------|-----|----------|-----------|
| **A** | High | 5 formal gates | 24-72h | 90%+ | Security/compliance/architecture changes |
| **B** | Moderate | 5 standard gates | 8-48h | 85%+ | Feature development, refactoring |
| **C** | Low | 5 fast-lane gates (4 auto-approved) | 1-24h | 70%+ | Documentation, utilities, minor fixes |

**Key principle**: *The tiers modulate rigor, not sequence.* 

**Same workflow, different rigor.** All tiers follow the canonical 5-gate model:

1. **Planning** [G0: Plan Approval]
2. **Prompt Engineering** [G1: Code Readiness]
3. **Implementation** [G3: Deployment Approval]
4. **Testing** [G2: Pre-Release]
5. **Governance** [G4: Post-Implementation]

### Human-Friendly Workflow

**Write specs in Markdown, execute validated YAML:**

```
specs/                          # Human-authored specifications
├── my-feature.md              # Write here! (Markdown)
└── my-feature.compiled.yaml   # Generated (don't edit)

aips/                          # Validated AIPs ready for execution
└── AIP-2025-10-31-001.yaml    # Promoted from compiled spec
```

This separation ensures:
- **Humans collaborate in Markdown** (easy to read/write/review)
- **Machines execute YAML** (validated, deterministic)
- **Git tracks both** (spec shows intent, AIP shows execution)

---

## 🛠️ CLI Commands

### `spec new`

Create a new Markdown specification from tier template.

```bash
spec new --tier <A|B|C> --title "Task title" --owner "Your Name" --goal "What we're building"

# Interactive prompts
spec new

# Specify output path
spec new --tier B --title "Add feature" --owner alice --goal "Implement X" --output custom/path.md
```

**Output**: Human-editable Markdown spec with:
- YAML frontmatter (tier, title, owner, goal)
- Structured sections (Objective, Context, Plan, etc.)
- Step templates with gates, prompts, commands, outputs

### `spec compile`

Compile Markdown spec to validated YAML AIP.

```bash
spec compile specs/my-feature.md

# Specify output path
spec compile specs/my-feature.md --output custom/output.yaml

# Force overwrite if compiled file exists
spec compile specs/my-feature.md --overwrite
```

**What it does**:
- Parses Markdown using markdown-it-py (robust token-based parsing)
- Validates frontmatter, sections, plan steps
- Checks output paths are within repo bounds
- Generates canonical YAML with source hash
- Round-trip guard: fails if existing compiled file differs (unless `--overwrite`)

**Output includes**:
```yaml
meta:
  source_md_path: specs/my-feature.md
  source_md_rel: specs/my-feature.md
  source_md_sha256: "abc123..."
  compiler_version: spec-compiler/0.1.0
  compiled_at: null  # intentionally null for determinism
  tier: B
  title: "My Feature"
  # ...
```

### `spec validate`

Validate AIP against JSON schema with tier defaults merged.

```bash
spec validate specs/my-feature.compiled.yaml
spec validate aips/AIP-2025-10-31-001.yaml
```

**What it checks**:
- Schema compliance (required fields, types, constraints)
- Tier-specific requirements (coverage targets, gate structure)
- Path safety (no escaping repo root)
- Gate references (G0-G4 only)

### `spec run`

Execute an AIP in guided mode with interactive gate approvals.

```bash
# Interactive execution with gate approvals
spec run

# Run specific step with agentic execution
spec run --step 1

# Dry run (write input bundle, don't execute)
spec run --step 1 --dry-run

# Allow execution on dirty worktree
spec run --step 1 --allow-dirty
```

**What it does**:
- Displays each step with role, prompts, commands, outputs
- Shows interactive gate checkpoints with checklists (Tier A/B)
- Prompts for approval decisions (Approve/Reject/Defer/Conditional)
- Logs all approvals to audit trail (`.aip_artifacts/{AIP_ID}/gate_approvals.jsonl`)
- Blocks execution on rejection or deferral
- Tier C gates auto-approve with logging

**Agentic Step Execution** (`spec run --step N`):

When running a specific step, the executor orchestrates the agent with strict scope enforcement:

```bash
# Happy path: agent produces valid patch within scope
$ spec run --step 1
[AIP-oauth-2024-001] Running step step-001: Add OAuth config
Baseline: abc123
Invoking codex adapter...
Patch applied: src/auth/oauth.py, src/auth/config.py
Scope check: PASSED (2 files, 0 violations)
Verification: PASSED (3/3 commands)
Step completed: PASS

# Where to look:
runs/AIP-oauth-2024-001/2024-12-15T10-30-00/step-001/
├── result.json          # {"termination_reason": "PASS", ...}
├── gate.md              # Human-readable summary
├── input/
│   ├── contract.yaml    # Scope constraints
│   └── prompt.md        # Agent prompt
└── iter-0/
    ├── output/
    │   ├── patch.diff   # Agent's output
    │   └── agent.json   # Status, notes
    └── policy_report.json
```

```bash
# Failure path: agent touches file outside allowed_paths
$ spec run --step 1
[AIP-oauth-2024-001] Running step step-001: Add OAuth config
Baseline: abc123
Invoking codex adapter...
Patch applied: src/auth/oauth.py, config/secrets.yaml
Scope check: FAILED
  - config/secrets.yaml: not in allowed paths (src/**)

Step failed: FAIL_SCOPE (exit code 1)

# Diagnose at:
runs/AIP-oauth-2024-001/2024-12-15T10-31-00/step-001/
├── result.json          # {"termination_reason": "FAIL_SCOPE", ...}
├── gate.md              # Shows violation details
└── iter-0/
    └── policy_report.json  # {"passed": false, "violations": [...]}
```

**Exit codes**:
- `0` = PASS
- `1` = FAIL_SCOPE, FAIL_PATCH_APPLY, FAIL_VERIFY_*, FAIL_ADAPTER_*, GATE_REJECTED
- `2` = ESCALATE_NEEDS_HUMAN, ESCALATE_AMBIGUOUS, GATE_DEFERRED

**Note:** Runner verification is authoritative; agent `cmdlog.txt` is advisory (for audit, not enforcement).

See [docs/EXECUTOR.md](docs/EXECUTOR.md) for the full lifecycle and invariants.

**Approval Decisions** (guided mode):
- **Approved** - Proceed to next step
- **Rejected** - Halt execution with rationale
- **Deferred** - Pause for review (resume with `--step`)
- **Conditional** - Approve with conditions

### `spec gate-list`

List all gate approvals from audit trail.

```bash
spec gate-list
```

Shows: step ID, gate ref, decision, reviewer, timestamp, rationale, conditions

### `spec gate-report`

Generate summary statistics of gate approvals.

```bash
spec gate-report
```

Shows: total approvals, breakdown by decision type, per-gate statistics

### `spec diff`

Show semantic diff between Markdown and compiled YAML.

```bash
spec diff specs/my-feature.md

# Detailed output
spec diff specs/my-feature.md --verbose
```

Useful for:
- Catching compilation drift
- Reviewing changes before commit
- Validating round-trip integrity

---

## 📐 Design Principles

### 1. Markdown-First Authoring

**Humans write in Markdown. Machines execute YAML.**

**Why Markdown?**
- Human-readable and writable
- Great for collaboration (Git diffs, PR reviews)
- Natural section structure (H2/H3 headings)
- Easy to template with Jinja2

**Why not edit YAML directly?**
- YAML is verbose and error-prone for humans
- Hard to review in PRs
- Machine format should be generated, not authored

### 2. Deterministic Compilation

Every compilation is **reproducible and verifiable**:

**What it does**:

- **Canonical YAML ordering**: sorted keys, no anchors/aliases
- **Source hash tracking**: `source_md_sha256` for integrity
- **Null timestamps**: `compiled_at: null` for bit-identical output
- **Round-trip guard**: fails if recompiling produces different output

This enables:
- Git-friendly diffs (no spurious changes)
- Pre-commit hooks (enforce MD/YAML sync)
- Audit trails (hash verification)

**Compiled YAML includes**:

```yaml
meta:
  source_md_path: specs/user-auth.md
  source_md_sha256: "abc123..."
  compiler_version: "spec-compiler/0.1.0"
  compiled_at: null  # intentionally null for determinism
  tier: "B"
```

### 3. Governance as Code

AIPs aren't just checklists — they're **executable governance contracts**:

- **Schema-validated** (JSON Schema)
- **Tier-aware defaults**
- **Gate approvals enforced**
- **Metrics tracked** (coverage, defects, budget)

### 4. Token-Based Markdown Parsing

Uses **markdown-it-py** instead of regex:

- Handles nested code blocks correctly
- Robust against edge cases (backticks in headings, etc.)
- Proper token tree for precise extraction
- Extensible for future enhancements

### 5. Tiered Governance, Not Tiered Workflows

**Same workflow for all tiers**, different governance:

- **Tier A**: All gates require human approval (24-72h SLAs)
- **Tier B**: Standard approval process (8-48h SLAs)
- **Tier C**: Most gates auto-approved (1-24h SLAs, only G2 requires human)

This ensures:
- Process integrity (no skipped steps)
- Flexibility (adjust rigor to risk)
- Auditability (all tiers traceable)

### 6. Schema Validation with Defaults Merging

AIPs can be **sparse** (only specify what differs from tier defaults):

```yaml
# In your compiled AIP (minimal)
meta:
  tier: B
  title: "My Feature"
# ...

# At validation time, merged with tier-B defaults:
gates:
  - gate_id: G0-plan-approval
    approver_role: "Tech Lead + Peer"
    # ... all default gate config
```

This keeps specs concise while ensuring complete validation.

---

## 📖 Learn More

- **[Agentsway Implementation Guide](docs/agentsway-implementation-guide.md)** - Core principles and governance framework
- **[Getting Started](docs/getting-started.md)** - 5-minute walkthrough
- **[Templates](config/templates/specs/)** - Tier-specific Markdown templates
- **[Schema](config/schemas/aip.schema.json)** - JSON Schema for AIP validation
- **[Defaults](config/defaults/)** - Tier-specific default configurations
- **[Contributing](CONTRIBUTING.md)** - How to contribute to Specwright

---

## 🏗️ Project Structure

```
specwright/
├── src/spec/                    # Core implementation
│   ├── cli/spec.py             # CLI commands
│   ├── compiler/               # Markdown→YAML compiler
│   │   ├── parser.py           # Token-based MD parser
│   │   └── compiler.py         # Deterministic YAML generator
│   └── core/                   # Shared utilities
│       └── loader.py           # YAML loading + defaults merging
│
├── config/                      # Configuration
│   ├── templates/
│   │   ├── specs/              # Markdown templates (tier-a/b/c)
│   │   └── aips/               # YAML templates (legacy)
│   ├── defaults/               # Tier defaults (tier-A/B/C.yaml)
│   ├── schemas/                # JSON Schema for validation
│   └── policies/               # Reusable policy packs
│
├── specs/                       # Human-authored Markdown specs
├── aips/                        # Validated AIPs (YAML)
├── docs/                        # Documentation
├── tests/                       # Test suite
│   ├── compiler/
│   │   └── golden/             # Golden test snapshots
│   └── integration/
│
├── pyproject.toml              # Project configuration
└── README.md                   # This file
```

---

## 🧪 Testing

```bash
# Run linter
ruff check src/ tests/

# Type checking
mypy src/

# Unit tests
pytest tests/

# Golden tests (snapshot-based)
pytest tests/compiler/golden/ -v

# Integration tests
pytest tests/integration/ -v
```

### Pre-commit Hook

Enforce MD/YAML sync:

```bash
# .git/hooks/pre-commit
#!/bin/bash
for md in specs/*.md; do
    yaml="${md%.md}.compiled.yaml"
    if [ -f "$yaml" ]; then
        spec diff "$md" || exit 1
    fi
done
```

---

## 🔄 Workflow Example

### 1. Create a Tier B feature spec

```bash
spec new --tier B --title "Add OAuth login" --owner alice --goal "Implement Google OAuth"
```

**Generated**: `specs/add-oauth-login.md`

### 2. Edit the spec

```markdown
---
tier: B
title: Add OAuth login
owner: alice
goal: Implement Google OAuth
---

# Add OAuth login

## Objective

Add Google OAuth 2.0 authentication flow to allow users to sign in with their Google accounts.

## Acceptance Criteria

- [ ] Users can click "Sign in with Google"
- [ ] OAuth callback handles authorization code
- [ ] User profile synced to local database
- [ ] Session management with JWT
- [ ] 85% test coverage achieved

## Context

### Background

Current email/password auth is limiting adoption. Users expect social login.

### Constraints

- Must use Google's official OAuth 2.0 library
- Store only necessary user data (email, name, profile picture)
- GDPR compliant (user can revoke access)

## Plan

### Step 1: Planning [G0: Plan Approval]

**Prompt:**

Create detailed WBS for OAuth integration:
- Frontend: Google Sign-In button + callback page
- Backend: OAuth flow, token exchange, user provisioning
- Database: user table updates for OAuth identifiers
- Security: CSRF protection, state validation

**Outputs:**

- `artifacts/plan/wbs.md`
- `artifacts/plan/security-checklist.md`

### Step 2: Prompt Engineering [G1: Code Readiness]

**Prompt:**

Generate implementation prompts for:
- Frontend: React component with Google OAuth SDK
- Backend: FastAPI endpoints for /auth/google/callback
- Database migrations for oauth_provider, oauth_id fields

**Outputs:**

- `artifacts/prompts/frontend-prompts.md`
- `artifacts/prompts/backend-prompts.md`

### Step 3: Implementation [G3: Deployment Approval]

**Commands:**

```bash
ruff .
mypy .
pytest -q
```

**Outputs:**

- `artifacts/code/release-notes.md`
- `artifacts/code/runbook.md`

### Step 4: Testing [G2: Pre-Release]

**Commands:**

```bash
pytest --cov=src --cov-report=xml
```

**Outputs:**

- `artifacts/test/coverage.xml`

### Step 5: Governance [G4: Post-Implementation]

**Outputs:**

- `artifacts/governance/decision-log.md`
- `artifacts/governance/privacy-checklist.md`

## Models & Tools

**Tools:** bash, pytest, ruff, mypy

## Repository

**Branch:** `feat/add-oauth-login`

**Merge Strategy:** squash
```

### 3. Compile and validate

```bash
spec compile specs/add-oauth-login.md
spec validate specs/add-oauth-login.compiled.yaml
```

### 4. Execute

```bash
# Interactive guided execution
spec run specs/add-oauth-login.compiled.yaml

# Or preview first
spec run specs/add-oauth-login.compiled.yaml --plan
```

### 5. Promote to AIP (optional)

```bash
spec promote specs/add-oauth-login.md --to aips/
```

**Output**: `aips/AIP-2025-10-31-001.yaml` (immutable release artifact)

---

## 🎓 Learning Resources

### For New Users

1. Read [Agentsway Implementation Guide](docs/agentsway-implementation-guide.md)
2. Try creating a Tier C spec: `spec new --tier C`
3. Review the generated Markdown template
4. Compile and run through the workflow

### For Contributors

1. Read [Spec Compilation Guide](docs/spec-compilation.md)
2. Review [compiler implementation](src/spec/compiler/)
3. Run golden tests: `pytest tests/compiler/golden/ -v`
4. Check [open issues](https://github.com/yourusername/spec-core/issues)

---

## 🎨 The Story

Specwright was built to solve a real problem: **How do you govern AI-driven development without crushing velocity?**

The answer: **Tiered governance**. Not every change needs a 72-hour review cycle. Documentation updates can fast-lane with auto-approved gates. Security changes get formal sign-offs.

**Specwright ensures the right rigor for the right risk.**

It's part of a larger ecosystem:
- **Specwright** defines the governance framework
- **Dogfold** learns from builds and scaffolds recursively
- **Gorch** orchestrates on Google Cloud
- **LifeOS** presents it all to humans

This is meta-engineering: **tools that build the builders, then build the world.**

---

## 🚀 Roadmap

### v0.5.0 (Current)
- ✅ Markdown-first authoring with Jinja2 templates
- ✅ Deterministic compilation with source hash tracking
- ✅ Token-based Markdown parsing with gate review blocks
- ✅ Round-trip validation and diff detection
- ✅ Tier-specific governance with 5-gate model
- ✅ Schema validation with defaults merging
- ✅ Interactive gate approvals with questionary + rich
- ✅ HITL gate checkpoints with approval workflows
- ✅ Full audit trail logging (JSONL format)
- ✅ Gate management commands (gate-list, gate-report)
- ✅ Validation checkpoints alongside formal gate reviews

### v0.4.0 (Next Quarter)
- [ ] Rename to `specwright` package
- [ ] Actual agent execution (replace checklist mode)
- [ ] State persistence (`.aip_artifacts/state.json`)
- [ ] Automated gate approvals (Slack/email integration)
- [ ] Metrics tracking (budget, coverage, time-to-green)
- [ ] Integration with Dogfold scaffolding

### v1.0.0 (Future)
- [ ] Multi-agent orchestration
- [ ] Policy enforcement engine
- [ ] Compliance reporting (ISO 42001, NIST AI RMF)
- [ ] Web UI for spec management
- [ ] Full Gorch integration (Google Cloud orchestration)

---

## 🤝 Contributing

Contributions welcome! Please:

1. Read [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines
2. See [DEVELOPMENT.md](DEVELOPMENT.md) for local development workflow (dogfooding while building)
3. Check [open issues](https://github.com/yourusername/spec-core/issues)
4. Submit PRs against `main` branch
5. Ensure tests pass: `pytest tests/`
6. Run linter: `ruff check src/`

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Agentsway Implementation Guide** - Governance framework foundation
- **ISO 42001:2023** - AI management system standards
- **NIST AI RMF 1.0** - Risk management framework
- **Dogfold** - Recursive scaffolding partner
- **Gorch** - Google Cloud orchestration layer

---

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/specwright/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/specwright/discussions)
- **Email**: bfarmstrong@example.com

---

**Built with ❤️ for rigorous, traceable, human-in-the-loop AI-assisted development.**

_Specwright defines. Dogfold builds. Gorch orchestrates. LifeOS lives._