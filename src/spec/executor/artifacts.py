"""
Artifact Writer

Manages the artifact directory structure and file writing for step execution runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spec.executor.runner import StepResult


class ArtifactWriter:
    """
    Writes execution artifacts to the standardized directory structure.

    Directory layout:
        runs/
          <aip_id>/
            <timestamp>/
              step-N/
                input/
                  contract.yaml
                  prompt.md
                  repo_state.json
                output/
                iter-0/
                  input/
                  output/
                  policy_report.json
                  verification_report.json
                policy_report.json      # final
                verification_report.json # final
                gate.md
                result.json
    """

    def __init__(self, runs_dir: Path) -> None:
        """
        Initialize the artifact writer.

        Args:
            runs_dir: Root directory for all run artifacts (e.g., repo_root/runs)
        """
        self.runs_dir = runs_dir.resolve()

    def create_run_dir(self, aip_id: str, step_id: str) -> Path:
        """
        Create a timestamped run directory for a step.

        Args:
            aip_id: AIP identifier
            step_id: Step identifier (e.g., step-003)

        Returns:
            Path to the created run directory
        """
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        run_dir = self.runs_dir / aip_id / timestamp / step_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def write_result(self, run_dir: Path, result: StepResult) -> Path:
        """
        Write the final result.json file.

        Args:
            run_dir: Path to the step run directory
            result: Step execution result

        Returns:
            Path to the written result.json
        """
        result_dict = self._result_to_dict(result)
        result_path = run_dir / "result.json"
        result_path.write_text(json.dumps(result_dict, indent=2, default=str))
        return result_path

    def write_gate_package(self, run_dir: Path, gate_content: str) -> Path:
        """
        Write the gate.md file for human review.

        Args:
            run_dir: Path to the step run directory
            gate_content: Rendered gate package markdown

        Returns:
            Path to the written gate.md
        """
        gate_path = run_dir / "gate.md"
        gate_path.write_text(gate_content)
        return gate_path

    def write_final_reports(
        self,
        run_dir: Path,
        policy_report: dict[str, Any] | None,
        verification_report: dict[str, Any] | None,
    ) -> None:
        """
        Write the final policy and verification reports to step root.

        These are the authoritative final reports (vs per-iteration reports).

        Args:
            run_dir: Path to the step run directory
            policy_report: Final policy report (or None)
            verification_report: Final verification report (or None)
        """
        if policy_report is not None:
            (run_dir / "policy_report.json").write_text(json.dumps(policy_report, indent=2))
        if verification_report is not None:
            (run_dir / "verification_report.json").write_text(
                json.dumps(verification_report, indent=2)
            )

    def _result_to_dict(self, result: StepResult) -> dict[str, Any]:
        """Convert StepResult to a JSON-serializable dict."""
        # Build details dict for failure context
        details: dict[str, Any] = {}
        if result.error:
            details["error_message"] = result.error
        if result.verification_report:
            details["failure_category"] = result.verification_report.get("failure_category")
        if result.policy_report and not result.policy_report.get("passed", True):
            details["failure_category"] = "scope_violation"

        return {
            # Required identifiers
            "aip_id": result.aip_id,
            "step_idx": result.step_idx,
            "step_id": result.step_id,
            # Execution context
            "baseline_sha": result.baseline_sha,
            "adapter_name": result.adapter_name,
            # Result
            "termination_reason": result.termination_reason.value,
            "iterations_attempted": len(result.iterations),
            # Artifact paths
            "artifacts_dir": result.artifacts_dir,
            "final_patch_path": str(result.final_patch_path) if result.final_patch_path else None,
            # Files touched
            "touched_files": result.touched_files,
            # Details (when applicable)
            "details": details if details else None,
            # Meta
            "dry_run": result.dry_run,
            "timestamp": datetime.now(UTC).isoformat(),
        }


def create_artifact_writer(runs_dir: Path) -> ArtifactWriter:
    """Factory function to create an ArtifactWriter."""
    return ArtifactWriter(runs_dir)


def write_input_bundle(
    input_dir: Path,
    contract_yaml: str,
    prompt_content: str,
    repo_state: dict[str, Any],
) -> None:
    """
    Write the input bundle files.

    Args:
        input_dir: Path to the input directory
        contract_yaml: Serialized contract YAML
        prompt_content: Step prompt content
        repo_state: Repository state dict
    """
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "contract.yaml").write_text(contract_yaml)
    (input_dir / "prompt.md").write_text(prompt_content)
    (input_dir / "repo_state.json").write_text(json.dumps(repo_state, indent=2))


def write_failure_context(
    input_dir: Path,
    iteration: int,
    failure_category: str,
    failed_commands: list[dict[str, Any]],
    previous_patch_path: str | None = None,
    previous_verification_report_path: str | None = None,
) -> None:
    """
    Write failure_context.json for retry iterations.

    Args:
        input_dir: Path to the iteration input directory
        iteration: Current iteration number
        failure_category: Category of previous failure
        failed_commands: List of failed command info dicts
        previous_patch_path: Relative path to previous patch
        previous_verification_report_path: Relative path to previous verification report
    """
    context: dict[str, Any] = {
        "iteration": iteration,
        "failure_category": failure_category,
        "failed_commands": failed_commands,
    }
    if previous_patch_path:
        context["previous_patch_path"] = previous_patch_path
    if previous_verification_report_path:
        context["previous_verification_report_path"] = previous_verification_report_path

    (input_dir / "failure_context.json").write_text(json.dumps(context, indent=2))
