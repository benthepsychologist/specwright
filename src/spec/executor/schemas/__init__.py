"""
Executor V2 Schemas

Core data models for the job-based executor engine.
"""

from spec.executor.schemas.attempt import AttemptRecord
from spec.executor.schemas.capture import AgentCapture, GitCapture, StepCapture
from spec.executor.schemas.contract import (
    AgentResponse,
    AgentStatus,
    CodexConfig,
    CommandResult,
    FailedCommand,
    FailureContext,
    RepoState,
    ScopeResult,
    ScopeViolation,
    StepContract,
    StepResult,
    TerminationReason,
    VerificationResult,
)
from spec.executor.schemas.job_def import JobDef, StepTemplate
from spec.executor.schemas.job_instance import Common, JobInstance, Step
from spec.executor.schemas.manifest import StepManifest
from spec.executor.schemas.outcome import OutcomeStatus, StepOutcome
from spec.executor.schemas.run import Policy, RepoScope, RunRecord, RunStatus
from spec.executor.schemas.shared import Backend

__all__ = [
    # Shared
    "Backend",
    # Run
    "RunRecord",
    "RepoScope",
    "Policy",
    "RunStatus",
    # JobDef
    "JobDef",
    "StepTemplate",
    # JobInstance
    "JobInstance",
    "Step",
    "Common",
    # Manifest
    "StepManifest",
    # Outcome
    "StepOutcome",
    "OutcomeStatus",
    # Capture
    "StepCapture",
    "GitCapture",
    "AgentCapture",
    # Attempt
    "AttemptRecord",
    # Contract (autonomous step execution)
    "StepContract",
    "CodexConfig",
    "RepoState",
    "FailureContext",
    "FailedCommand",
    "AgentResponse",
    "AgentStatus",
    "ScopeViolation",
    "ScopeResult",
    "CommandResult",
    "VerificationResult",
    "StepResult",
    "TerminationReason",
]
