"""
Step capture schemas: StepCapture, GitCapture, AgentCapture.
"""

from typing import Any

from pydantic import BaseModel, Field


class GitCapture(BaseModel):
    """
    Git state capture for a step.

    Captures the git state before and after step execution.
    """

    base_commit: str = Field(description="SHA of the base commit before step")
    pre_status: str = Field(description="Git status output before step")
    post_status: str = Field(description="Git status output after step")
    patch_file: str | None = Field(
        default=None,
        description="Relative path to unified diff file (e.g., 'steps/step-001/changes.patch')",
    )
    changed_files: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of changed files with before/after hashes",
    )
    commit_sha: str | None = Field(
        default=None, description="SHA if agent committed during step"
    )

    model_config = {"extra": "forbid"}


class AgentCapture(BaseModel):
    """
    Agent output capture for a step.

    Captures stdout, stderr, and exit code from agent execution.
    """

    stdout_file: str = Field(
        description="Relative path to stdout file (e.g., 'steps/step-001/stdout.txt')"
    )
    stderr_file: str = Field(
        description="Relative path to stderr file (e.g., 'steps/step-001/stderr.txt')"
    )
    exit_code: int = Field(description="Agent exit code")
    transcript_file: str | None = Field(
        default=None,
        description="Relative path to transcript file if available",
    )

    model_config = {"extra": "forbid"}


class StepCapture(BaseModel):
    """
    Evidence bundle for a step execution.

    Stored at: ~/.local/local-governor/runs/{run_id}/steps/step-{step_n:03d}/capture.yaml

    Contains all evidence captured during step execution.
    """

    step_n: int = Field(ge=1, description="Step number (1-indexed)")
    step_id: str = Field(description="Unique identifier for this step")
    git: GitCapture | None = Field(
        default=None, description="Git state capture (if applicable)"
    )
    agent: AgentCapture | None = Field(
        default=None, description="Agent output capture (if applicable)"
    )
    assessments: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured assessments from llm backend",
    )
    traces: list[str] = Field(
        default_factory=list,
        description="Relative paths to trace files",
    )

    model_config = {"extra": "forbid"}
