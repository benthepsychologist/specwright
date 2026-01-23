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
    manifest_ref: str = Field(
        description="Relative path to manifest.yaml (e.g., 'steps/step-001/manifest.yaml')"
    )
    capture_ref: str = Field(
        description="Relative path to capture.yaml (e.g., 'steps/step-001/capture.yaml')"
    )
    error: str | None = Field(default=None, description="Error message if failed")

    model_config = {"extra": "forbid"}
