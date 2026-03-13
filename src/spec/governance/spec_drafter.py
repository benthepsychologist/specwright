"""LLM-assisted spec drafting using Claude Code.

Provides two-stage drafting: scaffold first, then ask LLM to fill in TODOs
by exploring the repository with read-only tools.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec.governance.spec_scaffolder import SpecScaffolder


# Read-only tool allowlist for drafting mode
DRAFTING_ALLOWLIST = [
    "Read",
    "Glob",
    "Grep",
    "Bash(ls:*)",
    "Bash(find:*)",
    "Bash(tree:*)",
    "Bash(cat:*)",
    "Bash(head:*)",
    "Bash(tail:*)",
    "Bash(wc:*)",
    "Bash(git status:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(git diff:*)",
    "Bash(git ls-files:*)",
]


class SpecDrafter:
    """LLM-assisted spec drafting.

    Uses Claude Code in headless mode to explore a repository and fill in
    TODO fields of a scaffolded YAML spec.
    """

    def __init__(
        self,
        scaffolder: SpecScaffolder,
        model: str = "claude-sonnet-4-20250514",
        timeout_s: int = 600,
        max_turns: int = 50,
        context: str | None = None,
    ):
        """Initialize drafter.

        Args:
            scaffolder: SpecScaffolder instance with intent and repo_path.
            model: Model to use for drafting.
            timeout_s: Timeout in seconds (default 10 minutes).
            max_turns: Maximum conversation turns.
            context: Additional context content to include in prompt.
        """
        self.scaffolder = scaffolder
        self.model = model
        self.timeout_s = timeout_s
        self.max_turns = max_turns
        self.context = context or scaffolder.context

    def draft(self) -> str:
        """Generate full spec with LLM assistance.

        Returns:
            Complete spec YAML with TODOs filled in.

        Raises:
            FileNotFoundError: If claude CLI not found.
            RuntimeError: If Claude Code fails or times out.
        """
        # Stage 1: Generate scaffold
        scaffold = self.scaffolder.scaffold()

        # Stage 2: Ask LLM to fill in TODOs
        prompt = self._build_prompt(scaffold)
        filled = self._call_claude_code(prompt)

        return filled

    def _build_prompt(self, scaffold: str) -> str:
        """Build the prompt for Claude Code.

        Args:
            scaffold: Scaffolded spec YAML.

        Returns:
            Complete prompt string.
        """
        context_section = ""
        if self.context:
            context_section = f"""
## Additional Context

The following additional context was provided to guide your drafting:

{self.context}

"""

        return f"""You have a scaffolded spec in YAML (spec-v2.1 format) that needs to be completed.
Your job is to explore the codebase and fill in TODO fields.

## Scaffolded Spec

{scaffold}
{context_section}
## Your Task

1. Explore the repository to understand the current state
2. Fill in objective/key_decisions with concrete details
3. Fill in each `phases[]` entry with concrete implementation slices:
   - objective: what capability this phase implements
   - files_to_touch: specific files expected to change
   - notes based on existing patterns in the codebase
   - verification commands (pytest, ruff, etc.) to validate the phase

## Output Rules

IMPORTANT: Do NOT use TodoWrite or Task tools. Your ONLY job is to output the spec.

When you are done exploring, output the complete filled-in spec YAML.
Replace TODO fields with real content based on your exploration.

Output ONLY the spec YAML as your final response, nothing else."""

    def _call_claude_code(self, prompt: str) -> str:
        """Call Claude Code in headless mode with read-only tools.

        Args:
            prompt: The prompt to send to Claude Code.

        Returns:
            Claude Code's response (the filled YAML spec).

        Raises:
            FileNotFoundError: If claude CLI not found.
            RuntimeError: If Claude Code fails or times out.
        """
        # Check if claude CLI is available
        claude_path = shutil.which("claude")
        if claude_path is None:
            raise FileNotFoundError(
                "claude CLI not found. Install it from https://github.com/anthropics/claude-code"
            )

        cmd = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--output-format", "text",
            "--allowedTools", ",".join(DRAFTING_ALLOWLIST),
            "--max-turns", str(self.max_turns),
            "--model", self.model,
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=self.scaffolder.repo_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        try:
            stdout, stderr = proc.communicate(input=prompt, timeout=self.timeout_s)
            if proc.returncode != 0:
                raise RuntimeError(f"Claude Code failed: {stderr}")

            # If stdout already looks like spec YAML, return it
            if self._looks_like_spec_yaml(stdout):
                return stdout

            # Otherwise, try to extract spec from conversation history
            extracted = self._extract_spec_from_conversation()
            if extracted:
                return extracted

            # Fall back to stdout even if it doesn't look like a spec
            return stdout
        except subprocess.TimeoutExpired:
            # Kill the process group to clean up any child processes
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            proc.wait()
            raise RuntimeError(f"Claude Code timed out after {self.timeout_s}s")

    def _extract_spec_from_conversation(self) -> str | None:
        """Extract spec YAML from most recent Claude conversation.

        Looks for assistant messages containing spec YAML blocks.

        Returns:
            Extracted spec YAML, or None if not found.
        """
        # Find most recent conversation file
        claude_projects = Path.home() / ".claude" / "projects"
        if not claude_projects.exists():
            return None

        # Look for conversation files modified in last 10 minutes
        import time
        cutoff = time.time() - 600

        recent_convos: list[Path] = []
        for project_dir in claude_projects.iterdir():
            if project_dir.is_dir():
                for jsonl in project_dir.glob("*.jsonl"):
                    if jsonl.stat().st_mtime > cutoff:
                        recent_convos.append(jsonl)

        if not recent_convos:
            return None

        # Sort by modification time, most recent first
        recent_convos.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # Search for spec content in most recent conversation
        for convo_path in recent_convos[:3]:  # Check top 3 most recent
            spec = self._extract_spec_from_jsonl(convo_path)
            if spec:
                return spec

        return None

    def _extract_spec_from_jsonl(self, jsonl_path: Path) -> str | None:
        """Extract YAML spec from a conversation JSONL file.

        Args:
            jsonl_path: Path to conversation JSONL file.

        Returns:
            Extracted spec YAML, or None if not found.
        """
        spec_content: str | None = None

        with open(jsonl_path) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") != "assistant":
                    continue

                message = obj.get("message", {})
                content = message.get("content", [])

                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        if self._looks_like_spec_yaml(text):
                            # Extract the spec portion
                            extracted = self._extract_spec_block(text)
                            if extracted:
                                spec_content = extracted  # Keep last (most complete) one

        return spec_content

    def _extract_spec_block(self, text: str) -> str | None:
        """Extract YAML spec block from text.

        Args:
            text: Text that may contain a spec.

        Returns:
            Extracted YAML spec, or None.
        """
        match = re.search(
            r"((?:artifact_id:|name:|---\s*\nid:)[\s\S]*)",
            text,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip()
        return None

    def _looks_like_spec_yaml(self, text: str) -> bool:
        """Heuristic check whether text appears to be a YAML spec."""
        stripped = text.strip()
        if not stripped:
            return False
        if stripped.startswith("---\nid:"):
            return True
        return (
            "kind: spec" in stripped
            and ("name:" in stripped or "artifact_id:" in stripped)
            and "title:" in stripped
        )


def check_claude_available() -> bool:
    """Check if claude CLI is available.

    Returns:
        True if claude CLI is in PATH, False otherwise.
    """
    return shutil.which("claude") is not None
