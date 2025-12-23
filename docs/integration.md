# Claude Code ↔ Specwright Integration

## ✅ What We Just Built

**Option 4: Slash Command Integration** - NOW LIVE!

Created 4 slash commands that bridge Claude Code into the Specwright workflow:

1. **`/spec-run`** - Execute complete AIP with gate integration
2. **`/spec-status`** - Show current AIP progress
3. **`/spec-next`** - Execute next incomplete step
4. **`/spec-pause`** - Checkpoint and save progress

## 🚀 How to Use It

### Quick Start

```bash
# 1. Create a spec
spec create --tier B --title "Add Search Feature" --goal "Implement full-text search"

# 2. Edit the spec (add steps, gates, acceptance criteria)
vim specs/add-search-feature.md

# 3. Compile it
spec compile specs/add-search-feature.md

# 4. Execute with Claude Code
# Just type this in Claude Code:
/spec-run
```

### What Happens When You Type `/spec-run`:

```
╔════════════════════════════════════════════════════════════
║ SPECWRIGHT EXECUTOR MODE
╠════════════════════════════════════════════════════════════
║ AIP: Add Search Feature (AIP-specwright-2025-11-11-003)
║ Tier: B
║ Goal: Implement full-text search
║
║ Acceptance Criteria:
║   1. Search API endpoint implemented
║   2. Full-text indexing working
║   3. 90% test coverage
║   4. Sub-200ms response time
╚════════════════════════════════════════════════════════════

╔════════════════════════════════════════════════════════════
║ Step 1/5: Design Search Architecture
║ ID: plan-01
║ Role: planning_agent
║ Gate: G0: Plan Approval
╚════════════════════════════════════════════════════════════

Prompt:
Design the search architecture. Create:
- Database indexing strategy
- API endpoint specification
- Performance optimization plan

Outputs:
- artifacts/plan/search-architecture.md
- artifacts/plan/api-spec.yaml

🤖 Should I execute this step now?
  (Yes, execute | Skip | Pause)
```

**You choose "Yes, execute":**

```
Executing step 1...

✓ Created artifacts/plan/search-architecture.md
  [Shows content...]

✓ Created artifacts/plan/api-spec.yaml
  [Shows content...]

Step 1 complete! Triggering gate review...

$ spec run --step 1
```

**The spec CLI shows the gate checklist:**

```
╔════════════════════════════════════════════════════════════
║ 🚧 GATE CHECKPOINT: G0: Plan Approval
╠════════════════════════════════════════════════════════════
║ This is a Tier B gate - approval required to proceed
╚════════════════════════════════════════════════════════════

#### Gate Review Checklist

##### Architecture Review
  [ ] Work breakdown structure is complete
  [ ] File touch map identifies all components
  [ ] Dependencies clearly defined
  [ ] No circular dependencies

##### Risk Assessment
  [ ] Risk analysis completed
  [ ] Mitigation strategies identified
  [ ] Rollback plan documented

[Select items with spacebar, Enter to continue]

Approval Decision:
  ( ) APPROVED
  ( ) APPROVED WITH CONDITIONS
  ( ) REJECTED
  ( ) DEFERRED

Reviewer: _______
Rationale: _______
```

**You approve the gate, execution continues to Step 2...**

## 📊 Audit Trail

Everything is logged automatically:

### Execution History
```bash
cat .aip_artifacts/execution_history.jsonl | jq .
```

```json
{
  "timestamp": "2025-11-11T19:30:00",
  "event": "spec_compiled",
  "aip_id": "AIP-specwright-2025-11-11-003",
  "git": {
    "branch": "feat/search",
    "commit": "abc123...",
    "has_uncommitted_changes": false
  }
}
```

### Gate Approvals
```bash
cat .aip_artifacts/AIP-specwright-2025-11-11-003/gate_approvals.jsonl | jq .
```

```json
{
  "timestamp": "2025-11-11T19:35:00",
  "gate_ref": "G0: Plan Approval",
  "decision": "approved",
  "reviewer": "alice",
  "rationale": "Architecture looks solid, all risks addressed",
  "completed_checklist": {
    "Architecture Review": [
      "Work breakdown structure is complete",
      "File touch map identifies all components"
    ]
  }
}
```

### Claude Execution Log
```bash
cat .aip_artifacts/claude-execution.log
```

```
[2025-11-11T19:30:15] Starting step plan-01
[2025-11-11T19:31:42] Completed step plan-01
[2025-11-11T19:31:50] Gate G0: Plan Approval - APPROVED
[2025-11-11T19:32:00] Starting step code-01
...
```

## 🎯 Complete Workflow Example

### Scenario: Implement a new feature end-to-end

```bash
# 1. Create spec
spec create --tier B --title "User Notifications" --goal "Add push notifications"

# 2. Edit spec (write steps, add gates)
# specs/user-notifications.md

# 3. Compile
spec compile specs/user-notifications.md
# → Logs: spec_compiled with source hash

# 4. Check status before starting
```

In Claude Code:
```
/spec-status
```

**Claude shows:**
```
╔════════════════════════════════════════════════════════════
║ CURRENT AIP STATUS
╠════════════════════════════════════════════════════════════
║ AIP ID: AIP-myapp-2025-11-11-005
║ Title: User Notifications
║ Tier: B
║
║ STEPS:
║  1. [ ] Planning & Design (plan-01) ← NEXT
║  2. [ ] Backend Implementation (code-01)
║  3. [ ] Frontend Integration (code-02)
║  4. [ ] Testing (test-01)
║  5. [ ] Deployment (deploy-01)
║
║ GATES: None approved yet
╚════════════════════════════════════════════════════════════

Next: /spec-run
```

```
# 5. Execute with Claude
/spec-run

# Claude executes step 1, triggers gate
# You approve gate via `spec run --step 1`
# Claude continues to step 2...

# 6. Need to pause?
/spec-pause

# 7. Resume later
/spec-next

# 8. Check acceptance criteria
/spec-status
```

```bash
# 9. View full audit trail
cat .aip_artifacts/execution_history.jsonl | jq .
spec gate-report

# 10. When complete, create PR
git add .
git commit -m "Implement user notifications

🤖 Generated via Specwright AIP-myapp-2025-11-11-005"
gh pr create --fill
```

## 🔄 Integration Points

### Current State (Phase 1 - NOW)

| Action | Claude Code | Spec CLI | Audit Log |
|--------|------------|----------|-----------|
| Load AIP | ✅ Reads YAML | - | - |
| Execute step | ✅ Writes code | - | Manual log |
| Trigger gate | ✅ Calls `spec run` | ✅ Interactive UI | ✅ gate_approvals.jsonl |
| Log progress | ✅ Manual echo | - | ✅ claude-execution.log |
| View status | ✅ `/spec-status` | - | - |

### Future State (Phase 2 - Next)

Add CLI commands for better integration:

```bash
spec step-start <step-id>        # Claude calls this
spec step-complete <step-id>     # Claude calls this
spec step-log <step-id> "msg"    # Claude logs progress
spec history                      # View execution history
spec history --aip <id>          # Filter by AIP
```

Then Claude can properly log to the official audit trail instead of manual logs.

### Future State (Phase 3 - Best)

MCP Server integration - native tools in Claude Code:

```javascript
// Claude sees these tools automatically:
tools: [
  "specwright__get_current_aip",
  "specwright__execute_step",
  "specwright__approve_gate",
  "specwright__get_history"
]
```

## 📋 Slash Commands Reference

### `/spec-run`
**Execute complete AIP step-by-step**
- Loads current AIP
- Executes each step in order
- Triggers gates via `spec run --step N`
- Logs all activity
- Stops at first incomplete step

### `/spec-status`
**Show current AIP progress**
- AIP metadata
- Step completion status
- Gate approval status
- Acceptance criteria checklist
- Next action suggestion

### `/spec-next`
**Execute next incomplete step**
- Resumes from last completed step
- Same execution flow as `/spec-run`
- Useful for continuing after pause

### `/spec-pause`
**Checkpoint progress**
- Logs pause event
- Shows execution summary
- Provides resume instructions
- Saves state to JSON

## 💡 Tips

1. **Always compile before running:** `spec compile` generates the YAML that Claude reads
2. **Use `/spec-status` first:** Check state before starting
3. **Don't skip gates for Tier A/B:** They're there for a reason
4. **Review code before approving gates:** You're the human-in-the-loop
5. **Check audit logs:** Verify everything is tracked
6. **Commit often:** Git commits between steps help track progress

## 🐛 Troubleshooting

**Slash command not found:**
- Make sure files are in `.claude/commands/`
- Check file permissions: `chmod 644 .claude/commands/*.md`
- Restart Claude Code session

**"No current AIP":**
- Run `spec compile <spec>.md` first
- Check `.specwright.yaml` has `current.aip` set

**Gate not triggering:**
- Verify step has `gate_ref` in compiled YAML
- Make sure you're using `spec run --step N` (not just `spec run`)

**Lost progress:**
- Check `.aip_artifacts/claude-execution.log`
- Use `/spec-status` to see what's done
- Resume with `/spec-next`

## 🎉 What This Enables

You can now:

✅ **Systematically execute AIPs** through Claude Code
✅ **Enforce human-in-the-loop gates** at critical points
✅ **Maintain full audit trail** of all decisions and changes
✅ **Track progress** through complex multi-step implementations
✅ **Resume execution** after pauses
✅ **Verify governance** requirements are met (Tier A/B/C)

**Next:** Try it out! Create a simple Tier C spec and run `/spec-run` to see it in action.

## 📚 Further Reading

- [Slash Commands README](.claude/commands/README.md)
- [Specwright Guide](src/spec/templates/GUIDE.md)
- [AIP Schema](src/spec/schemas/aip.schema.json)
