"""DAG utilities for epic spec dependencies.

This module provides topological sorting and cycle detection for
spec dependencies within an epic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec.epic.schema import SpecRef, SpecStatus


class DAGError(Exception):
    """Error raised when DAG operations fail.

    Attributes:
        message: Human-readable error message.
        cycle: Optional list of spec IDs forming the cycle.
    """

    def __init__(self, message: str, cycle: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.cycle = cycle


def detect_cycle(specs: list[SpecRef]) -> list[str] | None:
    """Detect cycle in spec dependency graph.

    Uses DFS to find cycles and returns the full cycle path for
    clear error messages.

    Args:
        specs: List of specs with depends_on relationships.

    Returns:
        List of spec IDs forming the cycle if found, None otherwise.
        The cycle path includes the starting spec repeated at the end
        to show the complete cycle.
    """
    spec_map = {s.id: s for s in specs}

    # Track visit state: 0=unvisited, 1=visiting, 2=visited
    state: dict[str, int] = {s.id: 0 for s in specs}
    path: list[str] = []

    def dfs(spec_id: str) -> list[str] | None:
        if spec_id not in spec_map:
            # Dependency not in spec list - skip
            return None

        if state[spec_id] == 1:
            # Found cycle - return path from cycle start
            cycle_start = path.index(spec_id)
            return path[cycle_start:] + [spec_id]

        if state[spec_id] == 2:
            return None

        state[spec_id] = 1
        path.append(spec_id)

        for dep_id in spec_map[spec_id].depends_on:
            cycle = dfs(dep_id)
            if cycle:
                return cycle

        path.pop()
        state[spec_id] = 2
        return None

    for spec in specs:
        if state[spec.id] == 0:
            cycle = dfs(spec.id)
            if cycle:
                return cycle

    return None


def topological_sort(specs: list[SpecRef]) -> list[SpecRef]:
    """Return specs in dependency order (dependencies first).

    Uses Kahn's algorithm for topological sorting.

    Args:
        specs: List of specs with depends_on relationships.

    Returns:
        Specs sorted so dependencies come before dependents.

    Raises:
        DAGError: If a cycle is detected, includes the cycle path.
    """
    if not specs:
        return []

    # First check for cycles
    cycle = detect_cycle(specs)
    if cycle:
        cycle_path = " -> ".join(cycle)
        raise DAGError(f"Dependency cycle detected: {cycle_path}", cycle=cycle)

    # Build adjacency list and in-degree count
    spec_map = {s.id: s for s in specs}
    in_degree: dict[str, int] = {s.id: 0 for s in specs}
    dependents: dict[str, list[str]] = {s.id: [] for s in specs}

    for spec in specs:
        for dep_id in spec.depends_on:
            if dep_id in spec_map:
                in_degree[spec.id] += 1
                dependents[dep_id].append(spec.id)

    # Start with nodes that have no dependencies
    queue = [s.id for s in specs if in_degree[s.id] == 0]
    result: list[SpecRef] = []

    while queue:
        spec_id = queue.pop(0)
        result.append(spec_map[spec_id])

        for dependent_id in dependents[spec_id]:
            in_degree[dependent_id] -= 1
            if in_degree[dependent_id] == 0:
                queue.append(dependent_id)

    return result


def get_ready_specs(specs: list[SpecRef]) -> list[SpecRef]:
    """Return specs whose dependencies are all done.

    A spec is "ready" if:
    - Its status is 'planned' (not yet started)
    - All specs it depends on have status 'done'

    Args:
        specs: List of specs with depends_on relationships and status.

    Returns:
        List of specs that are ready to be worked on.
    """
    from spec.epic.schema import SpecStatus

    spec_map = {s.id: s for s in specs}
    ready: list[SpecRef] = []

    for spec in specs:
        # Only consider planned specs
        if spec.status != SpecStatus.PLANNED:
            continue

        # Check all dependencies are done
        all_deps_done = True
        for dep_id in spec.depends_on:
            dep_spec = spec_map.get(dep_id)
            if dep_spec is None or dep_spec.status != SpecStatus.DONE:
                all_deps_done = False
                break

        if all_deps_done:
            ready.append(spec)

    return ready
