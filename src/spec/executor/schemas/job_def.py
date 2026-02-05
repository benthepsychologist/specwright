"""
Job definition schemas: JobDef, StepTemplate.
"""

from typing import Any

from pydantic import BaseModel, Field

from spec.executor.schemas.shared import Backend


class StepTemplate(BaseModel):
    """
    Template for a step in a JobDef.

    Step templates are expanded during compilation to produce Step instances.
    """

    step_id: str = Field(description="Unique identifier for this step template")
    backend: Backend = Field(description="Execution backend")
    description: str = Field(default="", description="Human-readable description")
    condition: str | None = Field(
        default=None,
        description="Optional condition expression (e.g., '@ctx.some_flag == true')",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Backend-specific payload (may contain @ref expressions)",
    )
    timeout_s: int | None = Field(
        default=None, description="Step-specific timeout override"
    )
    continue_on_failure: bool = Field(
        default=False,
        description="If True, continue to next step even if this step fails",
    )
    on_failure_skip_to: str | None = Field(
        default=None,
        description="If set and step fails, skip to the step with this step_id",
    )
    capture_patch: bool = Field(
        default=False,
        description="If True, generate changes.patch for this step (diff since baseline)",
    )
    interactive: bool = Field(
        default=False,
        description="If True, step runs interactively (exit code is telemetry, not success signal)",
    )

    model_config = {"extra": "forbid"}


class JobDef(BaseModel):
    """
    Job definition template.

    JobDefs are registered templates that describe how to execute a type of job.
    They are compiled with an envelope to produce a JobInstance.

    Example job_id values: 'aip-1', 'verify', 'deploy'
    """

    job_id: str = Field(description="Unique identifier for this job template")
    version: str = Field(default="1.0", description="Job template version")
    description: str = Field(default="", description="Human-readable description")
    steps: list[StepTemplate] = Field(
        description="Ordered list of step templates to execute"
    )
    defaults: dict[str, Any] = Field(
        default_factory=dict,
        description="Default values for @payload.* expressions",
    )

    model_config = {"extra": "forbid"}
