"""Epic writer: create and update epics.

This module provides functions for creating new epics and updating
existing ones with proper file structure and history tracking.

Uses ruamel.yaml for round-trip YAML preservation - comments, ordering,
and formatting are preserved when updating existing epic.yaml files.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from spec.epic.loader import (
    EpicValidationError,
    get_epic_path,
)
from spec.epic.schema import (
    Actor,
    Epic,
    EpicState,
    EventType,
    HistoryEvent,
    SpecRef,
    SpecStatus,
    Target,
)

if TYPE_CHECKING:
    pass


def _disable_implicit_timestamps(yaml: YAML) -> None:
    """Disable YAML 1.1 implicit timestamp parsing.

    Keeps ISO-like scalars (e.g., 2026-01-16T00:00:00Z) as strings instead of
    auto-converting to datetime objects.
    """
    try:
        resolvers = yaml.Resolver.yaml_implicit_resolvers
    except Exception:
        return

    for key, mappings in list(resolvers.items()):
        resolvers[key] = [
            m for m in mappings if not m or m[0] != "tag:yaml.org,2002:timestamp"
        ]


def _get_yaml() -> YAML:
    """Get configured YAML instance for round-trip preservation."""
    yaml = YAML()
    _disable_implicit_timestamps(yaml)
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _load_yaml_roundtrip(path: Path) -> CommentedMap:
    """Load YAML file preserving comments and structure.

    Args:
        path: Path to YAML file.

    Returns:
        CommentedMap that preserves comments on round-trip.
    """
    yaml = _get_yaml()
    with open(path) as f:
        return yaml.load(f)


def _save_yaml_roundtrip(path: Path, data: CommentedMap) -> None:
    """Save YAML file preserving comments and structure.

    Args:
        path: Path to YAML file.
        data: CommentedMap to save.
    """
    yaml = _get_yaml()
    with open(path, "w") as f:
        yaml.dump(data, f)


def save_epic(epic: Epic, update_timestamp: bool = True) -> None:
    """Save epic to epic.yaml with round-trip preservation.

    If the file exists, loads it first to preserve comments and ordering,
    then updates only the changed fields. For new files, creates fresh YAML.

    Args:
        epic: Epic instance to save.
        update_timestamp: If True, update the 'updated' field.
    """
    if update_timestamp:
        epic.updated = datetime.now(UTC)

    epic_dir = get_epic_path(epic.id)
    epic_file = epic_dir / "epic.yaml"

    if epic_file.exists():
        # Round-trip: load existing, update in-place
        data = _load_yaml_roundtrip(epic_file)
        _update_yaml_from_epic(data, epic)
    else:
        # New file: create from scratch
        data = _epic_to_commented_map(epic)

    _save_yaml_roundtrip(epic_file, data)


def _update_yaml_from_epic(data: CommentedMap, epic: Epic) -> None:
    """Update YAML data in-place from Epic, preserving structure.

    Only updates fields that might change during normal operations.
    Preserves comments and ordering of existing fields.
    """
    # Update timestamp
    data["updated"] = epic.updated.isoformat()

    # Update state
    if epic.state:
        if "state" not in data:
            data["state"] = CommentedMap()
        data["state"]["status"] = epic.state.status.value
        if epic.state.current_spec:
            data["state"]["current_spec"] = epic.state.current_spec
        elif "current_spec" in data["state"]:
            del data["state"]["current_spec"]

        # Update history - append new events
        if "history" not in data["state"]:
            data["state"]["history"] = CommentedSeq()

        existing_ids = {h["id"] for h in data["state"]["history"]}
        for event in epic.state.history:
            if event.id not in existing_ids:
                data["state"]["history"].append(_history_event_to_map(event))

    # Update specs (status changes)
    if "specs" in data:
        spec_map = {s.id: s for s in epic.specs}
        for spec_data in data["specs"]:
            spec_id = spec_data["id"]
            if spec_id in spec_map:
                spec_data["status"] = spec_map[spec_id].status.value

    # Update targets if changed
    if epic.targets:
        existing_target_ids = {t["id"] for t in data.get("targets", [])}
        for target in epic.targets:
            if target.id not in existing_target_ids:
                if "targets" not in data:
                    data["targets"] = CommentedSeq()
                data["targets"].append(_target_to_map(target))

    # Update specs if new ones added
    if epic.specs:
        existing_spec_ids = {s["id"] for s in data.get("specs", [])}
        for spec in epic.specs:
            if spec.id not in existing_spec_ids:
                if "specs" not in data:
                    data["specs"] = CommentedSeq()
                data["specs"].append(_spec_to_map(spec))


def _epic_to_commented_map(epic: Epic) -> CommentedMap:
    """Convert Epic to CommentedMap for new files."""
    data = CommentedMap()
    data["version"] = epic.version
    data["kind"] = epic.kind
    data["id"] = epic.id
    data["title"] = epic.title
    data["owner"] = epic.owner
    data["created"] = epic.created.isoformat()
    data["updated"] = epic.updated.isoformat()

    data["intent"] = CommentedMap()
    data["intent"]["goal"] = epic.intent.goal
    if epic.intent.narrative:
        data["intent"]["narrative"] = epic.intent.narrative

    if epic.run_context:
        data["run_context"] = CommentedMap()
        data["run_context"]["governor_root"] = epic.run_context.governor_root
        data["run_context"]["cli_bin"] = epic.run_context.cli_bin
        data["run_context"]["cwd_policy"] = epic.run_context.cwd_policy
        if epic.run_context.env_override:
            if isinstance(epic.run_context.env_override, str):
                raise AssertionError(
                    f"env_override must be a dict, got str: "
                    f"{epic.run_context.env_override!r}. "
                    "String env_override is no longer supported as of epic@0-3-0."
                )
            data["run_context"]["env_override"] = epic.run_context.env_override

    if epic.governance:
        data["governance"] = CommentedMap()
        data["governance"]["enabled"] = epic.governance.enabled
        data["governance"]["source"] = epic.governance.source
        data["governance"]["project"] = epic.governance.project
        if epic.governance.include:
            data["governance"]["include"] = CommentedSeq(epic.governance.include)

    if epic.defaults and epic.defaults.model:
        data["defaults"] = CommentedMap()
        data["defaults"]["model"] = epic.defaults.model

    data["targets"] = CommentedSeq([_target_to_map(t) for t in epic.targets])
    data["specs"] = CommentedSeq([_spec_to_map(s) for s in epic.specs])
    data["checks"] = CommentedSeq([_check_to_map(c) for c in epic.checks])

    if epic.state:
        data["state"] = CommentedMap()
        data["state"]["status"] = epic.state.status.value
        if epic.state.current_spec:
            data["state"]["current_spec"] = epic.state.current_spec
        data["state"]["history"] = CommentedSeq(
            [_history_event_to_map(e) for e in epic.state.history]
        )

    return data


def _target_to_map(target: Target) -> CommentedMap:
    """Convert Target to CommentedMap."""
    m = CommentedMap()
    m["id"] = target.id
    m["repo_path"] = target.repo_path
    m["default_branch"] = target.default_branch
    if target.governor_project:
        m["governor_project"] = target.governor_project
    return m


def _spec_to_map(spec: SpecRef) -> CommentedMap:
    """Convert SpecRef to CommentedMap."""
    m = CommentedMap()
    m["id"] = spec.id
    m["repo"] = spec.repo
    m["branch"] = spec.branch
    if spec.path:
        m["path"] = spec.path
    m["status"] = spec.status.value
    if spec.depends_on:
        m["depends_on"] = CommentedSeq(spec.depends_on)
    if spec.expectations:
        m["expectations"] = CommentedSeq(spec.expectations)
    if getattr(spec, "constraints", None):
        if spec.constraints:
            m["constraints"] = CommentedSeq(spec.constraints)
    if spec.checks:
        m["checks"] = CommentedSeq(spec.checks)
    return m


def _check_to_map(check: Any) -> CommentedMap:
    """Convert Check to CommentedMap."""

    m = CommentedMap()
    m["id"] = check.id
    m["name"] = check.name
    m["scope"] = check.scope.value
    m["prompt_ref"] = check.prompt_ref
    if check.model:
        m["model"] = check.model
    if check.default_spec:
        m["default_spec"] = check.default_spec
    if check.response_contract:
        m["response_contract"] = CommentedMap()
        m["response_contract"]["verdicts"] = CommentedSeq(
            check.response_contract.verdicts
        )
        m["response_contract"]["required_sections"] = CommentedSeq(
            check.response_contract.required_sections
        )
    if check.inputs:
        m["inputs"] = CommentedSeq([_check_input_to_map(i) for i in check.inputs])
    return m


def _check_input_to_map(inp: Any) -> CommentedMap:
    """Convert CheckInput to CommentedMap."""
    m = CommentedMap()
    m["type"] = inp.type
    if inp.path:
        m["path"] = inp.path
    if inp.args:
        m["args"] = CommentedSeq(inp.args)
    if inp.target:
        m["target"] = inp.target
    if inp.range:
        m["range"] = inp.range
    if inp.include:
        m["include"] = CommentedSeq(inp.include)
    return m


def _history_event_to_map(event: HistoryEvent) -> CommentedMap:
    """Convert HistoryEvent to CommentedMap."""
    m = CommentedMap()
    m["id"] = event.id
    m["at"] = event.at.isoformat()
    m["event"] = event.event.value
    m["actor"] = event.actor.value
    if event.spec_id:
        m["spec_id"] = event.spec_id
    if event.check_id:
        m["check_id"] = event.check_id
    if event.verdict:
        m["verdict"] = event.verdict
    if event.report:
        m["report"] = event.report
    if event.note:
        m["note"] = event.note
    if event.step is not None:
        m["step"] = event.step
    if event.plan_artifact:
        m["plan_artifact"] = event.plan_artifact
    if event.commit:
        m["commit"] = event.commit
    if event.verification:
        m["verification"] = CommentedMap()
        m["verification"]["commands"] = CommentedSeq(event.verification.commands)
        m["verification"]["status"] = event.verification.status
    return m


def update_spec_status(
    epic: Epic,
    spec_id: str,
    status: SpecStatus,
    note: str | None = None,
) -> None:
    """Update a spec's status and append history event.

    Args:
        epic: Epic to modify.
        spec_id: ID of spec to update.
        status: New status.
        note: Optional note for history event.

    Raises:
        EpicValidationError: If spec not found.
    """
    spec = epic.get_spec(spec_id)
    if not spec:
        raise EpicValidationError(f"Spec not found: {spec_id}")

    old_status = spec.status
    spec.status = status

    # Map status to event type
    event_map = {
        SpecStatus.ACTIVE: EventType.SPEC_ACTIVATED,
        SpecStatus.BLOCKED: EventType.SPEC_BLOCKED,
        SpecStatus.DONE: EventType.SPEC_DONE,
        SpecStatus.ABANDONED: EventType.SPEC_ABANDONED,
    }

    event_type = event_map.get(status, EventType.EPIC_UPDATED)

    event = HistoryEvent(
        id=generate_event_id(epic),
        at=datetime.now(UTC),
        event=event_type,
        actor=Actor.SPECWRIGHT,
        spec_id=spec_id,
        note=note or f"Status changed from {old_status.value} to {status.value}",
    )

    append_history(epic, event)


def mark_spec_done(
    epic: Epic,
    spec_id: str,
    note: str | None = None,
) -> str | None:
    """Mark a spec as done.

    Clears current_spec if this spec was current. Returns the next
    ready spec ID as a suggestion, but does not set it as current.

    Args:
        epic: Epic to modify.
        spec_id: ID of spec to mark done.
        note: Optional completion note.

    Returns:
        ID of next ready spec (suggestion only), or None if none ready.

    Raises:
        EpicValidationError: If spec not found.
    """
    spec = epic.get_spec(spec_id)
    if not spec:
        raise EpicValidationError(f"Spec not found: {spec_id}")

    spec.status = SpecStatus.DONE

    # Clear current_spec if this was it
    if epic.state and epic.state.current_spec == spec_id:
        epic.state.current_spec = None

    event = HistoryEvent(
        id=generate_event_id(epic),
        at=datetime.now(UTC),
        event=EventType.SPEC_DONE,
        actor=Actor.SPECWRIGHT,
        spec_id=spec_id,
        note=note or "Spec completed",
    )

    append_history(epic, event)

    # Find next ready spec
    from spec.epic.dag import get_ready_specs

    ready = get_ready_specs(epic.specs)
    return ready[0].id if ready else None


def append_history(epic: Epic, event: HistoryEvent) -> None:
    """Append a history event and save.

    Args:
        epic: Epic to modify.
        event: Event to append.
    """
    if not epic.state:
        epic.state = EpicState(
            status=SpecStatus.PLANNED,
            current_spec=None,
            history=[],
        )

    epic.state.history.append(event)
    save_epic(epic)


def generate_event_id(epic: Epic) -> str:
    """Generate the next event ID.

    IDs are monotonic: next = max(existing numeric IDs) + 1.
    Format: EVT-0001, EVT-0002, etc.

    Args:
        epic: Epic to generate ID for.

    Returns:
        Next event ID string.
    """
    max_num = 0

    if epic.state and epic.state.history:
        for event in epic.state.history:
            # Parse EVT-XXXX format
            if event.id.startswith("EVT-"):
                try:
                    num = int(event.id[4:])
                    max_num = max(max_num, num)
                except ValueError:
                    pass

    next_num = max_num + 1
    return f"EVT-{next_num:04d}"
