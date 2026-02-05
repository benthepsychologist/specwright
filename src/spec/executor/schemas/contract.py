"""
Step Contract schemas for autonomous step execution.

Defines the contract between runner and agent for a single step execution,
including scope constraints, execution policies, and IO protocols.
"""

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TerminationReason(str, Enum):
    """
    Termination reasons for autonomous step execution.

    Categorized into:
    - PASS: Successful completion
    - FAIL_*: Failures that may or may not be retryable
    - ESCALATE_*: Requires human intervention
    - GATE_*: Human gate decision outcomes
    """

    # Success
    PASS = "PASS"

    # Failures (retryable)
    FAIL_VERIFY_RETRYABLE = "FAIL_VERIFY_RETRYABLE"

    # Failures (not retryable)
    FAIL_SCOPE = "FAIL_SCOPE"
    FAIL_PATCH_APPLY = "FAIL_PATCH_APPLY"
    FAIL_ADAPTER_PROTOCOL = "FAIL_ADAPTER_PROTOCOL"
    FAIL_DIRTY_WORKTREE = "FAIL_DIRTY_WORKTREE"

    # Escalations (require human)
    ESCALATE_NEEDS_HUMAN = "ESCALATE_NEEDS_HUMAN"
    ESCALATE_AMBIGUOUS = "ESCALATE_AMBIGUOUS"

    # Gate outcomes
    GATE_REJECTED = "GATE_REJECTED"
    GATE_DEFERRED = "GATE_DEFERRED"

    def is_retryable(self) -> bool:
        """Check if this termination reason allows retry."""
        return self == TerminationReason.FAIL_VERIFY_RETRYABLE

    def is_success(self) -> bool:
        """Check if this is a successful termination."""
        return self == TerminationReason.PASS

    def requires_human(self) -> bool:
        """Check if this termination requires human intervention."""
        return self in (
            TerminationReason.ESCALATE_NEEDS_HUMAN,
            TerminationReason.ESCALATE_AMBIGUOUS,
            TerminationReason.GATE_REJECTED,
            TerminationReason.GATE_DEFERRED,
        )


class CodexConfig(BaseModel):
    """
    Codex-specific execution configuration.

    Controls how the Codex CLI is invoked for this step.
    """

    sandbox: str = Field(
        default="read-only",
        description="Codex sandbox mode: read-only | workspace-write | danger-full-access",
    )
    emit_json_events: bool = Field(
        default=True,
        description="Whether adapter should call codex exec --json",
    )
    output_schema: str | None = Field(
        default=None,
        description="Path to JSON schema file for --output-schema",
    )

    model_config = {"extra": "forbid"}


class StepContract(BaseModel):
    """
    Machine-readable contract for autonomous step execution.

    Defines the scope, constraints, and execution parameters for a single step.
    The runner builds this contract, the agent operates within its bounds.
    """

    # Identity
    step_id: str = Field(description="Unique identifier for this step")
    aip_id: str = Field(description="AIP identifier this step belongs to")
    repo_root: Path = Field(description="Absolute path to repository root")

    # Scope constraints
    allowed_paths: list[str] = Field(
        default_factory=lambda: ["src/**", "tests/**"],
        description="Glob patterns for files the agent may modify",
    )
    forbidden_paths: list[str] = Field(
        default_factory=list,
        description="Glob patterns for files the agent must not modify",
    )

    # Operations allowed
    allowed_ops: list[str] = Field(
        default_factory=lambda: ["read", "write", "test"],
        description="Operations the agent may perform: read, write, test, lint, build",
    )

    # Iteration control
    max_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry iterations for this step",
    )

    # Codex-specific configuration
    codex: CodexConfig = Field(
        default_factory=CodexConfig,
        description="Codex CLI execution configuration",
    )

    model_config = {"extra": "forbid"}


class RepoState(BaseModel):
    """
    Repository state snapshot.

    Captured at step start, used for baseline tracking and reset.
    Written to input/repo_state.json for the agent.
    """

    commit: str = Field(description="Current HEAD commit SHA")
    branch: str = Field(description="Current branch name")
    dirty: bool = Field(description="Whether working tree has uncommitted changes")
    baseline: str = Field(description="Baseline commit SHA for this step (usually same as commit)")

    model_config = {"extra": "forbid"}


class FailedCommand(BaseModel):
    """
    Record of a failed command from verification.

    Used in failure_context.json to give agent context on what failed.
    """

    command: str = Field(description="The command that was run")
    exit_code: int = Field(description="Exit code of the command")
    stderr_tail: str = Field(
        default="",
        description="Last lines of stderr output (truncated if long)",
    )

    model_config = {"extra": "forbid"}


class FailureContext(BaseModel):
    """
    Context provided to agent on retry iterations.

    Written to input/failure_context.json when iteration > 0.
    Helps agent understand what went wrong and where to look.
    """

    iteration: int = Field(ge=0, description="Current iteration number (0-indexed)")
    failure_category: str = Field(
        description="Category of failure: verify_fail, scope_violation, patch_fail, etc."
    )
    failed_commands: list[FailedCommand] = Field(
        default_factory=list,
        description="Commands that failed during verification",
    )
    previous_patch_path: str | None = Field(
        default=None,
        description="Relative path to previous iteration's patch.diff",
    )
    previous_verification_report_path: str | None = Field(
        default=None,
        description="Relative path to previous iteration's verification_report.json",
    )

    model_config = {"extra": "forbid"}


class AgentStatus(str, Enum):
    """Status reported by agent in agent.json."""

    success = "success"
    failure = "failure"
    needs_human = "needs_human"


class AgentResponse(BaseModel):
    """
    Agent response structure.

    Written to output/agent.json by the adapter after parsing Codex response.
    """

    status: AgentStatus = Field(description="Agent-reported status")
    needs_human: bool = Field(
        default=False,
        description="Whether agent is requesting human intervention",
    )
    notes: str = Field(
        default="",
        description="Agent notes/explanation of what was done",
    )

    model_config = {"extra": "forbid"}


class ScopeViolation(BaseModel):
    """
    Record of a scope violation.

    Captured when agent touches files outside allowed_paths or inside forbidden_paths.
    """

    file_path: str = Field(description="Path of the violating file")
    violation_type: str = Field(
        description="Type: 'not_allowed' or 'forbidden'"
    )
    matched_pattern: str | None = Field(
        default=None,
        description="The pattern that matched (for forbidden) or should have matched (for not_allowed)",
    )

    model_config = {"extra": "forbid"}


class ScopeResult(BaseModel):
    """
    Result of scope checking.

    Returned by check_scope() after comparing touched files against contract.
    """

    passed: bool = Field(description="Whether all files are within scope")
    violations: list[ScopeViolation] = Field(
        default_factory=list,
        description="List of scope violations found",
    )
    touched_files: list[str] = Field(
        default_factory=list,
        description="All files that were touched (from git diff)",
    )

    model_config = {"extra": "forbid"}


class CommandResult(BaseModel):
    """
    Result of running a single verification command.
    """

    command: str = Field(description="The command that was run")
    exit_code: int = Field(description="Exit code")
    stdout: str = Field(default="", description="Standard output")
    stderr: str = Field(default="", description="Standard error")
    duration_ms: int = Field(description="Execution time in milliseconds")
    timed_out: bool = Field(default=False, description="Whether command timed out")

    model_config = {"extra": "forbid"}


class VerificationResult(BaseModel):
    """
    Result of running verification commands.
    """

    passed: bool = Field(description="Whether all commands passed")
    commands: list[CommandResult] = Field(
        default_factory=list,
        description="Results of each command",
    )
    failure_category: str | None = Field(
        default=None,
        description="Category of failure if any: test_fail, lint_fail, build_fail",
    )

    model_config = {"extra": "forbid"}


class StepResult(BaseModel):
    """
    Final result of autonomous step execution.

    Returned by StepRunner.run_step() after the full lifecycle completes.
    """

    step_id: str = Field(description="Step identifier")
    aip_id: str = Field(description="AIP identifier")
    termination_reason: TerminationReason = Field(
        description="Why the step terminated"
    )
    iterations_used: int = Field(
        ge=0,
        description="Number of iterations attempted",
    )
    final_patch_path: str | None = Field(
        default=None,
        description="Path to final patch.diff if successful",
    )
    touched_files: list[str] = Field(
        default_factory=list,
        description="Files modified in final iteration",
    )
    verification_passed: bool = Field(
        default=False,
        description="Whether final verification passed",
    )
    scope_passed: bool = Field(
        default=False,
        description="Whether scope check passed",
    )
    gate_package_path: str | None = Field(
        default=None,
        description="Path to gate.md for human review",
    )
    artifacts_dir: Path | None = Field(
        default=None,
        description="Directory containing all step artifacts",
    )
    error: str | None = Field(
        default=None,
        description="Error message if terminated with failure",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )

    model_config = {"extra": "forbid"}
