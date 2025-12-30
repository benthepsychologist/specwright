"""
SEP Builder

Materializes Step Execution Plans (SEPs) from AIP steps.
This is deterministic - no LLM calls. It parses the step prompt
to extract file references and builds a reviewable execution plan.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from typing import Any

from spec.executor.contract import StepContract
from spec.executor.sep import FileChange, StepExecutionPlan, VerificationStep


class SEPBuilder:
    """
    Builder for Step Execution Plans.

    Materializes SEPs from AIP steps deterministically by parsing
    prompts to extract file references and actions.
    """

    # Patterns to match file references in prompts
    # Format: "Action `path/to/file.py`" -> (action_type, path)
    FILE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        ("create", re.compile(r"Create\s+`([^`]+)`", re.IGNORECASE)),
        ("modify", re.compile(r"Update\s+`([^`]+)`", re.IGNORECASE)),
        ("modify", re.compile(r"Modify\s+`([^`]+)`", re.IGNORECASE)),
        ("delete", re.compile(r"Delete\s+`([^`]+)`", re.IGNORECASE)),
        ("modify", re.compile(r"Add\s+to\s+`([^`]+)`", re.IGNORECASE)),
    ]

    _ACTION_PRIORITY: dict[str, int] = {"delete": 3, "modify": 2, "create": 1}

    def build(
        self,
        aip: dict[str, Any],
        step_idx: int,
        contract: StepContract,
    ) -> StepExecutionPlan:
        """
        Build a Step Execution Plan from AIP step and contract.

        This is deterministic - no LLM calls. It parses the step prompt
        to extract:
        - Files mentioned (Create `path`, Update `path`, etc.)
        - Actions per file (create, modify, delete)
        - Verification commands from contract

        Returns a SEP that can be reviewed before execution.

        Args:
            aip: The parsed AIP dictionary
            step_idx: Zero-based index of the step
            contract: The StepContract for this step

        Returns:
            StepExecutionPlan ready for review
        """
        plan = aip.get("plan", [])
        if not isinstance(plan, list):
            raise ValueError("AIP 'plan' must be a list")
        if step_idx < 0 or step_idx >= len(plan):
            raise ValueError(
                f"step_idx out of range: {step_idx} (plan has {len(plan)} steps)"
            )

        step = plan[step_idx]
        if not isinstance(step, dict):
            raise ValueError(f"AIP plan entries must be mappings, got {type(step).__name__}")

        # Extract the prompt/objective from the step
        prompt = step.get("prompt", "") or step.get("objective", "") or ""
        prompt = str(prompt) if prompt is not None else ""
        objective = self._summarize_objective(prompt)

        # Extract file changes from the prompt
        files = self._extract_files_from_prompt(prompt)

        # Build verification steps from contract
        verification_steps = [
            VerificationStep(
                command=cmd,
                expected_outcome="Command exits successfully with code 0",
                required=True,
            )
            for cmd in contract.verification_commands
        ]

        # Estimate complexity
        complexity = self._estimate_complexity(files)

        # Check if human review is recommended
        requires_review = self._check_sensitive_paths(files, contract.forbidden_paths)

        step_number = step_idx + 1
        # Guardrail: contract should also be 1-based.
        if getattr(contract, "step_index", step_number) != step_number:
            raise ValueError(
                f"Contract step_index mismatch: contract={contract.step_index} expected={step_number}"
            )

        return StepExecutionPlan(
            aip_id=contract.aip_id,
            step_id=contract.step_id,
            step_index=step_number,
            objective=objective,
            files_to_touch=files,
            verification_steps=verification_steps,
            allowed_paths=contract.allowed_paths,
            forbidden_paths=contract.forbidden_paths,
            estimated_complexity=complexity,
            requires_human_review=requires_review,
        )

    def _summarize_objective(self, prompt: str) -> str:
        """Deterministically summarize a step prompt into a short objective."""
        text = " ".join((prompt or "").strip().split())
        if not text:
            return ""

        # Prefer first sentence if it looks reasonable.
        match = re.match(r"^(.+?[.!?])(\s+|$)", text)
        summary = match.group(1) if match else text
        max_len = 200
        if len(summary) > max_len:
            summary = summary[: max_len - 1].rstrip() + "…"
        return summary

    def _extract_files_from_prompt(self, prompt: str) -> list[FileChange]:
        """
        Parse prompt to find file references.

        Matches patterns like:
        - "Create `path/to/file.py`" -> create
        - "Update `path/to/file.py`" -> modify
        - "Modify `path/to/file.py`" -> modify
        - "Delete `path/to/file.py`" -> delete
        - "Add to `path/to/file.py`" -> modify

        Args:
            prompt: The step prompt text to parse

        Returns:
            List of FileChange objects describing planned modifications
        """
        prompt = prompt or ""
        matches: list[tuple[int, str, str]] = []  # (start, action, path)
        for action, pattern in self.FILE_PATTERNS:
            for match in pattern.finditer(prompt):
                path = (match.group(1) or "").strip()
                if not path:
                    continue
                matches.append((match.start(), action, path))

        matches.sort(key=lambda t: t[0])

        # Preserve first-seen order, but allow action upgrades deterministically.
        by_path: dict[str, FileChange] = {}
        order: list[str] = []

        for _pos, action, path in matches:
            if path not in by_path:
                order.append(path)
                by_path[path] = FileChange(
                    path=path,
                    action=action,
                    description=self._describe_change(action, path),
                )
                continue

            existing = by_path[path]
            if self._ACTION_PRIORITY.get(action, 0) >= self._ACTION_PRIORITY.get(
                existing.action, 0
            ):
                existing.action = action
                existing.description = self._describe_change(action, path)

        return [by_path[p] for p in order]

    def _describe_change(self, action: str, path: str) -> str:
        if action == "create":
            return f"Create new file: {path}"
        if action == "modify":
            return f"Modify existing file: {path}"
        if action == "delete":
            return f"Delete file: {path}"
        return f"{action.capitalize()} file: {path}"

    def _estimate_complexity(self, files: list[FileChange]) -> str:
        """
        Estimate complexity based on number of files and actions.

        Args:
            files: List of planned file changes

        Returns:
            Complexity level: "low", "medium", or "high"
        """
        num_files = len(files)

        # Count different action types
        creates = sum(1 for f in files if f.action == "create")
        deletes = sum(1 for f in files if f.action == "delete")

        # High complexity: many files or any deletes
        if num_files > 5 or deletes > 0:
            return "high"

        # Medium complexity: multiple files or multiple creates
        if num_files > 2 or creates > 1:
            return "medium"

        # Low complexity: few files, simple operations
        return "low"

    def _check_sensitive_paths(
        self,
        files: list[FileChange],
        forbidden: list[str],
    ) -> bool:
        """
        Return True if human review is recommended.

        Checks if any planned file changes match or are close to
        forbidden path patterns.

        Args:
            files: List of planned file changes
            forbidden: List of forbidden path patterns (glob patterns)

        Returns:
            True if human review is recommended
        """
        for file_change in files:
            path = file_change.path

            for pattern in forbidden:
                # Direct match against forbidden pattern
                if fnmatch(path, pattern):
                    return True

                # Prefix patterns like '.env*' should flag close matches deterministically.
                if self._is_simple_prefix_pattern(pattern):
                    prefix = pattern[:-1]
                    if prefix and path.startswith(prefix):
                        return True

        return False

    def _is_simple_prefix_pattern(self, pattern: str) -> bool:
        # Treat only trailing-star patterns without path separators as prefixes.
        # Example: '.env*' -> prefix match, but '.git/**' should NOT.
        if not pattern.endswith("*"):
            return False
        if "/" in pattern:
            return False
        # Only allow a single trailing '*', no other glob metacharacters.
        core = pattern[:-1]
        if any(ch in core for ch in ["*", "?", "[", "]"]):
            return False
        return True
