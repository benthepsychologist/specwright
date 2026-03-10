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
)
from spec.executor.jobdefs import (
    JobDefError,
    JobDefNotFoundError,
    install_default_jobdefs,
    list_job_defs,
    load_job_def,
)
from spec.executor.run_writers import ConsolidatedRunWriter
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
    "CompileError",
    "ExecutorError",
    "VariableError",
    # JobDef loading
    "load_job_def",
    "list_job_defs",
    "install_default_jobdefs",
    "JobDefError",
    "JobDefNotFoundError",
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
    "ConsolidatedRunWriter",
]
