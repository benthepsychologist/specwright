"""
Step manifest schema: StepManifest.
"""

from typing import Any

from pydantic import BaseModel, Field

from spec.executor.schemas.job_instance import Common
from spec.executor.schemas.shared import Backend


class StepManifest(BaseModel):
    """
    Fully resolved manifest for a step at dispatch time.

    Stored at: ~/.local/local-governor/runs/{run_id}/steps/step-{step_n:03d}/manifest.yaml

    The manifest is the complete, resolved input to a backend.
    All @run.* references have been resolved at this point.
    """

    step_n: int = Field(ge=1, description="Step number (1-indexed)")
    step_id: str = Field(description="Unique identifier for this step")
    backend: Backend = Field(description="Execution backend")
    common: Common = Field(description="Engine-enforced common block")
    payload: dict[str, Any] = Field(
        description="Backend-specific payload (fully resolved, including @run.*)"
    )

    model_config = {"extra": "forbid"}
