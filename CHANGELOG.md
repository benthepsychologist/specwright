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

[Unreleased]: https://github.com/bfarmstrong/specwright/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/bfarmstrong/specwright/releases/tag/v0.3.0
[0.1.0]: https://github.com/bfarmstrong/specwright/releases/tag/v0.1.0

