"""Tests for DAG utilities - cycle detection and topological sort."""

import pytest

from spec.epic.dag import DAGError, detect_cycle, get_ready_specs, topological_sort
from spec.epic.schema import SpecRef, SpecStatus


@pytest.fixture
def linear_chain() -> list[SpecRef]:
    """A -> B -> C linear dependency chain."""
    return [
        SpecRef(id="a", repo="r", branch="b", path="p", depends_on=[]),
        SpecRef(id="b", repo="r", branch="b", path="p", depends_on=["a"]),
        SpecRef(id="c", repo="r", branch="b", path="p", depends_on=["b"]),
    ]


@pytest.fixture
def diamond_dag() -> list[SpecRef]:
    """Diamond: A -> B,C -> D."""
    return [
        SpecRef(id="a", repo="r", branch="b", path="p", depends_on=[]),
        SpecRef(id="b", repo="r", branch="b", path="p", depends_on=["a"]),
        SpecRef(id="c", repo="r", branch="b", path="p", depends_on=["a"]),
        SpecRef(id="d", repo="r", branch="b", path="p", depends_on=["b", "c"]),
    ]


@pytest.fixture
def simple_cycle() -> list[SpecRef]:
    """A -> B -> C -> A cycle."""
    return [
        SpecRef(id="a", repo="r", branch="b", path="p", depends_on=["c"]),
        SpecRef(id="b", repo="r", branch="b", path="p", depends_on=["a"]),
        SpecRef(id="c", repo="r", branch="b", path="p", depends_on=["b"]),
    ]


@pytest.fixture
def self_cycle() -> list[SpecRef]:
    """A -> A self-referential cycle."""
    return [
        SpecRef(id="a", repo="r", branch="b", path="p", depends_on=["a"]),
    ]


class TestDetectCycle:
    """Tests for detect_cycle function."""

    def test_no_cycle_empty(self):
        """Empty list has no cycle."""
        assert detect_cycle([]) is None

    def test_no_cycle_single(self):
        """Single spec with no deps has no cycle."""
        specs = [SpecRef(id="a", repo="r", branch="b", path="p")]
        assert detect_cycle(specs) is None

    def test_no_cycle_linear(self, linear_chain: list[SpecRef]):
        """Linear chain has no cycle."""
        assert detect_cycle(linear_chain) is None

    def test_no_cycle_diamond(self, diamond_dag: list[SpecRef]):
        """Diamond DAG has no cycle."""
        assert detect_cycle(diamond_dag) is None

    def test_cycle_detected(self, simple_cycle: list[SpecRef]):
        """Simple cycle is detected."""
        cycle = detect_cycle(simple_cycle)
        assert cycle is not None
        assert len(cycle) >= 2  # At least 2 nodes in cycle

    def test_self_cycle_detected(self, self_cycle: list[SpecRef]):
        """Self-referential cycle is detected."""
        cycle = detect_cycle(self_cycle)
        assert cycle is not None
        assert "a" in cycle

    def test_cycle_path_includes_start(self, simple_cycle: list[SpecRef]):
        """Cycle path includes the starting node at the end."""
        cycle = detect_cycle(simple_cycle)
        assert cycle is not None
        # First and last should be the same (cycle completes)
        assert cycle[0] == cycle[-1]

    def test_external_dep_ignored(self):
        """Dependencies on non-existent specs are ignored."""
        specs = [
            SpecRef(id="a", repo="r", branch="b", path="p", depends_on=["external"]),
        ]
        assert detect_cycle(specs) is None


class TestTopologicalSort:
    """Tests for topological_sort function."""

    def test_empty_list(self):
        """Empty list returns empty."""
        assert topological_sort([]) == []

    def test_single_spec(self):
        """Single spec is returned as-is."""
        specs = [SpecRef(id="a", repo="r", branch="b", path="p")]
        result = topological_sort(specs)
        assert len(result) == 1
        assert result[0].id == "a"

    def test_linear_order(self, linear_chain: list[SpecRef]):
        """Linear chain is sorted correctly."""
        result = topological_sort(linear_chain)
        ids = [s.id for s in result]
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")

    def test_diamond_order(self, diamond_dag: list[SpecRef]):
        """Diamond DAG is sorted correctly."""
        result = topological_sort(diamond_dag)
        ids = [s.id for s in result]
        # A must come first
        assert ids[0] == "a"
        # D must come last
        assert ids[-1] == "d"
        # B and C must come after A, before D
        assert ids.index("b") > ids.index("a")
        assert ids.index("c") > ids.index("a")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_cycle_raises_error(self, simple_cycle: list[SpecRef]):
        """Cycle raises DAGError."""
        with pytest.raises(DAGError) as exc_info:
            topological_sort(simple_cycle)
        assert exc_info.value.cycle is not None
        assert "cycle" in exc_info.value.message.lower()

    def test_independent_specs(self):
        """Independent specs can be in any order."""
        specs = [
            SpecRef(id="a", repo="r", branch="b", path="p"),
            SpecRef(id="b", repo="r", branch="b", path="p"),
            SpecRef(id="c", repo="r", branch="b", path="p"),
        ]
        result = topological_sort(specs)
        assert len(result) == 3
        assert {s.id for s in result} == {"a", "b", "c"}


class TestGetReadySpecs:
    """Tests for get_ready_specs function."""

    def test_empty_list(self):
        """Empty list returns empty."""
        assert get_ready_specs([]) == []

    def test_no_deps_planned(self):
        """Planned spec with no deps is ready."""
        specs = [
            SpecRef(id="a", repo="r", branch="b", path="p", status=SpecStatus.PLANNED),
        ]
        ready = get_ready_specs(specs)
        assert len(ready) == 1
        assert ready[0].id == "a"

    def test_active_not_ready(self):
        """Active spec is not ready (already started)."""
        specs = [
            SpecRef(id="a", repo="r", branch="b", path="p", status=SpecStatus.ACTIVE),
        ]
        ready = get_ready_specs(specs)
        assert len(ready) == 0

    def test_done_not_ready(self):
        """Done spec is not ready (already completed)."""
        specs = [
            SpecRef(id="a", repo="r", branch="b", path="p", status=SpecStatus.DONE),
        ]
        ready = get_ready_specs(specs)
        assert len(ready) == 0

    def test_deps_done_is_ready(self):
        """Spec with all done deps is ready."""
        specs = [
            SpecRef(id="a", repo="r", branch="b", path="p", status=SpecStatus.DONE),
            SpecRef(
                id="b",
                repo="r",
                branch="b",
                path="p",
                status=SpecStatus.PLANNED,
                depends_on=["a"],
            ),
        ]
        ready = get_ready_specs(specs)
        assert len(ready) == 1
        assert ready[0].id == "b"

    def test_deps_not_done_not_ready(self):
        """Spec with undone deps is not ready."""
        specs = [
            SpecRef(id="a", repo="r", branch="b", path="p", status=SpecStatus.PLANNED),
            SpecRef(
                id="b",
                repo="r",
                branch="b",
                path="p",
                status=SpecStatus.PLANNED,
                depends_on=["a"],
            ),
        ]
        ready = get_ready_specs(specs)
        # Only 'a' is ready (no deps), 'b' has undone dep
        assert len(ready) == 1
        assert ready[0].id == "a"

    def test_chain_ready_progression(self):
        """As deps complete, next specs become ready."""
        specs = [
            SpecRef(id="a", repo="r", branch="b", path="p", status=SpecStatus.DONE),
            SpecRef(id="b", repo="r", branch="b", path="p", status=SpecStatus.DONE, depends_on=["a"]),
            SpecRef(id="c", repo="r", branch="b", path="p", status=SpecStatus.PLANNED, depends_on=["b"]),
        ]
        ready = get_ready_specs(specs)
        assert len(ready) == 1
        assert ready[0].id == "c"

    def test_diamond_multiple_ready(self):
        """Multiple specs can be ready at once."""
        specs = [
            SpecRef(id="a", repo="r", branch="b", path="p", status=SpecStatus.DONE),
            SpecRef(id="b", repo="r", branch="b", path="p", status=SpecStatus.PLANNED, depends_on=["a"]),
            SpecRef(id="c", repo="r", branch="b", path="p", status=SpecStatus.PLANNED, depends_on=["a"]),
        ]
        ready = get_ready_specs(specs)
        assert len(ready) == 2
        assert {s.id for s in ready} == {"b", "c"}
