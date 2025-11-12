"""Tests for audit.logger (gate audit logger) module."""

import json
from pathlib import Path
import pytest
from spec.audit.logger import GateAuditLogger


@pytest.fixture
def tmp_artifacts(tmp_path):
    """Create temporary artifacts directory."""
    artifacts_dir = tmp_path / ".aip_artifacts" / "AIP-test-001"
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


@pytest.fixture
def logger(tmp_artifacts):
    """Create gate audit logger."""
    return GateAuditLogger("AIP-test-001", tmp_artifacts)


def test_init_creates_artifacts_dir(tmp_path):
    """Test that logger creates artifacts directory."""
    artifacts_dir = tmp_path / "new_dir"
    logger = GateAuditLogger("AIP-test-001", artifacts_dir)

    assert artifacts_dir.exists()
    assert logger.log_file == artifacts_dir / "gate_approvals.jsonl"


def test_log_approval_basic(logger, tmp_artifacts):
    """Test logging basic gate approval."""
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice",
        rationale="Looks good"
    )

    log_file = tmp_artifacts / "gate_approvals.jsonl"
    assert log_file.exists()

    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["aip_id"] == "AIP-test-001"
    assert entry["step_id"] == "step-001"
    assert entry["gate_ref"] == "G0: Plan Approval"
    assert entry["decision"] == "approved"
    assert entry["reviewer"] == "alice"
    assert entry["rationale"] == "Looks good"
    assert "timestamp" in entry


def test_log_approval_with_conditions(logger, tmp_artifacts):
    """Test logging conditional approval."""
    logger.log_approval(
        step_id="step-002",
        gate_ref="G1: Code Readiness",
        decision="conditional",
        reviewer="bob",
        rationale="Approved with conditions",
        conditions="Must add unit tests before merge"
    )

    log_file = tmp_artifacts / "gate_approvals.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["decision"] == "conditional"
    assert entry["conditions"] == "Must add unit tests before merge"


def test_log_approval_with_checklist(logger, tmp_artifacts):
    """Test logging approval with completed checklist."""
    checklist = {
        "Architecture Review": [
            "Work breakdown structure is complete",
            "File touch map identifies all components"
        ],
        "Risk Assessment": [
            "Risk analysis completed"
        ]
    }

    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice",
        rationale="All checks passed",
        completed_checklist=checklist
    )

    log_file = tmp_artifacts / "gate_approvals.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["completed_checklist"] == checklist
    assert len(entry["completed_checklist"]["Architecture Review"]) == 2


def test_log_approval_with_metadata(logger, tmp_artifacts):
    """Test logging approval with custom metadata."""
    metadata = {
        "duration_minutes": 15,
        "reviewed_by_team": True,
        "git_commit": "abc123"
    }

    logger.log_approval(
        step_id="step-003",
        gate_ref="G3: Deployment Approval",
        decision="approved",
        reviewer="alice",
        metadata=metadata
    )

    log_file = tmp_artifacts / "gate_approvals.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["metadata"] == metadata


def test_log_approval_empty_optional_fields(logger, tmp_artifacts):
    """Test logging approval with minimal fields."""
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice"
        # No rationale, conditions, checklist, or metadata
    )

    log_file = tmp_artifacts / "gate_approvals.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["rationale"] == ""
    assert entry["conditions"] == ""
    assert entry["completed_checklist"] == {}
    assert entry["metadata"] == {}


def test_log_multiple_approvals(logger, tmp_artifacts):
    """Test logging multiple approvals appends to file."""
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice"
    )

    logger.log_approval(
        step_id="step-002",
        gate_ref="G1: Code Readiness",
        decision="approved",
        reviewer="bob"
    )

    log_file = tmp_artifacts / "gate_approvals.jsonl"
    with open(log_file) as f:
        lines = f.readlines()

    assert len(lines) == 2
    entry1 = json.loads(lines[0])
    entry2 = json.loads(lines[1])
    assert entry1["step_id"] == "step-001"
    assert entry2["step_id"] == "step-002"


def test_log_rejection(logger, tmp_artifacts):
    """Test logging gate rejection."""
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="rejected",
        reviewer="alice",
        rationale="Missing risk analysis"
    )

    log_file = tmp_artifacts / "gate_approvals.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["decision"] == "rejected"
    assert "risk analysis" in entry["rationale"]


def test_log_deferral(logger, tmp_artifacts):
    """Test logging gate deferral."""
    logger.log_approval(
        step_id="step-003",
        gate_ref="G3: Deployment Approval",
        decision="deferred",
        reviewer="bob",
        rationale="Need to check with security team first"
    )

    log_file = tmp_artifacts / "gate_approvals.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["decision"] == "deferred"


def test_get_approvals_empty(logger):
    """Test getting approvals when none exist."""
    approvals = logger.get_approvals()
    assert approvals == []


def test_get_approvals_single(logger):
    """Test getting single approval."""
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice"
    )

    approvals = logger.get_approvals()
    assert len(approvals) == 1
    assert approvals[0]["step_id"] == "step-001"


def test_get_approvals_multiple(logger):
    """Test getting multiple approvals."""
    for i in range(3):
        logger.log_approval(
            step_id=f"step-{i:03d}",
            gate_ref=f"G{i}: Gate {i}",
            decision="approved",
            reviewer="alice"
        )

    approvals = logger.get_approvals()
    assert len(approvals) == 3


def test_get_approval_for_step_found(logger):
    """Test getting approval for specific step."""
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice"
    )

    logger.log_approval(
        step_id="step-002",
        gate_ref="G1: Code Readiness",
        decision="approved",
        reviewer="bob"
    )

    approval = logger.get_approval_for_step("step-001")
    assert approval is not None
    assert approval["step_id"] == "step-001"
    assert approval["gate_ref"] == "G0: Plan Approval"


def test_get_approval_for_step_not_found(logger):
    """Test getting approval for non-existent step."""
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice"
    )

    approval = logger.get_approval_for_step("step-999")
    assert approval is None


def test_get_approval_for_step_returns_most_recent(logger):
    """Test that get_approval_for_step returns most recent approval."""
    # Log two approvals for same step
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="deferred",
        reviewer="alice",
        rationale="First attempt"
    )

    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="bob",
        rationale="Second attempt"
    )

    approval = logger.get_approval_for_step("step-001")
    assert approval is not None
    assert approval["rationale"] == "Second attempt"
    assert approval["reviewer"] == "bob"


def test_get_summary_empty(logger):
    """Test getting summary with no approvals."""
    summary = logger.get_summary()

    assert summary["total"] == 0
    assert summary["approved"] == 0
    assert summary["rejected"] == 0
    assert summary["deferred"] == 0
    assert summary["conditional"] == 0
    assert summary["by_gate"] == {}


def test_get_summary_single_approval(logger):
    """Test getting summary with single approval."""
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice"
    )

    summary = logger.get_summary()

    assert summary["total"] == 1
    assert summary["approved"] == 1
    assert summary["rejected"] == 0
    assert "G0: Plan Approval" in summary["by_gate"]
    assert summary["by_gate"]["G0: Plan Approval"]["total"] == 1
    assert summary["by_gate"]["G0: Plan Approval"]["approved"] == 1


def test_get_summary_multiple_decisions(logger):
    """Test getting summary with multiple decision types."""
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice"
    )

    logger.log_approval(
        step_id="step-002",
        gate_ref="G1: Code Readiness",
        decision="rejected",
        reviewer="bob"
    )

    logger.log_approval(
        step_id="step-003",
        gate_ref="G2: Pre-Release",
        decision="deferred",
        reviewer="charlie"
    )

    logger.log_approval(
        step_id="step-004",
        gate_ref="G3: Deployment Approval",
        decision="conditional",
        reviewer="dave"
    )

    summary = logger.get_summary()

    assert summary["total"] == 4
    assert summary["approved"] == 1
    assert summary["rejected"] == 1
    assert summary["deferred"] == 1
    assert summary["conditional"] == 1


def test_get_summary_by_gate(logger):
    """Test getting summary breakdown by gate."""
    # Multiple approvals for same gate
    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="deferred",
        reviewer="alice"
    )

    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="bob"
    )

    # Approval for different gate
    logger.log_approval(
        step_id="step-002",
        gate_ref="G1: Code Readiness",
        decision="approved",
        reviewer="charlie"
    )

    summary = logger.get_summary()

    assert summary["total"] == 3
    assert len(summary["by_gate"]) == 2
    assert summary["by_gate"]["G0: Plan Approval"]["total"] == 2
    assert summary["by_gate"]["G0: Plan Approval"]["approved"] == 1
    assert summary["by_gate"]["G0: Plan Approval"]["deferred"] == 1
    assert summary["by_gate"]["G1: Code Readiness"]["total"] == 1
    assert summary["by_gate"]["G1: Code Readiness"]["approved"] == 1


def test_get_summary_ignores_unknown_decisions(logger):
    """Test that summary handles unknown decision types gracefully."""
    # Manually create log entry with invalid decision
    log_entry = {
        "timestamp": "2025-01-01T00:00:00",
        "aip_id": "AIP-test-001",
        "step_id": "step-001",
        "gate_ref": "G0: Plan Approval",
        "decision": "invalid_decision_type",
        "reviewer": "alice",
        "rationale": "",
        "conditions": "",
        "completed_checklist": {},
        "metadata": {}
    }

    with open(logger.log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    summary = logger.get_summary()

    # Unknown decision should not crash, just not be counted in known categories
    assert summary["total"] == 1
    assert summary["approved"] == 0
    assert summary["rejected"] == 0


def test_logger_with_string_path(tmp_path):
    """Test that logger works with string path."""
    artifacts_dir = str(tmp_path / "artifacts")
    logger = GateAuditLogger("AIP-test-001", artifacts_dir)

    logger.log_approval(
        step_id="step-001",
        gate_ref="G0: Plan Approval",
        decision="approved",
        reviewer="alice"
    )

    approvals = logger.get_approvals()
    assert len(approvals) == 1


def test_approvals_file_path(tmp_artifacts):
    """Test that approvals file is in correct location."""
    logger = GateAuditLogger("AIP-test-001", tmp_artifacts)

    expected_path = tmp_artifacts / "gate_approvals.jsonl"
    assert logger.log_file == expected_path
