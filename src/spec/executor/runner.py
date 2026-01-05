"""
Step Execution Runner (Orchestrator)

Implements the full step lifecycle: extract → loop → gate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from spec.executor.adapters import (
    AdapterError,
    EscalationRequired,
    ProtocolError,
    ToolNotFoundError,
    get_adapter,
)
from spec.executor.artifacts import ArtifactWriter
from spec.executor.contract import StepContract, build_contract, save_contract
from spec.executor.scope import ScopeResult, check_scope, generate_policy_report
from spec.executor.sep import StepExecutionPlan, save_sep
from spec.executor.sep_builder import SEPBuilder
from spec.executor.verify import (
    VerificationResult,
    generate_verification_report,
    verify,
)


class TerminationReason(Enum):
    """Termination reasons for step execution (v1 minimal)."""

    # Success
    PASS = "PASS"

    # Failures (no retry or retries exhausted)
    FAIL_VERIFY_RETRYABLE = "FAIL_VERIFY_RETRYABLE"
    FAIL_SCOPE = "FAIL_SCOPE"
    FAIL_PATCH_APPLY = "FAIL_PATCH_APPLY"
    FAIL_ADAPTER_PROTOCOL = "FAIL_ADAPTER_PROTOCOL"
    FAIL_DIRTY_WORKTREE = "FAIL_DIRTY_WORKTREE"

    # Escalations (human review required)
    ESCALATE_NEEDS_HUMAN = "ESCALATE_NEEDS_HUMAN"
    ESCALATE_AMBIGUOUS = "ESCALATE_AMBIGUOUS"

    # Gate decisions (post-execution)
    GATE_REJECTED = "GATE_REJECTED"
    GATE_DEFERRED = "GATE_DEFERRED"


@dataclass
class IterationResult:
    """Result from a single iteration."""

    iteration: int
    patch_applied: bool = False
    patch_path: Path | None = None
    scope_result: ScopeResult | None = None
    verification_result: VerificationResult | None = None
    agent_json: dict[str, Any] | None = None
    cmdlog_path: Path | None = None
    error: str | None = None
    termination_reason: TerminationReason | None = None


@dataclass
class StepResult:
    """Result from executing a step."""

    # Required identifiers
    step_id: str
    aip_id: str
    termination_reason: TerminationReason
    # Execution context (for result.json)
    step_idx: int = -1
    baseline_sha: str | None = None
    adapter_name: str = "claude"
    artifacts_dir: str | None = None
    # Iteration results
    iterations: list[IterationResult] = field(default_factory=list)
    final_patch_path: Path | None = None
    touched_files: list[str] = field(default_factory=list)
    # Reports
    policy_report: dict[str, Any] | None = None
    verification_report: dict[str, Any] | None = None
    # SEP
    sep: StepExecutionPlan | None = None
    # Error info
    error: str | None = None
    # Dry run
    dry_run: bool = False
    dry_run_command: str | None = None


@dataclass
class RepoState:
    """Repository state snapshot."""

    commit: str
    branch: str
    dirty: bool
    baseline: str


class StepRunner:
    """Orchestrates step execution with scope enforcement and retry logic."""

    def __init__(
        self,
        repo_root: Path,
        runs_dir: Path | None = None,
        adapter_name: str = "claude",
    ) -> None:
        """
        Initialize the step runner.

        Args:
            repo_root: Path to repository root
            runs_dir: Directory for run artifacts (default: repo_root/runs)
            adapter_name: Name of adapter to use (default: claude)
        """
        self.repo_root = repo_root.resolve()
        self.runs_dir = runs_dir or (self.repo_root / "runs")
        self.adapter_name = adapter_name
        self._adapter = get_adapter(adapter_name)
        self._artifact_writer = ArtifactWriter(self.runs_dir)

    def run_step(
        self,
        aip: dict[str, Any],
        step_idx: int,
        dry_run: bool = False,
        max_iterations: int = 3,
        allow_dirty: bool = False,
        autogov_policy: dict[str, Any] | None = None,
        governance_context: dict[str, Any] | None = None,
        mode_override: str | None = None,
        run_dir: Path | None = None,
        sep: StepExecutionPlan | None = None,
    ) -> StepResult:
        """
        Execute a step through its full lifecycle.

        Args:
            aip: Parsed AIP document
            step_idx: Step index (0-based)
            dry_run: If True, stop after writing input bundle
            max_iterations: Maximum retry attempts
            allow_dirty: Allow execution with dirty working tree
            autogov_policy: Optional autogov policy for scope constraints
            governance_context: Optional autogov governance context for prompt/contract
            mode_override: Optional adapter mode override ('oneshot' or 'interactive')
            run_dir: Optional explicit run directory (must be under runs_dir)
            sep: Optional pre-built Step Execution Plan; if None, builds from contract

        Returns:
            StepResult with termination reason and artifacts
        """
        # Extract step info
        aip_id = aip.get("aip_id", "unknown")
        steps = aip.get("plan", [])

        # Validate step index - this is the only failure that can't produce artifacts
        if step_idx < 0 or step_idx >= len(steps):
            # Prefer a 1-based step ID for human readability.
            display_step_id = f"step-{step_idx + 1:03d}" if step_idx >= 0 else f"step-{step_idx:03d}"
            return StepResult(
                step_id=display_step_id,
                aip_id=aip_id,
                step_idx=step_idx,
                adapter_name=self.adapter_name,
                termination_reason=TerminationReason.FAIL_ADAPTER_PROTOCOL,
                error=f"Step index {step_idx} out of range (0-{len(steps) - 1})",
            )

        step = steps[step_idx]
        step_id = step.get("step_id") or step.get("id") or f"step-{step_idx + 1:03d}"

        # Create run directory early so we can write artifacts on ANY failure.
        # If provided, reuse caller-created run_dir to colocate artifacts (e.g., SEP) with execution.
        runs_root = self.runs_dir.resolve()
        if run_dir is not None:
            resolved_run_dir = run_dir
            if not resolved_run_dir.is_absolute():
                resolved_run_dir = (self.repo_root / resolved_run_dir)
            resolved_run_dir = resolved_run_dir.resolve()

            try:
                resolved_run_dir.relative_to(runs_root)
            except ValueError as e:
                raise ValueError(
                    f"run_dir must be under runs_dir ({runs_root}); got: {resolved_run_dir}"
                ) from e

            if resolved_run_dir.name != step_id:
                raise ValueError(
                    f"run_dir must end with step_id '{step_id}'; got: '{resolved_run_dir.name}'"
                )

            resolved_run_dir.mkdir(parents=True, exist_ok=True)
            run_dir = resolved_run_dir
        else:
            timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
            run_dir = self.runs_dir / aip_id / timestamp / step_id
            run_dir.mkdir(parents=True, exist_ok=True)

        artifacts_dir = str(run_dir.relative_to(self.runs_dir))

        # Helper to build result with common fields
        def make_result(
            reason: TerminationReason,
            error: str | None = None,
            baseline: str | None = None,
            **kwargs: Any,
        ) -> StepResult:
            return StepResult(
                step_id=step_id,
                aip_id=aip_id,
                step_idx=step_idx,
                baseline_sha=baseline,
                adapter_name=self.adapter_name,
                artifacts_dir=artifacts_dir,
                termination_reason=reason,
                error=error,
                **kwargs,
            )

        # Phase 1: Extract - check dirty state, build contract, write input bundle
        try:
            repo_state = self._get_repo_state()
        except subprocess.CalledProcessError as e:
            result = make_result(
                TerminationReason.FAIL_DIRTY_WORKTREE,
                error=f"Failed to get repo state: {e}",
            )
            return self._finalize_artifacts(result, run_dir)

        if repo_state.dirty and not allow_dirty:
            result = make_result(
                TerminationReason.FAIL_DIRTY_WORKTREE,
                error="Working tree is dirty. Use --allow-dirty to override.",
                baseline=repo_state.baseline,
            )
            return self._finalize_artifacts(result, run_dir)

        # Build contract
        try:
            contract = build_contract(aip, step_idx, autogov_policy, mode_override)
        except Exception as e:
            result = make_result(
                TerminationReason.ESCALATE_AMBIGUOUS,
                error=f"Failed to build contract: {e}",
                baseline=repo_state.baseline,
            )
            return self._finalize_artifacts(result, run_dir)

        # Add governance context to contract if available
        # This is separate from forbidden_paths - governance paths are guidance
        if governance_context:
            contract.governance = {
                "guidance": {
                    "forbidden_paths": governance_context.get("autogov_forbidden_paths", []),
                    "policy_name": governance_context.get("autogov_policy_name"),
                    "policy_version": governance_context.get("autogov_policy_version"),
                    "arch_decisions": governance_context.get("autogov_arch_decisions", []),
                    "policy_rules": governance_context.get("autogov_policy_rules", []),
                },
                "autogov": governance_context.get("autogov", {}),
            }

        # Write input bundle (always, even if we fail later)
        input_dir = run_dir / "input"
        output_dir = run_dir / "output"
        input_dir.mkdir(exist_ok=True)
        output_dir.mkdir(exist_ok=True)

        # Save contract
        save_contract(contract, input_dir / "contract.yaml")

        # Build or use provided SEP
        step_sep: StepExecutionPlan | None = sep
        if step_sep is None:
            try:
                step_sep = self.build_sep(aip, step_idx, contract)
            except Exception as e:
                result = make_result(
                    TerminationReason.ESCALATE_AMBIGUOUS,
                    error=f"Failed to build SEP: {e}",
                    baseline=repo_state.baseline,
                )
                return self._finalize_artifacts(result, run_dir)

        # Write SEP to canonical location: runs/<aip_id>/<timestamp>/step-N/sep.yaml
        save_sep(step_sep, run_dir / "sep.yaml")

        # Also write SEP to input bundle so adapter has access (optional use)
        save_sep(step_sep, input_dir / "sep.yaml")

        # Write prompt.md
        prompt_content = self._build_prompt(step, contract, governance_context)
        (input_dir / "prompt.md").write_text(prompt_content)

        # Write repo_state.json
        repo_state_dict = {
            "commit": repo_state.commit,
            "branch": repo_state.branch,
            "dirty": repo_state.dirty,
            "baseline": repo_state.baseline,
            "adapter": contract.adapter,
        }
        (input_dir / "repo_state.json").write_text(json.dumps(repo_state_dict, indent=2))

        # Dry run: stop here
        if dry_run:
            # Build a generic dry-run command showing input/output paths
            dry_run_cmd = f"claude --input {input_dir} --output {output_dir}"
            result = make_result(
                TerminationReason.PASS,
                baseline=repo_state.baseline,
                dry_run=True,
                dry_run_command=dry_run_cmd,
                sep=step_sep,
            )
            return self._finalize_artifacts(result, run_dir)

        # Phase 2: Loop - iterate until success or max iterations
        iterations: list[IterationResult] = []
        baseline = repo_state.baseline
        final_patch_path: Path | None = None
        touched_files: list[str] = []
        policy_report: dict[str, Any] | None = None
        verification_report: dict[str, Any] | None = None

        # Soft determinism: Skip git reset on iter-0 for Claude interactive mode
        # This allows Claude to work with the current repo state rather than
        # forcing a reset, which is useful for interactive/iterative workflows
        is_soft_determinism = (
            self.adapter_name == "claude"
            and contract.adapter.get("mode") == "interactive"
        )

        for iteration in range(max_iterations):
            # Reset to baseline before iteration (deterministic starting state)
            # Skip reset on iter-0 for soft determinism mode
            should_reset = True
            if iteration == 0 and is_soft_determinism:
                should_reset = False

            if should_reset:
                self._reset_to_baseline(baseline)

            iter_result = self._run_iteration(
                iteration=iteration,
                contract=contract,
                input_dir=input_dir,
                output_dir=output_dir,
                run_dir=run_dir,
                baseline=baseline,
                previous_iterations=iterations,
            )
            iterations.append(iter_result)

            # Check termination conditions
            if iter_result.termination_reason == TerminationReason.PASS:
                final_patch_path = iter_result.patch_path
                if iter_result.scope_result:
                    policy_report = generate_policy_report(iter_result.scope_result)
                if iter_result.verification_result:
                    verification_report = generate_verification_report(
                        iter_result.verification_result
                    )
                    touched_files, _ = self._get_touched_files(baseline)
                result = make_result(
                    TerminationReason.PASS,
                    baseline=baseline,
                    iterations=iterations,
                    final_patch_path=final_patch_path,
                    touched_files=touched_files,
                    policy_report=policy_report,
                    verification_report=verification_report,
                    sep=step_sep,
                )
                return self._finalize_artifacts(result, run_dir)

            # Non-retryable failures
            if iter_result.termination_reason in (
                TerminationReason.FAIL_SCOPE,
                TerminationReason.FAIL_PATCH_APPLY,
                TerminationReason.FAIL_ADAPTER_PROTOCOL,
                TerminationReason.ESCALATE_NEEDS_HUMAN,
                TerminationReason.ESCALATE_AMBIGUOUS,
            ):
                if iter_result.scope_result:
                    policy_report = generate_policy_report(iter_result.scope_result)
                touched_files, _ = self._get_touched_files(baseline)
                result = make_result(
                    iter_result.termination_reason,
                    error=iter_result.error,
                    baseline=baseline,
                    iterations=iterations,
                    touched_files=touched_files,
                    policy_report=policy_report,
                    sep=step_sep,
                )
                return self._finalize_artifacts(result, run_dir)

            # Retryable failure - continue if iterations remain
            # (baseline reset happens at loop start)

        # Max iterations exhausted
        if iterations:
            last_iter = iterations[-1]
            if last_iter.verification_result:
                verification_report = generate_verification_report(last_iter.verification_result)

        touched_files, _ = self._get_touched_files(baseline)
        result = make_result(
            TerminationReason.FAIL_VERIFY_RETRYABLE,
            error=f"Max iterations ({max_iterations}) exhausted",
            baseline=baseline,
            iterations=iterations,
            touched_files=touched_files,
            verification_report=verification_report,
            sep=step_sep,
        )
        return self._finalize_artifacts(result, run_dir)

    def _run_iteration(
        self,
        iteration: int,
        contract: StepContract,
        input_dir: Path,
        output_dir: Path,
        run_dir: Path,
        baseline: str,
        previous_iterations: list[IterationResult],
    ) -> IterationResult:
        """Run a single iteration of the step execution loop."""
        result = IterationResult(iteration=iteration)

        # Create iteration directory
        iter_dir = run_dir / f"iter-{iteration}"
        iter_dir.mkdir(exist_ok=True)
        iter_input_dir = iter_dir / "input"
        iter_output_dir = iter_dir / "output"
        iter_input_dir.mkdir(exist_ok=True)
        iter_output_dir.mkdir(exist_ok=True)

        # Helper to write stub artifacts on early failure
        def write_iteration_stubs(error: str, reason: str) -> None:
            """Write stub artifacts when adapter fails before producing outputs."""
            # Stub patch.diff (empty with reason)
            if not (iter_output_dir / "patch.diff").exists():
                (iter_output_dir / "patch.diff").write_text(f"# No patch produced - {reason}\n")
            # Stub agent.json
            if not (iter_output_dir / "agent.json").exists():
                stub_agent = {
                    "status": "failure",
                    "needs_human": False,
                    "notes": f"Adapter failed: {error}",
                }
                (iter_output_dir / "agent.json").write_text(json.dumps(stub_agent, indent=2))

        # Copy input bundle to iteration dir
        for src_file in input_dir.iterdir():
            if src_file.is_file():
                (iter_input_dir / src_file.name).write_bytes(src_file.read_bytes())

        # Write failure_context.json if retrying
        if iteration > 0 and previous_iterations:
            failure_context = self._build_failure_context(
                iteration, previous_iterations[-1], run_dir
            )
            (iter_input_dir / "failure_context.json").write_text(
                json.dumps(failure_context, indent=2)
            )

        # Invoke adapter
        try:
            self._adapter.execute(
                input_dir=iter_input_dir,
                output_dir=iter_output_dir,
                repo_root=self.repo_root,
            )
        except ToolNotFoundError as e:
            result.error = str(e)
            result.termination_reason = TerminationReason.FAIL_ADAPTER_PROTOCOL
            write_iteration_stubs(str(e), "tool_not_found")
            return result
        except EscalationRequired as e:
            result.error = str(e)
            result.termination_reason = TerminationReason.ESCALATE_NEEDS_HUMAN
            write_iteration_stubs(str(e), "escalation_required")
            return result
        except ProtocolError as e:
            result.error = str(e)
            result.termination_reason = TerminationReason.FAIL_ADAPTER_PROTOCOL
            write_iteration_stubs(str(e), "protocol_error")
            return result
        except AdapterError as e:
            result.error = str(e)
            result.termination_reason = TerminationReason.FAIL_ADAPTER_PROTOCOL
            write_iteration_stubs(str(e), "adapter_error")
            return result

        # Validate outputs exist
        patch_path = iter_output_dir / "patch.diff"
        agent_json_path = iter_output_dir / "agent.json"
        cmdlog_path = iter_output_dir / "cmdlog.txt"

        if not patch_path.exists():
            result.error = "Adapter did not produce patch.diff"
            result.termination_reason = TerminationReason.FAIL_ADAPTER_PROTOCOL
            return result

        if not agent_json_path.exists():
            result.error = "Adapter did not produce agent.json"
            result.termination_reason = TerminationReason.FAIL_ADAPTER_PROTOCOL
            return result

        result.patch_path = patch_path
        result.cmdlog_path = cmdlog_path if cmdlog_path.exists() else None

        # Load agent.json
        try:
            result.agent_json = json.loads(agent_json_path.read_text())
        except json.JSONDecodeError as e:
            result.error = f"Invalid agent.json: {e}"
            result.termination_reason = TerminationReason.FAIL_ADAPTER_PROTOCOL
            return result

        # Check if agent requests human review
        if result.agent_json.get("needs_human", False):
            result.error = "Agent requested human review"
            result.termination_reason = TerminationReason.ESCALATE_NEEDS_HUMAN
            return result

        # Apply patch
        patch_content = patch_path.read_text()
        if patch_content.strip():
            # Check patch applies cleanly
            check_result = subprocess.run(
                ["git", "apply", "--check", str(patch_path)],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if check_result.returncode != 0:
                result.error = f"Patch does not apply cleanly: {check_result.stderr}"
                result.termination_reason = TerminationReason.FAIL_PATCH_APPLY
                return result

            # Apply patch
            apply_result = subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if apply_result.returncode != 0:
                result.error = f"Failed to apply patch: {apply_result.stderr}"
                result.termination_reason = TerminationReason.FAIL_PATCH_APPLY
                return result

            result.patch_applied = True

        # Scope check (fail fast on violations)
        touched_files, touched_metadata = self._get_touched_files(baseline)
        scope_result = check_scope(touched_files, contract)
        result.scope_result = scope_result

        # Write policy report to iteration dir (with touched file breakdown)
        policy_report = generate_policy_report(scope_result, touched_metadata)
        (iter_dir / "policy_report.json").write_text(json.dumps(policy_report, indent=2))

        if not scope_result.passed:
            result.error = f"Scope violation: {scope_result.violations}"
            result.termination_reason = TerminationReason.FAIL_SCOPE
            return result

        # Verification
        verification_result = verify(
            contract.verification_commands,
            self.repo_root,
        )
        result.verification_result = verification_result

        # Write verification report to iteration dir
        verification_report = generate_verification_report(verification_result)
        (iter_dir / "verification_report.json").write_text(
            json.dumps(verification_report, indent=2)
        )

        if verification_result.passed:
            result.termination_reason = TerminationReason.PASS
        else:
            result.error = f"Verification failed: {verification_result.failure_category}"
            result.termination_reason = TerminationReason.FAIL_VERIFY_RETRYABLE

        return result

    def _get_repo_state(self) -> RepoState:
        """Get current repository state."""
        # Get current commit
        commit_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        commit = commit_result.stdout.strip()

        # Get current branch
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        branch = branch_result.stdout.strip()

        # Check if dirty
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        dirty = len(status_result.stdout.strip()) > 0

        return RepoState(
            commit=commit,
            branch=branch,
            dirty=dirty,
            baseline=commit,
        )

    def _get_touched_files(self, baseline: str) -> tuple[list[str], dict[str, int]]:
        """Get list of files changed since baseline, including new untracked files.

        This includes:
        1. Files modified/deleted since baseline (git diff --name-only)
        2. New untracked files (git ls-files --others --exclude-standard)

        Both are needed because git apply creates new files as untracked,
        which don't appear in git diff output.

        Files in runs_dir are excluded since they are executor artifacts,
        not code changes from the patch. The exclusion uses the exact configured
        runs_dir path (normalized), not a hardcoded pattern.

        Returns:
            Tuple of (sorted file list, metadata dict with counts)
        """
        tracked: set[str] = set()
        untracked: set[str] = set()

        # Get modified/deleted files since baseline (tracked changes)
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", baseline],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if diff_result.returncode == 0:
            tracked.update(f for f in diff_result.stdout.strip().split("\n") if f)

        # Get new untracked files (created by patch)
        untracked_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if untracked_result.returncode == 0:
            untracked.update(f for f in untracked_result.stdout.strip().split("\n") if f)

        # Combine tracked + untracked before filtering
        all_touched = tracked | untracked
        excluded_artifacts = 0

        # Filter out executor artifacts (runs_dir) - EXACT path match only
        # Uses the configured runs_dir, not a hardcoded pattern
        try:
            runs_rel = self.runs_dir.relative_to(self.repo_root)
            runs_prefix = str(runs_rel) + "/"
            before_filter = len(all_touched)
            all_touched = {f for f in all_touched if not f.startswith(runs_prefix)}
            excluded_artifacts = before_filter - len(all_touched)
        except ValueError:
            # runs_dir is outside repo_root, no filtering needed
            pass

        # Build metadata for policy report
        metadata = {
            "touched_total": len(all_touched),
            "touched_tracked": len(tracked - untracked),  # Only in tracked
            "touched_untracked": len(untracked),
            "touched_excluded_artifacts": excluded_artifacts,
        }

        return sorted(all_touched), metadata

    def _reset_to_baseline(self, baseline: str) -> None:
        """Reset working tree to baseline commit."""
        subprocess.run(
            ["git", "reset", "--hard", baseline],
            cwd=self.repo_root,
            capture_output=True,
            check=True,
        )

    def _finalize_artifacts(self, result: StepResult, run_dir: Path) -> StepResult:
        """
        Write final artifacts (result.json, gate.md, final reports, step.summary.json, patch.diff).

        This method is called for ALL termination paths (success, failure, escalation,
        protocol error) to ensure artifacts are always written for debugging/audit.

        Args:
            result: Step execution result
            run_dir: Path to the step run directory

        Returns:
            The same result (for chaining)
        """
        # Materialize a staged diff snapshot to patch.diff (always write, even if empty).
        # We must not mutate the user's real index, so we use a temporary GIT_INDEX_FILE.
        patch_content = self._materialize_cached_diff_snapshot() or ""
        (run_dir / "patch.diff").write_text(patch_content)

        # Write result.json
        self._artifact_writer.write_result(run_dir, result)

        # Write gate.md
        gate_content = render_gate_package(result, run_dir)
        self._artifact_writer.write_gate_package(run_dir, gate_content)

        # Write final reports to step root
        self._artifact_writer.write_final_reports(
            run_dir, result.policy_report, result.verification_report
        )

        # Write step.summary.json (always, even on failure/escalation)
        # This provides a quick-reference summary for downstream tooling
        summary = {
            "step_id": result.step_id,
            "aip_id": result.aip_id,
            "termination_reason": result.termination_reason.value,
            "iterations_attempted": len(result.iterations),
            "passed": result.termination_reason == TerminationReason.PASS,
            "error": result.error,
            "touched_files_count": len(result.touched_files),
            "adapter_name": result.adapter_name,
            "artifacts_dir": result.artifacts_dir,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        (run_dir / "step.summary.json").write_text(json.dumps(summary, indent=2))

        return result

    def _materialize_cached_diff_snapshot(self) -> str | None:
        """Return `git diff --cached` for the current working tree without touching the real index.

        Implementation detail:
        - Copies .git/index to a temp location
        - Runs `git add -A` against the temp index
        - Runs `git diff --cached` against the temp index

        Returns None on failure (caller should treat as empty diff).
        """

        git_index = self.repo_root / ".git" / "index"
        if not git_index.exists():
            return None

        try:
            with tempfile.TemporaryDirectory(prefix="specwright-index-") as tmpdir:
                tmp_index = Path(tmpdir) / "index"
                shutil.copy2(git_index, tmp_index)

                env = os.environ.copy()
                env["GIT_INDEX_FILE"] = str(tmp_index)

                # Stage everything into the temp index (including untracked files).
                add_result = subprocess.run(
                    ["git", "add", "-A"],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                if add_result.returncode != 0:
                    return None

                diff_result = subprocess.run(
                    ["git", "diff", "--cached"],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                if diff_result.returncode != 0:
                    return None
                return diff_result.stdout
        except Exception:
            return None

    def _build_prompt(
        self,
        step: dict[str, Any],
        contract: StepContract,
        governance_context: dict[str, Any] | None = None,
    ) -> str:
        """Build the prompt for the agent.

        If governance_context is provided, the prompt begins with a
        deterministic governance header: === GOVERNANCE (AUTOGOV) ===
        """
        prompt_parts: list[str] = []

        # Prepend governance header if available
        if governance_context:
            policy_name = governance_context.get("autogov_policy_name", "unknown")
            policy_version = governance_context.get("autogov_policy_version", "0.0.0")
            prompt_parts.extend([
                "=== GOVERNANCE (AUTOGOV) ===",
                f"Policy: {policy_name} v{policy_version}",
                "",
            ])

            # Add governance guidance section
            arch_decisions = governance_context.get("autogov_arch_decisions", [])
            policy_rules = governance_context.get("autogov_policy_rules", [])
            forbidden_paths = governance_context.get("autogov_forbidden_paths", [])

            if arch_decisions:
                prompt_parts.append("### Architecture Decisions")
                for decision in arch_decisions:
                    line = f"- **{decision.get('id', 'ADR')}**: {decision.get('title', '')}"
                    if decision.get('summary'):
                        line += f" - {decision['summary']}"
                    prompt_parts.append(line)
                prompt_parts.append("")

            if policy_rules:
                prompt_parts.append("### Policy Rules")
                for rule in policy_rules:
                    line = f"- **{rule.get('id', 'RULE')}**: {rule.get('name', '')}"
                    if rule.get('description'):
                        line += f" - {rule['description']}"
                    prompt_parts.append(line)
                prompt_parts.append("")

            if forbidden_paths:
                prompt_parts.append("### Governance Forbidden Paths (advisory)")
                for fp in forbidden_paths:
                    prompt_parts.append(f"- `{fp.get('path', '')}` - {fp.get('reason', '')}")
                prompt_parts.append("")

            prompt_parts.append("---")
            prompt_parts.append("")

        step_id = step.get("step_id") or step.get("id", "unknown")
        # Support both 'prompt' and 'description' fields for step objective
        prompt_text = step.get("prompt") or step.get("description", "No prompt provided.")
        prompt_parts.extend([
            f"# Step: {step_id}",
            "",
            "## Objective",
            prompt_text,
            "",
            "## Scope Constraints",
            "",
            "### Allowed Paths",
        ])

        for path in contract.allowed_paths:
            prompt_parts.append(f"- `{path}`")

        prompt_parts.extend(
            [
                "",
                "### Forbidden Paths",
            ]
        )

        for path in contract.forbidden_paths:
            prompt_parts.append(f"- `{path}`")

        prompt_parts.extend(
            [
                "",
                "## Verification Commands",
                "",
                "Your changes will be verified by running:",
                "",
            ]
        )

        for cmd in contract.verification_commands:
            prompt_parts.append(f"```bash\n{cmd}\n```")

        prompt_parts.extend(
            [
                "",
                "## Output Requirements",
                "",
                "Your final output MUST be valid JSON matching the provided schema.",
                "`patch_diff` MUST be a unified diff against the current baseline.",
                "",
            ]
        )

        return "\n".join(prompt_parts)

    def build_sep(
        self,
        aip: dict[str, Any],
        step_idx: int,
        contract: StepContract,
    ) -> StepExecutionPlan:
        """Build SEP for the step.

        This is a convenience method that wraps SEPBuilder.build().
        Use this when you need to build a SEP outside the run_step flow.

        Args:
            aip: The parsed AIP dictionary
            step_idx: Zero-based index of the step
            contract: The StepContract for this step

        Returns:
            StepExecutionPlan ready for review
        """
        builder = SEPBuilder()
        return builder.build(aip, step_idx, contract)

    def _build_failure_context(
        self,
        iteration: int,
        previous_result: IterationResult,
        run_dir: Path,
    ) -> dict[str, Any]:
        """Build failure context for retry iteration."""
        context: dict[str, Any] = {
            "iteration": iteration,
            "failure_category": "verify_fail",
            "failed_commands": [],
        }

        if previous_result.verification_result:
            context["failure_category"] = (
                previous_result.verification_result.failure_category or "verify_fail"
            )
            for cmd_result in previous_result.verification_result.commands:
                if not cmd_result.success:
                    context["failed_commands"].append(
                        {
                            "command": cmd_result.command,
                            "exit_code": cmd_result.exit_code,
                            "stderr_tail": cmd_result.stderr[-500:] if cmd_result.stderr else "",
                        }
                    )

        if previous_result.patch_path:
            context["previous_patch_path"] = str(previous_result.patch_path.relative_to(run_dir))

        prev_iter_dir = run_dir / f"iter-{iteration - 1}"
        prev_report = prev_iter_dir / "verification_report.json"
        if prev_report.exists():
            context["previous_verification_report_path"] = str(prev_report.relative_to(run_dir))

        return context


def render_gate_package(result: StepResult, run_dir: Path) -> str:
    """
    Render the gate package as markdown for human review.

    Args:
        result: Step execution result
        run_dir: Directory containing run artifacts

    Returns:
        Markdown string for gate presentation
    """
    lines = [
        f"# Gate Review: {result.step_id}",
        "",
        f"**AIP:** {result.aip_id}",
        f"**Termination Reason:** `{result.termination_reason.value}`",
        f"**Iterations:** {len(result.iterations)}",
        "",
    ]

    # Include SEP summary if available
    if result.sep:
        lines.extend(
            [
                "## Step Execution Plan (SEP)",
                "",
                f"**Objective:** {result.sep.objective}",
                f"**Complexity:** {result.sep.estimated_complexity}",
                f"**Files to Touch:** {len(result.sep.files_to_touch)}",
                "",
            ]
        )
        if result.sep.files_to_touch:
            lines.append("### Planned Files")
            lines.append("")
            for fc in result.sep.files_to_touch:
                lines.append(f"- `{fc.path}` ({fc.action}): {fc.description}")
            lines.append("")
        if result.sep.requires_human_review:
            lines.append("**⚠️ Human Review Recommended**")
            lines.append("")

    if result.error:
        lines.extend(
            [
                "## Error",
                "",
                f"```\n{result.error}\n```",
                "",
            ]
        )

    if result.dry_run:
        lines.extend(
            [
                "## Dry Run",
                "",
                "Execution was stopped after writing input bundle.",
                "",
                "### Command",
                "",
                f"```bash\n{result.dry_run_command}\n```",
                "",
            ]
        )
        return "\n".join(lines)

    if result.touched_files:
        lines.extend(
            [
                "## Touched Files",
                "",
            ]
        )
        for f in result.touched_files:
            lines.append(f"- `{f}`")
        lines.append("")

    if result.final_patch_path and result.final_patch_path.exists():
        patch_content = result.final_patch_path.read_text()
        # Truncate if huge
        if len(patch_content) > 10000:
            patch_content = patch_content[:10000] + "\n... (truncated)"
        lines.extend(
            [
                "## Final Patch",
                "",
                f"```diff\n{patch_content}\n```",
                "",
            ]
        )

    if result.verification_report:
        lines.extend(
            [
                "## Verification Summary",
                "",
                f"**Passed:** {result.verification_report.get('passed', False)}",
                "",
            ]
        )

    if result.policy_report:
        lines.extend(
            [
                "## Policy Report",
                "",
                f"**Passed:** {result.policy_report.get('passed', False)}",
                "",
            ]
        )
        if result.policy_report.get("violations"):
            lines.append("### Violations")
            lines.append("")
            for v in result.policy_report["violations"]:
                lines.append(f"- `{v.get('file', 'unknown')}`: {v.get('reason', '')}")
            lines.append("")

    lines.extend(
        [
            "---",
            "",
            "**Approve / Reject / Defer**",
        ]
    )

    return "\n".join(lines)
