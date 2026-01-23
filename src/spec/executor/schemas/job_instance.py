"""
Job instance schemas: JobInstance, Step, Common.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from spec.executor.schemas.shared import Backend


class Common(BaseModel):
    """
    Engine-enforced common block for all steps.

    These fields are managed by the executor, not the backend.
    """

    repo_path: Path = Field(description="Path to the target repository")
    branch: str = Field(description="Branch being worked on")
    base_commit: str = Field(description="SHA of the base commit")
    timeout_s: int = Field(default=300, description="Step timeout in seconds")
    policy_profile: str = Field(default="default", description="Policy profile name")

    model_config = {"extra": "forbid"}


class Step(BaseModel):
    """
    A materialized step in a JobInstance.

    Steps are fully resolved - no @ref expressions remain.
    """

    step_n: int = Field(ge=1, description="Step number (1-indexed)")
    step_id: str = Field(description="Unique identifier for this step")
    backend: Backend = Field(description="Execution backend")
    description: str = Field(default="", description="Human-readable description")
    common: Common = Field(description="Engine-enforced common block")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Backend-specific payload (fully resolved)"
    )

    model_config = {"extra": "forbid"}


class JobInstance(BaseModel):
    """
    A materialized job ready for execution.

    Produced by: compile(job_def, envelope) -> JobInstance

    The step list is fixed and never mutated by the executor.
    """

    job_id: str = Field(description="Job template ID this was compiled from")
    job_hash: str = Field(description="Hash of this instance for deduplication")
    steps: list[Step] = Field(description="Ordered list of steps to execute")

    model_config = {"extra": "forbid"}
