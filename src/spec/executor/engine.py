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

import yaml

from spec.executor.backends import BackendError, get_backend
from spec.executor.gate_emission import emit_step_record
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


def _resolve_backend(
    backend: Backend | str,
    payload: dict[str, Any],
) -> Backend:
    """Resolve backend variable references to Backend enum values."""
    if isinstance(backend, Backend):
        return backend

    # Handle @payload.* variable references
    if isinstance(backend, str) and backend.startswith("@payload."):
        key = backend[len("@payload."):]
        value = payload.get(key)
        if value is None:
            raise CompileError(
                f"Required payload key '{key}' not found for backend variable '{backend}'"
            )
        backend = value

    # Convert string to Backend enum (by value, e.g., "claude-code" → Backend.claude_code)
    try:
        return Backend(backend)
    except ValueError:
        raise CompileError(f"Unknown backend: '{backend}'") from None


def _require_llm_preflight(*, run_id: str, review_model: str | None = None) -> None:
    """Hard gate for LLM availability.

    Called before executing any steps for runs that require LLM (LLM steps and/or
    LLM-backed run report). This prevents partially-executed runs when the LLM
    backend is misconfigured.

    Args:
        run_id: Current run ID for error context.
        review_model: Optional model override for LLM review steps.
            If set, preflight validates this model instead of the default.

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
    old_model_flag = os.environ.get("SPECWRIGHT_LLM_MODEL")
    os.environ["SPECWRIGHT_LLM_NETWORK_PREFLIGHT"] = "1"
    if review_model:
        os.environ["SPECWRIGHT_LLM_MODEL"] = review_model
    try:
        LlmBackend().verify()
    except Exception as e:
        raise ExecutorError(f"LLM preflight failed: {e}", run_id=run_id) from e
    finally:
        if old_network_flag is None:
            os.environ.pop("SPECWRIGHT_LLM_NETWORK_PREFLIGHT", None)
        else:
            os.environ["SPECWRIGHT_LLM_NETWORK_PREFLIGHT"] = old_network_flag
        if review_model:
            if old_model_flag is None:
                os.environ.pop("SPECWRIGHT_LLM_MODEL", None)
            else:
                os.environ["SPECWRIGHT_LLM_MODEL"] = old_model_flag


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


def _preflight_backend_checks(
    job_instance: JobInstance, *, run_id: str
) -> None:
    """Verify all backends are available before dispatch."""
    if _is_truthy_env(os.environ.get("SPECWRIGHT_SKIP_BACKEND_PREFLIGHT")):
        return
    unique_backends = {step.backend for step in job_instance.steps}
    for backend_enum in unique_backends:
        backend_instance = get_backend(backend_enum.value)
        try:
            backend_instance.verify()
        except BackendError as e:
            raise ExecutorError(
                f"Backend '{backend_enum.value}' is not available: {e}",
                run_id=run_id,
            ) from e


# =============================================================================
# Variable Resolution
# =============================================================================

# Pattern to match @ref.path.to.value or @ref['key'] or @ref["key"]
_REF_PATTERN = re.compile(
    r"@(ctx|payload|run)(?:\.([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)|\[(['\"])([^'\"]+)\3\])"
)


def _get_nested(data: dict[str, Any], path: str) -> Any:
    """Get a nested value from a dict using dot notation.

    Handles dotted keys (e.g., step IDs like "branch.create") by trying
    progressively longer compound keys when a simple key lookup fails.
    For path "steps.branch.create.outcome", tries:
      steps -> branch.create -> outcome
    """
    parts = path.split(".")
    current = data
    i = 0
    while i < len(parts):
        if not isinstance(current, dict):
            raise KeyError(f"Cannot traverse non-dict at {'.'.join(parts[:i])} in path {path}")
        # Try simple key first
        if parts[i] in current:
            current = current[parts[i]]
            i += 1
            continue
        # Try compound keys: parts[i].parts[i+1], parts[i].parts[i+1].parts[i+2], ...
        found = False
        for j in range(i + 2, len(parts) + 1):
            compound = ".".join(parts[i:j])
            if compound in current:
                current = current[compound]
                i = j
                found = True
                break
        if not found:
            raise KeyError(f"Key not found: {parts[i]} in path {path}")
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
    # For passthrough keys (spec_md, prompt, etc.), we need special handling:
    # - If the value is a direct variable reference like '@payload.spec_md', resolve it
    # - If the value is actual content (resolved markdown), don't scan it for @refs
    if _current_key in PASSTHROUGH_KEYS:
        if isinstance(value, str) and _REF_PATTERN.fullmatch(value):
            # Direct variable reference - resolve it to get the actual content
            return _resolve_string(value, ctx, payload, run, allow_run=allow_run, preserve_run=preserve_run)
        # Actual content - return unchanged (don't scan for embedded @refs)
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

        resolved_backend = _resolve_backend(template.backend, payload)

        step = Step(
            step_n=step_n,
            step_id=template.step_id,
            backend=resolved_backend,
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


def _extract_acceptance_criteria(spec_md: str) -> str:
    """Extract just the acceptance criteria section from spec markdown.

    Returns the criteria block for use in drift prompts.
    Falls back to the full spec if no AC section is found.
    """
    lines = spec_md.split("\n")
    ac_lines: list[str] = []
    in_ac = False

    for line in lines:
        if line.strip().lower().startswith("## acceptance criteria"):
            in_ac = True
            ac_lines.append(line)
            continue
        if in_ac:
            if line.startswith("## ") and "acceptance" not in line.lower():
                break
            ac_lines.append(line)

    if ac_lines:
        return "\n".join(ac_lines)

    # Fallback: no AC section found — return full spec
    return spec_md


def _extract_spec_ground_truth(spec_md: str) -> dict[str, Any]:
    """Extract compact, structured ground truth from a YAML-native spec."""

    def _text_list(raw: Any) -> list[str]:
        items: list[str] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    items.append(item.strip())
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        items.append(text.strip())
        return items

    try:
        parsed = yaml.safe_load(spec_md) or {}
    except Exception:
        parsed = {}

    if not isinstance(parsed, dict):
        return {
            "goal": None,
            "objective": None,
            "acceptance_criteria": [],
            "constraints": [],
            "touch_list": [],
            "steps": [],
            "body": None,
        }

    doc = parsed.get("document") if isinstance(parsed.get("document"), dict) else {}

    touch_list: list[dict[str, str]] = []
    for item in doc.get("touch_list", []):
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        action = item.get("action")
        reason = item.get("reason")
        if isinstance(path, str) and path.strip():
            touch_list.append({
                "path": path.strip(),
                "action": action.strip() if isinstance(action, str) else "",
                "reason": reason.strip() if isinstance(reason, str) else "",
            })

    steps: list[dict[str, Any]] = []
    for item in doc.get("steps", []):
        if not isinstance(item, dict):
            continue
        files = item.get("files") if isinstance(item.get("files"), list) else []
        steps.append({
            "id": item.get("id"),
            "description": item.get("description", ""),
            "verification": item.get("verification", ""),
            "files": [f for f in files if isinstance(f, str)],
        })

    body = doc.get("body")
    return {
        "goal": parsed.get("goal") if isinstance(parsed.get("goal"), str) else None,
        "objective": parsed.get("objective") if isinstance(parsed.get("objective"), str) else None,
        "acceptance_criteria": _text_list(doc.get("acceptance_criteria", [])),
        "constraints": _text_list(doc.get("constraints", [])),
        "touch_list": touch_list,
        "steps": steps,
        "body": body if isinstance(body, str) else None,
    }


def _format_spec_ground_truth(spec_md: str, *, include_body_excerpt: bool = False) -> str:
    """Format a compact spec-ground-truth summary for agent prompts."""

    summary = _extract_spec_ground_truth(spec_md)
    lines: list[str] = ["## Spec Ground Truth (Authoritative)", ""]

    if summary["goal"]:
        lines.extend(["### Goal", str(summary["goal"]), ""])

    if summary["objective"]:
        lines.extend(["### Objective", str(summary["objective"]), ""])

    if summary["acceptance_criteria"]:
        lines.append("### Acceptance Criteria")
        for idx, item in enumerate(summary["acceptance_criteria"], 1):
            lines.append(f"{idx}. {item}")
        lines.append("")

    if summary["constraints"]:
        lines.append("### Constraints / Invariants")
        for item in summary["constraints"]:
            lines.append(f"- {item}")
        lines.append("")

    if summary["touch_list"]:
        lines.append("### Intended File Surface")
        for item in summary["touch_list"]:
            action = f" ({item['action']})" if item["action"] else ""
            reason = f" — {item['reason']}" if item["reason"] else ""
            lines.append(f"- {item['path']}{action}{reason}")
        lines.append("")

    if summary["steps"]:
        lines.append("### Execution Steps")
        for item in summary["steps"]:
            header = f"Step {item['id']}: {item['description']}" if item["id"] is not None else str(item["description"])
            lines.append(f"- {header}")
            if item["verification"]:
                lines.append(f"  Verification: {item['verification']}")
        lines.append("")

    if include_body_excerpt and summary["body"]:
        excerpt = str(summary["body"]).strip()
        if len(excerpt) > 4000:
            excerpt = excerpt[:4000] + "\n... (truncated)"
        lines.extend(["### Body Excerpt", excerpt, ""])

    return "\n".join(lines).strip()


def _build_execute_spec_prompt(epic_spec: dict | None = None, spec_md: str | None = None) -> str:
    """Build prompt for Run 1: initial spec execution."""
    prompt = """# Execute Spec

You are implementing a governed spec. Follow the spec literally.

## Non-negotiable rules

1. Acceptance criteria and constraints are authoritative.
2. Do NOT invent a cleaner architecture if it conflicts with the spec.
3. Do NOT rewrite tests to bless an implementation that violates the spec.
4. If the spec states an existing ground truth (shape, API, file contract,
   data contract), preserve that exact ground truth.
5. Prefer the files in the touch list. If you must touch another file, do the
   minimum necessary and keep it clearly tied to the spec.

## Required workflow

1. Read the spec ground truth below and extract the invariants before editing.
2. Inspect the current repo implementation to confirm the stated ground truth.
3. Implement only what the spec asks for.
4. Run the verification commands from the spec steps and acceptance criteria.
5. Before finishing, re-check the implementation against the constraints,
   not just the updated tests.
"""

    if spec_md:
        prompt += "\n\n" + _format_spec_ground_truth(spec_md, include_body_excerpt=True)

        forbidden = _extract_forbidden_legacy_semantics(spec_md)
        if forbidden:
            prompt += "\n\n## Forbidden Legacy Semantics (Must NOT Remain)\n\n"
            for item in forbidden:
                prompt += f"- {item}\n"

    if epic_spec:
        prompt += _format_epic_expectations(epic_spec)

    return prompt


def _extract_forbidden_legacy_semantics(spec_md: str) -> list[str]:
    """Extract forbidden legacy semantics from YAML-native or markdown specs."""

    def _normalize(raw: Any) -> list[str]:
        if isinstance(raw, str):
            return [raw.strip()] if raw.strip() else []
        if isinstance(raw, list):
            items: list[str] = []
            for item in raw:
                if isinstance(item, str) and item.strip():
                    items.append(item.strip())
            return items
        return []

    stripped = spec_md.lstrip()
    if stripped and not stripped.startswith("---"):
        try:
            raw = yaml.safe_load(spec_md) or {}
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            doc = raw.get("document") if isinstance(raw.get("document"), dict) else {}
            semantics = raw.get("forbidden_legacy_semantics")
            if semantics is None and isinstance(doc, dict):
                semantics = doc.get("forbidden_legacy_semantics")
            values = _normalize(semantics)
            if values:
                return values

    if stripped.startswith("---"):
        end = spec_md.find("\n---\n", 4)
        if end != -1:
            try:
                frontmatter = yaml.safe_load(spec_md[4:end]) or {}
            except Exception:
                frontmatter = {}
            if isinstance(frontmatter, dict):
                values = _normalize(frontmatter.get("forbidden_legacy_semantics"))
                if values:
                    return values

    lines = spec_md.splitlines()
    collected: list[str] = []
    in_section = False
    for line in lines:
        stripped_line = line.strip()
        if stripped_line.lower().startswith("## forbidden legacy semantics"):
            in_section = True
            continue
        if in_section:
            if stripped_line.startswith("## "):
                break
            if stripped_line.startswith(("- ", "* ")):
                item = stripped_line[2:].strip()
                if item:
                    collected.append(item)
    return collected


def _build_drift_fix_prompt(epic_spec: dict | None = None, spec_md: str | None = None) -> str:
    """Build prompt for Run 2: drift inspection and fix.

    Uses only acceptance criteria and touched-file context (not the full spec)
    to keep the prompt small and the agent focused.

    Args:
        epic_spec: Optional epic spec expectations to include as ground truth
        spec_md: Optional full spec markdown (AC will be extracted)
    """
    prompt = """# Drift Inspection and Fix

You are reviewing the code changes from the previous spec implementation run.

## Your Task

1. Run `git diff --name-only` from base commit to list touched files
2. Run `git diff --stat` to see scope of changes
3. Check each acceptance criterion below against the actual implementation
4. Run tests relevant to the touched files
5. If any criteria are unmet or tests fail, fix them

Focus ONLY on acceptance criteria and test correctness.
Do NOT refactor, restyle, or explore beyond the touched files.
"""

    if spec_md:
        prompt += "\n\n" + _format_spec_ground_truth(spec_md)

    # Add epic expectations as ground truth if provided
    if epic_spec:
        prompt += _format_epic_expectations(epic_spec)

    return prompt


def _build_drift_verify_prompt(epic_spec: dict | None = None, spec_md: str | None = None) -> str:
    """Build prompt for Run 3: final drift verification.

    Uses only acceptance criteria and touched-file context (not the full spec)
    to keep the agent focused on verification, not re-exploration.

    Args:
        epic_spec: Optional epic spec expectations to include as ground truth
        spec_md: Optional full spec markdown (AC will be extracted)
    """
    prompt = """# Final Drift Verification

You are performing a final verification pass on the spec implementation.

## Your Task

1. Run `git diff --name-only` from base commit — these are the ONLY files to check
2. Verify the implementation against the acceptance criteria, epic expectations,
   and architectural invariants — not just against the rewritten tests
3. Explicitly search for any forbidden legacy semantics listed below; if any are
   still present, that is drift even if tests pass
4. Run relevant test suites — if any test fails, fix it
5. Do NOT make unnecessary changes — only fix actual failures

This is the FINAL pass. Be surgical: verify criteria, check invariants, run tests,
and fix real failures.

Do not treat passing tests alone as sufficient evidence. Rewritten tests can still
encode stale architecture.
"""

    if spec_md:
        prompt += "\n\n" + _format_spec_ground_truth(spec_md)

        forbidden = _extract_forbidden_legacy_semantics(spec_md)
        if forbidden:
            prompt += "\n## Forbidden Legacy Semantics (Must NOT Remain)\n\n"
            for item in forbidden:
                prompt += f"- {item}\n"
            prompt += (
                "\nFor each forbidden semantic above, explicitly search the changed code "
                "and updated tests. If it remains, remove it or mark the run as drifting.\n"
            )

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
            _require_llm_preflight(run_id=run_id, review_model=payload.get("review_model"))

        # Verify all backends are available before dispatch.
        _preflight_backend_checks(job_instance, run_id=run_id)

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
            _emit_step_record_best_effort(
                store=store, run_id=run_record.run_id, step_n=step.step_n,
                job_id=job_instance.job_id,
            )

            # Variable errors are always fatal - can't continue without resolved payload
            return RunStatus.failed, outcomes

        # Inject review_model into LLM step payloads if set and step doesn't override
        if step.backend == Backend.llm and "model" not in resolved_payload:
            review_model = payload.get("review_model")
            if review_model:
                resolved_payload["model"] = review_model

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
            _emit_step_record_best_effort(
                store=store, run_id=run_record.run_id, step_n=step.step_n,
                job_id=job_instance.job_id,
            )

            # Log step failure
            duration_str = f"{duration_ms}ms" if duration_ms < 1000 else f"{duration_ms/1000:.1f}s"
            print(f"[{step.step_n}/{total_steps}] {step.step_id} ... failed ({duration_str})", flush=True)

            # Update run context even for failures
            run_ctx["steps"][step.step_id] = _build_step_run_ctx(
                outcome, capture, step_dir,
            )

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
        _emit_step_record_best_effort(
            store=store, run_id=run_record.run_id, step_n=step.step_n,
            job_id=job_instance.job_id,
        )

        # Log step completion
        duration_str = f"{duration_ms}ms" if duration_ms < 1000 else f"{duration_ms/1000:.1f}s"
        print(f"[{step.step_n}/{total_steps}] {step.step_id} ... {outcome_status.value} ({duration_str})", flush=True)

        outcomes.append(outcome)

        # Update run context with step output (structured data + artifact contents)
        # so later steps can reference via @run.steps.{step_id}.*
        run_ctx["steps"][step.step_id] = _build_step_run_ctx(
            outcome, capture, step_dir,
        )

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
    Generate final run artifacts: changes_final.patch and run report.

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
        print(f"Warning: Failed to generate run report artifact: {e}", flush=True)


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
    issues = [
        {
            "description": (
                f"Step {outcome.step_n} ({outcome.step_id}) "
                f"{outcome.outcome.value}"
                + (f": {outcome.error}" if outcome.error else "")
            ),
            "severity": "warning",
        }
        for outcome in (attempt.step_outcomes or [])
        if outcome.outcome != OutcomeStatus.completed
    ]

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
        report_data = {
            "run_id": run_record.run_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": run_record.status.value,
            "job_id": run_record.job_id,
            "summary": (
                "Automated run completed. "
                f"{len(attempt.step_outcomes or [])} step(s) executed."
            ),
            "assessment": (
                "Run completed successfully."
                if run_record.status == RunStatus.completed
                else f"Run completed with status: {run_record.status.value}."
            ),
            "issues": issues,
            "recommendation": (
                "Proceed with normal review and merge process."
                if run_record.status == RunStatus.completed
                else "Review failed/timed-out steps before merging."
            ),
        }
        store.write_run_report(run_record.run_id, report_data, report_content)
        report_name = "run_report.yaml" if (run_dir / "run_report.yaml").exists() else "run_report.md"
        print(f"Generated: {report_name}", flush=True)
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
        report_payload: dict[str, Any] = {"prompt": prompt}
        # Use review_model from envelope if available
        envelope_payload = (run_record.envelope or {}).get("payload", {})
        if envelope_payload.get("review_model"):
            report_payload["model"] = envelope_payload["review_model"]

        manifest = StepManifest(
            step_n=report_step_n,
            step_id="run_report",
            backend=Backend.llm,
            common=Common(
                repo_path=Path(run_record.repo.repo_path),
                branch=run_record.repo.branch,
                base_commit=run_record.repo.base_commit,
            ),
            payload=report_payload,
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
        report_data = {
            "run_id": run_record.run_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": run_record.status.value,
            "job_id": run_record.job_id,
            "summary": report_body,
            "assessment": (
                "LLM-generated report produced."
                if stdout_text
                else "LLM generated no summary output."
            ),
            "issues": issues,
            "recommendation": (
                "Review this run report and proceed with merge if acceptable."
                if run_record.status == RunStatus.completed
                else "Review issues before proceeding."
            ),
        }
        store.write_run_report(run_record.run_id, report_data, report_content)
        report_name = "run_report.yaml" if (run_dir / "run_report.yaml").exists() else "run_report.md"
        print(f"Generated: {report_name}", flush=True)

    except Exception as e:
        # Log but don't fail the run; still write a diagnostic report artifact.
        print(f"Warning: LLM report generation failed: {e}", flush=True)
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
        report_data = {
            "run_id": run_record.run_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": run_record.status.value,
            "job_id": run_record.job_id,
            "summary": "LLM report generation failed before producing output.",
            "assessment": "Run report fallback artifact generated from failure path.",
            "issues": [
                *issues,
                {"description": f"LLM report generation failed: {e}", "severity": "warning"},
            ],
            "recommendation": "Check LLM backend configuration and rerun report generation.",
        }
        store.write_run_report(run_record.run_id, report_data, report_content)


def _build_step_run_ctx(
    outcome: StepOutcome,
    capture: Any | None,
    artifacts_dir: Path,
) -> dict[str, Any]:
    """Build the run-context entry for a completed step.

    Includes structured data (assessments) and artifact file contents
    (stderr, stdout) so later steps can reference them via @run.steps.{id}.*
    """
    ctx: dict[str, Any] = {
        "outcome": outcome.outcome.value,
        "capture_ref": outcome.capture_ref,
        "error": outcome.error,
        "data": {},
        "stderr": "",
        "stdout": "",
        "exit_code": None,
    }

    if capture is None:
        return ctx

    # Structured data from python backend callables
    if capture.assessments:
        ctx["data"] = (
            capture.assessments[0]
            if len(capture.assessments) == 1
            else capture.assessments
        )

    # Agent output
    if capture.agent:
        ctx["exit_code"] = capture.agent.exit_code

        for key, filename in [("stderr", capture.agent.stderr_file), ("stdout", capture.agent.stdout_file)]:
            if not filename:
                continue
            fpath = artifacts_dir / filename
            try:
                if fpath.exists():
                    ctx[key] = fpath.read_text()
            except Exception as e:
                ctx[key] = f"[error reading {filename}: {e}]"
                print(f"Warning: failed to read {fpath} into run context: {e}", flush=True)

    return ctx


def _emit_step_record_best_effort(
    *, store: RunStore, run_id: str, step_n: int, job_id: str
) -> None:
    """Best-effort incremental run_step emission (t019-04 D(c)).

    Never raises and never alters execution — only the pre-execution
    claim (see exec_commands._emit_claim_record) is allowed to abort a
    run. A gate hiccup here just means one fewer step landed as a
    governed row before finalize's own emit_run_records() sweep, which
    still runs unchanged over every local step file.
    """
    try:
        emit_step_record(store=store, run_id=run_id, step_n=step_n, job_id=job_id)
    except Exception as e:
        print(f"Warning: incremental run_step emission failed for step {step_n}: {e}", flush=True)


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
                _emit_step_record_best_effort(
                    store=store, run_id=run_record.run_id, step_n=skipped_step.step_n,
                    job_id=job_instance.job_id,
                )

                # Log skipped step
                print(f"[{skipped_step.step_n}/{total_steps}] {skipped_step.step_id} ... skipped", flush=True)

            # Return the target index to continue from
            return (target_idx, True)

    # Fall back to continue_on_failure
    if step.continue_on_failure:
        return (step_idx + 1, True)

    # No skip-to and no continue_on_failure - abort
    return None
