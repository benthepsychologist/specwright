"""
Attempt record schema: AttemptRecord.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from spec.executor.schemas.outcome import StepOutcome


class AttemptStatus(str, Enum):
    """Status of an attempt."""

    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AttemptRecord(BaseModel):
    """
    Record for a single execution attempt.

    Stored at: ~/.local/local-governor/runs/{run_id}/attempts/attempt-{attempt_n:03d}.yaml

    A run may have multiple attempts if retries are enabled.
    """

    attempt_n: int = Field(ge=1, description="Attempt number (1-indexed)")
    started_at: datetime = Field(description="When this attempt started")
    ended_at: datetime | None = Field(default=None, description="When this attempt ended")
    status: AttemptStatus = Field(
        default=AttemptStatus.running, description="Attempt status"
    )
    step_outcomes: list[StepOutcome] = Field(
        default_factory=list,
        description="Outcomes for each completed step in this attempt",
    )
    final_step_n: int | None = Field(
        default=None, description="Last step that was executed (may be partial)"
    )
    error: str | None = Field(default=None, description="Error message if failed")

    model_config = {"extra": "forbid"}
