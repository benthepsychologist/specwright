---
id: t008-01
title: Agent Reference File Syncing Callable
tier: B
owner: benthepsychologist
goal: Implement agent.sync_refs callable that syncs project architecture from build.yaml into agent-specific reference files
status: refined
branch: feat/agent-sync-refs
repo:
  name: specwright
  url: https://github.com/workspace/specwright
created: 2026-02-05T00:00:00Z
updated: 2026-02-06T20:30:00Z
---

# t008-01: Agent Reference File Syncing Callable

**Epic**: t008-agent-reference-syncing-and-continuous-improvement
**Branch**: feat/agent-sync-refs
**Tier**: 2

## Objective

Implement `agent.sync_refs` callable that automatically syncs project architecture context from canonical `build.yaml` files into agent-specific reference files (CLAUDE.md, .goosehints, etc.), eliminating manual copy-paste workflows and ensuring agents have up-to-date project context.

## Problem

Currently, project architecture lives in `local-governor/projects/<project>/<project>.build.yaml` but agents working in repositories don't automatically see this context. Each agent has different file conventions for persistent reference data, and manual synchronization is error-prone and leads to stale context across coding sessions.

## Current Capabilities

The specwright project has established patterns for callables:
- **Callable Contract**: Functions with signature `(*, payload: dict, repo_path: Path) -> dict` returning `{passed: bool, data: dict, summary: str}`
- **Registration**: Via `register_callable()` in `spec.executor.backends.python`
- **Dispatch**: Through `PythonBackend.dispatch()` with payload extraction
- **Existing Callables**: `governance.validate_build`, `governance.validate_epic`, `governance.validate_contracts` in `/workspace/specwright/src/spec/governance/callables.py`

The build.yaml structure contains:
- `kernel.description` - Core project purpose
- `kernel.invariants` - Rules agents must follow
- `boundaries` - Integration points and constraints
- `decisions` - Architecture Decision Records (ADRs)

## Proposed build_delta

```yaml
target: "projects/specwright/specwright.build.yaml"
summary: "Add agent.sync_refs callable for automated reference file syncing"
adds:
  layout:
    - path: src/spec/governance/sync_refs.py
      module: governance
      role: "Agent reference file synchronization from build.yaml"
  modules:
    - name: sync_refs
      kind: callable
      provides: ["agent.sync_refs"]
      depends_on: ["governance"]
  kernel_surfaces:
    - name: callable
      entrypoints:
        - callable: "agent.sync_refs"
          usage: "Sync build.yaml architecture to agent reference files"
modifies:
  modules:
    - name: governance
      changes: "Add sync_refs callable registration to register_all()"
```

## Acceptance Criteria

- [ ] `agent.sync_refs` callable implemented with proper contract signature
- [ ] AGENT_REF_TARGETS mapping supports claude-code, cursor, aider, roo-code, goose, opencode
- [ ] Reads kernel.description, invariants, boundaries, decisions from build.yaml
- [ ] Writes to agent-specific reference file paths with proper formatting
- [ ] Content merging preserves existing user sections using synced block markers
- [ ] Idempotent execution (running twice produces identical results)
- [ ] Registered via `register_all()` pattern in governance module
- [ ] Error handling for missing build.yaml, unknown agents, write permissions
- [ ] Test coverage for fresh files, existing files with/without markers, error cases
- [ ] All existing governance tests continue passing

## Constraints

- Follow existing callable pattern from `spec/governance/callables.py`
- No agent-specific dependencies - use standard library file I/O only
- Respect existing content through marker-based merging, never overwrite user sections
- Agent-agnostic marker format determined by target file extension
- Must integrate with existing PythonBackend dispatch mechanism

## Phases

### Phase 1: Core Callable Implementation
**Objective**: Implement the basic sync_refs callable with file I/O operations

**Files to Touch**:
- `src/spec/governance/sync_refs.py` (new)
- `src/spec/governance/callables.py` (modify registration)

**Implementation Notes**:
- Define AGENT_REF_TARGETS mapping with 6 agent types
- Implement content extraction from build.yaml using PyYAML
- Build content formatting functions for different target file types
- Handle marker-based content merging with proper comment syntax by file extension

**Verification**:
```bash
python -c "from src.spec.governance.sync_refs import sync_refs; print('Import successful')"
pytest tests/governance/test_sync_refs.py::test_basic_sync -v
```

### Phase 2: Content Merging Strategy
**Objective**: Implement robust content preservation using synced block markers

**Files to Touch**:
- `src/spec/governance/sync_refs.py` (enhance)
- `tests/governance/test_sync_refs.py` (new)

**Implementation Notes**:
- Implement marker detection: `<!-- BEGIN/END SYNCED: project -->` for .md/.mdc files
- Implement marker detection: `# BEGIN/END SYNCED: project` for .goosehints/.txt files
- Content replacement algorithm that preserves user sections outside markers
- Handle edge cases: no existing file, no markers, malformed markers

**Verification**:
```bash
pytest tests/governance/test_sync_refs.py::test_content_merging -v
pytest tests/governance/test_sync_refs.py::test_marker_preservation -v
```

### Phase 3: Error Handling and Registration
**Objective**: Complete error handling and integrate with callable registration system

**Files to Touch**:
- `src/spec/governance/sync_refs.py` (complete)
- `src/spec/governance/callables.py` (register)
- `tests/governance/test_sync_refs.py` (complete)

**Implementation Notes**:
- Error handling: missing build.yaml, unknown agent, filesystem permissions
- Return proper callable contract with passed/data/summary fields
- Update `register_all()` to include `agent.sync_refs`
- Comprehensive test coverage including error scenarios

**Verification**:
```bash
pytest tests/governance/ -v
python -c "from src.spec.governance.callables import register_all; register_all(); print('Registration successful')"
spec execute --job=test-callable --payload='{"callable":"agent.sync_refs","agent":"claude-code","project":"specwright"}'
```