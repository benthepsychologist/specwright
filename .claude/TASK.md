---
id: t008-02
title: Run Analysis and Improvement Suggestions
tier: B
owner: benthepsychologist
goal: Analyze run failures and generate improvement suggestions via LLM backend
status: planned
branch: feat/suggest-improvements
repo:
  name: specwright
  url: https://github.com/workspace/specwright
created: 2026-02-05T00:00:00Z
updated: 2026-02-12T00:00:00Z
---

# t008-02: Run Analysis and Improvement Suggestions

**Epic**: t008-agent-reference-syncing-and-continuous-improvement
**Status**: planned
**Branch**: feat/suggest-improvements
**Target**: specwright
**Depends on**: (none - can be independent)

---

## Summary

Add an LLM backend step (`prompt_type: suggest_improvements`) that analyzes run failures and generates a markdown report with categorized improvement suggestions.

## Context

When runs fail, the knowledge gained—"we should validate X before dispatch", "add a test for Y", "timeout handling needed for Z"—is lost unless manually extracted. This feature systematically captures that knowledge in a readable format.

## Problem Statement

1. No structured capture of lessons from run failures
2. Same issues discovered multiple times
3. Manual process to extract actionable insights
4. No systematic way to track what improvements are needed

## Solution

Create an LLM backend step with `prompt_type: suggest_improvements` that:
1. Analyzes run outcomes, errors, and failures
2. Generates categorized suggestions (agent rules, code improvements, build updates, test gaps)
3. Outputs a markdown report with confidence levels
4. User manually reviews and applies relevant suggestions

## Constraints

- Read-only analysis — report only, no automatic modifications
- Must handle runs with no errors gracefully (empty suggestions)
- Use existing LLM backend infrastructure (don't create new callables)
- Suggestions include confidence level (high/medium/low) determined by LLM

## Expectations

### 1. LLM Backend Extension

Add `prompt_type: suggest_improvements` support to `LlmBackend`:
- Analyzes run artifacts: outcomes, stderr, stdout, patches
- Calls LLM with structured analysis prompt
- Generates JSON response with suggestions array

### 2. Suggestion Categories

Generated suggestions fall into:
- **Agent Instructions**: Rules for CLAUDE.md / reference files
  - E.g., "Always validate StepManifest.repo_path before dispatch"
- **Code Improvements**: Refactoring or enhancement ideas
  - E.g., "Add timeout handling to git capture"
- **Build System Updates**: Changes to build.yaml or invariants
  - E.g., "Add invariant: Python callables must validate required keys"
- **Test Coverage Gaps**: Missing test cases
  - E.g., "Add test for missing repo_path in StepManifest"

### 3. Output Format

Markdown report with structure:
```markdown
# Run Analysis: Improvement Suggestions

## Run Summary
- Run ID: {run_id}
- Status: {success/failed/timeout}
- Failed steps: N of M
- Duration: Xs

## Suggestions

### Agent Instructions
- **High confidence**: {suggestion text}
  - Rationale: {why this would help}
  - Related files: {files}

### Code Improvements
- **Medium confidence**: {suggestion}
  - Rationale: {explanation}
  - Related files: {files}

### Build System Updates
- **Low confidence**: {suggestion}
  - Rationale: {explanation}

### Test Coverage Gaps
- **High confidence**: {suggestion}
  - Rationale: {explanation}
```

### 4. Confidence Levels

LLM assigns confidence based on evidence:
- **High**: Clear root cause, actionable fix, likely to help
- **Medium**: Probable issue, should investigate
- **Low**: Possible issue, needs more evidence

### 5. Usage in JobDef

```yaml
steps:
  - step_id: analyze-improvements
    backend: llm
    description: Analyze run and suggest improvements
    payload:
      prompt_type: suggest_improvements
      run_id: "@run.run_id"
      job_id: "@run.job_id"
    continue_on_failure: true  # Don't block if analysis fails
```

## Implementation Notes

### Prompt Design

**System Prompt**:
```
You are analyzing a failed/timeout run to suggest improvements.
Generate actionable suggestions across these categories:
- Agent Instructions (for CLAUDE.md/reference files)
- Code Improvements (refactoring, enhancements)
- Build System Updates (invariants, boundaries, rules)
- Test Coverage Gaps (missing test cases)

For each suggestion:
1. Confidence (high/medium/low)
2. Clear description of what to do
3. Rationale (why it helps)
4. Related files (if applicable)
```

**User Prompt**:
```
## Run Analysis
Run: {run_id} | Job: {job_id} | Status: {status}

## Step Outcomes
{step_summary_table}

## Errors and Failures
{error_details}

## Recent Stderr (truncated to ~5K tokens)
{stderr_snippets}

## Git Changes
{files_changed_summary}

Please analyze and suggest improvements in each category.
Response: JSON array of suggestions.
```

### JSON Response Format

```json
{
  "suggestions": [
    {
      "confidence": "high|medium|low",
      "category": "agent|code|build|test",
      "suggestion": "Clear description of improvement",
      "rationale": "Why this would help",
      "related_files": ["file1.py", "file2.py"]
    }
  ]
}
```

### Token Management

- Target: Keep context under 50K tokens
- Prioritize: errors > stderr > stdout > patches
- Truncate with `... [N lines truncated] ...`

## Test Cases

1. Run with no errors → empty suggestions array
2. Run with validation error → agent instruction suggestion
3. Run with timeout → test coverage + code improvement suggestions
4. Run with git failure → build system + code improvement suggestions
5. Multiple failures → multiple categorized suggestions
6. Large stderr → truncated appropriately, still analyzes errors

## Build Delta

```yaml
target: projects/specwright/specwright.build.yaml
summary: "Add suggest_improvements prompt type to LLM backend"
modifies:
  modules:
    - name: backends
      note: "Add suggest_improvements prompt_type support"
  layout:
    - path: src/spec/executor/backends/llm.py
      note: "Extend _build_prompt() for suggest_improvements"
```

## Acceptance Criteria

- [ ] `prompt_type: suggest_improvements` handled in LlmBackend._build_prompt()
- [ ] Analyzes run outcomes, errors, and failures
- [ ] Generates JSON suggestions with confidence levels
- [ ] Outputs markdown report with categorized suggestions
- [ ] Handles runs with no errors gracefully
- [ ] Token limit strategy implemented (~5K for context)
- [ ] Works with all step types (completed, failed, timeout, skipped)
- [ ] Markdown output is readable and actionable
- [ ] All tests passing

## Future Work (Out of Scope)

- Suggestion queue storage (YAML persistence in local-governor)
- CLI commands to review/apply (spec suggest review/apply)
- Auto-apply to CLAUDE.md
- Cross-run aggregation of suggestions
