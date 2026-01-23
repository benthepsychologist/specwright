"""
Run-level schemas: RunRecord, RepoScope, Policy, RunStatus.
"""

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    """Status of a run."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RepoScope(BaseModel):
    """Repository scope for a run."""

    repo_path: Path
    branch: str
    base_commit: str = Field(description="SHA of the base commit at run start")
    remote: str | None = Field(default=None, description="Remote URL (optional)")

    model_config = {"extra": "forbid"}


class Policy(BaseModel):
    """Execution policy settings."""

    profile: str = Field(default="default", description="Policy profile name")
    blocked_commands: list[str] = Field(
        default_factory=lambda: ["git push", "git merge"],
        description="Commands blocked during execution",
    )
    allow_commit: bool = Field(default=True, description="Allow git commits")
    allow_push: bool = Field(default=False, description="Allow git push")
    allow_merge: bool = Field(default=False, description="Allow git merge")

    model_config = {"extra": "forbid"}


class RunRecord(BaseModel):
    """
    Top-level record for a run.

    Stored at: ~/.local/local-governor/runs/{run_id}/run.yaml
    """

    run_id: str = Field(description="Unique identifier for this run")
    job_id: str = Field(description="Job template ID (e.g., 'aip-1')")
    job_hash: str = Field(description="Hash of the compiled JobInstance")
    repo: RepoScope = Field(description="Repository scope")
    policy: Policy = Field(default_factory=Policy, description="Execution policy")
    status: RunStatus = Field(default=RunStatus.pending, description="Current status")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    envelope: dict[str, Any] = Field(
        default_factory=dict, description="Original envelope data"
    )
    error: str | None = Field(default=None, description="Error message if failed")

    model_config = {"extra": "forbid"}
