"""LLM-assisted spec entry drafting for epics.

Drafts spec entries (SpecRef) for adding to existing epics by crawling
repositories and generating meaningful expectations, constraints, and dependencies.
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
    from spec.epic.schema import Epic


class SpecEntryDrafter:
    """Draft spec entries for an existing epic.

    Uses Claude Code in headless mode to explore a repository and generate
    one or more spec entries with expectations, constraints, and dependencies.
    """

    def __init__(
        self,
        epic: Epic,
        description: str,
        target_id: str | None = None,
        context: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        timeout_s: int = 600,
        max_turns: int = 50,
    ):
        """Initialize drafter.

        Args:
            epic: The existing Epic to add specs to.
            description: Description of the work to be done.
            target_id: Primary target repo ID (optional, uses first target if not specified).
            context: Additional context content to include in prompt.
            model: Model to use for drafting.
            timeout_s: Timeout in seconds (default 10 minutes).
            max_turns: Maximum conversation turns.
        """
        self.epic = epic
        self.description = description
        self.target_id = target_id
        self.context = context
        self.model = model
        self.timeout_s = timeout_s
        self.max_turns = max_turns

    def draft(self) -> list[dict[str, Any]]:
        """Generate spec entry dicts by exploring repo.

        Returns:
            List of spec entry dicts ready for conversion to SpecRef objects.

        Raises:
            FileNotFoundError: If claude CLI not found.
            RuntimeError: If Claude Code fails or times out.
            ValueError: If no valid target repository found.
        """
        # Determine the working directory for exploration
        repo_path = self._get_repo_path()

        prompt = self._build_prompt()
        result = self._call_claude_code(prompt, repo_path)
        return self._parse_specs(result)

    def _get_repo_path(self) -> Path:
        """Get the repository path to explore.

        Returns:
            Path to the repository.

        Raises:
            ValueError: If no valid target found.
        """
        if self.target_id:
            target = self.epic.get_target(self.target_id)
            if target is None:
                raise ValueError(f"Target '{self.target_id}' not found in epic")
            return Path(target.repo_path).expanduser().resolve()

        # Use first target if available
        if self.epic.targets:
            return Path(self.epic.targets[0].repo_path).expanduser().resolve()

        # Fall back to cwd
        return Path.cwd()

    def _build_prompt(self) -> str:
        """Build the prompt for Claude Code.

        Returns:
            Complete prompt string.
        """
        # Build existing specs summary
        if self.epic.specs:
            existing_specs = "\n".join(
                f"- {s.id}: {s.title or '(no title)'} "
                f"(status: {s.status.value}, depends_on: {s.depends_on or 'none'})"
                for s in self.epic.specs
            )
        else:
            existing_specs = "(none)"

        # Build targets summary
        if self.epic.targets:
            targets_summary = "\n".join(
                f"- {t.id}: {t.repo_path} (branch: {t.default_branch})"
                for t in self.epic.targets
            )
        else:
            targets_summary = "(none)"

        # Determine spec ID pattern from existing specs
        spec_pattern = self._infer_spec_id_pattern()

        context_section = ""
        if self.context:
            context_section = f"""
## Additional Context

{self.context}

"""

        return f"""You are adding spec entries to an existing epic.

## Epic: {self.epic.id}
{self.epic.intent.goal}

## Epic Narrative
{self.epic.intent.narrative or "(no narrative)"}

## Existing Specs
{existing_specs}

## Target Repositories
{targets_summary}

## Description of New Work
{self.description}

## Primary Target
{self.target_id or self.epic.targets[0].id if self.epic.targets else "(cwd)"}
{context_section}
## Your Task

1. Explore the repository to understand the current state
2. Based on the description, determine what spec(s) are needed
3. For each spec, figure out:
   - ID following the pattern: {spec_pattern}
   - Clear title
   - Branch name (feat/<slug>)
   - Expectations (what it delivers)
   - Constraints (boundaries)
   - Dependencies on existing or new specs
   - Recommended mode: "headless" (automated) or "interactive" (needs human decisions)

## Output Format

Output YAML for the new spec entries:

```yaml
specs:
  - id: <spec-id>
    title: <title>
    repo: <target-id>
    branch: feat/<slug>
    path: specs/<spec-id>.md
    status: planned
    depends_on: [<existing-spec-ids-if-any>]
    mode: headless  # or interactive
    expectations:
      - <expectation>
    constraints:
      - <constraint>
```

You may output multiple specs if the work should be broken down.

IMPORTANT:
- Do NOT use TodoWrite or Task tools. Your ONLY job is to output the YAML.
- Output ONLY the YAML block, nothing else.
- The `mode` field should be "headless" for automated work, "interactive" for work needing human decisions.
- Dependencies should only reference existing specs or specs you're defining in this response."""

    def _infer_spec_id_pattern(self) -> str:
        """Infer the spec ID naming pattern from existing specs.

        Returns:
            Pattern description for new spec IDs.
        """
        if not self.epic.specs:
            # Default pattern based on epic ID
            epic_prefix = self.epic.id.split("-")[0]
            return f"{epic_prefix}-01, {epic_prefix}-02, etc."

        # Look for pattern in existing specs
        existing_ids = [s.id for s in self.epic.specs]

        # Try to find numeric suffix pattern
        last_id = existing_ids[-1]
        match = re.search(r"(\d+)$", last_id)
        if match:
            num = int(match.group(1))
            prefix = last_id[: match.start()]
            return f"{prefix}{num + 1:02d}, {prefix}{num + 2:02d}, etc."

        return f"(follow pattern of: {', '.join(existing_ids[:3])})"

    def _call_claude_code(self, prompt: str, repo_path: Path) -> str:
        """Call Claude Code in headless mode with read-only tools.

        Args:
            prompt: The prompt to send to Claude Code.
            repo_path: Working directory for Claude Code.

        Returns:
            Claude Code's response (the specs YAML).

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
            cwd=repo_path,
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

    def _parse_specs(self, response: str) -> list[dict[str, Any]]:
        """Parse spec entries from Claude Code response.

        Args:
            response: Raw response from Claude Code.

        Returns:
            List of spec entry dicts.

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

        specs = parsed.get("specs", [])
        if not isinstance(specs, list):
            raise RuntimeError(f"Expected specs list, got {type(specs).__name__}")

        return specs


def check_claude_available() -> bool:
    """Check if claude CLI is available.

    Returns:
        True if claude CLI is in PATH, False otherwise.
    """
    return shutil.which("claude") is not None
