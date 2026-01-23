"""
Sandbox enforcer: blocks policy-violating commands.

Enforces execution policy by checking commands against:
- allow_push / allow_merge flags
- blocked_commands list
- branch switching during run

SECURITY NOTE: This enforcer uses pattern matching to detect dangerous commands.
It is designed to catch both direct invocations and evasion attempts including:
- Command chaining (&&, ;, |, ||)
- Subshells (bash -c, sh -c, $(...), backticks)
- Path variations (/usr/bin/git, ./git)
- Environment variable prefixes
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec.executor.schemas import Policy


class PolicyViolation(Exception):
    """Raised when a command violates execution policy."""

    def __init__(
        self,
        message: str,
        command: str,
        policy_rule: str,
        *,
        repo_path: Path | None = None,
    ):
        super().__init__(message)
        self.command = command
        self.policy_rule = policy_rule
        self.repo_path = repo_path

    def __str__(self) -> str:
        base = f"Policy violation: {self.args[0]}"
        if self.repo_path:
            base += f" (repo: {self.repo_path})"
        return base


@dataclass
class CommandCheck:
    """Result of checking a command against policy."""

    allowed: bool
    command: str
    violation_reason: str | None = None
    policy_rule: str | None = None


def _normalize_command(command: str) -> str:
    """Normalize command for comparison (strip extra whitespace)."""
    return " ".join(command.split())


# Pattern to match 'git' command with optional path prefix
# Matches: git, /usr/bin/git, ./git, ../bin/git, etc.
_GIT_CMD_PATTERN = r"(?:(?:[./\w-]+/)?git)"

# Prefix pattern: start of string/line, or after command separator/subshell opener
# Does NOT match after # (comment)
_CMD_PREFIX = r"(?:^|[;&|`\n\(\$]|\s)(?!#)"

# Pattern to detect git push anywhere in command
# Handles: git push, /usr/bin/git push, git -C path push, env git push, etc.
_GIT_PUSH_PATTERN = re.compile(
    _CMD_PREFIX
    + r"(?:env\s+(?:\w+=\S*\s+)*)?"  # Optional env prefix
    r"(?:\w+=\S*\s+)*"  # Optional inline env vars
    + _GIT_CMD_PATTERN
    + r"\s+(?:-[A-Za-z]\s+\S+\s+)*"  # Optional git flags like -C
    r"push(?:\s|$|[;&|)\]])",  # The push command
    re.IGNORECASE,
)

# Pattern to detect git merge anywhere in command
_GIT_MERGE_PATTERN = re.compile(
    _CMD_PREFIX
    + r"(?:env\s+(?:\w+=\S*\s+)*)?"
    r"(?:\w+=\S*\s+)*"
    + _GIT_CMD_PATTERN
    + r"\s+(?:-[A-Za-z]\s+\S+\s+)*"
    r"merge(?:\s|$|[;&|)\]])",
    re.IGNORECASE,
)

# Pattern to detect git checkout (for branch switching detection)
_GIT_CHECKOUT_PATTERN = re.compile(
    _CMD_PREFIX
    + r"(?:env\s+(?:\w+=\S*\s+)*)?"
    r"(?:\w+=\S*\s+)*"
    + _GIT_CMD_PATTERN
    + r"\s+(?:-[A-Za-z]\s+\S+\s+)*"
    r"checkout(?:\s|$|[;&|)\]])",
    re.IGNORECASE,
)

# Dangerous shell patterns that could hide commands
_SHELL_EXEC_PATTERNS = [
    r"bash\s+-c\s+",
    r"sh\s+-c\s+",
    r"zsh\s+-c\s+",
    r"eval\s+",
    r"source\s+",
    r"\.\s+",  # source shorthand
]
_SHELL_EXEC_PATTERN = re.compile("|".join(_SHELL_EXEC_PATTERNS), re.IGNORECASE)

# Pattern to detect piping to a shell (very dangerous - can execute arbitrary commands)
_PIPE_TO_SHELL_PATTERN = re.compile(
    r"\|\s*(?:bash|sh|zsh|dash|ksh)(?:\s|$)",
    re.IGNORECASE,
)


def _strip_comments(command: str) -> str:
    """
    Remove shell comments from command.

    Handles:
    - Full line comments: # comment
    - Inline comments: cmd # comment (but not inside quotes)
    """
    lines = command.split("\n")
    result_lines = []

    for line in lines:
        # Skip full-line comments
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue

        # For inline comments, we'd need proper shell parsing
        # For now, just strip obvious trailing comments
        # This is a simplification - a real shell parser would be better
        result_lines.append(line)

    return "\n".join(result_lines)


def _contains_git_push(command: str) -> bool:
    """
    Check if command contains a git push anywhere.

    Handles evasion attempts including:
    - Command chaining: echo foo && git push
    - Subshells: bash -c 'git push'
    - Path variations: /usr/bin/git push
    - Env vars: GIT_DIR=/tmp git push
    - Piping to shell: echo 'git push' | sh
    """
    # Strip comments first
    cleaned = _strip_comments(command)
    if not cleaned.strip():
        return False

    # Direct pattern match
    if _GIT_PUSH_PATTERN.search(cleaned):
        return True

    # Check inside quoted strings for shell -c patterns OR pipe-to-shell patterns
    has_shell_exec = _SHELL_EXEC_PATTERN.search(cleaned)
    has_pipe_to_shell = _PIPE_TO_SHELL_PATTERN.search(cleaned)

    if has_shell_exec or has_pipe_to_shell:
        # Extract quoted content and check recursively
        for match in re.finditer(r"['\"]([^'\"]+)['\"]", cleaned):
            if _contains_git_push(match.group(1)):
                return True

    # Check inside backticks
    for match in re.finditer(r"`([^`]+)`", cleaned):
        if _contains_git_push(match.group(1)):
            return True

    return False


def _contains_git_merge(command: str) -> bool:
    """Check if command contains a git merge anywhere."""
    cleaned = _strip_comments(command)
    if not cleaned.strip():
        return False

    if _GIT_MERGE_PATTERN.search(cleaned):
        return True

    has_shell_exec = _SHELL_EXEC_PATTERN.search(cleaned)
    has_pipe_to_shell = _PIPE_TO_SHELL_PATTERN.search(cleaned)

    if has_shell_exec or has_pipe_to_shell:
        for match in re.finditer(r"['\"]([^'\"]+)['\"]", cleaned):
            if _contains_git_merge(match.group(1)):
                return True

    for match in re.finditer(r"`([^`]+)`", cleaned):
        if _contains_git_merge(match.group(1)):
            return True

    return False


def _contains_git_checkout(command: str) -> bool:
    """Check if command contains a git checkout anywhere."""
    cleaned = _strip_comments(command)
    if not cleaned.strip():
        return False

    if _GIT_CHECKOUT_PATTERN.search(cleaned):
        return True

    has_shell_exec = _SHELL_EXEC_PATTERN.search(cleaned)
    has_pipe_to_shell = _PIPE_TO_SHELL_PATTERN.search(cleaned)

    if has_shell_exec or has_pipe_to_shell:
        for match in re.finditer(r"['\"]([^'\"]+)['\"]", cleaned):
            if _contains_git_checkout(match.group(1)):
                return True

    for match in re.finditer(r"`([^`]+)`", cleaned):
        if _contains_git_checkout(match.group(1)):
            return True

    return False


def _is_git_push(command: str) -> bool:
    """Check if command contains a git push."""
    return _contains_git_push(command)


def _is_git_merge(command: str) -> bool:
    """Check if command contains a git merge."""
    return _contains_git_merge(command)


def _is_git_checkout_branch(command: str) -> bool:
    """
    Check if command switches branches.

    Allows: git checkout -- file, git checkout HEAD file
    Blocks: git checkout branch_name, git checkout -b new_branch

    Also blocks any checkout found in chained/subshell commands
    as we can't reliably determine if it's a file checkout.
    """
    if not _contains_git_checkout(command):
        return False

    normalized = _normalize_command(command)

    # If command has chaining or subshells, be conservative and block
    # We can't reliably parse what the checkout is doing
    if re.search(r"[;&|`\n]|\$\(|bash\s+-c|sh\s+-c", normalized):
        return True

    # For simple commands, try to parse
    try:
        parts = shlex.split(normalized)
    except ValueError:
        # If we can't parse it, be conservative and block
        return True

    # Find the checkout position
    checkout_idx = -1
    for i, part in enumerate(parts):
        if part == "checkout":
            checkout_idx = i
            break

    if checkout_idx == -1:
        # Pattern matched but couldn't find checkout - be conservative
        return True

    # Check args after 'checkout'
    after_checkout = parts[checkout_idx + 1 :] if checkout_idx + 1 < len(parts) else []

    # If there's a '--' it's file checkout (allowed)
    if "--" in after_checkout:
        return False

    # git checkout -b is branch creation (block)
    if "-b" in after_checkout or "-B" in after_checkout:
        return True

    # git checkout with just a ref and no file path is branch switch
    # This is heuristic - if there's no path-like arg after, it's likely a branch
    if after_checkout and not any(
        "/" in arg or "." in arg or arg.startswith("-") for arg in after_checkout
    ):
        return True

    return False


def check_command(command: str, policy: Policy) -> CommandCheck:
    """
    Check if a command is allowed by the policy.

    Args:
        command: The shell command to check
        policy: The execution policy

    Returns:
        CommandCheck with allowed=True if command is permitted
    """
    normalized = _normalize_command(command)

    # Check git push - if explicitly allowed, skip blocklist check for push
    is_push = _is_git_push(command)
    if is_push:
        if policy.allow_push:
            return CommandCheck(allowed=True, command=command)
        return CommandCheck(
            allowed=False,
            command=command,
            violation_reason="git push is not allowed by policy",
            policy_rule="allow_push",
        )

    # Check git merge - if explicitly allowed, skip blocklist check for merge
    is_merge = _is_git_merge(command)
    if is_merge:
        if policy.allow_merge:
            return CommandCheck(allowed=True, command=command)
        return CommandCheck(
            allowed=False,
            command=command,
            violation_reason="git merge is not allowed by policy",
            policy_rule="allow_merge",
        )

    # Check explicit blocked commands (for non-push/merge commands)
    for blocked in policy.blocked_commands:
        blocked_normalized = _normalize_command(blocked)
        if normalized.startswith(blocked_normalized):
            return CommandCheck(
                allowed=False,
                command=command,
                violation_reason=f"Command matches blocked pattern: {blocked}",
                policy_rule="blocked_commands",
            )

    return CommandCheck(allowed=True, command=command)


class SandboxEnforcer:
    """
    Enforces execution policy for a run.

    Tracks the expected branch and validates commands before execution.
    """

    def __init__(
        self,
        policy: Policy,
        repo_path: Path,
        expected_branch: str,
    ):
        self.policy = policy
        self.repo_path = repo_path
        self.expected_branch = expected_branch
        self._violations: list[PolicyViolation] = []

    @property
    def violations(self) -> list[PolicyViolation]:
        """List of policy violations encountered."""
        return list(self._violations)

    def check(self, command: str) -> CommandCheck:
        """
        Check if a command is allowed.

        Args:
            command: The shell command to check

        Returns:
            CommandCheck result
        """
        return check_command(command, self.policy)

    def enforce(self, command: str) -> None:
        """
        Enforce policy on a command.

        Args:
            command: The shell command to execute

        Raises:
            PolicyViolation: If the command violates policy
        """
        result = self.check(command)
        if not result.allowed:
            violation = PolicyViolation(
                result.violation_reason or "Unknown violation",
                command=command,
                policy_rule=result.policy_rule or "unknown",
                repo_path=self.repo_path,
            )
            self._violations.append(violation)
            raise violation

    def check_branch_switch(self, command: str) -> CommandCheck:
        """
        Check if a command would switch branches.

        Branch switching during a run is blocked to maintain deterministic execution.

        Args:
            command: The shell command to check

        Returns:
            CommandCheck result
        """
        if _is_git_checkout_branch(command):
            return CommandCheck(
                allowed=False,
                command=command,
                violation_reason="Branch switching is not allowed during run execution",
                policy_rule="branch_integrity",
            )
        return CommandCheck(allowed=True, command=command)

    def enforce_branch_integrity(self, command: str) -> None:
        """
        Enforce branch integrity (no branch switching).

        Args:
            command: The shell command to execute

        Raises:
            PolicyViolation: If the command would switch branches
        """
        result = self.check_branch_switch(command)
        if not result.allowed:
            violation = PolicyViolation(
                result.violation_reason or "Branch switch detected",
                command=command,
                policy_rule=result.policy_rule or "branch_integrity",
                repo_path=self.repo_path,
            )
            self._violations.append(violation)
            raise violation

    def full_check(self, command: str) -> None:
        """
        Run all policy checks on a command.

        Args:
            command: The shell command to execute

        Raises:
            PolicyViolation: If any policy check fails
        """
        self.enforce(command)
        self.enforce_branch_integrity(command)
