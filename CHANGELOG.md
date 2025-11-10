# Changelog

All notable changes to Specwright will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Actual agent execution (replace checklist mode)
- State persistence
- Automated gate approvals (Slack/email)
- Metrics tracking dashboard
- Integration with Dogfold scaffolding
- Full Gorch orchestration integration

## [0.5.0] - 2025-11-10

### Added - Interactive HITL Gate Approvals
- **Interactive gate approval UI**: Beautiful CLI with questionary + rich for gate checkpoints
- **`spec run`**: Now supports interactive gate approval workflows with tier-specific behavior
  - Tier A/B: Blocking gates with human approval required
  - Tier C: Auto-approve gates with audit logging
- **`spec gate-list`**: List all gate approvals from audit trail
- **`spec gate-report`**: Generate summary statistics of gate approvals by decision type
- **Gate audit logging**: Full JSONL audit trail at `.aip_artifacts/{AIP_ID}/gate_approvals.jsonl`
- **Gate review blocks**: HTML comment-based syntax for embedding gate checklists in Markdown specs
- **Validation checkpoints**: Lightweight automated checks alongside formal gate reviews
- **Approval decisions**: Support for Approved/Rejected/Deferred/Conditional with metadata capture

### Changed - Gate Structure and Documentation
- **Enhanced Tier A/B templates**: Added validation checkpoints and comprehensive gate review blocks to all steps
- **GUIDE.md**: Added "Understanding Gate Structure" and "Validation Checkpoints vs Gate Reviews" sections
- **Parser**: Extended to extract gate review blocks from Markdown and compile to YAML
- **Schema**: Added `gate_ref` and `gate_review` fields to step schema
- **Interactive CLI**: Gate checkpoints display with tier-specific styling and color-coded decisions

### Fixed
- Gate review parsing now handles multi-category checklists correctly
- Approval metadata structure validated against schema
- Step compilation preserves gate references from step titles

### Documentation
- Added comprehensive gate approval documentation to GUIDE.md
- Updated IMPLEMENTATION_SUMMARY.md with Phase 7 clarifications
- Clarified dual representation of gates (Markdown vs YAML formats)
- Added examples of validation checkpoints vs formal gate reviews

## [0.4.0] - 2025-11-08

### Added
- **`spec init`**: Initialize `.specwright.yaml` config in project directory
- **`spec config`**: Display current effective configuration
- **`spec compile`**: Compile Markdown specs to validated YAML AIPs
- **Config auto-discovery**: Commands now walk up directory tree to find config
- **Jinja2 template rendering**: Markdown templates now properly use Jinja2 variables

### Changed
- **`spec create` defaults to Markdown**: Now generates `.md` files in `specs/` by default
- **`--yaml` flag**: Added to `spec create` for legacy direct YAML generation
- **Workflow updated**: Full Markdown-first workflow now functional (init → create → compile → validate → run)
- **Documentation**: Updated README.md and DEVELOPMENT.md with new workflow examples

### Fixed
- Template path resolution now uses config-aware discovery
- Output directories now created automatically when missing

## [0.3.2] - 2025-11-07

### Changed
- **Dependency management**: Migrated from pip to uv for faster, more reliable installs
- Updated all documentation (DEVELOPMENT.md, CONTRIBUTING.md, README.md) with uv commands
- Updated all GitHub Actions workflows to use uv for package installation
- Installation now requires: `pip install uv && uv pip install specwright`

## [0.3.1] - 2025-11-07

### Changed
- **Ecosystem positioning**: Updated README to clarify Specwright is Alpha (v0.3.1), not production-ready
- **Tool separation**: Dogfold acknowledged as experimental, independent companion tool
- **Documentation clarity**: Emphasized standalone nature of Specwright

### Added
- **DEVELOPMENT.md**: Complete guide for dogfooding workflow (dual-repo development)
- **Release process docs**: Automated PyPI publishing instructions in CONTRIBUTING.md

### Fixed
- GitHub Actions workflow now correctly triggers on releases from `main` branch
- Consolidated branch naming from `master` to `main` for consistency

## [0.3.0] - 2025-10-31

### Added
- **Markdown-first authoring**: Write specs in Markdown, compile to YAML
- **Deterministic compilation**: Source hash tracking, canonical YAML ordering
- **5-gate governance model**: G0 through G4 with tier-specific rigor
- **Jinja2 templates**: Tier-specific Markdown templates (A/B/C)
- **Token-based parsing**: Robust Markdown parsing with validation
- **Round-trip validation**: Ensures MD↔YAML consistency
- **`spec new`**: Create specs from templates
- **`spec compile`**: MD→YAML with validation
- **`spec validate`**: Schema validation with defaults merging
- **`spec run`**: Guided execution (checklist mode)
- **Tier defaults**: Complete gate definitions for A/B/C tiers
- **Schema validation**: JSON Schema for AIP structure
- **Pre-commit hooks**: Enforce MD/YAML sync
- **GitHub Actions**: CI/CD workflows for testing and publishing

### Changed
- **Rebranded to Specwright** for clarity and ecosystem positioning
- Lifecycle scope now canonical: `[planning, prompting, coding, testing, governance]`
- All tiers use same 5-step workflow with different governance rigor
- Updated to MIT license
- Comprehensive README with ecosystem positioning
- Complete CONTRIBUTING.md

### Documentation
- Ecosystem positioning (Specwright, Dogfold, Gorch, LifeOS)
- Agentsway implementation guide
- Tier-specific templates with gate references
- Markdown→YAML compilation guide

---
- Basic tier system (A/B/C)
- YAML-based AIPs
- JSON Schema validation
- Tier defaults merging

### Changed
- Version reset to 0.1.0 (first external release)
- Repository structure: removed `life-cli` product code
- Documentation updated to reflect composable-tools approach

---

[Unreleased]: https://github.com/bfarmstrong/specwright/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/bfarmstrong/specwright/releases/tag/v0.5.0
[0.4.0]: https://github.com/bfarmstrong/specwright/releases/tag/v0.4.0
[0.3.2]: https://github.com/bfarmstrong/specwright/releases/tag/v0.3.2
[0.3.1]: https://github.com/bfarmstrong/specwright/releases/tag/v0.3.1
[0.3.0]: https://github.com/bfarmstrong/specwright/releases/tag/v0.3.0
[0.1.0]: https://github.com/bfarmstrong/specwright/releases/tag/v0.1.0

