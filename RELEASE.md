# Specwright v0.3.0 - Initial Release

**Release Date**: October 31, 2025  
**Package Name**: `specwright`  
**CLI Command**: `spec`

---

## 🎯 What is Specwright?

**Specwright** - "The architect of agentic workflows"

A meta-engineering orchestration layer for defining, validating, and executing Agentic Implementation Plans (AIPs) with human-in-the-loop governance.

**Ecosystem Positioning**:
> _Specwright defines. Dogfold builds. Gorch orchestrates. LifeOS lives._

---

## 🌟 Core Features

### Markdown-First Authoring

Write specs in human-friendly Markdown, compile to machine-executable YAML:

```bash
spec new --tier B --title "Add OAuth" --owner alice
# Edit specs/add-oauth.md (human-friendly Markdown)
spec compile specs/add-oauth.md
# Generates specs/add-oauth.compiled.yaml (machine-executable)
```

### 5-Gate Governance Model

All tiers follow the canonical 5-gate workflow:
- **G0**: Plan Approval
- **G1**: Code Readiness  
- **G2**: Pre-Release
- **G3**: Deployment Approval
- **G4**: Post-Implementation

**Tier A**: All gates require formal approval (24-72h SLAs)  
**Tier B**: Standard peer review (8-48h SLAs)  
**Tier C**: Auto-approved except G2 (1-24h SLAs)

### Deterministic Compilation

Every MD→YAML compilation is:
- **Reproducible**: Same input = same output
- **Traceable**: Source hash tracking (`source_md_sha256`)
- **Validated**: Round-trip checks prevent drift

### CLI Commands

```bash
spec new       # Create spec from tier template
spec compile   # MD → YAML with validation
spec validate  # Schema validation + defaults merge
spec run       # Guided execution (checklist mode)
```

---

## 📦 Package Info

### Installation

```bash
# From source (until PyPI published)
cd specwright
make dev

# After PyPI publish
pip install specwright
```

### Key Files

- **`README.md`**: Complete ecosystem overview
- **`CONTRIBUTING.md`**: Contributor guide with pre-commit hooks
- **`CHANGELOG.md`**: Full release history
- **`PYPI.md`**: PyPI publishing guide
- **`COMMIT-CHECKLIST.md`**: Pre-commit verification

### Templates

- `config/templates/specs/tier-a-template.md`
- `config/templates/specs/tier-b-template.md`
- `config/templates/specs/tier-c-template.md`

All use Jinja2 variables: `{{ title }}`, `{{ owner }}`, `{{ goal }}`, `{{ branch }}`

---

## 🏗️ Architecture

```
specwright/
├── src/spec/                 # Core (rename to specwright/ in v0.4.0)
│   ├── cli/spec.py          # CLI commands
│   ├── compiler/            # MD→YAML compilation
│   │   ├── parser.py        # Token-based MD parsing
│   │   └── compiler.py      # Deterministic YAML generation
│   └── core/loader.py       # YAML + defaults merging
│
├── config/
│   ├── templates/specs/     # Tier templates (Markdown)
│   ├── defaults/            # Tier defaults (YAML)
│   └── schemas/             # JSON Schema validation
│
├── .github/workflows/       # CI/CD
│   ├── test.yml            # Run tests on PR
│   └── publish.yml         # Auto-publish to PyPI
│
└── docs/                    # Documentation
```

---

## 🎨 Design Principles

1. **Markdown-First**: Humans write MD, machines execute YAML
2. **Deterministic**: Reproducible builds with hash tracking
3. **Tiered Governance**: Same workflow, different rigor
4. **Governance as Code**: Schema-validated, executable contracts
5. **Traceable**: Full audit trail from plan to execution

---

## 🚀 Next Steps (v0.4.0)

- [ ] Rename `src/spec/` → `src/specwright/`
- [ ] Actual agent execution (replace checklist mode)
- [ ] State persistence (`.aip_artifacts/state.json`)
- [ ] Automated gate approvals (Slack/email)
- [ ] Metrics tracking dashboard
- [ ] Integration with Dogfold scaffolding

---

## 📚 Documentation

- **Quick Start**: See README.md "Quick Start" section
- **Full Workflow**: See README.md "Workflow Example"
- **Contributing**: See CONTRIBUTING.md
- **PyPI Publishing**: See PYPI.md
- **Agentsway Guide**: See docs/agentsway-implementation-guide.md

---

## 🎯 PyPI Strategy

### Namespaces to Claim

1. **`specwright`** ✅ - Publish immediately (v0.3.0)
2. **`dogfold`** 🎯 - Reserve with placeholder
3. **`gorch`** 🎯 - Reserve with placeholder
4. **`lifeos`** 🎯 - Reserve with placeholder (optional)

### Publishing Steps

1. Get PyPI API token
2. Add to GitHub secrets: `PYPI_API_TOKEN`
3. Create GitHub release for `v0.3.0`
4. GitHub Actions auto-publishes to PyPI
5. Verify: `pip install specwright && spec --help`

---

## ✅ Quality Checklist

### Before First Commit
- [ ] Run `make lint` - no errors
- [ ] Run `make typecheck` - no errors
- [ ] Test CLI: `spec new`, `spec compile`, `spec validate`
- [ ] Verify templates render correctly

### Before GitHub Release
- [ ] Tag created: `v0.3.0`
- [ ] CHANGELOG updated
- [ ] README complete
- [ ] All documentation consistent

### After PyPI Publish
- [ ] Package visible: https://pypi.org/project/specwright/
- [ ] `pip install specwright` works
- [ ] `spec --help` shows correct version
- [ ] README badges updated (if any)

---

## 📣 Announcement Text

### GitHub Release

```markdown
# Specwright v0.3.0 - The Architect of Agentic Workflows

**First public release of Specwright** - a meta-engineering orchestration layer for AI-driven development.

## What's Included

- 🎨 **Markdown-First Authoring**: Write human-friendly specs, compile to validated YAML
- 🏗️ **5-Gate Governance**: G0 through G4, tiered by risk
- 🔒 **Deterministic Compilation**: Source hash tracking, reproducible builds
- 📐 **Tier Templates**: Jinja2-based templates for A/B/C tiers
- ✅ **Full Validation**: Round-trip checks, schema validation

Part of the ecosystem:
> _Specwright defines. Dogfold builds. Gorch orchestrates. LifeOS lives._

See CHANGELOG.md for full details.
```

### Social Media

```
🚀 Launching Specwright v0.3.0!

The architect of agentic workflows. Write specs in Markdown, execute with governance.

✅ Tiered risk controls (A/B/C)
✅ 5-gate model (G0-G4)
✅ Deterministic compilation
✅ ISO 42001 & NIST AI RMF aligned

Part of the Specwright/Dogfold/Gorch/LifeOS ecosystem.

pip install specwright

https://github.com/bfarmstrong/specwright
```

---

**Built with ❤️ for rigorous, traceable, human-in-the-loop AI-assisted development.**
