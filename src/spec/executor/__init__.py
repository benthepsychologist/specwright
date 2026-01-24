"""
Spec Executor Module - v2 Job-Based Executor

Job-based execution with compile → execute flow.
"""

from spec.executor.backends import (
    BackendBase,
    BackendError,
    UnknownBackendError,
    get_backend,
    list_backends,
)
from spec.executor.engine import (
    CompileError,
    ExecutorError,
    VariableError,
    compile_job,
    execute,
    execute_instance,
    get_job_def,
    list_job_defs,
    register_job_def,
)
from spec.executor.sandbox import (
    PolicyViolation,
    SandboxEnforcer,
    capture_git_state,
)
from spec.executor.schemas import (
    AttemptRecord,
    Backend,
    Common,
    GitCapture,
    JobDef,
    JobInstance,
    OutcomeStatus,
    Policy,
    RepoScope,
    RunRecord,
    RunStatus,
    Step,
    StepCapture,
    StepManifest,
    StepOutcome,
    StepTemplate,
)
from spec.executor.store import RunStore

__all__ = [
    # Engine
    "compile_job",
    "execute",
    "execute_instance",
    "register_job_def",
    "get_job_def",
    "list_job_defs",
    "CompileError",
    "ExecutorError",
    "VariableError",
    # Backends
    "BackendBase",
    "BackendError",
    "UnknownBackendError",
    "get_backend",
    "list_backends",
    # Sandbox
    "SandboxEnforcer",
    "PolicyViolation",
    "capture_git_state",
    # Schemas
    "Backend",
    "JobDef",
    "StepTemplate",
    "JobInstance",
    "Step",
    "Common",
    "RunRecord",
    "Policy",
    "RepoScope",
    "RunStatus",
    "AttemptRecord",
    "StepManifest",
    "StepOutcome",
    "OutcomeStatus",
    "StepCapture",
    "GitCapture",
    # Store
    "RunStore",
]
