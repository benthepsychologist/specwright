---
id: t004-07-spec-refine
title: "t004-07-spec-refine"
tier: B
owner: benthepsychologist
goal: "Add 'spec refine' CLI command that takes an existing spec path"
branch: feat/t004-07-spec-refine
status: draft
created: 2026-02-05T19:10:33Z
---

# t004-07-spec-refine: t004-07-spec-refine

**Epic:** t004-specwright-governance
**Branch:** `feat/t004-07-spec-refine`
**Tier:** B

## Objective

> Add 'spec refine' CLI command that takes an existing spec path

This command enables iterative spec improvement by accepting an existing spec file and using LLM assistance to analyze, suggest improvements, and optionally apply refinements. It leverages the existing spec scaffolding and LLM infrastructure to provide intelligent feedback on spec quality, completeness, and alignment with project patterns. The command maintains user content integrity while offering structured improvement suggestions.

The refine command addresses the gap between initial spec drafting and production-ready specifications by providing automated analysis and enhancement capabilities similar to code review but specifically tailored for specification documents.

## Problem

1. **No incremental spec improvement workflow**: Currently specs are drafted once and manually improved through reviews, with no automated assistance for enhancement
2. **Inconsistent spec quality**: Without systematic refinement tools, specs vary widely in completeness and adherence to patterns
3. **Manual context gathering**: Developers must manually research codebase patterns and constraints when improving specs
4. **Lost opportunity for LLM assistance**: The existing LLM infrastructure is only used for initial drafting, not for iterative improvement
5. **No structured feedback mechanism**: Spec improvement relies on human review with no systematic analysis of common issues

## Current Capabilities

### kernel.surfaces

```yaml
- command: "spec compile"
  usage: "spec compile aip-1 ./my-feature.md"
- command: "spec execute"
  usage: "spec execute ./job_instance.yaml"
- command: "spec run"
  usage: "spec run aip-1 ./my-feature.md --repo /workspace/target"
- command: "spec status"
  usage: "spec status [run-id]"
- command: "spec logs"
  usage: "spec logs <run-id>"
- command: "spec create"
  usage: "spec create 'feature name' --tier C"
- command: "spec init"
  usage: "spec init"
- command: "spec config"
  usage: "spec config current.spec ./my-feature.md"
- command: "spec epic"
  usage: "spec epic status e011"
- command: "spec validate spec"
  usage: "spec validate spec ./my-feature.md"
- command: "spec validate build"
  usage: "spec validate build specwright [--json] [--fix]"
- command: "spec validate epic"
  usage: "spec validate epic t004 [--json]"
- command: "spec validate contracts"
  usage: "spec validate contracts [--json]"
```

### modules

```yaml
- name: cli
  provides: ['spec command-line interface']
- name: executor
  provides: ['job compilation', 'step execution', 'run tracking']
- name: backends
  provides: ['claude-code backend', 'cmd backend', 'python backend', 'llm backend', 'codex backend']
- name: executor_schemas
  provides: ['StepTemplate', 'JobDef', 'JobInstance', 'StepOutcome', 'StepCapture']
- name: epic
  provides: ['epic loading', 'epic schema', 'DAG validation', 'epic writing']
- name: governor
  provides: ['governor locator', 'epic/spec resolver', 'spec reader', 'materializer']
- name: governance
  provides: ['build validation', 'epic validation', 'contract validation']
- name: checks
  provides: ['LLM check execution', 'check input resolution']
- name: llm
  provides: ['LLM client', 'prompt rendering', 'report generation']
- name: compiler
  provides: ['spec markdown parsing', 'v1 YAML compilation']
```

### layout

```yaml
- path: src/spec/cli/
  role: "Typer CLI commands and subcommand registration"
- path: src/spec/executor/
  role: "v2 job engine: compile, dispatch, step execution, run tracking"
- path: src/spec/executor/backends/
  role: "Pluggable execution backends (claude-code, cmd, python, llm, codex)"
- path: src/spec/executor/schemas/
  role: "Step, job, and capture dataclasses"
- path: src/spec/epic/
  role: "Epic loading, schema dataclasses, DAG validation, writer"
- path: src/spec/governor/
  role: "Local-governor integration: locator, reader, resolver, materializer, targets"
- path: src/spec/governance/
  role: "Build, epic, and contract validation"
- path: src/spec/checks/
  role: "LLM check execution and input resolution"
- path: src/spec/llm/
  role: "LLM client, config, prompts, and report generation"
- path: src/spec/compiler/
  role: "Spec markdown parser and v1 compiler (legacy)"
```

## Proposed build_delta

```yaml
target: "projects/specwright/specwright.build.yaml"
summary: "Add 'spec refine' CLI command with LLM-assisted spec improvement capabilities"

adds:
  layout: []
  modules: []
  kernel_surfaces:
    - command: "spec refine"
      usage: "spec refine ./my-spec.md [--context feedback.md] [--dry-run] [--apply]"
modifies: {}
removes: {}
```

## Acceptance Criteria

- [ ] Add 'spec refine' CLI command that takes an existing spec path
- [ ] Accept optional --context file with feedback or additional requirements
- [ ] Use LLM to analyze spec and suggest improvements
- [ ] Support --dry-run to preview changes without writing
- [ ] Support --apply to update spec in place
- [ ] Preserve user-written sections while improving others
- [ ] Output structured diff or suggestions in non-apply mode

## Constraints

- Follow existing CLI patterns from draft command
- Never lose user content - merge, don't overwrite

---

## Phase 1: CLI Command Registration and Argument Parsing

### Objective
Implement the basic CLI command structure for `spec refine` with proper argument validation and help text, following the patterns established in the draft command.

### Files to Touch
- `src/spec/cli/refine.py` (create) — New CLI command module with typer command definition
- `src/spec/cli/spec.py` (modify) — Register the refine command in the main CLI app

### Implementation Notes
- Follow the exact pattern from `src/spec/cli/draft.py` for command structure and imports
- Use typer.Argument for required spec_path and typer.Option for optional flags
- Support --context, --dry-run, --apply, --model flags similar to draft command
- Include comprehensive help text and examples in the docstring
- Add proper error handling for missing files with typer.Exit(1)

### Verification
- `pytest tests/cli/test_refine.py` → passes
- `ruff check src/spec/cli/` → clean
- `spec refine --help` → shows proper usage information

## Phase 2: Spec Analysis and Refinement Engine

### Objective
Create the core refinement logic that analyzes existing specs, identifies improvement opportunities, and generates refinement suggestions using the LLM infrastructure.

### Files to Touch
- `src/spec/governance/spec_refiner.py` (create) — Core refinement engine class
- `src/spec/llm/prompts.py` (modify) — Add refinement prompt templates
- `tests/governance/test_spec_refiner.py` (create) — Unit tests for refinement logic

### Implementation Notes
- Create SpecRefiner class that loads and analyzes existing specs using SpecParser
- Leverage existing LLMClient infrastructure from spec_drafter.py patterns
- Use similar read-only tool allowlist as SpecDrafter for repository exploration
- Implement diff generation for suggested changes vs original content
- Support both dry-run (suggestions only) and apply modes (actual modifications)
- Preserve user-written content by marking generated vs manual sections
- Add prompt templates for spec analysis covering structure, completeness, and patterns

### Verification
- `pytest tests/governance/test_spec_refiner.py` → passes
- `pytest tests/llm/test_prompts.py` → passes for new prompts
- `ruff check src/spec/governance/` → clean
- Manual testing with sample specs shows appropriate suggestions