"""Tests for epic writer - create and update epics."""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spec.epic.loader import EpicValidationError, load_epic_from_path
from spec.epic.schema import (
    Actor,
    Epic,
    EpicState,
    EventType,
    HistoryEvent,
    Intent,
    SpecRef,
    SpecStatus,
    Target,
)
from spec.epic.writer import (
    add_spec,
    add_target,
    append_history,
    create_epic,
    generate_event_id,
    mark_spec_done,
    save_epic,
    set_current_spec,
    update_spec_status,
)


@pytest.fixture
def temp_governor(tmp_path: Path):
    """Create a temporary governor directory."""
    epics_dir = tmp_path / "epics"
    epics_dir.mkdir()

    old_env = os.environ.get("SPECWRIGHT_GOVERNOR_ROOT")
    os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = str(tmp_path)

    yield tmp_path

    if old_env:
        os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = old_env
    else:
        del os.environ["SPECWRIGHT_GOVERNOR_ROOT"]


@pytest.fixture
def sample_epic() -> Epic:
    """Create a sample epic for testing."""
    now = datetime.now(timezone.utc)
    return Epic(
        version="0.1",
        kind="epic",
        id="test-epic",
        title="Test Epic",
        owner="testuser",
        created=now,
        updated=now,
        intent=Intent(goal="Test goal"),
        targets=[Target(id="myrepo", repo_path="/workspace/myrepo", default_branch="main")],
        specs=[
            SpecRef(
                id="spec-001",
                repo="myrepo",
                branch="main",
                path="specs/test.md",
                status=SpecStatus.ACTIVE,
            )
        ],
        checks=[],
        state=EpicState(
            status=SpecStatus.ACTIVE,
            current_spec="spec-001",
            history=[
                HistoryEvent(
                    id="EVT-0001",
                    at=now,
                    event=EventType.EPIC_CREATED,
                    actor=Actor.HUMAN,
                )
            ],
        ),
    )


class TestCreateEpic:
    """Tests for create_epic function."""

    def test_creates_directory_structure(self, temp_governor: Path):
        """Creates correct directory structure."""
        epic = create_epic(
            id="new-epic",
            title="New Epic",
            owner="testuser",
            goal="Test goal",
        )

        epic_dir = temp_governor / "epics" / "new-epic"
        assert epic_dir.exists()
        assert (epic_dir / "checks").is_dir()
        assert (epic_dir / "reports").is_dir()
        assert (epic_dir / "notes.md").is_file()
        assert (epic_dir / "epic.yaml").is_file()

    def test_creates_notes_stub(self, temp_governor: Path):
        """Creates notes.md with title."""
        epic = create_epic(
            id="new-epic",
            title="My New Epic",
            owner="testuser",
            goal="Test goal",
        )

        notes_path = temp_governor / "epics" / "new-epic" / "notes.md"
        notes_content = notes_path.read_text()
        assert "My New Epic" in notes_content

    def test_returns_loaded_epic(self, temp_governor: Path):
        """Returns a loaded Epic instance."""
        epic = create_epic(
            id="new-epic",
            title="New Epic",
            owner="testuser",
            goal="Test goal",
        )

        assert isinstance(epic, Epic)
        assert epic.id == "new-epic"
        assert epic.title == "New Epic"

    def test_includes_creation_event(self, temp_governor: Path):
        """Epic has creation event in history."""
        epic = create_epic(
            id="new-epic",
            title="New Epic",
            owner="testuser",
            goal="Test goal",
        )

        assert epic.state is not None
        assert len(epic.state.history) >= 1
        assert epic.state.history[0].event == EventType.EPIC_CREATED

    def test_epic_already_exists(self, temp_governor: Path):
        """Raises error if epic already exists."""
        create_epic(id="existing", title="First", owner="test", goal="Test")

        with pytest.raises(EpicValidationError):
            create_epic(id="existing", title="Second", owner="test", goal="Test")


class TestSaveEpic:
    """Tests for save_epic function."""

    def test_saves_epic_yaml(self, temp_governor: Path, sample_epic: Epic):
        """Saves epic to epic.yaml."""
        # Create directory first
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)

        save_epic(sample_epic, update_timestamp=False)

        epic_file = epic_dir / "epic.yaml"
        assert epic_file.exists()

        # Reload and verify
        loaded = load_epic_from_path(epic_file)
        assert loaded.id == sample_epic.id
        assert loaded.title == sample_epic.title

    def test_updates_timestamp(self, temp_governor: Path, sample_epic: Epic):
        """Updates timestamp when requested."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)

        original_updated = sample_epic.updated
        save_epic(sample_epic, update_timestamp=True)

        loaded = load_epic_from_path(epic_dir / "epic.yaml")
        assert loaded.updated > original_updated

    def test_preserves_comments(self, temp_governor: Path):
        """Preserves comments on round-trip."""
        epic_dir = temp_governor / "epics" / "comment-test"
        epic_dir.mkdir(parents=True)

        # Create epic with comment
        yaml_with_comment = '''version: "0.1"  # Version number
kind: epic
id: comment-test
title: "Comment Test"
owner: test
created: 2025-12-26T00:00:00Z
updated: 2025-12-26T00:00:00Z
intent:
  goal: "Test comments"
targets: []
specs:
  - id: spec-001
    repo: test
    branch: main
    path: test.md
    status: active
state:
  status: active
  current_spec: spec-001
  history: []
'''
        # We need a target for validation
        yaml_with_comment = yaml_with_comment.replace(
            "targets: []",
            "targets:\n  - id: test\n    repo_path: /test\n    default_branch: main",
        )
        epic_file = epic_dir / "epic.yaml"
        epic_file.write_text(yaml_with_comment)

        # Load and save
        epic = load_epic_from_path(epic_file)
        save_epic(epic, update_timestamp=False)

        # Check comment preserved
        content = epic_file.read_text()
        assert "# Version number" in content


class TestAddTarget:
    """Tests for add_target function."""

    def test_adds_target(self, temp_governor: Path, sample_epic: Epic):
        """Adds target to epic."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)
        save_epic(sample_epic, update_timestamp=False)

        new_target = Target(id="other-repo", repo_path="/other", default_branch="main")
        add_target(sample_epic, new_target)

        loaded = load_epic_from_path(epic_dir / "epic.yaml")
        assert len(loaded.targets) == 2
        assert any(t.id == "other-repo" for t in loaded.targets)

    def test_duplicate_target_error(self, temp_governor: Path, sample_epic: Epic):
        """Raises error for duplicate target ID."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)
        save_epic(sample_epic, update_timestamp=False)

        duplicate = Target(id="myrepo", repo_path="/other", default_branch="main")
        with pytest.raises(EpicValidationError):
            add_target(sample_epic, duplicate)


class TestAddSpec:
    """Tests for add_spec function."""

    def test_adds_spec(self, temp_governor: Path, sample_epic: Epic):
        """Adds spec to epic."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)
        save_epic(sample_epic, update_timestamp=False)

        new_spec = SpecRef(
            id="spec-002",
            repo="myrepo",
            branch="main",
            path="specs/other.md",
        )
        add_spec(sample_epic, new_spec)

        loaded = load_epic_from_path(epic_dir / "epic.yaml")
        assert len(loaded.specs) == 2

    def test_validates_target_ref(self, temp_governor: Path, sample_epic: Epic):
        """Raises error for invalid target reference."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)
        save_epic(sample_epic, update_timestamp=False)

        new_spec = SpecRef(
            id="spec-002",
            repo="unknown-repo",
            branch="main",
            path="test.md",
        )
        with pytest.raises(EpicValidationError) as exc_info:
            add_spec(sample_epic, new_spec)
        assert "unknown target" in str(exc_info.value)

    def test_validates_no_cycle(self, temp_governor: Path, sample_epic: Epic):
        """Raises error if spec would create cycle."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)

        # Create mutual dependency
        sample_epic.specs[0].depends_on = ["spec-002"]
        save_epic(sample_epic, update_timestamp=False)

        new_spec = SpecRef(
            id="spec-002",
            repo="myrepo",
            branch="main",
            path="test.md",
            depends_on=["spec-001"],
        )
        with pytest.raises(EpicValidationError) as exc_info:
            add_spec(sample_epic, new_spec)
        assert "cycle" in str(exc_info.value)


class TestUpdateSpecStatus:
    """Tests for update_spec_status function."""

    def test_updates_status(self, temp_governor: Path, sample_epic: Epic):
        """Updates spec status."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)
        # Clear current_spec since we'll change the status
        sample_epic.state.current_spec = None
        save_epic(sample_epic, update_timestamp=False)

        update_spec_status(sample_epic, "spec-001", SpecStatus.DONE)

        loaded = load_epic_from_path(epic_dir / "epic.yaml")
        spec = loaded.get_spec("spec-001")
        assert spec is not None
        assert spec.status == SpecStatus.DONE

    def test_adds_history_event(self, temp_governor: Path, sample_epic: Epic):
        """Adds history event for status change."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)
        # Clear current_spec since we'll change the status
        sample_epic.state.current_spec = None
        save_epic(sample_epic, update_timestamp=False)

        initial_history_len = len(sample_epic.state.history)
        update_spec_status(sample_epic, "spec-001", SpecStatus.DONE, note="Completed")

        loaded = load_epic_from_path(epic_dir / "epic.yaml")
        assert len(loaded.state.history) > initial_history_len

    def test_spec_not_found(self, temp_governor: Path, sample_epic: Epic):
        """Raises error for unknown spec."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)
        save_epic(sample_epic, update_timestamp=False)

        with pytest.raises(EpicValidationError):
            update_spec_status(sample_epic, "unknown", SpecStatus.DONE)


class TestSetCurrentSpec:
    """Tests for set_current_spec function."""

    def test_sets_current(self, temp_governor: Path, sample_epic: Epic):
        """Sets current spec."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)

        # Add another spec
        sample_epic.specs.append(
            SpecRef(id="spec-002", repo="myrepo", branch="main", path="test.md")
        )
        save_epic(sample_epic, update_timestamp=False)

        set_current_spec(sample_epic, "spec-002")

        loaded = load_epic_from_path(epic_dir / "epic.yaml")
        assert loaded.state.current_spec == "spec-002"

    def test_marks_active(self, temp_governor: Path, sample_epic: Epic):
        """Marks spec as active when setting current."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)

        sample_epic.specs.append(
            SpecRef(
                id="spec-002",
                repo="myrepo",
                branch="main",
                path="test.md",
                status=SpecStatus.PLANNED,
            )
        )
        save_epic(sample_epic, update_timestamp=False)

        set_current_spec(sample_epic, "spec-002")

        loaded = load_epic_from_path(epic_dir / "epic.yaml")
        spec = loaded.get_spec("spec-002")
        assert spec.status == SpecStatus.ACTIVE


class TestMarkSpecDone:
    """Tests for mark_spec_done function."""

    def test_marks_done(self, temp_governor: Path, sample_epic: Epic):
        """Marks spec as done."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)
        save_epic(sample_epic, update_timestamp=False)

        mark_spec_done(sample_epic, "spec-001")

        loaded = load_epic_from_path(epic_dir / "epic.yaml")
        spec = loaded.get_spec("spec-001")
        assert spec.status == SpecStatus.DONE

    def test_clears_current(self, temp_governor: Path, sample_epic: Epic):
        """Clears current_spec when marking done."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)
        save_epic(sample_epic, update_timestamp=False)

        mark_spec_done(sample_epic, "spec-001")

        loaded = load_epic_from_path(epic_dir / "epic.yaml")
        assert loaded.state.current_spec is None

    def test_returns_next_ready(self, temp_governor: Path, sample_epic: Epic):
        """Returns next ready spec."""
        epic_dir = temp_governor / "epics" / sample_epic.id
        epic_dir.mkdir(parents=True)

        # Add dependent spec
        sample_epic.specs.append(
            SpecRef(
                id="spec-002",
                repo="myrepo",
                branch="main",
                path="test.md",
                status=SpecStatus.PLANNED,
                depends_on=["spec-001"],
            )
        )
        save_epic(sample_epic, update_timestamp=False)

        next_spec = mark_spec_done(sample_epic, "spec-001")
        assert next_spec == "spec-002"


class TestGenerateEventId:
    """Tests for generate_event_id function."""

    def test_first_event(self):
        """Generates EVT-0001 for first event."""
        now = datetime.now(timezone.utc)
        epic = Epic(
            version="0.1",
            kind="epic",
            id="test",
            title="Test",
            owner="test",
            created=now,
            updated=now,
            intent=Intent(goal="Test"),
            state=EpicState(status=SpecStatus.PLANNED, history=[]),
        )

        event_id = generate_event_id(epic)
        assert event_id == "EVT-0001"

    def test_monotonic_increment(self):
        """Generates monotonically increasing IDs."""
        now = datetime.now(timezone.utc)
        epic = Epic(
            version="0.1",
            kind="epic",
            id="test",
            title="Test",
            owner="test",
            created=now,
            updated=now,
            intent=Intent(goal="Test"),
            state=EpicState(
                status=SpecStatus.PLANNED,
                history=[
                    HistoryEvent(id="EVT-0001", at=now, event=EventType.EPIC_CREATED, actor=Actor.HUMAN),
                    HistoryEvent(id="EVT-0003", at=now, event=EventType.EPIC_UPDATED, actor=Actor.HUMAN),
                ],
            ),
        )

        event_id = generate_event_id(epic)
        assert event_id == "EVT-0004"

    def test_handles_non_numeric_ids(self):
        """Handles non-standard event IDs."""
        now = datetime.now(timezone.utc)
        epic = Epic(
            version="0.1",
            kind="epic",
            id="test",
            title="Test",
            owner="test",
            created=now,
            updated=now,
            intent=Intent(goal="Test"),
            state=EpicState(
                status=SpecStatus.PLANNED,
                history=[
                    HistoryEvent(id="OLD-EVENT", at=now, event=EventType.EPIC_CREATED, actor=Actor.HUMAN),
                    HistoryEvent(id="EVT-0002", at=now, event=EventType.EPIC_UPDATED, actor=Actor.HUMAN),
                ],
            ),
        )

        event_id = generate_event_id(epic)
        assert event_id == "EVT-0003"
