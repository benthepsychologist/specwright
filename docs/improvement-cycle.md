# Specwright Improvement Cycle

## Overview

The **aip-1** JobDef implements a continuous improvement loop that goes beyond single-pass spec execution. It captures agent behavior, analyzes it, and generates actionable improvements that feed back into the development process.

## 3-Pass Execution Model

### Pass 1: Execute Spec (`agent.run_spec`)
- Agent receives full spec and executes all phases
- All changes captured via git diff
- Stdout/stderr recorded for analysis

### Pass 2: Drift Inspection & Fix (`agent.drift_fix`)
- Agent analyzes what was implemented vs. what was specified
- Identifies divergence ("drift") from original intent
- Generates and applies fixes
- Reports findings

### Pass 3: Verification (`agent.drift_verify`)
- Final verification that implementation meets spec
- Confirms no regressions from drift fixes
- Provides confidence signal for merge decision

## Improvement Cycle (Steps 12-13)

After the 3 execution passes complete, two automated steps close the improvement loop:

### Step 12: `analyze.suggest_improvements` (LLM)

**Input:**
- Agent transcripts from all 3 passes
- Acceptance assessment results
- Git change summary

**Process:**
- LLM reviews the full conversation and results
- Identifies recurring mistakes or patterns
- Generates improvement suggestions across categories:
  - **Agent Instructions** - CLAUDE.md updates
  - **Code Improvements** - Refactoring, enhancements
  - **Build System Updates** - Invariants, boundaries, rules
  - **Test Coverage Gaps** - Missing test cases

**Output:**
Structured markdown report with for each suggestion:
1. **Confidence** (high/medium/low)
2. **Clear description** of what to do
3. **Rationale** (why it helps)
4. **Related files** (if applicable)

### Step 13: `stage.improvements` (cmd)

**Process:**
- Writes improvement suggestions to `~/.local/local-governor/improvements/pending/`
- File format: `{spec_id}.md`
- Includes full suggestion content (not just pointers)

**Output Location:**
```
~/.local/local-governor/improvements/pending/{spec_id}.md
```

**File Format:**
```markdown
# Improvement Suggestions: {spec_id}
# Run: {run_id}
# Branch: {branch}
# Status: PENDING REVIEW

[Full improvement suggestions from LLM analysis]
```

## Integration with CLAUDE.md

Improvements flow into global `~/.claude/CLAUDE.md`:

1. **Review** - Open `improvements/pending/{spec_id}.md`
2. **Evaluate** - Assess confidence and applicability
3. **Integrate** - Add high-confidence items to CLAUDE.md sections:
   - `## Development Guidelines` - Agent behavior patterns
   - `## Architecture` - System design insights
   - `## Invariants` - Non-negotiable constraints

## Closed-Loop Pattern

```
Run (Pass 1-3)
    ↓
Analyze Transcripts (Step 12)
    ↓
Stage Improvements (Step 13)
    ↓
~/.local/local-governor/improvements/pending/{spec_id}.md
    ↓
[Human Review]
    ↓
Integrate into ~/.claude/CLAUDE.md
    ↓
Next run uses updated guidelines
```

## Example Improvement Suggestions

From e013-03-pipeline-batch-infrastructure run:

### 1. Verify API Contracts (HIGH confidence)
**Mistake:** Spec assumed `StepOutcome.output` field existed; actually only had `output_ref`

**Suggestion for CLAUDE.md:**
> **Verify API Contracts**: Before implementing features, verify that class attributes and method signatures assumed by the spec actually exist in the codebase.

### 2. Schema Source of Truth (HIGH confidence)
**Mistake:** Documentation described old "two-table pattern" while code used newer "WAL pattern"

**Suggestion for CLAUDE.md:**
> **Schema Source of Truth**: Always consult actual DDL or definitions when writing SQL or logic that maps to database rows. Do not rely on cached text in documentation.

### 3. Fail-Fast Semantics (MEDIUM confidence)
**Mistake:** Loop implementation checked `stop_on_failure` after entire loop completed rather than immediately

**Suggestion for CLAUDE.md:**
> **Fail-Fast by Default**: When implementing loops or batch operations, `stop_on_failure` implies immediate termination upon first exception.

## Configuration

The improvement analysis is controlled via the aip-1 JobDef:

```yaml
- step_id: analyze.suggest_improvements
  backend: llm
  payload:
    system: |
      [Instructions for LLM to generate suggestions]
    context: |
      [Structured data from run]
    prompt: |
      [Specific guidance for this run]
  continue_on_failure: true

- step_id: stage.improvements
  backend: cmd
  payload:
    command: |
      mkdir -p ~/.local/local-governor/improvements/pending
      cat > ~/.local/local-governor/improvements/pending/@payload.spec_id"".md << 'EOF'
      [Writes full suggestions]
      EOF
  continue_on_failure: true
```

## Usage

After running a spec with aip-1:

```bash
# 1. View improvement suggestions
cat ~/.local/local-governor/improvements/pending/{spec_id}.md

# 2. Review and evaluate suggestions
# (Open in editor, assess confidence levels)

# 3. Integrate high-confidence items
vim ~/.claude/CLAUDE.md
# Add suggestions to appropriate sections

# 4. Next run automatically uses updated CLAUDE.md
```

## Future Enhancements

- **Automatic integration** - Flag high-confidence suggestions for auto-merge into CLAUDE.md
- **Suggestion versioning** - Track which suggestions have been implemented
- **Cross-run analysis** - Identify patterns across multiple runs
- **Feedback loop** - Track impact of implemented suggestions on future runs
