"""Executor for running checks within epics.

This module provides the CheckExecutor class for executing check prompts,
gathering inputs, calling LLM (or stub), parsing verdicts, and saving reports.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from spec.checks.inputs import GatheredInput, InputGatherError, gather_inputs
from spec.checks.resolver import resolve_prompt
from spec.epic.schema import Actor, EventType, HistoryEvent
from spec.epic.writer import append_history, generate_event_id
from spec.llm.reporter import CheckReport, parse_verdict, write_report

if TYPE_CHECKING:
    from spec.epic.schema import Check, Epic


class LLMClient(Protocol):
    """Protocol for LLM clients."""

    def complete(self, prompt: str, model: str) -> str:
        """Generate a completion for the given prompt.

        Args:
            prompt: The full prompt to send to the LLM.
            model: The model alias to use.

        Returns:
            The LLM response text.
        """
        ...


class CheckExecutor:
    """Executor for running checks within epics."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        """Initialize executor.

        Args:
            llm_client: Optional LLM client. If None, uses stub responses.
        """
        self.llm_client = llm_client

    def execute(
        self,
        epic: Epic,
        check_id: str,
        epic_path: Path,
        spec_id: str | None = None,
    ) -> CheckReport:
        """Execute a check and return report (does not save).

        Args:
            epic: The epic containing the check definition.
            check_id: ID of the check to execute.
            epic_path: Path to the epic directory.
            spec_id: Optional spec ID for spec-scoped checks.

        Returns:
            CheckReport with execution results.

        Raises:
            ValueError: If check not found in epic.
        """
        # 1. Find check by ID
        check = epic.get_check(check_id)
        if check is None:
            raise ValueError(f"Check not found: {check_id}")

        # 2. Resolve prompt from prompt_ref
        template = resolve_prompt(check.prompt_ref, epic_path)

        # 3. Gather inputs
        inputs = gather_inputs(check, epic, epic_path)

        # 4. Assemble full prompt
        full_prompt = self._assemble_prompt(template, inputs)

        # 5. Call LLM or stub
        if self.llm_client is None:
            response = self._stub_response(check, inputs_count=len(inputs))
            model_used = "stub"
            is_stub = True
        else:
            model_used = self._resolve_model(check, epic)
            response = self.llm_client.complete(full_prompt, model_used)
            is_stub = False

        # 6. Parse verdict from response
        verdict = parse_verdict(response, is_stub=is_stub)

        # 7. Return CheckReport
        return CheckReport(
            check_id=check_id,
            epic_id=epic.id,
            spec_id=spec_id,
            model=model_used,
            timestamp=datetime.now(UTC),
            inputs=[inp.source for inp in inputs],
            verdict=verdict,
            content=response,
        )

    def run_and_save(
        self,
        epic: Epic,
        check_id: str,
        epic_path: Path,
        spec_id: str | None = None,
    ) -> tuple[CheckReport, Path]:
        """Execute check, write report, update history.

        Args:
            epic: The epic containing the check definition.
            check_id: ID of the check to execute.
            epic_path: Path to the epic directory.
            spec_id: Optional spec ID for spec-scoped checks.

        Returns:
            Tuple of (report, report_path).

        Raises:
            ValueError: If check not found in epic.
        """
        # Resolve check early so we can produce a report even if input gathering fails.
        check = epic.get_check(check_id)
        if check is None:
            raise ValueError(f"Check not found: {check_id}")

        try:
            report = self.execute(epic, check_id, epic_path, spec_id)
        except InputGatherError as e:
            report = CheckReport(
                check_id=check_id,
                epic_id=epic.id,
                spec_id=spec_id,
                model="internal",
                timestamp=datetime.now(UTC),
                inputs=[],
                verdict="ERROR",
                content=(
                    f"VERDICT: ERROR\n"
                    f"SUMMARY: Input gathering failed\n\n"
                    f"# Check Report: {check.name}\n\n"
                    f"## Error\n\n"
                    f"{e}".rstrip()
                ),
            )

            report_path = write_report(report, epic_path)

            event = HistoryEvent(
                id=generate_event_id(epic),
                at=report.timestamp,
                event=EventType.CHECK_COMPLETED,
                actor=Actor.SPECWRIGHT,
                spec_id=spec_id,
                check_id=check_id,
                verdict=report.verdict,
                report=str(report_path.relative_to(epic_path)),
            )
            append_history(epic, event)

            raise

        # Write the report
        report_path = write_report(report, epic_path)

        # Update history
        event = HistoryEvent(
            id=generate_event_id(epic),
            at=report.timestamp,
            event=EventType.CHECK_COMPLETED,
            actor=Actor.SPECWRIGHT,
            spec_id=spec_id,
            check_id=check_id,
            verdict=report.verdict,
            report=str(report_path.relative_to(epic_path)),
        )

        append_history(epic, event)

        return report, report_path

    def _assemble_prompt(
        self,
        template: str,
        inputs: list[GatheredInput],
    ) -> str:
        """Assemble full prompt with inputs section.

        Appends an "# Inputs" section to the template containing
        all gathered inputs with their type and source.

        Args:
            template: The prompt template text.
            inputs: List of gathered inputs.

        Returns:
            Full prompt with inputs section.
        """
        if not inputs:
            return template

        lines = [template, "", "# Inputs", ""]

        for inp in inputs:
            lines.append(f"## {inp.type}: {inp.source}")
            lines.append("")
            lines.append("```")
            lines.append(inp.content)
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    def _stub_response(self, check: Check, inputs_count: int) -> str:
        """Generate stub response when no LLM client.

        Args:
            check: The check being executed.

        Returns:
            Formatted stub response with NOT_RUN verdict.
        """
        return (
            f"VERDICT: NOT_RUN\n"
            f"SUMMARY: LLM integration not configured\n\n"
            f"# Check Report: {check.name}\n\n"
            f"## Status\n\n"
            f"This check was not executed because LLM integration is not configured.\n\n"
            f"To enable LLM checks:\n"
            f"1. Install llm package: `pip install llm`\n"
            f"2. Configure a model: `llm keys set openai`\n"
            f"3. Enable in config: `~/.local/local-governor/config.yaml` → `llm.enabled: true`\n"
            f"4. Re-run this check\n\n"
            f"## Inputs\n\n"
            f"{inputs_count} inputs were gathered successfully."
        )

    def _resolve_model(self, check: Check, epic: Epic) -> str:
        """Resolve model to use for a check.

        Priority:
        1. check.model if set
        2. epic.defaults.model if set
        3. Default to "default"

        Args:
            check: The check being executed.
            epic: The epic containing defaults.

        Returns:
            Model alias to use.
        """
        if check.model:
            return check.model
        if epic.defaults and epic.defaults.model:
            return epic.defaults.model
        return "default"
