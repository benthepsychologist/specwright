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
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec.executor.backends import BackendError, get_backend
from spec.executor.sandbox.capture import generate_patch
from spec.executor.schemas import (
    AttemptRecord,
    Backend,
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


def _is_truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _require_llm_preflight(*, run_id: str) -> None:
    """Hard gate for LLM availability.

    Called before executing any steps for runs that require LLM (LLM steps and/or
    LLM-backed run report). This prevents partially-executed runs when the LLM
    backend is misconfigured.

    Escape hatch:
    - If `SPECWRIGHT_SKIP_LLM_PREFLIGHT` is truthy, this check is skipped.

    Note: Network connectivity checks remain optional and are controlled by the
    LLM backend itself (e.g. `SPECWRIGHT_LLM_NETWORK_PREFLIGHT`).
    """

    if _is_truthy_env(os.environ.get("SPECWRIGHT_SKIP_LLM_PREFLIGHT")):
        return

    from spec.executor.backends.llm import LlmBackend

    # We want preflight to be a *real* preflight: when LLM is required, verify()
    # should also make a minimal provider call so we fail before step 1.
    old_network_flag = os.environ.get("SPECWRIGHT_LLM_NETWORK_PREFLIGHT")
    os.environ["SPECWRIGHT_LLM_NETWORK_PREFLIGHT"] = "1"
    try:
        LlmBackend().verify()
    except Exception as e:
        raise ExecutorError(f"LLM preflight failed: {e}", run_id=run_id) from e
    finally:
        if old_network_flag is None:
            os.environ.pop("SPECWRIGHT_LLM_NETWORK_PREFLIGHT", None)
        else:
            os.environ["SPECWRIGHT_LLM_NETWORK_PREFLIGHT"] = old_network_flag


def _job_requires_llm(job_instance: JobInstance) -> bool:
    return any(step.backend == Backend.llm for step in (job_instance.steps or []))


def _use_llm_for_run_report(*, job_instance: JobInstance) -> bool:
    # interactive-1 should always generate an LLM-backed run report.
    if job_instance.job_id == "interactive-1":
        return True
    # If the job already requires LLM, default to LLM-backed run report.
    if _job_requires_llm(job_instance):
        return True
    # Otherwise, only use LLM if explicitly requested.
    return _is_truthy_env(os.environ.get("SPECWRIGHT_RUN_REPORT_LLM"))


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


# Keys in payload that should NOT have variable resolution applied.
# These contain arbitrary user content (spec markdown, prompts) that may
# include @-prefixed strings that are NOT specwright variables.
PASSTHROUGH_KEYS = frozenset({"spec_md", "epic_spec", "prompt"})


def resolve_variables(
    value: Any,
    ctx: dict[str, Any],
    payload: dict[str, Any],
    run: dict[str, Any] | None = None,
    *,
    allow_run: bool = True,
    preserve_run: bool = False,
    _current_key: str | None = None,
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
        _current_key: Internal - the dict key being processed (to check passthrough)

    Returns:
        The value with all references resolved

    Raises:
        VariableError: If a reference cannot be resolved
    """
    # Skip resolution for passthrough keys (user content like spec_md)
    if _current_key in PASSTHROUGH_KEYS:
        return value

    if isinstance(value, str):
        return _resolve_string(value, ctx, payload, run, allow_run=allow_run, preserve_run=preserve_run)
    elif isinstance(value, dict):
        return {
            k: resolve_variables(
                v, ctx, payload, run,
                allow_run=allow_run,
                preserve_run=preserve_run,
                _current_key=k,
            )
            for k, v in value.items()
        }
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
            continue_on_failure=template.continue_on_failure,
            on_failure_skip_to=template.on_failure_skip_to,
            capture_patch=template.capture_patch,
            interactive=template.interactive,
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


def _build_drift_fix_prompt(epic_spec: dict | None = None) -> str:
    """Build prompt for Run 2: drift inspection and fix.

    Args:
        epic_spec: Optional epic spec expectations to include as ground truth
    """
    prompt = """# Drift Inspection and Fix

You are reviewing the code changes from the previous spec implementation run.

## Your Task

1. **Inspect Changes**: Review all code changes made so far (use `git diff` from base commit)

2. **Check for Drift**: Compare the implementation against the spec requirements:
   - Are all acceptance criteria being addressed?
   - Is the implementation aligned with the spec's intent?
   - Are there any missing pieces or incomplete implementations?
   - Are there any deviations from the expected behavior?

3. **Make a Plan**: If you find any drift or issues:
   - Document what needs to be fixed
   - Prioritize the fixes

4. **Execute Fixes**: Implement any necessary corrections to bring the code back in alignment with the spec.

## Context

The spec data is provided to you. The repository is the working directory.
Check `git log` and `git diff` to see what was implemented.

Focus on correctness and spec adherence, not on style or refactoring.
"""

    # Add epic expectations as ground truth if provided
    if epic_spec:
        prompt += _format_epic_expectations(epic_spec)

    return prompt


def _build_drift_verify_prompt(epic_spec: dict | None = None) -> str:
    """Build prompt for Run 3: final drift verification.

    Args:
        epic_spec: Optional epic spec expectations to include as ground truth
    """
    prompt = """# Final Drift Verification

You are performing a final verification pass on the spec implementation.

## Your Task

1. **Final Review**: Review ALL changes made across previous runs (use `git diff` from base commit)

2. **Acceptance Criteria Check**: Go through each acceptance criterion in the spec:
   - Is it fully implemented?
   - Does it work as expected?
   - Are there any edge cases missed?

3. **Fix Remaining Issues**: If you find any remaining problems:
   - Fix them directly
   - Focus on correctness over completeness

4. **Verification**: Run any verification commands specified in the spec.

## Context

The spec data is provided to you. The repository is the working directory.
This is the FINAL pass - focus on making sure everything is correct and complete.

Do not make unnecessary changes. Only fix actual issues.
"""

    # Add epic expectations as ground truth if provided
    if epic_spec:
        prompt += _format_epic_expectations(epic_spec)

    return prompt


def _format_epic_expectations(epic_spec: dict) -> str:
    """Format epic spec expectations for inclusion in prompts.

    Args:
        epic_spec: Dict containing spec expectations from epic

    Returns:
        Formatted string to append to prompts
    """
    lines = ["\n\n## Epic Expectations (Ground Truth)"]
    lines.append("The following expectations come from the epic definition and take precedence over spec details:")

    if expectations := epic_spec.get("expectations"):
        lines.append("\n### Expected Outcomes")
        for exp in expectations:
            lines.append(f"- {exp}")

    if constraints := epic_spec.get("constraints"):
        lines.append("\n### Constraints")
        for con in constraints:
            lines.append(f"- {con}")

    if check_paths := epic_spec.get("check_paths"):
        lines.append("\n### Files to be Verified (exact paths from epic)")
        for path in check_paths:
            lines.append(f"- {path}")

    lines.append("\n**Important**: If the spec suggests different file paths than the epic expectations, the epic expectations are authoritative.")

    return "\n".join(lines)


# =============================================================================
# Executor Engine
# =============================================================================


def generate_run_id(spec_id: str | None = None) -> str:
    """Generate a unique run_id with timestamp and optional spec.

    Args:
        spec_id: Optional spec identifier to include in run_id (e.g., 'e008-01-core')

    Returns:
        Run ID in format: run-{spec}-{timestamp}-{hash} or run-{timestamp}-{hash}
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suffix = hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:6]

    if spec_id:
        return f"run-{spec_id}-{timestamp}-{suffix}"
    else:
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
        envelope: The envelope containing job_def (or job_def dict), ctx, and payload.
            The job_def must be a JobDef object or a dict that can be parsed as one.
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
    job_def_data = envelope.get("job_def")
    if not job_def_data:
        raise ExecutorError("Missing job_def in envelope", run_id=run_id)

    # Parse job_def if it's a dict
    if isinstance(job_def_data, dict):
        try:
            job_def = JobDef.model_validate(job_def_data)
        except Exception as e:
            raise ExecutorError(f"Invalid job_def: {e}", run_id=run_id) from e
    elif isinstance(job_def_data, JobDef):
        job_def = job_def_data
    else:
        raise ExecutorError(
            f"job_def must be a dict or JobDef, got {type(job_def_data).__name__}",
            run_id=run_id,
        )

    job_id = job_def.job_id
    ctx = envelope.get("ctx", {})
    payload = envelope.get("payload", {})

    # Get repo info from payload
    repo_path = Path(payload.get("repo_path", ".")).resolve()

    # Resolve base_commit to SHA if not provided (determinism)
    base_commit = payload.get("base_commit")
    if not base_commit or base_commit == "HEAD":
        base_commit = _get_current_commit(repo_path)
        # Update envelope so compile_job sees the resolved SHA
        payload["base_commit"] = base_commit

    # Resolve branch
    branch = payload.get("feature_branch", payload.get("branch"))
    if not branch:
        branch = _get_current_branch(repo_path)

    # Compile to JobInstance (uses resolved base_commit from payload)
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
        job_requires_llm = _job_requires_llm(job_instance)
        use_llm_report = _use_llm_for_run_report(job_instance=job_instance)
        if job_requires_llm or use_llm_report:
            # Hard gate: require successful LLM preflight before any steps.
            _require_llm_preflight(run_id=run_id)

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

    # Generate final artifacts (patch and report)
    _generate_run_artifacts(run_record, attempt, store)

    # Write final state
    store.write_attempt(run_id, attempt)
    store.write_run_record(run_id, run_record)

    return run_record


def execute_instance(
    job_instance: JobInstance,
    *,
    store: RunStore | None = None,
    run_id: str | None = None,
    policy: Policy | None = None,
) -> RunRecord:
    """
    Execute a pre-compiled JobInstance directly without recompiling.

    Use this when you have a JobInstance from compile_job() or loaded from disk.

    Args:
        job_instance: The pre-compiled JobInstance to execute
        store: Optional RunStore (defaults to standard location)
        run_id: Optional run_id (defaults to generated)
        policy: Optional execution policy (defaults to standard policy)

    Returns:
        The final RunRecord

    Raises:
        ExecutorError: If execution fails
    """
    store = store or RunStore()
    run_id = run_id or generate_run_id()
    policy = policy or Policy()

    # Get repo info from first step
    if not job_instance.steps:
        raise ExecutorError("JobInstance has no steps", run_id=run_id)

    first_step = job_instance.steps[0]
    repo_path = first_step.common.repo_path
    branch = first_step.common.branch
    base_commit = first_step.common.base_commit

    # Create RunRecord
    run_record = RunRecord(
        run_id=run_id,
        job_id=job_instance.job_id,
        job_hash=job_instance.job_hash,
        repo=RepoScope(
            repo_path=repo_path,
            branch=branch,
            base_commit=base_commit,
        ),
        policy=policy,
        status=RunStatus.running,
        envelope={},  # No envelope for direct instance execution
    )

    # Create run directory and write initial artifacts
    store.create_run(run_id)
    store.write_run_record(run_id, run_record)
    store.write_job_instance(run_id, job_instance)

    # Execute with attempt tracking
    attempt_n = 1
    attempt = AttemptRecord(
        attempt_n=attempt_n,
        started_at=datetime.now(UTC),
        status=AttemptStatus.running,
    )

    try:
        job_requires_llm = _job_requires_llm(job_instance)
        use_llm_report = _use_llm_for_run_report(job_instance=job_instance)
        if job_requires_llm or use_llm_report:
            # Hard gate: require successful LLM preflight before any steps.
            _require_llm_preflight(run_id=run_id)

        # Build ctx/payload from common block for variable resolution
        ctx: dict[str, Any] = {}
        payload: dict[str, Any] = {
            "repo_path": str(repo_path),
            "branch": branch,
            "base_commit": base_commit,
        }

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

    # Generate final artifacts (patch and report)
    _generate_run_artifacts(run_record, attempt, store)

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

    Respects continue_on_failure and on_failure_skip_to flags on steps:
    - If a step fails and on_failure_skip_to is set, skip to that step
    - If a step fails and continue_on_failure=False (and no skip_to), abort immediately
    - If a step fails and continue_on_failure=True (and no skip_to), continue to next step
    - Final status: completed (all ok), completed_with_errors (some failed/skipped), failed (abort)

    Returns:
        Tuple of (final_status, list of step outcomes)
    """
    outcomes: list[StepOutcome] = []
    any_step_failed = False

    # Build run context for variable resolution
    run_ctx = {
        "run_id": run_record.run_id,
        "repo_path": str(run_record.repo.repo_path),
        "branch": run_record.repo.branch,
        "base_commit": run_record.repo.base_commit,
        "steps": {},  # Will be populated as steps complete
    }

    # Use index-based loop to support skip-to jumps
    step_idx = 0
    while step_idx < len(job_instance.steps):
        step = job_instance.steps[step_idx]
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

            # Variable errors are always fatal - can't continue without resolved payload
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

        # Log step start
        total_steps = len(job_instance.steps)
        print(f"[{step.step_n}/{total_steps}] {step.step_id} ... started", flush=True)

        # Dispatch to backend
        capture = None
        backend_error = None
        try:
            backend = get_backend(step.backend.value)
            capture = backend.dispatch(
                manifest=manifest,
                artifacts_dir=step_dir,
                policy=run_record.policy,
                capture_patch=step.capture_patch,
            )
        except BackendError as e:
            backend_error = str(e)
        except Exception as e:
            backend_error = f"Unexpected error: {e}"

        duration_ms = int((time.time() - start_time) * 1000)

        # Handle backend errors
        if backend_error:
            outcome = _create_failed_outcome(
                step=step,
                error=backend_error,
                duration_ms=duration_ms,
            )
            outcomes.append(outcome)
            store.write_step_outcome(run_record.run_id, step.step_n, outcome)

            # Log step failure
            duration_str = f"{duration_ms}ms" if duration_ms < 1000 else f"{duration_ms/1000:.1f}s"
            print(f"[{step.step_n}/{total_steps}] {step.step_id} ... failed ({duration_str})", flush=True)

            # Update run context even for failures
            run_ctx["steps"][step.step_id] = {
                "outcome": OutcomeStatus.failed.value,
                "capture_ref": outcome.capture_ref,
            }

            # Handle skip-to or continue-on-failure
            skip_result = _handle_step_failure(
                step, step_idx, job_instance, outcomes, run_record, store
            )
            if skip_result is None:
                # No skip-to, no continue_on_failure - abort
                return RunStatus.failed, outcomes
            step_idx, any_step_failed = skip_result[0], True
            continue

        # Determine outcome status from capture
        assert capture is not None
        if step.interactive:
            # Interactive steps always complete — exit code is telemetry only.
            # The human was present and knows whether work was done.
            outcome_status = OutcomeStatus.completed
        elif capture.agent and capture.agent.exit_code == 124:
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

        # Log step completion
        duration_str = f"{duration_ms}ms" if duration_ms < 1000 else f"{duration_ms/1000:.1f}s"
        print(f"[{step.step_n}/{total_steps}] {step.step_id} ... {outcome_status.value} ({duration_str})", flush=True)

        outcomes.append(outcome)

        # Update run context with step info
        run_ctx["steps"][step.step_id] = {
            "outcome": outcome_status.value,
            "capture_ref": outcome.capture_ref,
        }

        # Check if we should abort, skip, or continue
        if outcome_status != OutcomeStatus.completed:
            # Handle skip-to or continue-on-failure
            skip_result = _handle_step_failure(
                step, step_idx, job_instance, outcomes, run_record, store
            )
            if skip_result is None:
                # No skip-to, no continue_on_failure - abort
                return RunStatus.failed, outcomes
            step_idx, any_step_failed = skip_result[0], True
            continue

        step_idx += 1

    # All steps completed (some may have failed/skipped with continue_on_failure or skip_to)
    if any_step_failed:
        return RunStatus.completed_with_errors, outcomes
    return RunStatus.completed, outcomes


def _generate_run_artifacts(
    run_record: RunRecord,
    attempt: AttemptRecord,
    store: RunStore,
) -> None:
    """
    Generate final run artifacts: changes_final.patch and run_report.md.

    Called after all steps complete (success or failure).
    """
    run_dir = store.get_run_path(run_record.run_id)
    repo_path = Path(run_record.repo.repo_path)
    base_commit = run_record.repo.base_commit

    # Generate final cumulative patch
    try:
        patch_path = run_dir / "changes_final.patch"
        generate_patch(repo_path, base_commit, output_path=patch_path)
        print(f"Generated: {patch_path.name}", flush=True)
    except Exception as e:
        print(f"Warning: Failed to generate changes_final.patch: {e}", flush=True)

    # Generate run report (LLM-backed only when requested/required)
    try:
        job_instance = store.read_job_instance(run_record.run_id)
        _generate_run_report(
            run_record,
            attempt,
            store,
            run_dir,
            use_llm=_use_llm_for_run_report(job_instance=job_instance),
        )
    except Exception as e:
        print(f"Warning: Failed to generate run_report.md: {e}", flush=True)


def _generate_run_report(
    run_record: RunRecord,
    attempt: AttemptRecord,
    store: RunStore,
    run_dir: Path,
    *,
    use_llm: bool,
) -> None:
    """Generate a run report.

    If `use_llm` is True, uses the LLM backend. Otherwise, writes a plain report
    based on step outcomes and the final patch.
    """

    # Build summary of step outcomes
    outcomes_summary = []
    for outcome in attempt.step_outcomes or []:
        outcomes_summary.append(
            f"- Step {outcome.step_n} ({outcome.step_id}): {outcome.outcome.value}"
            + (f" - {outcome.error}" if outcome.error else "")
        )

    # StepManifest enforces step_n >= 1. This report isn't a real job step, but
    # we still need a valid, non-colliding step number for backend dispatch.
    report_step_n = 1
    if attempt.step_outcomes:
        report_step_n = max(o.step_n for o in attempt.step_outcomes) + 1

    # Read the final patch if it exists
    patch_path = run_dir / "changes_final.patch"
    patch_content = ""
    if patch_path.exists():
        patch_content = patch_path.read_text()
        # Truncate if too long
        if len(patch_content) > 50000:
            patch_content = patch_content[:50000] + "\n... (truncated)"

    if not use_llm:
        report_path = run_dir / "run_report.md"
        report_content = f"""# Run Report: {run_record.run_id}

**Generated**: {datetime.now(UTC).isoformat()}
**Status**: {run_record.status.value}
**Job**: {run_record.job_id}

---

## Step Outcomes
{chr(10).join(outcomes_summary) if outcomes_summary else "(no steps)"}

## Code Changes (diff from baseline)
```diff
{patch_content if patch_content else "(no changes)"}
```
"""
        report_path.write_text(report_content)
        print(f"Generated: {report_path.name}", flush=True)
        return

    from spec.executor.backends.llm import LlmBackend

    prompt = f"""Analyze this automated job run and provide a brief report.

## Run Information
- Run ID: {run_record.run_id}
- Job ID: {run_record.job_id}
- Status: {run_record.status.value}
- Repository: {run_record.repo.repo_path}
- Branch: {run_record.repo.branch}

## Step Outcomes
{chr(10).join(outcomes_summary)}

## Code Changes (diff from baseline)
```diff
{patch_content if patch_content else "(no changes)"}
```

## Instructions
Provide a concise report (200-400 words) covering:
1. **Summary**: What was accomplished in this run?
2. **Assessment**: How well did the implementation meet expectations?
3. **Issues**: Any failures, warnings, or concerns?
4. **Recommendation**: What should happen next? (merge, fix issues, manual review, etc.)

Be direct and actionable. Focus on what matters for the person reviewing this run.
"""

    # Use LLM backend to generate report
    backend = LlmBackend()
    try:
        # Preflight (non-network): ensure model resolves and required key exists.
        # In tests we may monkeypatch LlmBackend with a dummy that doesn't implement verify.
        verify = getattr(backend, "verify", None)
        if callable(verify):
            verify()

        # Create a minimal manifest for the LLM call
        manifest = StepManifest(
            step_n=report_step_n,
            step_id="run_report",
            backend=Backend.llm,
            common=Common(
                repo_path=Path(run_record.repo.repo_path),
                branch=run_record.repo.branch,
                base_commit=run_record.repo.base_commit,
            ),
            payload={
                "prompt": prompt,
            },
        )

        capture = backend.dispatch(
            manifest=manifest,
            artifacts_dir=run_dir,
            policy=run_record.policy,
        )

        # Extract response and write report.
        # LlmBackend writes the model output to the captured stdout file.
        stdout_text = ""
        stderr_text = ""

        if capture.agent and capture.agent.stdout_file:
            stdout_path = run_dir / capture.agent.stdout_file
            if stdout_path.exists():
                stdout_text = stdout_path.read_text().strip()

        if capture.agent and capture.agent.stderr_file:
            stderr_path = run_dir / capture.agent.stderr_file
            if stderr_path.exists():
                stderr_text = stderr_path.read_text().strip()

        report_path = run_dir / "run_report.md"
        if stdout_text:
            report_body = stdout_text
        else:
            # Ensure reviewers still get a useful artifact even if the LLM call fails fast
            # (e.g., model not configured / missing provider / missing API key).
            report_body = """LLM report generation produced no output.

This usually means the LLM backend failed immediately (model not available, provider plugin missing, or credentials not configured).
"""
            if stderr_text:
                report_body += f"\n\n## LLM stderr\n\n```\n{stderr_text}\n```\n"

        report_content = f"""# Run Report: {run_record.run_id}

**Generated**: {datetime.now(UTC).isoformat()}
**Status**: {run_record.status.value}
**Job**: {run_record.job_id}

---

{report_body}
"""
        report_path.write_text(report_content)
        print(f"Generated: {report_path.name}", flush=True)

    except Exception as e:
        # Log but don't fail the run; still write a diagnostic report artifact.
        print(f"Warning: LLM report generation failed: {e}", flush=True)

        report_path = run_dir / "run_report.md"
        report_content = f"""# Run Report: {run_record.run_id}

**Generated**: {datetime.now(UTC).isoformat()}
**Status**: {run_record.status.value}
**Job**: {run_record.job_id}

---

LLM report generation failed before producing output.

## Error

```
{e}
```
"""
        report_path.write_text(report_content)


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


def _handle_step_failure(
    step: Step,
    step_idx: int,
    job_instance: JobInstance,
    outcomes: list[StepOutcome],
    run_record: RunRecord,
    store: RunStore,
) -> tuple[int, bool] | None:
    """
    Handle step failure with skip-to or continue-on-failure logic.

    Args:
        step: The step that failed
        step_idx: Current index in job_instance.steps
        job_instance: The job instance
        outcomes: List of outcomes to append skipped outcomes to
        run_record: The run record
        store: The run store

    Returns:
        Tuple of (next_step_idx, any_failed) if should continue, None if should abort
    """
    # Check for on_failure_skip_to first
    if step.on_failure_skip_to:
        # Find target step index
        target_idx = next(
            (i for i, s in enumerate(job_instance.steps) if s.step_id == step.on_failure_skip_to),
            None,
        )

        if target_idx is not None and target_idx > step_idx:
            # Log skip-to action
            total_steps = len(job_instance.steps)
            print(f"  → skipping to {step.on_failure_skip_to}", flush=True)

            # Skip intermediate steps
            for skip_idx in range(step_idx + 1, target_idx):
                skipped_step = job_instance.steps[skip_idx]
                skip_outcome = StepOutcome(
                    step_n=skipped_step.step_n,
                    step_id=skipped_step.step_id,
                    outcome=OutcomeStatus.skipped,
                    duration_ms=0,
                    manifest_ref=None,
                    capture_ref=None,
                    error=f"Skipped due to failure of {step.step_id}",
                )
                outcomes.append(skip_outcome)
                store.write_step_outcome(run_record.run_id, skipped_step.step_n, skip_outcome)

                # Log skipped step
                print(f"[{skipped_step.step_n}/{total_steps}] {skipped_step.step_id} ... skipped", flush=True)

            # Return the target index to continue from
            return (target_idx, True)

    # Fall back to continue_on_failure
    if step.continue_on_failure:
        return (step_idx + 1, True)

    # No skip-to and no continue_on_failure - abort
    return None
