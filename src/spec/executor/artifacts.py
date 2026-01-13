"""
Artifact Writer

Manages the artifact directory structure and file writing for step execution runs.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spec.executor.runner import StepResult


def get_artifact_root(
    project_slug: str | None = None,
    governor_path: Path | None = None,
    override_path: Path | None = None,
    project_root: Path | None = None,
) -> Path:
    """
    Resolve the artifact root directory for step execution runs.

    Resolution order:
    1. If override_path is provided, use it directly (for tests/CI)
    2. If project_slug is provided, use local-governor:
       ~/.local/local-governor/projects/<project_slug>/runs/
    3. Otherwise, fall back to repo-local: <project_root>/.specwright/runs/

    Args:
        project_slug: Project identifier from .specwright.yaml
        governor_path: Path to local-governor root (default: ~/.local/local-governor)
        override_path: Explicit override for tests/CI (takes precedence over all else)
        project_root: Project root directory (for fallback to repo-local path)

    Returns:
        Resolved artifact root path (created if needed)

    Raises:
        ValueError: If neither project_slug nor project_root is provided (and no override)
    """
    if override_path is not None:
        artifact_root = override_path.expanduser().resolve()
        artifact_root.mkdir(parents=True, exist_ok=True)
        return artifact_root

    # Use local-governor if project_slug is available
    if project_slug is not None:
        if governor_path is None:
            governor_path = Path("~/.local/local-governor").expanduser()

        artifact_root = governor_path / "projects" / project_slug / "runs"
        artifact_root.mkdir(parents=True, exist_ok=True)
        return artifact_root

    # Fall back to repo-local path (legacy behavior)
    if project_root is None:
        raise ValueError(
            "Either project_slug or project_root is required when artifact root "
            "is not explicitly overridden"
        )

    artifact_root = project_root / ".specwright" / "runs"
    artifact_root.mkdir(parents=True, exist_ok=True)
    return artifact_root


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    if not path.exists():
        return ""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def parse_diff_stats(diff_content: str) -> dict[str, Any]:
    """
    Parse unified diff to extract file list and insertion/deletion counts.

    Returns:
        dict with keys: files_changed, insertions, deletions, files, parse_error
    """
    if not diff_content or not diff_content.strip():
        return {
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
            "files": [],
            "parse_error": None,
        }

    try:
        files: list[str] = []
        insertions = 0
        deletions = 0

        # Match "diff --git a/... b/..." lines to extract file paths
        diff_header_pattern = re.compile(r"^diff --git a/(.*?) b/(.*)$", re.MULTILINE)
        for match in diff_header_pattern.finditer(diff_content):
            # Use the b/ path (destination) as the canonical path
            file_path = match.group(2)
            if file_path not in files:
                files.append(file_path)

        # Count insertions and deletions from hunk lines
        for line in diff_content.splitlines():
            # Skip header lines (---, +++, diff, index, etc.)
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("diff ") or line.startswith("index "):
                continue
            if line.startswith("@@ "):
                continue
            if line.startswith("\\ No newline"):
                continue
            # Count + and - lines
            if line.startswith("+"):
                insertions += 1
            elif line.startswith("-"):
                deletions += 1

        return {
            "files_changed": len(files),
            "insertions": insertions,
            "deletions": deletions,
            "files": sorted(files),
            "parse_error": None,
        }
    except Exception as e:
        return {
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
            "files": [],
            "parse_error": str(e),
        }


def write_step_summary(
    run_dir: Path,
    result: "StepResult",
    contract_path: Path | None = None,
    prompt_path: Path | None = None,
    sep_path: Path | None = None,
    patch_path: Path | None = None,
    llm_verification: dict | None = None,
) -> Path:
    """
    Write step_summary.yaml with execution metadata and patch evaluation.

    Args:
        run_dir: Path to the step run directory
        result: StepResult from execution
        contract_path: Path to contract.yaml (auto-discovered if None)
        prompt_path: Path to prompt.md (auto-discovered if None)
        sep_path: Path to sep.yaml (auto-discovered if None)
        patch_path: Path to patch.diff (auto-discovered if None)
        llm_verification: Optional dict with LLM verification result:
            {status: "pass"|"fail"|"skipped", rationale: str, model: str}

    Returns:
        Path to written step_summary.yaml
    """
    # Auto-discover paths if not provided
    if contract_path is None:
        contract_path = run_dir / "input" / "contract.yaml"
    if prompt_path is None:
        prompt_path = run_dir / "input" / "prompt.md"
    if sep_path is None:
        sep_path = run_dir / "sep.yaml"
    if patch_path is None:
        patch_path = run_dir / "patch.diff"

    def _safe_rel(path: Path) -> str:
        try:
            return str(path.relative_to(run_dir))
        except Exception:
            return str(path)

    def _load_yaml(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            from ruamel.yaml import YAML

            yaml = YAML(typ="safe")
            with open(path, "r") as f:
                loaded = yaml.load(f)
            return loaded if isinstance(loaded, dict) else None
        except Exception:
            return None

    def _read_text_preview(path: Path, limit_chars: int) -> str | None:
        if not path.exists():
            return None
        try:
            text = path.read_text()
            if len(text) <= limit_chars:
                return text
            return text[:limit_chars] + "\n\n[...truncated...]\n"
        except Exception:
            return None

    # Build inputs section with hashes + safe previews/outlines
    inputs: dict[str, Any] = {}

    if prompt_path.exists():
        inputs["prompt"] = {
            "path": _safe_rel(prompt_path),
            "sha256": compute_file_hash(prompt_path),
            "size_bytes": prompt_path.stat().st_size,
            # Outline the prompt without requiring full reproduction.
            # This is a short preview only (use the file itself for full content).
            "preview": _read_text_preview(prompt_path, limit_chars=2000),
        }

    if sep_path.exists():
        inputs["sep"] = {
            "path": _safe_rel(sep_path),
            "sha256": compute_file_hash(sep_path),
            "size_bytes": sep_path.stat().st_size,
            # Outline key SEP fields for auditability.
            "outline": None,
        }

        sep_data = _load_yaml(sep_path)
        if sep_data:
            files_to_touch = sep_data.get("files_to_touch")
            verification_steps = sep_data.get("verification_steps")
            inputs["sep"]["outline"] = {
                "objective": sep_data.get("objective"),
                "files_to_touch": files_to_touch if isinstance(files_to_touch, list) else None,
                "verification_steps": (
                    verification_steps if isinstance(verification_steps, list) else None
                ),
                "allowed_paths": sep_data.get("allowed_paths"),
                "forbidden_paths": sep_data.get("forbidden_paths"),
            }

    if contract_path.exists():
        inputs["contract"] = {
            "path": _safe_rel(contract_path),
            "sha256": compute_file_hash(contract_path),
            "size_bytes": contract_path.stat().st_size,
            "outline": None,
        }

        contract_data = _load_yaml(contract_path)
        if contract_data:
            inputs["contract"]["outline"] = {
                "step_id": contract_data.get("step_id"),
                "allowed_paths": contract_data.get("allowed_paths"),
                "forbidden_paths": contract_data.get("forbidden_paths"),
                "verification_commands": contract_data.get("verification_commands"),
            }

    # Build patch evaluation (metadata only, no content)
    patch_eval: dict[str, Any] = {}
    if patch_path.exists():
        patch_content = patch_path.read_text()
        diff_stats = parse_diff_stats(patch_content)
        patch_eval = {
            "path": _safe_rel(patch_path),
            "sha256": compute_file_hash(patch_path),
            "size_bytes": patch_path.stat().st_size,
            "files_changed": diff_stats["files_changed"],
            "insertions": diff_stats["insertions"],
            "deletions": diff_stats["deletions"],
            "files": diff_stats["files"],
        }
        if diff_stats.get("parse_error"):
            patch_eval["parse_error"] = diff_stats["parse_error"]
    else:
        patch_eval = {
            "path": None,
            "sha256": None,
            "size_bytes": 0,
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
            "files": [],
        }

    # Build iteration summaries
    iteration_summaries = []
    for iter_result in result.iterations:
        iter_summary = {
            "iteration": iter_result.iteration,
            "patch_applied": iter_result.patch_applied,
            "scope_passed": (
                iter_result.scope_result.passed if iter_result.scope_result else None
            ),
            "verify_passed": (
                iter_result.verification_result.passed
                if iter_result.verification_result
                else None
            ),
            "error": iter_result.error,
        }
        iteration_summaries.append(iter_summary)

    # Build verification summary
    verification_summary: dict[str, Any] = {}
    if result.verification_report:
        verification_summary = {
            "passed": result.verification_report.get("passed", False),
            "commands_run": len(result.verification_report.get("commands", [])),
            "report_path": "verification_report.json",
        }
        commands = result.verification_report.get("commands")
        if isinstance(commands, list):
            verification_summary["commands"] = [
                {
                    "command": c.get("command"),
                    "exit_code": c.get("exit_code"),
                    "passed": c.get("passed"),
                }
                for c in commands[:50]
                if isinstance(c, dict)
            ]

    # Build scope summary
    scope_summary: dict[str, Any] = {}
    if result.policy_report:
        scope_summary = {
            "passed": result.policy_report.get("passed", True),
            "report_path": "policy_report.json",
        }
        violations = result.policy_report.get("violations", [])
        if violations:
            scope_summary["violation_count"] = len(violations)
            if isinstance(violations, list):
                scope_summary["violations"] = violations[:50]

    # Assemble full summary
    summary: dict[str, Any] = {
        # Identity
        "aip_id": result.aip_id,
        "step_id": result.step_id,
        "step_index": result.step_idx,
        "adapter_name": result.adapter_name,
        # Outcome
        "status": result.termination_reason.value,
        "passed": result.termination_reason.value == "PASS",
        "iterations_attempted": len(result.iterations),
        "touched_files": sorted(result.touched_files),
        # LLM verification (if performed)
        "llm_verification": llm_verification,
        # Inputs (hashes + safe previews/outlines)
        "inputs": inputs,
        # Patch evaluation (metadata only; never includes diff body)
        "patch_evaluation": patch_eval,
        # What happened
        "iterations": iteration_summaries,
        "verification": verification_summary,
        "scope": scope_summary,
        # Error info
        "error": result.error,
    }

    # Write as YAML for readability
    summary_path = run_dir / "step_summary.yaml"
    try:
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.default_flow_style = False
        with open(summary_path, "w") as f:
            yaml.dump(summary, f)
    except ImportError:
        # Fallback to JSON if ruamel.yaml unavailable
        summary_path = run_dir / "step_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, default=str))

    return summary_path


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
