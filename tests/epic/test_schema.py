"""Tests for epic schema dataclasses and validation."""

from datetime import UTC, datetime

import pytest

from spec.epic.schema import (
    Actor,
    Check,
    CheckInput,
    CheckScope,
    Epic,
    EpicState,
    EventType,
    HistoryEvent,
    Intent,
    ResponseContract,
    SpecRef,
    SpecStatus,
    Target,
    Verification,
)


@pytest.fixture
def sample_target() -> Target:
    """Create a sample target for testing."""
    return Target(
        id="myrepo",
        repo_path="/workspace/myrepo",
        default_branch="main",
        governor_project="projects/myrepo",
    )


@pytest.fixture
def sample_spec() -> SpecRef:
    """Create a sample spec reference for testing."""
    return SpecRef(
        id="spec-001",
        repo="myrepo",
        branch="feat/test",
        path="specs/test.md",
        status=SpecStatus.PLANNED,
        depends_on=[],
        expectations=["Feature implemented"],
        checks=["CHECK-001"],
    )


@pytest.fixture
def sample_check() -> Check:
    """Create a sample check for testing."""
    return Check(
        id="CHECK-001",
        name="Test Check",
        scope=CheckScope.SPEC,
        prompt_ref="checks/test.md",
        model="gpt-4o",
        response_contract=ResponseContract(
            verdicts=["PASS", "FAIL"],
            required_sections=["Findings", "Verdict"],
        ),
        inputs=[
            CheckInput(type="file", path="src/main.py"),
        ],
    )


@pytest.fixture
def sample_epic(sample_target: Target, sample_spec: SpecRef, sample_check: Check) -> Epic:
    """Create a sample epic for testing."""
    now = datetime.now(UTC)
    return Epic(
        version="0.1",
        kind="epic",
        id="e001-test",
        title="Test Epic",
        owner="testuser",
        created=now,
        updated=now,
        intent=Intent(goal="Test the epic system", narrative="A test narrative."),
        targets=[sample_target],
        specs=[sample_spec],
        checks=[sample_check],
        state=EpicState(
            status=SpecStatus.PLANNED,
            current_spec=None,
            history=[
                HistoryEvent(
                    id="EVT-0001",
                    at=now,
                    event=EventType.EPIC_CREATED,
                    actor=Actor.HUMAN,
                    note="Created for testing",
                )
            ],
        ),
    )


class TestEnums:
    """Tests for enum values."""

    def test_spec_status_values(self):
        """SpecStatus has correct values."""
        assert SpecStatus.PLANNED.value == "planned"
        assert SpecStatus.ACTIVE.value == "active"
        assert SpecStatus.BLOCKED.value == "blocked"
        assert SpecStatus.DONE.value == "done"
        assert SpecStatus.ABANDONED.value == "abandoned"

    def test_event_type_values(self):
        """EventType has correct values."""
        assert EventType.EPIC_CREATED.value == "epic.created"
        assert EventType.SPEC_ACTIVATED.value == "spec.activated"
        assert EventType.CHECK_COMPLETED.value == "check.completed"

    def test_actor_values(self):
        """Actor has correct values."""
        assert Actor.HUMAN.value == "human"
        assert Actor.SPECWRIGHT.value == "specwright"
        assert Actor.LLM.value == "llm"

    def test_check_scope_values(self):
        """CheckScope has correct values."""
        assert CheckScope.SPEC.value == "spec"
        assert CheckScope.EPIC.value == "epic"


class TestDataclasses:
    """Tests for dataclass creation."""

    def test_target_creation(self, sample_target: Target):
        """Target creates with correct fields."""
        assert sample_target.id == "myrepo"
        assert sample_target.repo_path == "/workspace/myrepo"
        assert sample_target.default_branch == "main"
        assert sample_target.governor_project == "projects/myrepo"

    def test_target_optional_governor_project(self):
        """Target allows None for governor_project."""
        target = Target(id="test", repo_path="/test", default_branch="main")
        assert target.governor_project is None

    def test_spec_ref_creation(self, sample_spec: SpecRef):
        """SpecRef creates with correct fields."""
        assert sample_spec.id == "spec-001"
        assert sample_spec.status == SpecStatus.PLANNED
        assert sample_spec.depends_on == []
        assert "Feature implemented" in sample_spec.expectations

    def test_check_creation(self, sample_check: Check):
        """Check creates with correct fields."""
        assert sample_check.id == "CHECK-001"
        assert sample_check.scope == CheckScope.SPEC
        assert sample_check.response_contract is not None
        assert len(sample_check.inputs) == 1

    def test_history_event_creation(self):
        """HistoryEvent creates with correct fields."""
        now = datetime.now(UTC)
        event = HistoryEvent(
            id="EVT-0001",
            at=now,
            event=EventType.EPIC_CREATED,
            actor=Actor.HUMAN,
            note="Test note",
            verification=Verification(commands=["pytest"], status="pass"),
        )
        assert event.id == "EVT-0001"
        assert event.actor == Actor.HUMAN
        assert event.verification is not None
        assert event.verification.commands == ["pytest"]

    def test_epic_creation(self, sample_epic: Epic):
        """Epic creates with correct fields."""
        assert sample_epic.id == "e001-test"
        assert sample_epic.title == "Test Epic"
        assert len(sample_epic.targets) == 1
        assert len(sample_epic.specs) == 1
        assert len(sample_epic.checks) == 1


class TestEpicValidation:
    """Tests for Epic validation methods."""

    def test_validate_success(self, sample_epic: Epic):
        """Valid epic passes validation."""
        errors = sample_epic.validate()
        assert errors == []

    def test_validate_invalid_target_ref(self, sample_epic: Epic):
        """Invalid target ref is detected."""
        sample_epic.specs[0].repo = "unknown-repo"
        errors = sample_epic.validate()
        assert len(errors) == 1
        assert "unknown target" in errors[0]

    def test_validate_dag_cycle(self):
        """DAG cycle is detected."""
        now = datetime.now(UTC)
        epic = Epic(
            version="0.1",
            kind="epic",
            id="cycle-test",
            title="Cycle Test",
            owner="test",
            created=now,
            updated=now,
            intent=Intent(goal="Test cycles"),
            targets=[Target(id="repo", repo_path="/repo", default_branch="main")],
            specs=[
                SpecRef(id="a", repo="repo", branch="b", path="p", depends_on=["c"]),
                SpecRef(id="b", repo="repo", branch="b", path="p", depends_on=["a"]),
                SpecRef(id="c", repo="repo", branch="b", path="p", depends_on=["b"]),
            ],
        )
        errors = epic.validate()
        assert any("cycle" in e.lower() for e in errors)

    def test_validate_invalid_check_ref(self, sample_epic: Epic):
        """Invalid check ref is detected."""
        sample_epic.specs[0].checks = ["NONEXISTENT-CHECK"]
        errors = sample_epic.validate()
        assert len(errors) == 1
        assert "unknown check" in errors[0]

    def test_validate_current_spec_not_active(self, sample_epic: Epic):
        """Current spec must be active."""
        sample_epic.state.current_spec = "spec-001"
        # spec-001 is still PLANNED, not ACTIVE
        errors = sample_epic.validate()
        assert any("not active" in e for e in errors)

    def test_validate_current_spec_active(self, sample_epic: Epic):
        """Active current spec passes validation."""
        sample_epic.specs[0].status = SpecStatus.ACTIVE
        sample_epic.state.current_spec = "spec-001"
        errors = sample_epic.validate()
        assert errors == []


class TestEpicHelpers:
    """Tests for Epic helper methods."""

    def test_get_spec(self, sample_epic: Epic):
        """get_spec returns correct spec."""
        spec = sample_epic.get_spec("spec-001")
        assert spec is not None
        assert spec.id == "spec-001"

    def test_get_spec_not_found(self, sample_epic: Epic):
        """get_spec returns None for unknown spec."""
        spec = sample_epic.get_spec("unknown")
        assert spec is None

    def test_get_check(self, sample_epic: Epic):
        """get_check returns correct check."""
        check = sample_epic.get_check("CHECK-001")
        assert check is not None
        assert check.id == "CHECK-001"

    def test_get_check_not_found(self, sample_epic: Epic):
        """get_check returns None for unknown check."""
        check = sample_epic.get_check("unknown")
        assert check is None

    def test_get_target(self, sample_epic: Epic):
        """get_target returns correct target."""
        target = sample_epic.get_target("myrepo")
        assert target is not None
        assert target.id == "myrepo"

    def test_get_target_not_found(self, sample_epic: Epic):
        """get_target returns None for unknown target."""
        target = sample_epic.get_target("unknown")
        assert target is None

    def test_topological_order_single(self, sample_epic: Epic):
        """topological_order works with single spec."""
        ordered = sample_epic.topological_order()
        assert len(ordered) == 1
        assert ordered[0].id == "spec-001"

    def test_topological_order_chain(self):
        """topological_order returns correct order for chain."""
        now = datetime.now(UTC)
        epic = Epic(
            version="0.1",
            kind="epic",
            id="chain-test",
            title="Chain Test",
            owner="test",
            created=now,
            updated=now,
            intent=Intent(goal="Test chain"),
            targets=[Target(id="repo", repo_path="/repo", default_branch="main")],
            specs=[
                SpecRef(id="c", repo="repo", branch="b", path="p", depends_on=["b"]),
                SpecRef(id="a", repo="repo", branch="b", path="p", depends_on=[]),
                SpecRef(id="b", repo="repo", branch="b", path="p", depends_on=["a"]),
            ],
        )
        ordered = epic.topological_order()
        ids = [s.id for s in ordered]
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")


class TestEpicSerialization:
    """Tests for Epic to_dict serialization."""

    def test_to_dict_basic_fields(self, sample_epic: Epic):
        """to_dict includes basic fields."""
        data = sample_epic.to_dict()
        assert data["version"] == "0.1"
        assert data["kind"] == "epic"
        assert data["id"] == "e001-test"
        assert data["title"] == "Test Epic"
        assert data["owner"] == "testuser"

    def test_to_dict_intent(self, sample_epic: Epic):
        """to_dict includes intent."""
        data = sample_epic.to_dict()
        assert "intent" in data
        assert data["intent"]["goal"] == "Test the epic system"

    def test_to_dict_targets(self, sample_epic: Epic):
        """to_dict includes targets."""
        data = sample_epic.to_dict()
        assert len(data["targets"]) == 1
        assert data["targets"][0]["id"] == "myrepo"

    def test_to_dict_specs(self, sample_epic: Epic):
        """to_dict includes specs with status value."""
        data = sample_epic.to_dict()
        assert len(data["specs"]) == 1
        assert data["specs"][0]["status"] == "planned"

    def test_to_dict_state(self, sample_epic: Epic):
        """to_dict includes state and history."""
        data = sample_epic.to_dict()
        assert "state" in data
        assert data["state"]["status"] == "planned"
        assert len(data["state"]["history"]) == 1

    def test_to_dict_datetimes_as_iso(self, sample_epic: Epic):
        """to_dict serializes datetimes as ISO strings."""
        data = sample_epic.to_dict()
        assert isinstance(data["created"], str)
        assert "T" in data["created"]  # ISO format contains T
