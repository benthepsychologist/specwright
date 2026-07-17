"""Session transcript capture callable for the python backend.

This module provides the ``session.capture_transcript`` callable used by the
free-range ``chat-1`` jobdef. It collects the Claude Code session transcript
for an interactive run and copies it into the run directory as a rich run
record, alongside a small summary of turn and tool-use counts.

Callable contract (python backend):
    fn(payload: dict, repo_path: Path) -> {"passed": bool, "data": dict, "summary": str}

How the callable learns the run directory
-----------------------------------------
The python backend invokes callables as ``fn(payload=..., repo_path=...)`` and
does NOT pass the run/step output directory. So the chat-1 jobdef threads the
run location through the payload instead:

    run_id:    "@run.run_id"        # resolved at dispatch time
    runs_root: "@payload.runs_root" # the sessions store root (set by the CLI)

The run directory is then ``Path(runs_root) / run_id`` — the same path the
RunStore uses (``store.get_run_path``). The transcript and summary are written
there so they live next to run.yaml / steps/ for the same run.

How the session JSONL is resolved
---------------------------------
Claude Code encodes the launch cwd into a project directory under
``~/.claude/projects/<enc>/`` where::

    <enc> = cwd.replace("/", "-").replace(".", "-")

e.g. ``/workspace`` -> ``-workspace`` and
``/workspace/.projections/cloud-governor`` -> ``-workspace--projections-cloud-governor``.

Within that directory each session is a ``*.jsonl`` file. We pick the session
for THIS run by preferring the newest file whose mtime is >= the run start
timestamp; if none qualifies (clock skew, missing start), we fall back to the
newest ``*.jsonl`` in the directory. A missing directory or file is handled
gracefully (warning + partial result) and never raises.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

TRANSCRIPT_FILENAME = "session-transcript.jsonl"
SUMMARY_JSON_FILENAME = "session-summary.json"
SUMMARY_YAML_FILENAME = "session-summary.yaml"


def encode_cwd(cwd: str | Path) -> str:
    """Encode a launch cwd into Claude's project directory name.

    ``<enc> = cwd.replace("/", "-").replace(".", "-")``. Verified:
      - ``/workspace`` -> ``-workspace``
      - ``/workspace/.projections/cloud-governor``
        -> ``-workspace--projections-cloud-governor``
    """
    return str(cwd).replace("/", "-").replace(".", "-")


def _claude_projects_root(home: Path) -> Path:
    """Return ``<home>/.claude/projects``."""
    return home / ".claude" / "projects"


def _parse_start_ts(raw: Any) -> float | None:
    """Best-effort parse of a run-start timestamp into an epoch float.

    Accepts an epoch number (int/float or numeric string) or an ISO-8601
    string. Returns None when it cannot be parsed (selection then falls back
    to the newest file).
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            pass
        try:
            # Support a trailing "Z" (UTC) which fromisoformat rejects pre-3.11.
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _select_session_file(session_dir: Path, start_ts: float | None) -> Path | None:
    """Pick the session ``*.jsonl`` for this run.

    Prefer the newest file with mtime >= start_ts; fall back to the newest
    ``*.jsonl`` in the directory. Returns None when there are no files.
    """
    files = sorted(
        session_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return None

    if start_ts is not None:
        for path in files:
            if path.stat().st_mtime >= start_ts:
                return path
        # No file at/after start: fall through to newest overall.

    return files[0]


def _summarize_transcript(transcript_path: Path) -> dict[str, Any]:
    """Parse a session JSONL and count turns + tool_use by tool name.

    Returns a dict with: total_events, parse_errors, user_turns,
    assistant_turns, tool_use_total, tool_use_by_name (dict).
    Robust to malformed lines (counted in parse_errors, never raised).
    """
    total_events = 0
    parse_errors = 0
    user_turns = 0
    assistant_turns = 0
    tool_use_by_name: Counter[str] = Counter()

    with transcript_path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            total_events += 1
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                parse_errors += 1
                continue
            if not isinstance(event, dict):
                continue

            role = _event_role(event)
            if role == "user":
                user_turns += 1
            elif role == "assistant":
                assistant_turns += 1

            for name in _tool_use_names(event):
                tool_use_by_name[name] += 1

    tool_use_total = int(sum(tool_use_by_name.values()))
    return {
        "total_events": total_events,
        "parse_errors": parse_errors,
        "user_turns": user_turns,
        "assistant_turns": assistant_turns,
        "tool_use_total": tool_use_total,
        "tool_use_by_name": dict(sorted(tool_use_by_name.items())),
    }


def _event_role(event: dict[str, Any]) -> str | None:
    """Extract the message role from a transcript event.

    Claude Code transcript lines carry the role both at the top level
    (``type``: "user"/"assistant") and nested under ``message.role``.
    Prefer the nested message role, then the top-level type.
    """
    message = event.get("message")
    if isinstance(message, dict):
        role = message.get("role")
        if isinstance(role, str):
            return role
    type_ = event.get("type")
    if isinstance(type_, str) and type_ in {"user", "assistant"}:
        return type_
    return None


def _tool_use_names(event: dict[str, Any]) -> list[str]:
    """Collect tool_use tool names from an assistant event's content blocks."""
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else event.get("content")
    if not isinstance(content, list):
        return []
    names: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue
        name = block.get("name")
        names.append(name if isinstance(name, str) and name else "unknown")
    return names


def _write_summaries(run_dir: Path, summary: dict[str, Any]) -> None:
    """Write session-summary.json and session-summary.yaml into the run dir."""
    import yaml  # type: ignore[import]

    (run_dir / SUMMARY_JSON_FILENAME).write_text(
        json.dumps(summary, indent=2, sort_keys=False, default=str),
        encoding="utf-8",
    )
    (run_dir / SUMMARY_YAML_FILENAME).write_text(
        yaml.dump(summary, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _resolve_run_dir(payload: dict, repo_path: Path) -> Path | None:
    """Resolve the run directory from the payload.

    The chat-1 jobdef threads ``runs_root`` (the sessions store root) and
    ``run_id`` (resolved via @run.run_id) so the collector can write next to
    the run's other artifacts. An explicit ``run_dir`` override wins (useful
    for tests).
    """
    explicit = payload.get("run_dir")
    if isinstance(explicit, str) and explicit.strip():
        return Path(explicit).expanduser()

    runs_root = payload.get("runs_root")
    run_id = payload.get("run_id")
    if (
        isinstance(runs_root, str)
        and runs_root.strip()
        and isinstance(run_id, str)
        and run_id.strip()
    ):
        return Path(runs_root).expanduser() / run_id

    return None


def capture_transcript(*, payload: dict, repo_path: Path) -> dict:
    """Collect the Claude session transcript for a free-range chat run.

    Payload keys:
        launch_cwd: str — the cwd Claude was launched at (used to encode the
                    ~/.claude/projects/<enc>/ session directory). Falls back to
                    repo_path when absent.
        run_started_at: str|float|None — run start (epoch or ISO-8601) used to
                    select the session JSONL for THIS run.
        runs_root: str — the sessions store root (the run dir is
                    runs_root/run_id).
        run_id: str — this run's id (resolved via @run.run_id).
        run_dir: str|None — explicit run directory override (mainly for tests).
        home: str|None — override for the home directory (mainly for tests).

    Never raises: any missing dir/file degrades to a warning + partial result.
    """
    launch_cwd_raw = payload.get("launch_cwd") or str(repo_path)
    launch_cwd = str(launch_cwd_raw)
    start_ts = _parse_start_ts(payload.get("run_started_at"))

    home_raw = payload.get("home")
    home = Path(home_raw).expanduser() if isinstance(home_raw, str) and home_raw.strip() else Path.home()

    run_dir = _resolve_run_dir(payload, repo_path)

    warnings: list[str] = []
    data: dict[str, Any] = {
        "launch_cwd": launch_cwd,
        "encoded_dir": encode_cwd(launch_cwd),
        "transcript_copied": False,
        "transcript_path": None,
        "source_transcript": None,
        "summary": None,
        "warnings": warnings,
    }

    if run_dir is None:
        warnings.append(
            "Could not resolve run directory (need runs_root + run_id, or run_dir) "
            "- transcript not captured"
        )
        return {
            "passed": True,
            "data": data,
            "summary": "PARTIAL: no run directory resolved; transcript not captured",
        }

    enc = encode_cwd(launch_cwd)
    session_dir = _claude_projects_root(home) / enc

    if not session_dir.is_dir():
        warnings.append(f"Claude session dir not found: {session_dir} - nothing to capture")
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_summaries(run_dir, _empty_summary())
        return {
            "passed": True,
            "data": data,
            "summary": f"PARTIAL: session dir missing ({session_dir}); empty summary written",
        }

    source = _select_session_file(session_dir, start_ts)
    if source is None:
        warnings.append(f"No *.jsonl session files in {session_dir} - nothing to capture")
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_summaries(run_dir, _empty_summary())
        return {
            "passed": True,
            "data": data,
            "summary": f"PARTIAL: no session files in {session_dir}; empty summary written",
        }

    run_dir.mkdir(parents=True, exist_ok=True)
    dest = run_dir / TRANSCRIPT_FILENAME
    try:
        shutil.copy(source, dest)
    except (OSError, shutil.Error) as exc:
        warnings.append(f"Failed to copy transcript {source} -> {dest}: {exc}")
        _write_summaries(run_dir, _empty_summary())
        return {
            "passed": True,
            "data": data,
            "summary": f"PARTIAL: transcript copy failed ({exc})",
        }

    try:
        summary = _summarize_transcript(dest)
    except OSError as exc:
        warnings.append(f"Failed to summarize transcript {dest}: {exc}")
        summary = _empty_summary()

    _write_summaries(run_dir, summary)

    data["transcript_copied"] = True
    data["transcript_path"] = str(dest)
    data["source_transcript"] = str(source)
    data["summary"] = summary

    summary_line = (
        f"Captured session transcript: {dest.name} "
        f"({summary['total_events']} events, {summary['user_turns']} user turns, "
        f"{summary['assistant_turns']} assistant turns, "
        f"{summary['tool_use_total']} tool_use calls)"
    )
    return {
        "passed": True,
        "data": data,
        "summary": summary_line,
    }


def _empty_summary() -> dict[str, Any]:
    """Return a zeroed summary for the no-transcript case."""
    return {
        "total_events": 0,
        "parse_errors": 0,
        "user_turns": 0,
        "assistant_turns": 0,
        "tool_use_total": 0,
        "tool_use_by_name": {},
    }
