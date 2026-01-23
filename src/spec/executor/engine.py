"""
Executor Engine: The main entry point for job-based execution.

Public API: execute(envelope) -> RunRecord

The engine:
1. Compiles JobDef + Envelope -> JobInstance
2. Creates run directory and writes initial artifacts
3. Iterates through steps, dispatching to backends
4. Records outcomes and captures for each step
5. Tracks attempts for retries
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec.executor.backends import BackendError, get_backend
from spec.executor.schemas import (
    AttemptRecord,
    Common,
    JobDef,
    JobInstance,
    OutcomeStatus,
    Policy,
    RepoScope,
    RunRecord,
    RunStatus,
    Step,
    StepManifest,
    StepOutcome,
)
from spec.executor.schemas.attempt import AttemptStatus
from spec.executor.schemas.job_def import StepTemplate
from spec.executor.store import RunStore


class ExecutorError(Exception):
    """Base exception for executor errors."""

    def __init__(
        self,
        message: str,
        *,
        run_id: str | None = None,
        step_n: int | None = None,
        step_id: str | None = None,
    ):
        super().__init__(message)
        self.run_id = run_id
        self.step_n = step_n
        self.step_id = step_id


class CompileError(ExecutorError):
    """Raised when compilation fails."""


class VariableError(ExecutorError):
    """Raised when variable resolution fails."""


# =============================================================================
# Variable Resolution
# =============================================================================

# Pattern to match @ref.path.to.value or @ref['key'] or @ref["key"]
_REF_PATTERN = re.compile(
    r"@(ctx|payload|run)(?:\.([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)|\[(['\"])([^'\"]+)\3\])"
)


def _get_nested(data: dict[str, Any], path: str) -> Any:
    """Get a nested value from a dict using dot notation."""
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(f"Key not found: {part} in path {path}")
    return current


def resolve_variables(
    value: Any,
    ctx: dict[str, Any],
    payload: dict[str, Any],
    run: dict[str, Any] | None = None,
    *,
    allow_run: bool = True,
    preserve_run: bool = False,
) -> Any:
    """
    Resolve @ctx.*, @payload.*, and @run.* references in a value.

    Args:
        value: The value to resolve (str, dict, list, or primitive)
        ctx: Context variables (@ctx.*)
        payload: Payload variables (@payload.*)
        run: Run variables (@run.*) - only available during execution
        allow_run: Whether @run.* references are allowed
        preserve_run: If True, preserve @run.* references when run is None (for compile time)

    Returns:
        The value with all references resolved

    Raises:
        VariableError: If a reference cannot be resolved
    """
    if isinstance(value, str):
        return _resolve_string(value, ctx, payload, run, allow_run=allow_run, preserve_run=preserve_run)
    elif isinstance(value, dict):
        return {k: resolve_variables(v, ctx, payload, run, allow_run=allow_run, preserve_run=preserve_run) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_variables(v, ctx, payload, run, allow_run=allow_run, preserve_run=preserve_run) for v in value]
    else:
        return value


def _resolve_string(
    value: str,
    ctx: dict[str, Any],
    payload: dict[str, Any],
    run: dict[str, Any] | None,
    *,
    allow_run: bool,
    preserve_run: bool = False,
) -> Any:
    """Resolve references in a string value."""
    # Check if the entire string is a single reference
    match = _REF_PATTERN.fullmatch(value)
    if match:
        namespace = match.group(1)
        path = match.group(2) or match.group(4)
        return _resolve_ref(namespace, path, ctx, payload, run, allow_run=allow_run, preserve_run=preserve_run)

    # Otherwise, do string interpolation for embedded references
    def replacer(m: re.Match) -> str:
        namespace = m.group(1)
        path = m.group(2) or m.group(4)
        resolved = _resolve_ref(namespace, path, ctx, payload, run, allow_run=allow_run, preserve_run=preserve_run)
        return str(resolved)

    return _REF_PATTERN.sub(replacer, value)


def _resolve_ref(
    namespace: str,
    path: str,
    ctx: dict[str, Any],
    payload: dict[str, Any],
    run: dict[str, Any] | None,
    *,
    allow_run: bool,
    preserve_run: bool = False,
) -> Any:
    """Resolve a single reference."""
    if namespace == "ctx":
        source = ctx
    elif namespace == "payload":
        source = payload
    elif namespace == "run":
        if not allow_run:
            raise VariableError(f"@run.* references not allowed in conditions: @run.{path}")
        if run is None:
            if preserve_run:
                # Return the original reference to be resolved later
                return f"@run.{path}"
            raise VariableError(f"@run.* not available at compile time: @run.{path}")
        source = run
    else:
        raise VariableError(f"Unknown namespace: @{namespace}")

    try:
        return _get_nested(source, path)
    except KeyError:
        raise VariableError(f"Unresolved variable: @{namespace}.{path}") from None


def has_unresolved_run_refs(value: Any) -> bool:
    """Check if a value contains any @run.* references."""
    if isinstance(value, str):
        return bool(re.search(r"@run\.", value))
    elif isinstance(value, dict):
        return any(has_unresolved_run_refs(v) for v in value.values())
    elif isinstance(value, list):
        return any(has_unresolved_run_refs(v) for v in value)
    return False


# =============================================================================
# Compilation
# =============================================================================


def compute_job_hash(job_instance: JobInstance) -> str:
    """Compute a deterministic hash of a JobInstance."""
    content = job_instance.model_dump_json(exclude={"job_hash"})
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()[:16]}"


def compile_job(
    job_def: JobDef,
    envelope: dict[str, Any],
) -> JobInstance:
    """
    Compile a JobDef + Envelope into a JobInstance.

    This is structural compilation:
    - Expands job.run (max depth 1) - not implemented in v0
    - Evaluates step.if conditions from @ctx.* and @payload.* only
    - Forbids loops
    - Forbids @run.* in conditions

    Args:
        job_def: The job definition template
        envelope: The envelope containing ctx and payload

    Returns:
        A compiled JobInstance ready for execution

    Raises:
        CompileError: If compilation fails
    """
    ctx = envelope.get("ctx", {})
    payload = envelope.get("payload", {})

    steps: list[Step] = []
    step_n = 0

    for template in job_def.steps:
        # Evaluate condition if present
        if template.condition:
            # Forbid @run.* in conditions
            if "@run." in template.condition:
                raise CompileError(
                    f"@run.* references not allowed in step conditions: {template.condition}",
                    step_id=template.step_id,
                )

            # Evaluate condition (simple expression evaluation)
            if not _evaluate_condition(template.condition, ctx, payload):
                continue  # Skip this step

        step_n += 1

        # Resolve payload variables (but allow @run.* to remain unresolved)
        # At compile time, we only resolve @ctx.* and @payload.*
        # @run.* refs are preserved to be resolved at dispatch time
        resolved_payload = resolve_variables(
            template.payload,
            ctx,
            payload,
            run=None,
            allow_run=True,
            preserve_run=True,
        )

        # Build common block from envelope
        repo_path = payload.get("repo_path", ".")
        branch = payload.get("feature_branch", payload.get("branch", "main"))
        base_commit = payload.get("base_commit", "HEAD")
        timeout_s = template.timeout_s or job_def.defaults.get("timeout_s", 300)

        step = Step(
            step_n=step_n,
            step_id=template.step_id,
            backend=template.backend,
            description=template.description,
            common=Common(
                repo_path=Path(repo_path),
                branch=branch,
                base_commit=base_commit,
                timeout_s=timeout_s,
                policy_profile=ctx.get("policy_profile", "default"),
            ),
            payload=resolved_payload,
        )
        steps.append(step)

    if not steps:
        raise CompileError("No steps after compilation - all conditions evaluated to false")

    instance = JobInstance(
        job_id=job_def.job_id,
        job_hash="",  # Computed below
        steps=steps,
    )

    # Compute hash
    instance = JobInstance(
        job_id=instance.job_id,
        job_hash=compute_job_hash(instance),
        steps=instance.steps,
    )

    return instance


def _evaluate_condition(condition: str, ctx: dict[str, Any], payload: dict[str, Any]) -> bool:
    """
    Evaluate a simple condition expression.

    Supports:
    - @ctx.key == 'value'
    - @payload.key == 'value'
    - @ctx.key != 'value'
    - @ctx.flag (truthy check)

    Missing variables evaluate to False (not an error in conditions).
    """
    condition = condition.strip()

    try:
        # Handle == comparison
        if "==" in condition:
            left, right = condition.split("==", 1)
            left_val = resolve_variables(left.strip(), ctx, payload, run=None, allow_run=False)
            right_val = right.strip().strip("'\"")
            return str(left_val) == right_val

        # Handle != comparison
        if "!=" in condition:
            left, right = condition.split("!=", 1)
            left_val = resolve_variables(left.strip(), ctx, payload, run=None, allow_run=False)
            right_val = right.strip().strip("'\"")
            return str(left_val) != right_val

        # Handle truthy check
        val = resolve_variables(condition, ctx, payload, run=None, allow_run=False)
        return bool(val)
    except VariableError:
        # Missing variables in conditions evaluate to False
        return False


# =============================================================================
# JobDef Registry (minimal for v0)
# =============================================================================

_JOB_DEFS: dict[str, JobDef] = {}


def register_job_def(job_def: JobDef) -> None:
    """Register a JobDef template."""
    _JOB_DEFS[job_def.job_id] = job_def


def get_job_def(job_id: str) -> JobDef:
    """Get a registered JobDef by ID."""
    if job_id not in _JOB_DEFS:
        raise CompileError(f"Unknown job_id: {job_id}")
    return _JOB_DEFS[job_id]


def list_job_defs() -> list[str]:
    """List all registered JobDef IDs."""
    return list(_JOB_DEFS.keys())


# =============================================================================
# aip-1 JobDef
# =============================================================================


def _create_aip1_job_def() -> JobDef:
    """Create the aip-1 JobDef template."""
    from spec.executor.schemas.shared import Backend

    return JobDef(
        job_id="aip-1",
        version="0.1",
        description="Execute an AIP with a single agent step",
        steps=[
            # Step 1: Create feature branch
            StepTemplate(
                step_id="branch.create",
                backend=Backend.cmd,
                description="Create feature branch for AIP execution",
                payload={
                    "command": "git checkout -b @payload.feature_branch",
                    "capture_git": True,
                },
            ),
            # Step 2: Run agent with AIP
            StepTemplate(
                step_id="agent.run_aip",
                backend=Backend.claude_code,
                description="Execute AIP with agent",
                payload={
                    "aip_path": "@payload.aip_path",
                    "repo_path": "@payload.repo_path",
                    "capture_git": True,
                },
                timeout_s=1800,  # 30 minutes for agent work
            ),
            # Step 3: Capture bundle
            StepTemplate(
                step_id="capture.bundle",
                backend=Backend.cmd,
                description="Bundle execution artifacts",
                payload={
                    "command": "git diff HEAD~1 --stat || git diff --stat",
                    "capture_git": True,
                },
            ),
            # Step 4: Assess acceptance
            StepTemplate(
                step_id="assess.acceptance",
                backend=Backend.llm,
                description="Assess AIP acceptance criteria",
                payload={
                    "prompt": "Review the changes and assess against acceptance criteria.",
                    "context": "AIP path: @payload.aip_path",
                },
            ),
            # Step 5: Finalize run
            StepTemplate(
                step_id="finalize.run",
                backend=Backend.cmd,
                description="Finalize run and write summary",
                payload={
                    "command": "echo 'Run finalized'",
                    "capture_git": False,
                },
            ),
        ],
    )


# Register aip-1 on module load
register_job_def(_create_aip1_job_def())


# =============================================================================
# Executor Engine
# =============================================================================


def generate_run_id() -> str:
    """Generate a unique run_id with timestamp."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suffix = hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:6]
    return f"run-{timestamp}-{suffix}"


def _get_current_commit(repo_path: Path) -> str:
    """Get the current HEAD commit SHA."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def _get_current_branch(repo_path: Path) -> str:
    """Get the current branch name."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or "HEAD"
    except subprocess.CalledProcessError:
        return "HEAD"


def execute(
    envelope: dict[str, Any],
    *,
    store: RunStore | None = None,
    run_id: str | None = None,
) -> RunRecord:
    """
    Execute a job from an envelope.

    This is the main entry point for the executor.

    Args:
        envelope: The envelope containing job_id, ctx, and payload
        store: Optional RunStore (defaults to standard location)
        run_id: Optional run_id (defaults to generated)

    Returns:
        The final RunRecord

    Raises:
        ExecutorError: If execution fails
    """
    store = store or RunStore()
    run_id = run_id or generate_run_id()

    # Extract envelope fields
    job_id = envelope.get("job_id")
    if not job_id:
        raise ExecutorError("Missing job_id in envelope", run_id=run_id)

    ctx = envelope.get("ctx", {})
    payload = envelope.get("payload", {})

    # Get repo info from payload
    repo_path = Path(payload.get("repo_path", ".")).resolve()

    # Resolve base_commit if not provided
    base_commit = payload.get("base_commit")
    if not base_commit or base_commit == "HEAD":
        base_commit = _get_current_commit(repo_path)

    # Resolve branch
    branch = payload.get("feature_branch", payload.get("branch"))
    if not branch:
        branch = _get_current_branch(repo_path)

    # Get JobDef
    job_def = get_job_def(job_id)

    # Compile to JobInstance
    job_instance = compile_job(job_def, envelope)

    # Build policy from ctx
    policy = Policy(
        profile=ctx.get("policy_profile", "default"),
        allow_commit=ctx.get("allow_commit", True),
        allow_push=ctx.get("allow_push", False),
        allow_merge=ctx.get("allow_merge", False),
    )

    # Create RunRecord
    run_record = RunRecord(
        run_id=run_id,
        job_id=job_id,
        job_hash=job_instance.job_hash,
        repo=RepoScope(
            repo_path=repo_path,
            branch=branch,
            base_commit=base_commit,
        ),
        policy=policy,
        status=RunStatus.running,
        envelope=envelope,
    )

    # Create run directory and write initial artifacts
    store.create_run(run_id)
    store.write_run_record(run_id, run_record)
    store.write_job_def(run_id, job_def)
    store.write_job_instance(run_id, job_instance)

    # Execute with attempt tracking
    attempt_n = 1
    attempt = AttemptRecord(
        attempt_n=attempt_n,
        started_at=datetime.now(UTC),
        status=AttemptStatus.running,
    )

    try:
        # Run step dispatch loop
        final_status, outcomes = _run_steps(
            job_instance=job_instance,
            run_record=run_record,
            store=store,
            ctx=ctx,
            payload=payload,
        )

        # Update attempt
        attempt = AttemptRecord(
            attempt_n=attempt.attempt_n,
            started_at=attempt.started_at,
            ended_at=datetime.now(UTC),
            status=AttemptStatus.completed if final_status == RunStatus.completed else AttemptStatus.failed,
            step_outcomes=outcomes,
            final_step_n=outcomes[-1].step_n if outcomes else None,
        )

        # Update run record
        run_record = RunRecord(
            run_id=run_record.run_id,
            job_id=run_record.job_id,
            job_hash=run_record.job_hash,
            repo=run_record.repo,
            policy=run_record.policy,
            status=final_status,
            created_at=run_record.created_at,
            updated_at=datetime.now(UTC),
            envelope=run_record.envelope,
        )

    except Exception as e:
        # Handle unexpected errors
        attempt = AttemptRecord(
            attempt_n=attempt.attempt_n,
            started_at=attempt.started_at,
            ended_at=datetime.now(UTC),
            status=AttemptStatus.failed,
            step_outcomes=attempt.step_outcomes,
            final_step_n=attempt.final_step_n,
            error=str(e),
        )

        run_record = RunRecord(
            run_id=run_record.run_id,
            job_id=run_record.job_id,
            job_hash=run_record.job_hash,
            repo=run_record.repo,
            policy=run_record.policy,
            status=RunStatus.failed,
            created_at=run_record.created_at,
            updated_at=datetime.now(UTC),
            envelope=run_record.envelope,
            error=str(e),
        )

    # Write final state
    store.write_attempt(run_id, attempt)
    store.write_run_record(run_id, run_record)

    return run_record


def _run_steps(
    job_instance: JobInstance,
    run_record: RunRecord,
    store: RunStore,
    ctx: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[RunStatus, list[StepOutcome]]:
    """
    Run the step dispatch loop.

    Returns:
        Tuple of (final_status, list of step outcomes)
    """
    outcomes: list[StepOutcome] = []

    # Build run context for variable resolution
    run_ctx = {
        "run_id": run_record.run_id,
        "repo_path": str(run_record.repo.repo_path),
        "branch": run_record.repo.branch,
        "base_commit": run_record.repo.base_commit,
        "steps": {},  # Will be populated as steps complete
    }

    for step in job_instance.steps:
        start_time = time.time()

        # Resolve any remaining @run.* references in payload
        try:
            resolved_payload = resolve_variables(
                step.payload,
                ctx,
                payload,
                run=run_ctx,
                allow_run=True,
            )
        except VariableError as e:
            # Unresolved variable - fail the step
            outcome = _create_failed_outcome(
                step=step,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )
            outcomes.append(outcome)
            store.write_step_outcome(run_record.run_id, step.step_n, outcome)
            return RunStatus.failed, outcomes

        # Create manifest
        manifest = StepManifest(
            step_n=step.step_n,
            step_id=step.step_id,
            backend=step.backend,
            common=step.common,
            payload=resolved_payload,
        )

        # Get artifacts directory
        step_dir = store.get_step_path(run_record.run_id, step.step_n)
        step_dir.mkdir(parents=True, exist_ok=True)

        # Write manifest
        store.write_step_manifest(run_record.run_id, step.step_n, manifest)

        # Dispatch to backend
        try:
            backend = get_backend(step.backend.value)
            capture = backend.dispatch(
                manifest=manifest,
                artifacts_dir=step_dir,
                policy=run_record.policy,
            )
        except BackendError as e:
            # Backend error - fail the step
            duration_ms = int((time.time() - start_time) * 1000)
            outcome = _create_failed_outcome(
                step=step,
                error=str(e),
                duration_ms=duration_ms,
            )
            outcomes.append(outcome)
            store.write_step_outcome(run_record.run_id, step.step_n, outcome)
            return RunStatus.failed, outcomes
        except Exception as e:
            # Unexpected error
            duration_ms = int((time.time() - start_time) * 1000)
            outcome = _create_failed_outcome(
                step=step,
                error=f"Unexpected error: {e}",
                duration_ms=duration_ms,
            )
            outcomes.append(outcome)
            store.write_step_outcome(run_record.run_id, step.step_n, outcome)
            return RunStatus.failed, outcomes

        duration_ms = int((time.time() - start_time) * 1000)

        # Determine outcome status
        if capture.agent and capture.agent.exit_code == 124:
            outcome_status = OutcomeStatus.timeout
        elif capture.agent and capture.agent.exit_code != 0:
            outcome_status = OutcomeStatus.failed
        else:
            outcome_status = OutcomeStatus.completed

        # Create outcome
        outcome = StepOutcome(
            step_n=step.step_n,
            step_id=step.step_id,
            outcome=outcome_status,
            duration_ms=duration_ms,
            manifest_ref=f"steps/step-{step.step_n:03d}/manifest.yaml",
            capture_ref=f"steps/step-{step.step_n:03d}/capture.yaml",
            error=None if outcome_status == OutcomeStatus.completed else f"Exit code: {capture.agent.exit_code if capture.agent else 'unknown'}",
        )

        # Write capture and outcome
        store.write_step_capture(run_record.run_id, step.step_n, capture)
        store.write_step_outcome(run_record.run_id, step.step_n, outcome)

        outcomes.append(outcome)

        # Update run context with step info
        run_ctx["steps"][step.step_id] = {
            "outcome": outcome_status.value,
            "capture_ref": outcome.capture_ref,
        }

        # Check if we should abort
        if outcome_status != OutcomeStatus.completed:
            return RunStatus.failed, outcomes

    return RunStatus.completed, outcomes


def _create_failed_outcome(
    step: Step,
    error: str,
    duration_ms: int,
) -> StepOutcome:
    """Create a failed StepOutcome."""
    return StepOutcome(
        step_n=step.step_n,
        step_id=step.step_id,
        outcome=OutcomeStatus.failed,
        duration_ms=duration_ms,
        manifest_ref=f"steps/step-{step.step_n:03d}/manifest.yaml",
        capture_ref=f"steps/step-{step.step_n:03d}/capture.yaml",
        error=error,
    )
