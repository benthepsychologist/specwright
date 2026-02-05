"""LLM-assisted spec refinement using Claude Code.

Provides iterative spec improvement by analyzing existing specs and
suggesting/applying refinements while preserving user-written content.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

# Read-only tool allowlist for refinement mode (same as drafting)
REFINEMENT_ALLOWLIST = [
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


class SpecRefiner:
    """LLM-assisted spec refinement.

    Uses Claude Code in headless mode to analyze an existing spec and suggest
    improvements while preserving user-written content.
    """

    def __init__(
        self,
        spec_path: Path,
        original_content: str,
        repo_path: Path | None = None,
        model: str = "claude-sonnet-4-20250514",
        timeout_s: int = 600,
        max_turns: int = 50,
        context: str | None = None,
    ):
        """Initialize refiner.

        Args:
            spec_path: Path to the spec file being refined.
            original_content: Current content of the spec.
            repo_path: Path to the target repository (for codebase exploration).
            model: Model to use for refinement.
            timeout_s: Timeout in seconds (default 10 minutes).
            max_turns: Maximum conversation turns.
            context: Additional context content (e.g., feedback, requirements).
        """
        self.spec_path = spec_path
        self.original_content = original_content
        self.repo_path = repo_path or spec_path.parent
        self.model = model
        self.timeout_s = timeout_s
        self.max_turns = max_turns
        self.context = context

    def analyze(self) -> str:
        """Analyze the spec and return suggestions without changes.

        Returns:
            Structured suggestions for improving the spec.

        Raises:
            FileNotFoundError: If claude CLI not found.
            RuntimeError: If Claude Code fails or times out.
        """
        prompt = self._build_analysis_prompt()
        return self._call_claude_code(prompt)

    def refine(self) -> str:
        """Refine the spec and return improved content.

        Returns:
            Refined spec markdown with improvements applied.

        Raises:
            FileNotFoundError: If claude CLI not found.
            RuntimeError: If Claude Code fails or times out.
        """
        prompt = self._build_refinement_prompt()
        result = self._call_claude_code(prompt)

        # Extract spec content if wrapped in other text
        extracted = self._extract_spec_content(result)
        return extracted if extracted else result

    def _build_analysis_prompt(self) -> str:
        """Build prompt for analysis-only mode (suggestions without changes).

        Returns:
            Complete prompt string for analysis.
        """
        context_section = self._format_context_section()

        return f"""You are analyzing a spec to suggest improvements. Do NOT output a modified spec.
Instead, provide structured feedback on how to improve it.

## Current Spec

{self.original_content}
{context_section}
## Analysis Tasks

1. **Structure Review**: Check for completeness of sections (Objective, Problem,
   Current Capabilities, build_delta, Acceptance Criteria, Phases)

2. **Content Quality**: Evaluate clarity, specificity, and actionability

3. **Pattern Alignment**: Compare against codebase patterns you discover

4. **build_delta Consistency**: Verify that Phases derive from the build_delta

5. **Verification Coverage**: Check that each Phase has proper verification steps

## Output Format

Provide your analysis as structured markdown:

### Summary
Brief overall assessment (1-2 sentences)

### Issues Found
- Issue 1: description
- Issue 2: description

### Suggested Improvements
1. **Section**: Specific improvement
2. **Section**: Specific improvement

### Pattern Observations
Any relevant patterns from the codebase that should inform the spec

IMPORTANT: Output ONLY your analysis. Do NOT output a modified spec."""

    def _build_refinement_prompt(self) -> str:
        """Build prompt for refinement mode (generate improved spec).

        Returns:
            Complete prompt string for refinement.
        """
        context_section = self._format_context_section()

        return f"""You are refining an existing spec to improve its quality while preserving user intent.

## Current Spec

{self.original_content}
{context_section}
## Refinement Guidelines

1. **Preserve User Intent**: Keep the original goal and direction intact
2. **Preserve User Content**: Maintain any custom content the user has written
3. **Fill Gaps**: Replace TODOs with concrete details based on codebase exploration
4. **Improve Specificity**: Make vague statements more concrete and actionable
5. **Ensure Consistency**: Align Phases with the build_delta
6. **Add Verification**: Ensure each Phase has concrete verification commands
7. **Follow Patterns**: Use patterns you discover in the codebase

## Content Preservation Rules

- NEVER remove sections the user has filled in
- NEVER change the core goal or objective meaning
- TODOs and placeholders CAN be replaced with real content
- Empty sections CAN be filled based on exploration
- Existing content CAN be enhanced but not fundamentally changed

## Exploration Instructions

1. Explore the repository to understand current patterns
2. Look at similar files for style/structure guidance
3. Check build.yaml for existing capabilities
4. Identify relevant tests and verification approaches

## Output Rules

IMPORTANT: Do NOT use TodoWrite or Task tools. Your ONLY job is to output the spec.

Output the complete refined spec markdown.
The spec must start with `---` (YAML frontmatter) and include all sections.
Preserve the original structure while improving content quality.

Output ONLY the spec markdown as your final response, nothing else."""

    def _format_context_section(self) -> str:
        """Format the optional context section for prompts.

        Returns:
            Formatted context section, or empty string if no context.
        """
        if not self.context:
            return ""

        return f"""
## Additional Context (Feedback/Requirements)

The following feedback or additional requirements should guide your refinement:

{self.context}
"""

    def _call_claude_code(self, prompt: str) -> str:
        """Call Claude Code in headless mode with read-only tools.

        Args:
            prompt: The prompt to send to Claude Code.

        Returns:
            Claude Code's response.

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
            "--allowedTools", ",".join(REFINEMENT_ALLOWLIST),
            "--max-turns", str(self.max_turns),
            "--model", self.model,
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

    def _extract_spec_content(self, text: str) -> str | None:
        """Extract spec markdown from Claude's response.

        Handles cases where the spec might be wrapped in explanation text.

        Args:
            text: Raw response text from Claude.

        Returns:
            Extracted spec content, or None if not found.
        """
        # If it already starts with frontmatter, return as-is
        if text.strip().startswith("---"):
            return text.strip()

        # Try to find frontmatter block
        match = re.search(r"(---\s*\nid:.*)", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        return None


def check_claude_available() -> bool:
    """Check if claude CLI is available.

    Returns:
        True if claude CLI is in PATH, False otherwise.
    """
    return shutil.which("claude") is not None
