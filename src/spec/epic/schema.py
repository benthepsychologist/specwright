"""Epic schema: dataclasses for the epic model.

This module defines the core data structures for epics, which are
multi-spec implementation plans with dependency tracking, status
management, and audit trails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class SpecStatus(str, Enum):
    """Status of a spec within an epic.

    Includes aliases for epic-level status values (in_progress, completed,
    superseded) to allow the same enum for both spec and epic status fields.
    """

    PLANNED = "planned"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"
    ABANDONED = "abandoned"
    # Epic-level status aliases (permissive parsing)
    IN_PROGRESS = "in_progress"  # alias for ACTIVE at epic level
    COMPLETED = "completed"  # alias for DONE at epic level
    SUPERSEDED = "superseded"  # epic-only status


class EventType(str, Enum):
    """Types of events in epic history.

    This enum is intentionally permissive to allow for organic event types
    that emerge during epic execution. Add new event types as needed.
    """

    # Core events
    EPIC_CREATED = "epic.created"
    EPIC_UPDATED = "epic.updated"
    EPIC_REVISED = "epic.revised"
    EPIC_RESTRUCTURED = "epic.restructured"
    EPIC_REDESIGNED = "epic.redesigned"
    EPIC_SIMPLIFIED = "epic.simplified"
    EPIC_AMENDED = "epic.amended"

    # Spec events
    SPEC_ADDED = "spec.added"
    SPEC_ACTIVATED = "spec.activated"
    SPEC_BLOCKED = "spec.blocked"
    SPEC_DONE = "spec.done"
    SPEC_ABANDONED = "spec.abandoned"
    SPEC_REVIEWED = "spec.reviewed"
    SPECS_RESTRUCTURED = "specs.restructured"
    SPECS_RESEQUENCED = "specs.resequenced"

    # Check events
    CHECK_COMPLETED = "check.completed"
    CHECK_FAILED = "check.failed"
    CHECKS_ADDED = "checks.added"

    # Step events
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"

    # Gate events
    GATE_COMPLETED = "gate.completed"
    GATE_RESCOPED = "gate.rescoped"

    # Scope events
    SCOPE_CLARIFIED = "scope.clarified"


class Actor(str, Enum):
    """Actor types for history events."""

    HUMAN = "human"
    AI = "ai"
    HUMAN_AI = "human+ai"
    SPECWRIGHT = "specwright"
    LLM = "llm"


class CheckScope(str, Enum):
    """Scope of a check."""

    SPEC = "spec"
    EPIC = "epic"


@dataclass
class Target:
    """A target repository for an epic."""

    id: str
    repo_path: str
    default_branch: str
    governor_project: str | None = None


@dataclass
class CheckInput:
    """Input specification for a check."""

    type: str
    path: str | None = None
    args: list[str] | None = None
    target: str | None = None
    range: str | None = None
    include: list[str] | None = None


@dataclass
class ResponseContract:
    """Expected response structure from a check."""

    verdicts: list[str] = field(default_factory=list)
    required_sections: list[str] = field(default_factory=list)


@dataclass
class Check:
    """A check definition for validating specs."""

    id: str
    name: str
    scope: CheckScope
    prompt_ref: str
    model: str | None = None
    default_spec: str | None = None
    response_contract: ResponseContract | None = None
    inputs: list[CheckInput] = field(default_factory=list)


@dataclass
class SpecRef:
    """Reference to a spec within an epic."""

    id: str
    repo: str
    branch: str
    title: str | None = None
    path: str | None = None
    status: SpecStatus = SpecStatus.PLANNED
    dev_intent: str | None = None
    depends_on: list[str] = field(default_factory=list)
    expectations: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    build_delta: dict | None = None


@dataclass
class Verification:
    """Verification result for a history event."""

    commands: list[str] = field(default_factory=list)
    status: str = ""


@dataclass
class HistoryEvent:
    """An event in the epic's history."""

    id: str
    at: datetime
    event: EventType
    actor: Actor
    spec_id: str | None = None
    check_id: str | None = None
    verdict: str | None = None
    report: str | None = None
    note: str | None = None
    step: int | None = None
    plan_artifact: str | None = None
    commit: str | None = None
    verification: Verification | None = None


@dataclass
class EpicState:
    """Current state of an epic."""

    status: SpecStatus
    current_spec: str | None = None
    history: list[HistoryEvent] = field(default_factory=list)


@dataclass
class Intent:
    """Epic intent - goal and narrative."""

    goal: str
    narrative: str = ""


@dataclass
class RunContext:
    """Runtime context configuration."""

    governor_root: str
    cli_bin: str
    cwd_policy: str
    env_override: dict[str, str | None] | None = None


@dataclass
class GovernanceConfig:
    """Governance configuration for an epic."""

    enabled: bool
    source: str
    project: str
    include: list[str] = field(default_factory=list)


@dataclass
class Defaults:
    """Default values for an epic."""

    model: str | None = None


@dataclass
class Epic:
    """An epic - a multi-spec implementation plan.

    Epics coordinate multiple specs with dependencies, status tracking,
    and audit trails.
    """

    version: str
    kind: str
    id: str
    title: str
    owner: str
    created: datetime
    updated: datetime
    intent: Intent
    targets: list[Target] = field(default_factory=list)
    specs: list[SpecRef] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    state: EpicState | None = None
    run_context: RunContext | None = None
    governance: GovernanceConfig | None = None
    defaults: Defaults | None = None

    def validate(self) -> list[str]:
        """Run all validations and return list of errors."""
        errors: list[str] = []
        errors.extend(self._validate_target_refs())
        errors.extend(self._validate_dag())
        errors.extend(self._validate_check_refs())
        errors.extend(self._validate_current_spec())
        return errors

    def _validate_target_refs(self) -> list[str]:
        """Check that all spec repos exist in targets."""
        errors: list[str] = []
        target_ids = {t.id for t in self.targets}
        for spec in self.specs:
            if spec.repo not in target_ids:
                errors.append(
                    f"Spec '{spec.id}' references unknown target '{spec.repo}'"
                )
        return errors

    def _validate_dag(self) -> list[str]:
        """Check for cycles in spec dependencies."""
        errors: list[str] = []
        cycle = self._detect_cycle()
        if cycle:
            cycle_path = " -> ".join(cycle)
            errors.append(f"Dependency cycle detected: {cycle_path}")
        return errors

    def _detect_cycle(self) -> list[str] | None:
        """Detect cycle in dependency graph using DFS.

        Returns the cycle path if found, None otherwise.
        """
        spec_map = {s.id: s for s in self.specs}

        # Track visit state: 0=unvisited, 1=visiting, 2=visited
        state: dict[str, int] = {s.id: 0 for s in self.specs}
        path: list[str] = []

        def dfs(spec_id: str) -> list[str] | None:
            if spec_id not in spec_map:
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

        for spec in self.specs:
            if state[spec.id] == 0:
                cycle = dfs(spec.id)
                if cycle:
                    return cycle

        return None

    def _validate_check_refs(self) -> list[str]:
        """Check that all spec checks exist."""
        errors: list[str] = []
        check_ids = {c.id for c in self.checks}
        for spec in self.specs:
            for check_id in spec.checks:
                if check_id not in check_ids:
                    errors.append(
                        f"Spec '{spec.id}' references unknown check '{check_id}'"
                    )
        return errors

    def _validate_current_spec(self) -> list[str]:
        """Check that current_spec exists if set.

        Note: We no longer require current_spec to be active. The state section
        is deprecated in v0.2 and this validation is permissive to allow for
        organic epic evolution (e.g., setting current_spec before marking it active).
        """
        errors: list[str] = []
        if self.state and self.state.current_spec:
            spec = self.get_spec(self.state.current_spec)
            if spec is None:
                errors.append(
                    f"current_spec '{self.state.current_spec}' does not exist"
                )
            # Permissive: don't require current_spec to be active
        return errors

    def get_spec(self, spec_id: str) -> SpecRef | None:
        """Get a spec by ID."""
        for spec in self.specs:
            if spec.id == spec_id:
                return spec
        return None

    def get_check(self, check_id: str) -> Check | None:
        """Get a check by ID."""
        for check in self.checks:
            if check.id == check_id:
                return check
        return None

    def get_target(self, target_id: str) -> Target | None:
        """Get a target by ID."""
        for target in self.targets:
            if target.id == target_id:
                return target
        return None

    def topological_order(self) -> list[SpecRef]:
        """Return specs in dependency order (dependencies first).

        Uses Kahn's algorithm. Raises ValueError if cycle detected.
        """
        # Build adjacency list and in-degree count
        spec_map = {s.id: s for s in self.specs}
        in_degree: dict[str, int] = {s.id: 0 for s in self.specs}
        dependents: dict[str, list[str]] = {s.id: [] for s in self.specs}

        for spec in self.specs:
            for dep_id in spec.depends_on:
                if dep_id in spec_map:
                    in_degree[spec.id] += 1
                    dependents[dep_id].append(spec.id)

        # Start with nodes that have no dependencies
        queue = [s.id for s in self.specs if in_degree[s.id] == 0]
        result: list[SpecRef] = []

        while queue:
            spec_id = queue.pop(0)
            result.append(spec_map[spec_id])

            for dependent_id in dependents[spec_id]:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(result) != len(self.specs):
            raise ValueError("Cycle detected in spec dependencies")

        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert epic to dictionary for serialization."""
        result: dict[str, Any] = {
            "version": self.version,
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "owner": self.owner,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "intent": {
                "goal": self.intent.goal,
                "narrative": self.intent.narrative,
            },
            "targets": [_target_to_dict(t) for t in self.targets],
            "specs": [_spec_to_dict(s) for s in self.specs],
            "checks": [_check_to_dict(c) for c in self.checks],
        }

        if self.state:
            result["state"] = _state_to_dict(self.state)

        if self.run_context:
            result["run_context"] = _run_context_to_dict(self.run_context)

        if self.governance:
            result["governance"] = _governance_to_dict(self.governance)

        if self.defaults:
            result["defaults"] = _defaults_to_dict(self.defaults)

        return result


def _target_to_dict(target: Target) -> dict[str, Any]:
    """Convert Target to dictionary."""
    result: dict[str, Any] = {
        "id": target.id,
        "repo_path": target.repo_path,
        "default_branch": target.default_branch,
    }
    if target.governor_project:
        result["governor_project"] = target.governor_project
    return result


def _spec_to_dict(spec: SpecRef) -> dict[str, Any]:
    """Convert SpecRef to dictionary."""
    result: dict[str, Any] = {
        "id": spec.id,
        "repo": spec.repo,
        "branch": spec.branch,
        "status": spec.status.value,
    }
    if spec.title:
        result["title"] = spec.title
    if spec.path:
        result["path"] = spec.path
    if spec.dev_intent:
        result["dev_intent"] = spec.dev_intent
    if spec.depends_on:
        result["depends_on"] = spec.depends_on
    if spec.expectations:
        result["expectations"] = spec.expectations
    if spec.constraints:
        result["constraints"] = spec.constraints
    if spec.checks:
        result["checks"] = spec.checks
    if spec.build_delta:
        result["build_delta"] = spec.build_delta
    return result


def _check_to_dict(check: Check) -> dict[str, Any]:
    """Convert Check to dictionary."""
    result: dict[str, Any] = {
        "id": check.id,
        "name": check.name,
        "scope": check.scope.value,
        "prompt_ref": check.prompt_ref,
    }
    if check.model:
        result["model"] = check.model
    if check.default_spec:
        result["default_spec"] = check.default_spec
    if check.response_contract:
        result["response_contract"] = {
            "verdicts": check.response_contract.verdicts,
            "required_sections": check.response_contract.required_sections,
        }
    if check.inputs:
        result["inputs"] = [_check_input_to_dict(i) for i in check.inputs]
    return result


def _check_input_to_dict(inp: CheckInput) -> dict[str, Any]:
    """Convert CheckInput to dictionary."""
    result: dict[str, Any] = {"type": inp.type}
    if inp.path:
        result["path"] = inp.path
    if inp.args:
        result["args"] = inp.args
    if inp.target:
        result["target"] = inp.target
    if inp.range:
        result["range"] = inp.range
    if inp.include:
        result["include"] = inp.include
    return result


def _state_to_dict(state: EpicState) -> dict[str, Any]:
    """Convert EpicState to dictionary."""
    result: dict[str, Any] = {
        "status": state.status.value,
        "history": [_history_event_to_dict(e) for e in state.history],
    }
    if state.current_spec:
        result["current_spec"] = state.current_spec
    return result


def _history_event_to_dict(event: HistoryEvent) -> dict[str, Any]:
    """Convert HistoryEvent to dictionary."""
    result: dict[str, Any] = {
        "id": event.id,
        "at": event.at.isoformat(),
        "event": event.event.value,
        "actor": event.actor.value,
    }
    if event.spec_id:
        result["spec_id"] = event.spec_id
    if event.check_id:
        result["check_id"] = event.check_id
    if event.verdict:
        result["verdict"] = event.verdict
    if event.report:
        result["report"] = event.report
    if event.note:
        result["note"] = event.note
    if event.step is not None:
        result["step"] = event.step
    if event.plan_artifact:
        result["plan_artifact"] = event.plan_artifact
    if event.commit:
        result["commit"] = event.commit
    if event.verification:
        result["verification"] = {
            "commands": event.verification.commands,
            "status": event.verification.status,
        }
    return result


def _run_context_to_dict(ctx: RunContext) -> dict[str, Any]:
    """Convert RunContext to dictionary."""
    result: dict[str, Any] = {
        "governor_root": ctx.governor_root,
        "cli_bin": ctx.cli_bin,
        "cwd_policy": ctx.cwd_policy,
    }
    if ctx.env_override:
        result["env_override"] = ctx.env_override
    return result


def _governance_to_dict(gov: GovernanceConfig) -> dict[str, Any]:
    """Convert GovernanceConfig to dictionary."""
    result: dict[str, Any] = {
        "enabled": gov.enabled,
        "source": gov.source,
        "project": gov.project,
    }
    if gov.include:
        result["include"] = gov.include
    return result


def _defaults_to_dict(defaults: Defaults) -> dict[str, Any]:
    """Convert Defaults to dictionary."""
    result: dict[str, Any] = {}
    if defaults.model:
        result["model"] = defaults.model
    return result
