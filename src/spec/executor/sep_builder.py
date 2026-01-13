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

import yaml

from spec.executor.contract import StepContract
from spec.executor.sep import (
    FileChange,
    SEPProvenance,
    SepValidationError,
    StepExecutionPlan,
    VerificationStep,
)


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
            provenance=SEPProvenance(generator="deterministic"),
        )

    def build_with_llm(
        self,
        aip: dict[str, Any],
        step_idx: int,
        contract: StepContract,
        model: str,
    ) -> StepExecutionPlan:
        """
        Build a Step Execution Plan using LLM.

        Uses LLM to generate a richer SEP based on the AIP context and contract.
        Falls back to deterministic build if LLM fails.

        Args:
            aip: The parsed AIP dictionary
            step_idx: Zero-based index of the step
            contract: The StepContract for this step
            model: LLM model alias (e.g., "gpt-4o", "claude-sonnet")

        Returns:
            StepExecutionPlan with provenance indicating LLM generation

        Raises:
            SepValidationError: If LLM response is invalid and fallback also fails
        """
        import typer

        from spec.llm.client import LLMClient, LLMExecutionError
        from spec.llm.config import LLMConfigError, require_llm_enabled
        from spec.llm.prompts import render_sep_generation_prompt

        # Build AIP context for the prompt
        aip_context = self._build_aip_context(aip, step_idx)
        contract_text = self._build_contract_text(contract)

        # Render the prompt
        prompt = render_sep_generation_prompt(
            aip_context=aip_context,
            step_index=step_idx,
            contract_text=contract_text,
        )

        try:
            # Load config and check LLM is enabled
            config = require_llm_enabled()

            # Create client and send prompt
            client = LLMClient(config, model)
            response = client.prompt(prompt)

            # Parse LLM response as YAML
            sep = self._parse_llm_sep_response(response, aip, step_idx, contract, model)
            typer.echo(f"✓ SEP generated via LLM ({model})")
            return sep

        except (LLMConfigError, LLMExecutionError) as e:
            # LLM failed - fall back to deterministic build with warning
            typer.secho(f"⚠ LLM SEP generation failed: {e}", fg=typer.colors.YELLOW, err=True)
            typer.echo("  Falling back to deterministic SEP builder...")
            return self.build(aip, step_idx, contract)

        except SepValidationError as e:
            # LLM returned invalid SEP - fall back with warning
            typer.secho(f"⚠ LLM returned invalid SEP: {e}", fg=typer.colors.YELLOW, err=True)
            typer.echo("  Falling back to deterministic SEP builder...")
            return self.build(aip, step_idx, contract)

    def _build_aip_context(self, aip: dict[str, Any], step_idx: int) -> str:
        """Build context string from AIP for LLM prompt."""
        lines = []

        title = aip.get("title", "Untitled")
        lines.append(f"Title: {title}")

        objective = aip.get("objective", {})
        if isinstance(objective, dict):
            goal = objective.get("goal", "")
            if goal:
                lines.append(f"Goal: {goal}")
        elif isinstance(objective, str):
            lines.append(f"Goal: {objective}")

        plan = aip.get("plan", [])
        if step_idx < len(plan):
            step = plan[step_idx]
            step_title = step.get("title", f"Step {step_idx + 1}")
            step_prompt = step.get("prompt", "")
            lines.append(f"\nStep Title: {step_title}")
            if step_prompt:
                lines.append(f"Step Prompt:\n{step_prompt}")

        return "\n".join(lines)

    def _build_contract_text(self, contract: StepContract) -> str:
        """Build contract text for LLM prompt."""
        lines = [
            f"AIP ID: {contract.aip_id}",
            f"Step ID: {contract.step_id}",
            f"Step Index: {contract.step_index}",
            "",
            "Allowed Paths:",
        ]
        for path in contract.allowed_paths:
            lines.append(f"  - {path}")

        lines.append("")
        lines.append("Forbidden Paths:")
        for path in contract.forbidden_paths:
            lines.append(f"  - {path}")

        lines.append("")
        lines.append("Verification Commands:")
        for cmd in contract.verification_commands:
            lines.append(f"  - {cmd}")

        return "\n".join(lines)

    def _parse_llm_sep_response(
        self,
        response: str,
        aip: dict[str, Any],
        step_idx: int,
        contract: StepContract,
        model: str,
    ) -> StepExecutionPlan:
        """Parse LLM response and build SEP.

        Args:
            response: Raw LLM response text (should be YAML)
            aip: The parsed AIP dictionary
            step_idx: Zero-based step index
            contract: The StepContract
            model: Model name for provenance

        Returns:
            StepExecutionPlan from LLM response

        Raises:
            SepValidationError: If response is not valid YAML or missing required fields
        """
        # Strip markdown code fences if present
        response = response.strip()
        if response.startswith("```yaml"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        try:
            data = yaml.safe_load(response)
        except yaml.YAMLError as e:
            raise SepValidationError(f"Invalid YAML in LLM response: {e}") from e

        if not isinstance(data, dict):
            raise SepValidationError(
                f"LLM response must be a YAML mapping, got {type(data).__name__}"
            )

        # Extract fields from LLM response
        objective = data.get("objective", "")
        if objective is None:
            objective = ""

        # Parse files_to_touch
        files_to_touch: list[FileChange] = []
        for fc_data in data.get("files_to_touch", []) or []:
            if not isinstance(fc_data, dict):
                continue
            path = fc_data.get("path", "")
            action = fc_data.get("action", "modify")
            description = fc_data.get("description", f"{action} {path}")
            if path:
                files_to_touch.append(
                    FileChange(
                        path=path,
                        action=action,
                        description=description,
                        estimated_lines=fc_data.get("estimated_lines"),
                    )
                )

        # Parse verification_steps or use contract's
        verification_steps: list[VerificationStep] = []
        llm_verification = data.get("verification_steps", [])
        if llm_verification:
            for vs_data in llm_verification:
                if not isinstance(vs_data, dict):
                    continue
                command = vs_data.get("command", "")
                expected = vs_data.get("expected_outcome", "Command exits successfully")
                if command:
                    verification_steps.append(
                        VerificationStep(
                            command=command,
                            expected_outcome=expected,
                            required=vs_data.get("required", True),
                        )
                    )
        else:
            # Fall back to contract verification commands
            verification_steps = [
                VerificationStep(
                    command=cmd,
                    expected_outcome="Command exits successfully with code 0",
                    required=True,
                )
                for cmd in contract.verification_commands
            ]

        # Use LLM's allowed/forbidden paths if provided, otherwise use contract's
        allowed_paths = data.get("allowed_paths") or contract.allowed_paths
        forbidden_paths = data.get("forbidden_paths") or contract.forbidden_paths

        step_number = step_idx + 1

        return StepExecutionPlan(
            aip_id=contract.aip_id,
            step_id=contract.step_id,
            step_index=step_number,
            objective=str(objective),
            files_to_touch=files_to_touch,
            verification_steps=verification_steps,
            allowed_paths=allowed_paths,
            forbidden_paths=forbidden_paths,
            estimated_complexity=data.get("estimated_complexity", "medium"),
            requires_human_review=data.get("requires_human_review", False),
            provenance=SEPProvenance(generator="llm", model=model),
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
