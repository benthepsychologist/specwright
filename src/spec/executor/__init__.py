"""
Spec Executor Module

Autonomous step execution with scope enforcement and agent adapters.
"""

from spec.executor.adapters import (
    AdapterError,
    AgentAdapter,
    CodexAdapter,
    ProtocolError,
    ToolNotFoundError,
    get_adapter,
    list_adapters,
)
from spec.executor.adapters import (
    EscalationRequired as AdapterEscalationRequired,
)
from spec.executor.artifacts import (
    ArtifactWriter,
    create_artifact_writer,
    write_failure_context,
    write_input_bundle,
)
from spec.executor.contract import (
    CodexConfig,
    EscalationRequired,
    StepContract,
    build_contract,
    load_contract,
    save_contract,
)
from spec.executor.runner import (
    IterationResult,
    StepResult,
    StepRunner,
    TerminationReason,
    render_gate_package,
)
from spec.executor.scope import (
    PathTraversalError,
    ScopeResult,
    ScopeViolation,
    ViolationType,
    check_scope,
    generate_policy_report,
)
from spec.executor.verify import (
    CommandResult,
    VerificationResult,
    generate_verification_report,
    run_command,
    run_commands,
    verify,
)

__all__ = [
    # Contract
    "StepContract",
    "CodexConfig",
    "EscalationRequired",
    "build_contract",
    "save_contract",
    "load_contract",
    # Artifacts
    "ArtifactWriter",
    "create_artifact_writer",
    "write_input_bundle",
    "write_failure_context",
    # Scope
    "PathTraversalError",
    "ScopeResult",
    "ScopeViolation",
    "ViolationType",
    "check_scope",
    "generate_policy_report",
    # Verification
    "CommandResult",
    "VerificationResult",
    "generate_verification_report",
    "run_command",
    "run_commands",
    "verify",
    # Adapters
    "AdapterError",
    "AdapterEscalationRequired",
    "AgentAdapter",
    "CodexAdapter",
    "ProtocolError",
    "ToolNotFoundError",
    "get_adapter",
    "list_adapters",
    # Runner
    "IterationResult",
    "StepResult",
    "StepRunner",
    "TerminationReason",
    "render_gate_package",
]
