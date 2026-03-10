<!-- BEGIN SYNCED: specwright -->
# Specwright Project Context

## Description

Spec execution engine. Compiles job definitions against spec markdown, executes step sequences via pluggable backends (claude-code, cmd, python, llm), and tracks runs with artifact capture.

## Invariants

- Job-based execution: specs compile to JobInstances with fixed step sequences.
- Executor never mutates the step list — it runs exactly what compile() produced.
- Run artifacts stored in ~/.local/local-governor/runs/, never in the target repo.

## Boundaries

### cli
- Type: inbound
- Contract: spec <command> [options]
- Consumers: developers, agentic workflows

### governor_fs
- Type: dependency
- Contract: ~/.local/local-governor/ filesystem layout
- Requires: epics/, projects/, runs/, contracts/ directories

### claude_code
- Type: dependency
- Contract: claude CLI binary
- Requires: claude CLI for claude-code backend execution

### llm_lib
- Type: dependency
- Contract: llm Python library (simon willison)
- Requires: llm>=0.19.0 for LLM check execution

## Architecture Decisions

### adr-001: Job-based execution model
**Status:** accepted

**Rationale:** Decouples spec authoring from execution. JobDefs are reusable templates. Specs are payload.

**Decision:** Specs compile to JobInstances via JobDef templates. Executor runs JobInstances.

### adr-002: Pluggable backends
**Status:** accepted

**Rationale:** Different step types need different execution strategies.

**Decision:** Backend registry dispatches steps to claude-code, cmd, python, llm, or codex backends.

### adr-003: Governor-based storage
**Status:** accepted

**Rationale:** Artifacts, runs, and config live outside target repos.

**Decision:** All specwright state in ~/.local/local-governor/. Target repos are never polluted.

<!-- END SYNCED: specwright -->
