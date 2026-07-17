"""Tests for the session.capture_transcript callable."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from spec.governance.session_capture import (
    capture_transcript,
    encode_cwd,
)


def test_encode_cwd_examples() -> None:
    """cwd encoding matches Claude's ~/.claude/projects/<enc>/ scheme."""
    assert encode_cwd("/workspace") == "-workspace"
    assert (
        encode_cwd("/workspace/.projections/cloud-governor")
        == "-workspace--projections-cloud-governor"
    )


def _make_transcript(path: Path) -> None:
    """Write a small fake Claude session JSONL fixture.

    2 user turns, 3 assistant turns, tool_use: Bash x2, Read x1, Edit x1.
    """
    events = [
        {"type": "user", "message": {"role": "user", "content": "hello"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "hi"},
                    {"type": "tool_use", "name": "Bash", "input": {}},
                ],
            },
        },
        {"type": "user", "message": {"role": "user", "content": "do stuff"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Read", "input": {}},
                    {"type": "tool_use", "name": "Bash", "input": {}},
                ],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Edit", "input": {}},
                ],
            },
        },
    ]
    lines = [json.dumps(e) for e in events]
    # Inject a malformed line to verify graceful parse-error handling.
    lines.append("{ this is not json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_capture_copies_transcript_and_counts(tmp_path: Path) -> None:
    """Happy path: transcript copied into run dir, summary counts correct."""
    home = tmp_path / "home"
    launch_cwd = "/workspace"
    session_dir = home / ".claude" / "projects" / encode_cwd(launch_cwd)
    session_dir.mkdir(parents=True)
    _make_transcript(session_dir / "session-abc.jsonl")

    run_dir = tmp_path / "sessions" / "run-chat-001"

    result = capture_transcript(
        payload={
            "launch_cwd": launch_cwd,
            "run_dir": str(run_dir),
            "home": str(home),
        },
        repo_path=Path(launch_cwd),
    )

    assert result["passed"] is True
    data = result["data"]
    assert data["transcript_copied"] is True
    assert data["encoded_dir"] == "-workspace"

    # Transcript copied into the run dir.
    transcript = run_dir / "session-transcript.jsonl"
    assert transcript.exists()

    # Summary counts.
    summary = data["summary"]
    assert summary["user_turns"] == 2
    assert summary["assistant_turns"] == 3
    assert summary["parse_errors"] == 1
    assert summary["tool_use_total"] == 4
    assert summary["tool_use_by_name"] == {"Bash": 2, "Edit": 1, "Read": 1}

    # Summary artifacts written in both formats.
    json_summary = json.loads((run_dir / "session-summary.json").read_text())
    assert json_summary["tool_use_by_name"]["Bash"] == 2
    yaml_summary = yaml.safe_load((run_dir / "session-summary.yaml").read_text())
    assert yaml_summary["assistant_turns"] == 3


def test_capture_selects_newest_after_start(tmp_path: Path) -> None:
    """Prefer the newest *.jsonl with mtime >= run start."""
    import os
    import time

    home = tmp_path / "home"
    launch_cwd = "/workspace/proj"
    session_dir = home / ".claude" / "projects" / encode_cwd(launch_cwd)
    session_dir.mkdir(parents=True)

    old = session_dir / "old.jsonl"
    new = session_dir / "new.jsonl"
    _make_transcript(old)
    _make_transcript(new)

    # old before start, new after start.
    start = time.time()
    os.utime(old, (start - 100, start - 100))
    os.utime(new, (start + 10, start + 10))

    run_dir = tmp_path / "sessions" / "run-chat-002"
    result = capture_transcript(
        payload={
            "launch_cwd": launch_cwd,
            "run_started_at": start,
            "run_dir": str(run_dir),
            "home": str(home),
        },
        repo_path=Path(launch_cwd),
    )
    assert result["data"]["source_transcript"] == str(new)


def test_capture_resolves_run_dir_from_runs_root_and_run_id(tmp_path: Path) -> None:
    """run_dir is runs_root/run_id when no explicit run_dir is given."""
    home = tmp_path / "home"
    launch_cwd = "/workspace"
    session_dir = home / ".claude" / "projects" / encode_cwd(launch_cwd)
    session_dir.mkdir(parents=True)
    _make_transcript(session_dir / "s.jsonl")

    runs_root = tmp_path / "sessions"
    result = capture_transcript(
        payload={
            "launch_cwd": launch_cwd,
            "runs_root": str(runs_root),
            "run_id": "run-chat-xyz",
            "home": str(home),
        },
        repo_path=Path(launch_cwd),
    )
    expected = runs_root / "run-chat-xyz" / "session-transcript.jsonl"
    assert result["data"]["transcript_path"] == str(expected)
    assert expected.exists()


def test_capture_graceful_when_session_dir_missing(tmp_path: Path) -> None:
    """Missing session dir: no raise, partial result, empty summary written."""
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    run_dir = tmp_path / "sessions" / "run-chat-003"

    result = capture_transcript(
        payload={
            "launch_cwd": "/workspace/does-not-exist",
            "run_dir": str(run_dir),
            "home": str(home),
        },
        repo_path=Path("/workspace/does-not-exist"),
    )

    assert result["passed"] is True
    assert result["data"]["transcript_copied"] is False
    assert any("session dir" in w.lower() for w in result["data"]["warnings"])
    # Empty summary still written.
    summary = json.loads((run_dir / "session-summary.json").read_text())
    assert summary["total_events"] == 0


def test_capture_graceful_when_no_files(tmp_path: Path) -> None:
    """Session dir exists but has no *.jsonl: graceful no-op."""
    home = tmp_path / "home"
    launch_cwd = "/workspace"
    session_dir = home / ".claude" / "projects" / encode_cwd(launch_cwd)
    session_dir.mkdir(parents=True)
    run_dir = tmp_path / "sessions" / "run-chat-004"

    result = capture_transcript(
        payload={
            "launch_cwd": launch_cwd,
            "run_dir": str(run_dir),
            "home": str(home),
        },
        repo_path=Path(launch_cwd),
    )
    assert result["passed"] is True
    assert result["data"]["transcript_copied"] is False


def test_capture_registered_callable() -> None:
    """The callable is registered under the expected name."""
    from spec.governance.callables import register_all

    register_all()
    from spec.executor.backends.python import get_callable

    assert get_callable("session.capture_transcript") is capture_transcript
