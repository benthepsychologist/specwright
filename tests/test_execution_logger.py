"""Tests for execution audit logger."""

import json
from datetime import datetime
from pathlib import Path
import pytest
from spec.audit.execution_logger import ExecutionAuditLogger


@pytest.fixture
def tmp_artifacts(tmp_path):
    """Create temporary artifacts directory."""
    artifacts_dir = tmp_path / ".aip_artifacts"
    artifacts_dir.mkdir()
    return artifacts_dir


@pytest.fixture
def logger(tmp_artifacts):
    """Create execution audit logger."""
    return ExecutionAuditLogger(tmp_artifacts)


def test_log_spec_created(logger, tmp_artifacts):
    """Test logging spec creation event."""
    logger.log_spec_created(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec"
    )

    # Verify log file was created
    log_file = tmp_artifacts / "execution_history.jsonl"
    assert log_file.exists()

    # Read and verify log entry
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["event"] == "spec_created"
    assert entry["aip_id"] == "AIP-test-2025-01-15-001"
    assert entry["project_slug"] == "test"
    assert entry["metadata"]["spec_path"] == "specs/test.md"
    assert entry["metadata"]["author"] == "alice"
    assert entry["metadata"]["tier"] == "B"
    assert "timestamp" in entry
    assert "git" in entry


def test_log_spec_compiled(logger, tmp_artifacts):
    """Test logging spec compilation event."""
    logger.log_spec_compiled(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        aip_path="aips/test.yaml",
        source_hash="sha256:abc123",
        compiler_version="0.5.0"
    )

    log_file = tmp_artifacts / "execution_history.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["event"] == "spec_compiled"
    assert entry["metadata"]["source_hash"] == "sha256:abc123"
    assert entry["metadata"]["compiler_version"] == "0.5.0"


def test_log_execution_started(logger, tmp_artifacts):
    """Test logging execution start event."""
    git_snapshot = logger.log_execution_started(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        executor="alice",
        aip_path="aips/test.yaml"
    )

    # Verify git metadata is returned
    assert isinstance(git_snapshot, dict)
    assert "branch" in git_snapshot
    assert "commit" in git_snapshot

    log_file = tmp_artifacts / "execution_history.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["event"] == "execution_started"
    assert entry["metadata"]["executor"] == "alice"


def test_log_execution_completed(logger, tmp_artifacts):
    """Test logging execution completion event."""
    logger.log_execution_completed(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        status="success",
        artifacts_path=".aip_artifacts/AIP-test-2025-01-15-001"
    )

    log_file = tmp_artifacts / "execution_history.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["event"] == "execution_completed"
    assert entry["metadata"]["status"] == "success"


def test_log_spec_closed(logger, tmp_artifacts):
    """Test logging spec closure event."""
    logger.log_spec_closed(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        outcome="merged",
        pr_url="https://github.com/user/repo/pull/42",
        notes="Completed successfully"
    )

    log_file = tmp_artifacts / "execution_history.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    assert entry["event"] == "spec_closed"
    assert entry["metadata"]["outcome"] == "merged"
    assert entry["metadata"]["pr_url"] == "https://github.com/user/repo/pull/42"


def test_get_events_no_filter(logger, tmp_artifacts):
    """Test retrieving all events."""
    # Log multiple events
    logger.log_spec_created(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec"
    )
    logger.log_spec_compiled(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        aip_path="aips/test.yaml",
        source_hash="sha256:abc123",
        compiler_version="0.5.0"
    )

    events = logger.get_events()
    assert len(events) == 2
    assert events[0]["event"] == "spec_created"
    assert events[1]["event"] == "spec_compiled"


def test_get_events_filter_by_aip_id(logger, tmp_artifacts):
    """Test filtering events by AIP ID."""
    # Log events for different AIPs
    logger.log_spec_created(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test1.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec 1"
    )
    logger.log_spec_created(
        aip_id="AIP-test-2025-01-15-002",
        project_slug="test",
        spec_path="specs/test2.md",
        spec_version="1.0.0",
        author="bob",
        tier="C",
        title="Test Spec 2"
    )

    events = logger.get_events(aip_id="AIP-test-2025-01-15-001")
    assert len(events) == 1
    assert events[0]["aip_id"] == "AIP-test-2025-01-15-001"


def test_get_events_filter_by_event_type(logger, tmp_artifacts):
    """Test filtering events by type."""
    logger.log_spec_created(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec"
    )
    logger.log_spec_compiled(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        aip_path="aips/test.yaml",
        source_hash="sha256:abc123",
        compiler_version="0.5.0"
    )

    events = logger.get_events(event_type="spec_compiled")
    assert len(events) == 1
    assert events[0]["event"] == "spec_compiled"


def test_get_events_filter_by_project_slug(logger, tmp_artifacts):
    """Test filtering events by project slug."""
    logger.log_spec_created(
        aip_id="AIP-project1-2025-01-15-001",
        project_slug="project1",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec"
    )
    logger.log_spec_created(
        aip_id="AIP-project2-2025-01-15-001",
        project_slug="project2",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="bob",
        tier="C",
        title="Test Spec"
    )

    events = logger.get_events(project_slug="project1")
    assert len(events) == 1
    assert events[0]["project_slug"] == "project1"


def test_get_timeline(logger, tmp_artifacts):
    """Test getting chronological timeline."""
    # Log events
    logger.log_spec_created(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec"
    )
    logger.log_spec_compiled(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        aip_path="aips/test.yaml",
        source_hash="sha256:abc123",
        compiler_version="0.5.0"
    )

    timeline = logger.get_timeline()
    assert len(timeline) == 2
    # Should be reverse chronological (newest first)
    assert timeline[0]["event"] == "spec_compiled"
    assert timeline[1]["event"] == "spec_created"


def test_get_timeline_with_limit(logger, tmp_artifacts):
    """Test timeline with limit."""
    # Log 3 events
    for i in range(3):
        logger.log_spec_created(
            aip_id=f"AIP-test-2025-01-15-{i:03d}",
            project_slug="test",
            spec_path=f"specs/test{i}.md",
            spec_version="1.0.0",
            author="alice",
            tier="B",
            title=f"Test Spec {i}"
        )

    timeline = logger.get_timeline(limit=2)
    assert len(timeline) == 2


def test_get_aip_history(logger, tmp_artifacts):
    """Test getting complete history for specific AIP."""
    aip_id = "AIP-test-2025-01-15-001"

    # Log lifecycle events
    logger.log_spec_created(
        aip_id=aip_id,
        project_slug="test",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec"
    )
    logger.log_spec_compiled(
        aip_id=aip_id,
        project_slug="test",
        spec_path="specs/test.md",
        aip_path="aips/test.yaml",
        source_hash="sha256:abc123",
        compiler_version="0.5.0"
    )
    logger.log_execution_started(
        aip_id=aip_id,
        project_slug="test",
        executor="alice",
        aip_path="aips/test.yaml"
    )

    history = logger.get_aip_history(aip_id)
    assert len(history) == 3
    # Should be chronological (oldest first)
    assert history[0]["event"] == "spec_created"
    assert history[1]["event"] == "spec_compiled"
    assert history[2]["event"] == "execution_started"


def test_multiple_events_append(logger, tmp_artifacts):
    """Test that events are appended to log file."""
    log_file = tmp_artifacts / "execution_history.jsonl"

    # Log first event
    logger.log_spec_created(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec"
    )

    # Log second event
    logger.log_spec_compiled(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        aip_path="aips/test.yaml",
        source_hash="sha256:abc123",
        compiler_version="0.5.0"
    )

    # Read all lines
    with open(log_file) as f:
        lines = f.readlines()

    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "spec_created"
    assert json.loads(lines[1])["event"] == "spec_compiled"


def test_git_metadata_capture(logger, tmp_artifacts):
    """Test that git metadata is captured."""
    logger.log_spec_created(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec"
    )

    log_file = tmp_artifacts / "execution_history.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    # Should have git metadata (even if None when not in git repo)
    assert "git" in entry
    assert "branch" in entry["git"]
    assert "commit" in entry["git"]
    assert "remote_url" in entry["git"]


def test_log_execution_completed_with_diff_stats(logger, tmp_artifacts):
    """Test logging execution completion with git diff stats."""
    # Start execution and capture git metadata
    git_start = logger.log_execution_started(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        executor="alice",
        aip_path="aips/test.yaml"
    )

    start_commit = git_start.get("commit")

    # Complete execution with start commit
    logger.log_execution_completed(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        status="success",
        start_git_commit=start_commit,
        artifacts_path=".aip_artifacts/AIP-test-2025-01-15-001"
    )

    log_file = tmp_artifacts / "execution_history.jsonl"
    with open(log_file) as f:
        # Skip first line (execution_started)
        f.readline()
        # Read completion entry
        entry = json.loads(f.readline())

    assert entry["event"] == "execution_completed"
    assert entry["metadata"]["status"] == "success"
    assert entry["metadata"]["artifacts_path"] == ".aip_artifacts/AIP-test-2025-01-15-001"

    # Diff stats may be present if in git repo
    if start_commit:
        assert "diff_stats" in entry["metadata"]


def test_get_events_filter_by_since(logger):
    """Test filtering events by timestamp."""
    from datetime import datetime, timedelta

    # Log first event
    logger.log_spec_created(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec 1"
    )

    # Set cutoff time
    cutoff = datetime.now()

    # Wait briefly and log second event
    import time
    time.sleep(0.1)

    logger.log_spec_compiled(
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        spec_path="specs/test.md",
        aip_path="aips/test.yaml",
        source_hash="sha256:abc123",
        compiler_version="0.5.0"
    )

    # Get events after cutoff
    events = logger.get_events(since=cutoff)

    # Should only get the second event
    assert len(events) == 1
    assert events[0]["event"] == "spec_compiled"


def test_get_timeline_with_project_filter(logger):
    """Test getting timeline filtered by project slug."""
    # Log events for different projects
    logger.log_spec_created(
        aip_id="AIP-project1-2025-01-15-001",
        project_slug="project1",
        spec_path="specs/test1.md",
        spec_version="1.0.0",
        author="alice",
        tier="B",
        title="Test Spec"
    )

    logger.log_spec_created(
        aip_id="AIP-project2-2025-01-15-001",
        project_slug="project2",
        spec_path="specs/test2.md",
        spec_version="1.0.0",
        author="bob",
        tier="C",
        title="Test Spec"
    )

    timeline = logger.get_timeline(project_slug="project1")

    assert len(timeline) == 1
    assert timeline[0]["project_slug"] == "project1"


def test_log_event_without_git_metadata(logger, tmp_artifacts):
    """Test logging event without git metadata."""
    logger.log_event(
        event_type="custom_event",
        aip_id="AIP-test-2025-01-15-001",
        project_slug="test",
        metadata={"custom": "data"},
        include_git=False
    )

    log_file = tmp_artifacts / "execution_history.jsonl"
    with open(log_file) as f:
        entry = json.loads(f.readline())

    # Should not have git metadata
    assert "git" not in entry
    assert entry["event"] == "custom_event"
    assert entry["metadata"]["custom"] == "data"
