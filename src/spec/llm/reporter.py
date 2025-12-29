"""Reporter for writing check reports.

This module handles writing check reports to the epic's reports directory
and parsing verdicts from LLM responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Valid verdicts
VALID_VERDICTS = frozenset({"PASS", "WARN", "FAIL", "ERROR", "NOT_RUN"})


@dataclass
class CheckReport:
    """Report from a check execution."""

    check_id: str
    epic_id: str
    spec_id: str | None
    model: str  # llm model alias used (or "stub" if no LLM)
    timestamp: datetime
    inputs: list[str]  # list of input source descriptions
    verdict: str  # PASS, WARN, FAIL, ERROR, NOT_RUN
    content: str  # markdown body


def write_report(report: CheckReport, epic_path: Path) -> Path:
    """Write report to the epic's reports directory.

    Creates a markdown file with YAML frontmatter containing metadata
    and the report content as the body.

    Args:
        report: The check report to write.
        epic_path: Path to the epic directory.

    Returns:
        Path to the written report file.
    """
    reports_dir = epic_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Format filename: YYYYMMDD-HHMM-<check_id>.md
    filename = f"{report.timestamp.strftime('%Y%m%d-%H%M')}-{report.check_id}.md"
    report_path = reports_dir / filename

    # Build YAML frontmatter
    frontmatter_lines = [
        "---",
        f"check_id: {report.check_id}",
        f"epic_id: {report.epic_id}",
    ]

    if report.spec_id:
        frontmatter_lines.append(f"spec_id: {report.spec_id}")

    frontmatter_lines.extend([
        f"model: {report.model}",
        f"timestamp: {report.timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "inputs:",
    ])

    for input_source in report.inputs:
        frontmatter_lines.append(f"  - {input_source}")

    frontmatter_lines.extend([
        f"verdict: {report.verdict}",
        "---",
    ])

    # Combine frontmatter and content
    frontmatter = "\n".join(frontmatter_lines)
    full_content = f"{frontmatter}\n{report.content}"

    report_path.write_text(full_content, encoding="utf-8")

    return report_path


def parse_verdict(response: str, is_stub: bool = False) -> str:
    """Parse verdict from LLM response.

    Looks for a line starting with "VERDICT:" and extracts the verdict value.
    Valid verdicts are: PASS, WARN, FAIL, ERROR, NOT_RUN.

    Args:
        response: The LLM response text.
        is_stub: Whether this is a stub response (no real LLM).

    Returns:
        The parsed verdict string.

    Note:
        - If no verdict found and is_stub=True, returns NOT_RUN.
        - If no verdict found and is_stub=False, returns ERROR (malformed output).
    """
    for line in response.splitlines():
        stripped = line.strip()
        if stripped.startswith("VERDICT:"):
            verdict_part = stripped[len("VERDICT:"):].strip()
            # Take the first word (in case of trailing content)
            verdict = verdict_part.split()[0] if verdict_part else ""
            if verdict in VALID_VERDICTS:
                return verdict
            # Invalid verdict value - fall through to default handling

    # No valid verdict found
    if is_stub:
        return "NOT_RUN"
    return "ERROR"
