"""LLM-assisted epic drafting using Claude Code.

Drafts epic content by crawling repositories and generating meaningful
narrative, specs, expectations, and constraints.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from spec.governance.spec_drafter import DRAFTING_ALLOWLIST

if TYPE_CHECKING:
    pass


class EpicDrafter:
    """Draft epic.yaml content by crawling repository.

    Uses Claude Code in headless mode to explore repositories and generate
    meaningful epic content including narrative, specs, and dependencies.
    """

    def __init__(
        self,
        title: str,
        goal: str,
        owner: str,
        repo_path: Path | None = None,
        context: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        timeout_s: int = 600,
        max_turns: int = 50,
    ):
        """Initialize drafter.

        Args:
            title: Epic title.
            goal: One-line goal statement.
            owner: Owner username.
            repo_path: Path to repository to explore (default: cwd).
            context: Additional context content to include in prompt.
            model: Model to use for drafting.
            timeout_s: Timeout in seconds (default 10 minutes).
            max_turns: Maximum conversation turns.
        """
        self.title = title
        self.goal = goal
        self.owner = owner
        self.repo_path = repo_path or Path.cwd()
        self.context = context
        self.model = model
        self.timeout_s = timeout_s
        self.max_turns = max_turns

    def draft(self) -> dict[str, Any]:
        """Generate epic patch dict by exploring repos.

        Returns:
            Epic patch dict ready for merging with skeleton epic.yaml.

        Raises:
            FileNotFoundError: If claude CLI not found.
            RuntimeError: If Claude Code fails or times out.
        """
        prompt = self._build_prompt()
        result = self._call_claude_code(prompt)
        return self._parse_patch(result)

    def _build_prompt(self) -> str:
        """Build the prompt for Claude Code.

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

        return f"""You are drafting an epic for the specwright system.

## Goal
{self.goal}

## Title
{self.title}

## Owner
{self.owner}

## Target Repository
Current working directory: {self.repo_path}
{context_section}
## Your Task

1. Explore the repository to understand the current state
2. Identify what work needs to be done to achieve the goal
3. Break the work into logical specs with clear boundaries
4. For each spec, determine:
   - A clear title and ID (e.g., t001-01, t001-02, etc.)
   - Expectations (what it should deliver)
   - Constraints (boundaries, limitations)
   - Dependencies on other specs
   - Recommended execution mode: "headless" (automated) or "interactive" (needs human interaction)

## Output Format

Output YAML for an epic *draft patch* (not a full epic.yaml). The CLI will:
1) create a valid skeleton epic.yaml (with created/updated/state/history), then
2) merge this patch into it, then
3) validate and write the final epic.yaml.

```yaml
patch:
  intent:
    narrative: |
      <Explain the problem and why this epic matters>
  targets:
    - id: <target-id>
      repo_path: <absolute-path-to-repo>
      default_branch: main
  specs:
    - id: <spec-id>
      title: <spec-title>
      repo: <target-id>
      branch: feat/<slug>
      path: specs/<spec-id>.md
      depends_on: []
      mode: headless  # or interactive
      expectations:
        - <what this spec delivers>
      constraints:
        - <boundaries and limitations>
```

IMPORTANT:
- Do NOT use TodoWrite or Task tools. Your ONLY job is to output the YAML.
- Output ONLY the YAML block, nothing else.
- The `mode` field should be "headless" for automated work, "interactive" for work needing human decisions."""

    def _call_claude_code(self, prompt: str) -> str:
        """Call Claude Code in headless mode with read-only tools.

        Args:
            prompt: The prompt to send to Claude Code.

        Returns:
            Claude Code's response (the patch YAML).

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
            "--output-format",
            "text",
            "--allowedTools",
            ",".join(DRAFTING_ALLOWLIST),
            "--max-turns",
            str(self.max_turns),
            "--model",
            self.model,
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=self.repo_path,
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
            return stdout
        except subprocess.TimeoutExpired:
            # Kill the process group to clean up any child processes
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            proc.wait()
            raise RuntimeError(f"Claude Code timed out after {self.timeout_s}s")

    def _parse_patch(self, response: str) -> dict[str, Any]:
        """Parse epic patch from Claude Code response.

        Args:
            response: Raw response from Claude Code.

        Returns:
            Parsed patch dict.

        Raises:
            RuntimeError: If parsing fails.
        """
        # Extract YAML block from response
        yaml_match = re.search(r"```yaml\s*(.*?)```", response, re.DOTALL)
        if yaml_match:
            yaml_content = yaml_match.group(1).strip()
        else:
            # Try to parse the entire response as YAML
            yaml_content = response.strip()

        try:
            parsed = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise RuntimeError(f"Failed to parse YAML response: {e}")

        if not isinstance(parsed, dict):
            raise RuntimeError(f"Expected dict, got {type(parsed).__name__}")

        # Handle both "patch:" wrapper and direct content
        if "patch" in parsed:
            return parsed["patch"]
        return parsed


def check_claude_available() -> bool:
    """Check if claude CLI is available.

    Returns:
        True if claude CLI is in PATH, False otherwise.
    """
    return shutil.which("claude") is not None
