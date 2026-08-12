"""
Step outcome schema: StepOutcome, OutcomeStatus.
"""

from enum import Enum

from pydantic import BaseModel, Field


class OutcomeStatus(str, Enum):
    """Outcome status for a step."""

    completed = "completed"
    failed = "failed"
    timeout = "timeout"
    cancelled = "cancelled"
    skipped = "skipped"
    # A step's subprocess exited 0 but produced no substantive change to the
    # target repo (see diff_substantive.diff_has_substantive_change). Deliberately
    # a minimal addition to *this* enum rather than wiring in the separate,
    # currently-unused StepContract/AgentResponse machinery in contract.py
    # (AgentStatus.needs_human / TerminationReason.ESCALATE_NEEDS_HUMAN) -- that
    # belongs to an unconnected autonomous-step-execution design only referenced
    # by its own tests, and adopting it here would be the "parallel status
    # system" this fix is explicitly meant to avoid. Any value other than
    # `completed` already drives the existing any_step_failed ->
    # RunStatus.completed_with_errors cascade (engine.py _run_steps), so this
    # is the smallest change that reaches it.
    no_change = "no_change"


class StepOutcome(BaseModel):
    """
    Summary record for a step execution.

    Stored at: ~/.local/local-governor/runs/{run_id}/steps/step-{step_n:03d}/outcome.yaml

    This is the summary - detailed evidence is in StepCapture.
    """

    step_n: int = Field(ge=1, description="Step number (1-indexed)")
    step_id: str = Field(description="Unique identifier for this step")
    outcome: OutcomeStatus = Field(description="Step outcome status")
    duration_ms: int = Field(ge=0, description="Execution duration in milliseconds")
    manifest_ref: str | None = Field(
        default=None,
        description="Relative path to manifest.yaml (e.g., 'steps/step-001/manifest.yaml')",
    )
    capture_ref: str | None = Field(
        default=None,
        description="Relative path to capture.yaml (e.g., 'steps/step-001/capture.yaml')",
    )
    error: str | None = Field(default=None, description="Error message if failed")

    model_config = {"extra": "forbid"}
