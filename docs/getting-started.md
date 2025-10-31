# Getting Started with Spec

This guide walks you through creating and running your first Agentic Implementation Plan (AIP).

---

## Prerequisites

- Python 3.12 or higher
- pip or poetry for package management
- Git (for repo integration)

---

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/spec-core.git
cd spec-core

# Install dependencies
pip install -e .

# Verify installation
spec --help
```

---

## Quick Start: Your First AIP

### Step 1: Create an AIP

```bash
spec create --tier C --title "Fix README typo" --owner alice
```

This creates a new `aip.yaml` file using the Tier C (low-risk) template.

**Output:**
```
✓ Created C AIP at aip.yaml
  Next steps:
    1. Edit aip.yaml to add description and customize
    2. Run: spec validate aip.yaml
    3. Run: spec run aip.yaml
```

### Step 2: Edit the AIP

Open `aip.yaml` in your editor:

```yaml
# Tier C AIP Template
# Low-risk, fast-lane workflow

metadata:
  title: "Fix README typo"
  description: ""  # REQUIRED: Add description here
  owner: "alice"
  created: "2024-01-15T10:00:00Z"
  risk: "low"

budget:
  max_tokens: 500000
  max_usd: 50.00
  currency: "USD"
```

Add a description:

```yaml
metadata:
  title: "Fix README typo"
  description: "Correct spelling error on line 42 of README.md"
  owner: "alice"
  created: "2024-01-15T10:00:00Z"
  risk: "low"
```

**Note:** For Tier C, you only need to provide minimal metadata. The `plan`, `metrics`, and other fields are inherited from `defaults/tier-C.yaml`.

### Step 3: Validate the AIP

```bash
spec validate aip.yaml
```

**Output:**
```
✓ aip.yaml is valid
```

If there are errors, you'll see helpful messages:

```
✗ Validation failed:
  'description' is a required property
  Path: metadata
```

### Step 4: Run the AIP

```bash
spec run aip.yaml
```

**Output:**
```
============================================================
AIP: Fix README typo
Risk: low
Owner: alice
============================================================

[Step 1/1] AGENT: Implement & Test
  Agent implements and tests solution
  🤖 Agent executing with models: claude-3-5-sonnet
     Tools: pytest, ruff
  Expected outputs: src/**/*.py, tests/**/*.py, test-results.xml
  ⚠  Note: Actual agent execution not yet implemented
  Press ENTER to continue...
```

Press ENTER to proceed through each step. The orchestrator will:
- Display step details
- Wait for human actions (for human steps)
- Request approvals (for gates)
- Simulate agent execution (actual execution coming soon)

---

## Example: Moderate-Risk AIP (Tier B)

### Create the AIP

```bash
spec create --tier B --title "Add user search API" --owner bob
```

### Edit the AIP

```yaml
metadata:
  title: "Add user search API"
  description: "Implement /api/users/search endpoint with pagination and filtering"
  owner: "bob"
  created: "2024-01-15T11:00:00Z"
  risk: "moderate"

budget:
  max_tokens: 1000000
  max_usd: 100.00
  currency: "USD"

# Optional: Override default plan if needed
# plan:
#   - type: "agent"
#     name: "Custom Step"
#     ...
```

### Validate and Run

```bash
spec validate aip.yaml
spec run aip.yaml
```

**Output:**
```
============================================================
AIP: Add user search API
Risk: moderate
Owner: bob
============================================================

[Step 1/4] AGENT: Planning
  Agent creates implementation plan
  🤖 Agent executing with models: claude-3-5-sonnet
  Expected outputs: plan.md
  Press ENTER to continue...

[Step 2/4] GATE: Senior developer reviews plan
  ⏸  Gate: approval required from senior-dev
  Approve? [y/N]: y
  ✓ Gate approved

[Step 3/4] AGENT: Implementation
  Agent implements solution
  🤖 Agent executing with models: claude-3-5-sonnet
     Tools: pytest, ruff
  Expected outputs: src/**/*.py, tests/**/*.py
  Press ENTER to continue...

[Step 4/4] AGENT: Testing
  Agent runs tests and validation
  🤖 Agent executing with models: gpt-4
     Tools: pytest
  Expected outputs: test-results.xml
  Press ENTER to continue...

============================================================
✓ AIP execution complete
============================================================
```

---

## Example: High-Risk AIP (Tier A)

### Create the AIP

```bash
spec create --tier A --title "Implement OAuth2 authentication" --owner security-team
```

### Edit the AIP

```yaml
metadata:
  title: "Implement OAuth2 authentication"
  description: "Add OAuth2 provider integration with PKCE flow for user authentication"
  owner: "security-team"
  created: "2024-01-15T12:00:00Z"
  risk: "high"

budget:
  max_tokens: 2500000
  max_usd: 250.00
  currency: "USD"

# Import security policy pack
policy_packs: ["security.paths"]

# Optional: Customize plan if needed
# Tier A defaults include 7 steps with multiple gates
```

### Validate and Run

```bash
spec validate aip.yaml
spec run aip.yaml
```

Tier A AIPs include:
- **7 steps** (requirements review, design, gate, implementation, testing, gate, deployment)
- **2 gates** (design approval, deployment approval)
- **Higher metrics targets** (95% coverage, 0% override rate)
- **Full audit trail** and compliance tracking

---

## Understanding the Defaults System

AIPs are sparse by design. Most fields come from hierarchical defaults.

### Precedence (Highest → Lowest)

1. **AIP file** (`aip.yaml`) - highest precedence
2. **Tier defaults** (`defaults/tier-{A,B,C}.yaml`)
3. **Project defaults** (`defaults/project.yaml`)
4. **Policy packs** (`policies/*.yaml`)

### Example: What You Write vs. What Gets Executed

**You write:**
```yaml
metadata:
  title: "My Feature"
  risk: "moderate"
budget:
  max_usd: 120.00
```

**System merges with:**
- `tier-B.yaml` (4-step plan, coverage targets, etc.)
- `project.yaml` (repo URL, models, tools, etc.)

**Result:**
```yaml
metadata:
  title: "My Feature"
  risk: "moderate"
version: "0.1"
schema_url: "https://specplatform.org/schemas/aip-v0.1.schema.json"
lifecycle_scope: ["planning", "coding", "testing"]
repo:
  url: "git@github.com:org/spec-core.git"
  default_branch: "main"
budget:
  max_tokens: 1000000
  max_usd: 120.00  # Your override
  currency: "USD"
plan:
  - type: "agent"
    name: "Planning"
    description: "Agent creates implementation plan"
    models: ["claude-3-5-sonnet"]
    output_artifacts: ["plan.md"]
  # ... 3 more steps from tier-B defaults
metrics:
  targets:
    coverage_min: 0.80
    override_rate_max: 0.10
    time_to_green_hours: 24
    defect_density_max: 2.0
  # ... more from tier-B and project defaults
```

---

## Customizing Defaults

### Project-Level Defaults

Edit `defaults/project.yaml`:

```yaml
repo:
  url: "git@github.com:myorg/myproject.git"
  default_branch: "main"

models_tools:
  models: ["claude-3-5-sonnet", "gpt-4"]  # Add models here
  tools: ["pytest", "ruff", "mypy", "bandit"]  # Add tools here

paths:
  protected: ["src/core/**", "infra/**"]
  allowed: ["src/features/**", "tests/**", "docs/**"]
```

These apply to **all AIPs** in your project.

### Tier-Level Defaults

Edit `defaults/tier-B.yaml` to customize Tier B workflow:

```yaml
risk: "moderate"

lifecycle_scope: ["planning", "coding", "testing", "deployment"]  # Add deployment

plan:
  - type: "agent"
    name: "Planning"
    # ... customize steps
  
  # Add new step
  - type: "agent"
    name: "Deployment"
    description: "Agent deploys to staging environment"
    models: ["claude-3-5-sonnet"]
    tools: ["kubectl", "helm"]
    output_artifacts: ["deployment.yaml"]
```

### Policy Packs

Create reusable governance in `policies/`:

**policies/security.paths.yaml:**
```yaml
paths:
  protected:
    - "src/auth/**"
    - "src/security/**"
  
metrics:
  targets:
    coverage_min: 0.95
    override_rate_max: 0.0  # Zero tolerance
```

**Use in AIP:**
```yaml
metadata:
  title: "Security feature"
  risk: "high"

policy_packs: ["security.paths"]  # Import policy
```

---

## Multi-Currency Budgets

Spec supports USD, CAD, and ARS with automatic normalization.

```yaml
budget:
  max_tokens: 1000000
  max_usd: 150.00
  currency: "CAD"  # Canadian dollars
```

Internal normalization uses exchange rates for tracking and reporting.

---

## Next Steps

### Level 1: Foundation (You Are Here)
- ✅ Create AIPs from templates
- ✅ Validate against schema
- ✅ Run with manual execution
- ⏳ Customize defaults for your project

### Level 2: Automation (Coming Soon)
- 🔜 Automated agent execution
- 🔜 GitHub Actions integration
- 🔜 Continuous testing
- 🔜 Coverage tracking

### Level 3: Full Orchestration (Future)
- 🔮 State machine automation
- 🔮 Budget tracking and alerts
- 🔮 Dashboard for AIP monitoring
- 🔮 Notification system (Slack, email)

### Level 4: Continuous Improvement (Future)
- 🔮 Agent performance analytics
- 🔮 Prompt optimization
- 🔮 Cost optimization
- 🔮 Defect prediction

---

## Troubleshooting

### "Import 'yaml' could not be resolved"

Install PyYAML:
```bash
pip install pyyaml
```

### "Import 'jsonschema' could not be resolved"

Install jsonschema:
```bash
pip install jsonschema
```

### "Template not found"

Ensure you're running `spec` from the project root, or the templates are in the expected location:
```
spec-core/
  templates/
    aips/
      tier-a-template.yaml
      tier-b-template.yaml
      tier-c-template.yaml
```

### "Validation failed: 'description' is a required property"

Add a description to your AIP:
```yaml
metadata:
  description: "Detailed description of the work"
```

---

## Resources

- **Methodology:** [Agentsway Implementation Guide](./agentsway-implementation-guide.md)
- **Architecture:** [Spec vs. Forge](./README-spec-vs-forge.md)
- **Schema:** [AIP JSON Schema](../schemas/aip.schema.json)
- **Templates:** [templates/aips/](../templates/aips/)
- **Defaults:** [defaults/](../defaults/)

---

## Community & Support

- **Issues:** [GitHub Issues](https://github.com/yourusername/spec-core/issues)
- **Discussions:** [GitHub Discussions](https://github.com/yourusername/spec-core/discussions)
- **Contributing:** [CONTRIBUTING.md](../CONTRIBUTING.md)

---

Happy specifying! 🚀
