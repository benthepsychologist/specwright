"""
Codex CLI Adapter

Adapter for invoking the Codex CLI with strict input/output contract.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from spec.executor.adapters.base import (
    AgentAdapter,
    EscalationRequired,
    ProtocolError,
    ToolNotFoundError,
)

# Required flags for Codex CLI v1 contract
# Each tuple contains alternative flag names (long, short) that satisfy the requirement
REQUIRED_FLAGS: list[tuple[str, ...]] = [
    ("--cd",),
    ("--sandbox",),
    ("--output-schema",),
    ("--output-last-message", "-o"),  # -o is short form
    ("--json",),
]

# Network tools - forbidden as first token (command name)
FORBIDDEN_NETWORK_TOOLS = {"curl", "wget", "ssh", "scp", "rsync", "nc", "netcat"}

# Git write subcommands - forbidden when git is first token
FORBIDDEN_GIT_SUBCOMMANDS = {
    "add",
    "commit",
    "push",
    "apply",
    "checkout",
    "reset",
    "merge",
    "rebase",
    "cherry-pick",
}

# Package manager install commands - forbidden as first token with install anywhere
FORBIDDEN_PACKAGE_MANAGERS = {
    "pip": {"install"},
    "npm": {"install"},
    "yarn": {"add"},
    "cargo": {"install"},
    "brew": {"install"},
    "apt": {"install"},
    "apt-get": {"install"},
}

# Privilege escalation - forbidden as first token
FORBIDDEN_PRIVILEGE_TOOLS = {"sudo", "doas", "su"}

# Dangerous system tools - forbidden as first token
FORBIDDEN_SYSTEM_TOOLS = {"dd", "mkfs", "mount", "umount", "fdisk", "chmod", "chown"}

# rm dangerous flags
RM_DANGEROUS_FLAGS = {"-r", "-rf", "-fr", "--recursive", "-R"}

# Allowed shell wrapper forms - Codex uses these in read-only mode
# e.g., {"type":"command_execution", "command":"bash -lc ls"}
# We allow these specific patterns and parse the inner command
ALLOWED_SHELL_WRAPPERS = {
    ("bash", "-lc"),
    ("bash", "-c"),
    ("sh", "-c"),
    ("sh", "-lc"),
}

# Forbidden shell entrypoints - interactive shells or unusual forms
# These suggest escape attempts, not normal Codex operation
FORBIDDEN_SHELL_FORMS = {
    "zsh",
    "fish",
    "dash",
    "ksh",
    "csh",
    "tcsh",  # Non-standard shells
    "powershell",
    "pwsh",
    "cmd",
    "cmd.exe",  # Windows shells
}

# Shell flags that indicate the next arg is a command string
SHELL_COMMAND_FLAGS = {"-c", "-lc", "-ic", "-lic", "/c", "-Command"}

# Shell compound operators - these enable command chaining
# Soft-fail: ESCALATE_NEEDS_HUMAN (not hard fail FAIL_ADAPTER_PROTOCOL)
# Note: ${ is parameter expansion (common, harmless), not command substitution
SHELL_COMPOUND_OPERATORS = {"&&", "||", ";", "`", "$("}

# Violation prefixes for categorization
# "hard:" -> FAIL_ADAPTER_PROTOCOL (dangerous tools, privilege escalation)
# "escalate:" -> ESCALATE_NEEDS_HUMAN (compound operators, unusual patterns)
VIOLATION_PREFIX_HARD = "hard:"
VIOLATION_PREFIX_ESCALATE = "escalate:"

# Default timeout for Codex execution (10 minutes)
CODEX_TIMEOUT_SECONDS = 600


def is_hard_violation(violation: str) -> bool:
    """Check if violation requires hard fail (FAIL_ADAPTER_PROTOCOL)."""
    return violation.startswith(VIOLATION_PREFIX_HARD)


def is_escalation_violation(violation: str) -> bool:
    """Check if violation requires escalation (ESCALATE_NEEDS_HUMAN)."""
    return violation.startswith(VIOLATION_PREFIX_ESCALATE)


def _tokenize_command(command: str) -> list[str]:
    """
    Tokenize a command string into tokens for analysis.

    Uses shlex for proper shell parsing, falls back to split on failure.
    """
    try:
        return shlex.split(command)
    except ValueError:
        # Malformed command, fall back to simple split
        return command.split()


def _is_allowed_shell_wrapper(tokens: list[str]) -> bool:
    """
    Check if tokens represent an allowed Codex shell wrapper form.

    Allowed forms: bash -c, bash -lc, sh -c, sh -lc
    Forbidden: zsh, fish, powershell, etc.
    """
    if len(tokens) < 2:
        return False

    base_cmd = tokens[0].split("/")[-1].lower()

    # Check against allowed wrapper forms
    for allowed_cmd, allowed_flag in ALLOWED_SHELL_WRAPPERS:
        if base_cmd == allowed_cmd:
            # Look for the flag anywhere in the command
            for token in tokens[1:]:
                if token.lower() == allowed_flag:
                    return True

    return False


def _is_forbidden_shell(tokens: list[str]) -> str | None:
    """
    Check if tokens use a forbidden shell entrypoint.

    Returns the forbidden shell name if found, None otherwise.
    """
    if not tokens:
        return None

    base_cmd = tokens[0].split("/")[-1].lower()

    if base_cmd in FORBIDDEN_SHELL_FORMS:
        return base_cmd

    return None


def _extract_inner_command(command: str) -> tuple[str | None, str | None]:
    """
    If command is a shell invocation (e.g., 'bash -lc ls'), extract the inner command.

    Returns:
        Tuple of (inner_command, violation_or_none)
        - If allowed shell wrapper: (inner_command, None)
        - If forbidden shell: (None, "forbidden_shell:<shell>")
        - If not a shell wrapper: (None, None)
    """
    tokens = _tokenize_command(command)
    if not tokens:
        return None, None

    base_cmd = tokens[0].split("/")[-1].lower()

    # Check for forbidden shells first
    forbidden = _is_forbidden_shell(tokens)
    if forbidden:
        return None, f"{VIOLATION_PREFIX_HARD}forbidden_shell:{forbidden}"

    # Check if this is an allowed Codex shell wrapper
    if not _is_allowed_shell_wrapper(tokens):
        # Not a shell invocation at all - return None, let caller check raw command
        # We only enter shell-parsing mode for bash/sh
        if base_cmd not in ("bash", "sh"):
            return None, None
        # It's bash/sh but not in allowed form (e.g., interactive mode)
        # This is suspicious but not necessarily fatal - escalate
        return None, f"{VIOLATION_PREFIX_ESCALATE}unusual_shell_form:{command[:50]}"

    # Look for shell command flag (-c, -lc, etc.)
    for i, token in enumerate(tokens[1:], start=1):
        if token.lower() in SHELL_COMMAND_FLAGS:
            # The command string is the next token(s)
            if i + 1 < len(tokens):
                # Join remaining tokens as the inner command
                return " ".join(tokens[i + 1 :]), None
            return None, None

    return None, None


def _check_single_command(command: str) -> str | None:
    """
    Check a single command for forbidden patterns using token-aware matching.

    Returns:
        - None if command is allowed
        - "hard:<violation>" for FAIL_ADAPTER_PROTOCOL (dangerous tools)
        - "escalate:<violation>" for ESCALATE_NEEDS_HUMAN (compound operators, unusual forms)

    Policy:
    - Codex emits shell invocations like "bash -lc ls" even in read-only mode
    - We parse the inner command and apply safety checks to it
    - Compound operators (&&, ||, ;, backticks, $()) -> escalate (soft fail)
    - Dangerous tools (rm -r, network tools, etc.) -> hard fail
    - Allow safe read operations (ls, cat, grep, find, git status, etc.)
    """
    # Check if this is a shell-wrapped command
    inner_command, shell_violation = _extract_inner_command(command)

    # If shell wrapper check found a violation, return it
    if shell_violation:
        return shell_violation

    # Use inner command if extracted, otherwise check raw command
    command_to_check = inner_command if inner_command else command

    # Check for compound operators inside the command string
    # These are soft-fail (escalate) - might be legitimate piping
    for op in SHELL_COMPOUND_OPERATORS:
        if op in command_to_check:
            return f"{VIOLATION_PREFIX_ESCALATE}shell_compound:{op}"

    tokens = _tokenize_command(command_to_check.lower())
    if not tokens:
        return None

    # Get the base command (handle paths like /usr/bin/rm)
    first_token = tokens[0]
    base_cmd = first_token.split("/")[-1]

    # Also check for python -m <module> pattern
    effective_cmd = base_cmd
    remaining_tokens = tokens[1:]

    if base_cmd in ("python", "python3") and len(tokens) >= 3 and tokens[1] == "-m":
        effective_cmd = tokens[2]
        remaining_tokens = tokens[3:]

    # 1. Network tools - forbidden as first token (HARD FAIL)
    if effective_cmd in FORBIDDEN_NETWORK_TOOLS:
        return f"{VIOLATION_PREFIX_HARD}network_tool:{effective_cmd}"

    # 2. Privilege escalation - forbidden as first token (HARD FAIL)
    if effective_cmd in FORBIDDEN_PRIVILEGE_TOOLS:
        return f"{VIOLATION_PREFIX_HARD}privilege_escalation:{effective_cmd}"

    # 3. Dangerous system tools - forbidden as first token (HARD FAIL)
    if effective_cmd in FORBIDDEN_SYSTEM_TOOLS:
        return f"{VIOLATION_PREFIX_HARD}system_tool:{effective_cmd}"

    # 4. rm with dangerous flags anywhere in args (HARD FAIL)
    if effective_cmd == "rm":
        for token in remaining_tokens:
            # Check for combined flags like -rf, -fr, or separate -r -f
            if token in RM_DANGEROUS_FLAGS:
                return f"{VIOLATION_PREFIX_HARD}rm_recursive:{token}"
            # Also catch -rf combined with other flags like -rfi
            if token.startswith("-") and ("r" in token or "R" in token):
                if "f" in token or len(token) > 2:  # -rf or -ri etc
                    return f"{VIOLATION_PREFIX_HARD}rm_recursive:{token}"

    # 5. Git with write subcommands anywhere in args (HARD FAIL)
    if effective_cmd == "git":
        for token in remaining_tokens:
            if token in FORBIDDEN_GIT_SUBCOMMANDS:
                return f"{VIOLATION_PREFIX_HARD}git_write:{token}"

    # 6. Package managers with install subcommand (HARD FAIL)
    if effective_cmd in FORBIDDEN_PACKAGE_MANAGERS:
        forbidden_subcommands = FORBIDDEN_PACKAGE_MANAGERS[effective_cmd]
        for token in remaining_tokens:
            if token in forbidden_subcommands:
                return f"{VIOLATION_PREFIX_HARD}package_install:{effective_cmd} {token}"

    return None


class CodexAdapter(AgentAdapter):
    """Adapter for the Codex CLI."""

    def __init__(self) -> None:
        self._verified = False
        self._preflight_status: str = "pending"  # pending, verified, inconclusive
        self._preflight_reason: str | None = None

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "codex"

    @property
    def preflight_status(self) -> str:
        """Return preflight verification status: 'pending', 'verified', or 'inconclusive'."""
        return self._preflight_status

    @property
    def preflight_reason(self) -> str | None:
        """Return reason if preflight was inconclusive."""
        return self._preflight_reason

    def verify(self) -> None:
        """
        Verify Codex CLI exists and supports required flags.

        Raises:
            ToolNotFoundError: If codex not in PATH
            ProtocolError: If required flags CLEARLY not supported

        Note:
            If help text parsing is inconclusive (timeout, empty, etc.),
            we proceed with preflight_status="inconclusive" rather than
            hard-failing. Execution attempt becomes the real test.
        """
        # 1. Check codex exists - this is a hard requirement
        if shutil.which("codex") is None:
            raise ToolNotFoundError("codex", "codex not found in PATH")

        # 2. Try to check `codex exec --help` for required flags
        # But degrade gracefully if help text is unavailable/unparseable
        help_text = ""
        try:
            result = subprocess.run(
                ["codex", "exec", "--help"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            help_text = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            # Help timed out - inconclusive, proceed with caution
            self._preflight_status = "inconclusive"
            self._preflight_reason = "codex exec --help timed out"
            self._verified = True
            return
        except FileNotFoundError as err:
            raise ToolNotFoundError("codex", "codex not found in PATH") from err

        # If help text is empty or very short, consider inconclusive
        if len(help_text.strip()) < 50:
            self._preflight_status = "inconclusive"
            self._preflight_reason = "help text too short to parse"
            self._verified = True
            return

        # Each requirement is satisfied if ANY of its alternative flags appear
        missing: list[str] = []
        for flag_alternatives in REQUIRED_FLAGS:
            if not any(flag in help_text for flag in flag_alternatives):
                # Report the primary (long) flag name for clarity
                missing.append(flag_alternatives[0])

        if missing:
            # Flags are CLEARLY missing - this is a hard failure
            raise ProtocolError(
                f"Codex CLI missing required flags: {missing}",
                failure_category="tool_contract_mismatch",
            )

        self._preflight_status = "verified"
        self._preflight_reason = None
        self._verified = True

    def execute(
        self,
        input_dir: Path,
        output_dir: Path,
        repo_root: Path,
        timeout: int = CODEX_TIMEOUT_SECONDS,
    ) -> None:
        """
        Execute Codex CLI and extract artifacts.

        Args:
            input_dir: Directory containing contract.yaml, prompt.md, repo_state.json
            output_dir: Directory where adapter writes patch.diff, agent.json, cmdlog.txt
            repo_root: Repository root for --cd flag
            timeout: Timeout in seconds

        Raises:
            ToolNotFoundError: If codex not found
            ProtocolError: If adapter contract violated
        """
        # Ensure verified before execution
        if not self._verified:
            self.verify()

        # Read repo_state.json for config
        repo_state = self._read_repo_state(input_dir)

        # Build command
        output_dir.mkdir(parents=True, exist_ok=True)
        last_message_path = output_dir / "last_message.json"
        schema_path = repo_root / repo_state.get(
            "codex_output_schema_path",
            "artifacts/schemas/codex_output.schema.json",
        )
        sandbox_mode = repo_state.get("codex_sandbox_mode", "read-only")

        # Validate sandbox mode is read-only for v1
        if sandbox_mode != "read-only":
            raise ProtocolError(
                f"v1 requires sandbox mode 'read-only', got '{sandbox_mode}'",
                failure_category="tool_contract_mismatch",
            )

        prompt_path = input_dir / "prompt.md"
        if not prompt_path.exists():
            raise ProtocolError(
                f"prompt.md not found in {input_dir}",
                failure_category="missing_input",
            )

        codex_command = [
            "codex",
            "exec",
            "--cd",
            str(repo_root),
            "--sandbox",
            sandbox_mode,
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(last_message_path),
            "--json",
        ]

        # Execute Codex
        try:
            prompt_content = prompt_path.read_text()
            result = subprocess.run(
                codex_command,
                input=prompt_content,
                capture_output=True,
                timeout=timeout,
                cwd=repo_root,
                text=True,
            )
        except subprocess.TimeoutExpired as err:
            raise ProtocolError(
                f"Codex timed out after {timeout}s",
                failure_category="timeout",
            ) from err
        except FileNotFoundError as err:
            raise ToolNotFoundError("codex", "codex not found in PATH") from err

        # Check exit code
        if result.returncode != 0:
            raise ProtocolError(
                f"Codex exited with code {result.returncode}: {result.stderr[:500]}",
                failure_category="codex_error",
            )

        # Parse JSON event stream for command log and extract actual commands
        cmdlog, commands_executed = self._parse_event_stream(result.stdout)
        (output_dir / "cmdlog.txt").write_text(cmdlog)

        # Check for forbidden commands - ONLY checks actual command strings,
        # not output text that might mention forbidden commands
        violations = self._check_forbidden_commands(commands_executed)

        # Separate hard failures from escalations
        hard_violations = [v for v in violations if is_hard_violation(v)]
        escalation_violations = [v for v in violations if is_escalation_violation(v)]

        # Hard violations cause immediate failure
        if hard_violations:
            raise ProtocolError(
                f"Forbidden command patterns detected: {hard_violations}",
                failure_category="forbidden_command",
            )

        # Escalation violations require human review (ESCALATE_NEEDS_HUMAN, not FAIL)
        if escalation_violations:
            raise EscalationRequired(
                f"Commands require human review: {escalation_violations}",
                violations=escalation_violations,
            )

        # Extract artifacts from last_message.json
        self._extract_artifacts(last_message_path, output_dir)

    def _read_repo_state(self, input_dir: Path) -> dict[str, Any]:
        """Read and validate repo_state.json."""
        repo_state_path = input_dir / "repo_state.json"
        if not repo_state_path.exists():
            raise ProtocolError(
                f"repo_state.json not found in {input_dir}",
                failure_category="missing_input",
            )

        try:
            with open(repo_state_path) as f:
                data: dict[str, Any] = json.load(f)
                return data
        except json.JSONDecodeError as err:
            raise ProtocolError(
                f"repo_state.json is not valid JSON: {err}",
                failure_category="invalid_input",
            ) from err

    def _parse_event_stream(self, stdout: str) -> tuple[str, list[str]]:
        """
        Parse JSON event stream from Codex --json output.

        Returns:
            Tuple of (cmdlog.txt formatted text, list of actual command strings)

        The command list is used for forbidden command checking - we only check
        the actual commands executed, NOT output text that might mention forbidden
        commands in documentation, test output, or code snippets.
        """
        cmdlog_lines: list[str] = []
        commands_executed: list[str] = []

        for line in stdout.strip().split("\n"):
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # Skip non-JSON lines
                continue

            # Codex emits command_execution events with the actual command
            event_type = event.get("type", "")
            if event_type in ("command", "command_execution"):
                timestamp = event.get("timestamp", "")
                command = event.get("command", "")
                exit_code = event.get("exit_code", 0)
                duration = event.get("duration_ms", 0)

                # Track the actual command for forbidden pattern checking
                if command:
                    commands_executed.append(command)

                cmdlog_lines.append(f"[{timestamp}] CMD: {command}")
                cmdlog_lines.append(f"[{timestamp}] EXIT: {exit_code}")
                cmdlog_lines.append(f"[{timestamp}] DURATION: {duration}ms")
                cmdlog_lines.append("---")

        return "\n".join(cmdlog_lines), commands_executed

    def _check_forbidden_commands(self, commands: list[str]) -> list[str]:
        """
        Check actual executed commands for forbidden patterns using token-aware matching.

        IMPORTANT: This checks ONLY the command strings extracted from JSONL events,
        NOT arbitrary output text. This avoids false positives from:
        - Code snippets printed in agent messages
        - Test output mentioning sudo, curl, etc.
        - Documentation content

        Token-aware matching catches:
        - rm with -r/-rf flags anywhere in args
        - git with write subcommands anywhere in args
        - python -m pip install (not just "pip install")
        - Network tools as first token
        - Privilege escalation as first token

        Args:
            commands: List of actual command strings from command_execution events

        Returns:
            List of violation descriptions. Empty list = passed.
        """
        violations: list[str] = []

        for command in commands:
            violation = _check_single_command(command)
            if violation and violation not in violations:
                violations.append(violation)

        return violations

    def _extract_artifacts(self, last_message_path: Path, output_dir: Path) -> None:
        """
        Extract patch.diff and agent.json from last_message.json.

        Raises:
            ProtocolError: If extraction fails
        """
        if not last_message_path.exists():
            raise ProtocolError(
                "last_message.json not found - Codex didn't produce structured output",
                failure_category="missing_output",
            )

        try:
            with open(last_message_path) as f:
                output = json.load(f)
        except json.JSONDecodeError as err:
            raise ProtocolError(
                f"last_message.json is not valid JSON: {err}",
                failure_category="invalid_output",
            ) from err

        # Extract patch
        patch_diff = output.get("patch_diff")
        if patch_diff is None:
            raise ProtocolError(
                "last_message.json missing 'patch_diff' field",
                failure_category="invalid_output",
            )
        (output_dir / "patch.diff").write_text(patch_diff)

        # Extract agent report
        agent_report = output.get("agent")
        if agent_report is None:
            raise ProtocolError(
                "last_message.json missing 'agent' field",
                failure_category="invalid_output",
            )

        # Validate agent report has required fields
        required_agent_fields = [
            "files_modified",
            "commands_executed",
            "confidence",
            "completion_status",
        ]
        missing_fields = [f for f in required_agent_fields if f not in agent_report]
        if missing_fields:
            raise ProtocolError(
                f"agent report missing required fields: {missing_fields}",
                failure_category="invalid_output",
            )

        with open(output_dir / "agent.json", "w") as f:
            json.dump(agent_report, f, indent=2)

        # Validate consistency: files_modified should not be empty if patch is non-empty
        if patch_diff.strip() and not agent_report.get("files_modified"):
            raise ProtocolError(
                "patch_diff is non-empty but files_modified is empty",
                failure_category="inconsistent_output",
            )


def check_forbidden_commands(commands: list[str]) -> list[str]:
    """
    Public function to check commands for forbidden patterns using token-aware matching.

    IMPORTANT: Pass actual command strings, not raw output text.
    This avoids false positives from documentation, test output, or code snippets.

    Token-aware matching catches:
    - Shell wrappers (bash -lc, sh -c) - extracts and checks inner command
    - rm with -r/-rf flags anywhere in args (not just adjacent)
    - git with write subcommands anywhere in args
    - python -m pip install (not just "pip install")
    - Network tools (curl, wget, ssh) as first token
    - Privilege escalation (sudo, doas) as first token
    - Forbidden shells (zsh, fish, powershell, etc.)
    - Shell compound operators (&&, ||, ;, backticks, $())

    Args:
        commands: List of actual command strings executed

    Returns:
        List of violation descriptions prefixed with severity:
        - "hard:<violation>" -> FAIL_ADAPTER_PROTOCOL (dangerous tools)
        - "escalate:<violation>" -> ESCALATE_NEEDS_HUMAN (compound operators)
        Empty list = passed.

    Use is_hard_violation() and is_escalation_violation() to categorize results.
    """
    violations: list[str] = []

    for command in commands:
        violation = _check_single_command(command)
        if violation and violation not in violations:
            violations.append(violation)

    return violations


def parse_commands_from_cmdlog(cmdlog_path: Path) -> list[str]:
    """
    Extract command strings from a cmdlog.txt file.

    This parses lines like "[timestamp] CMD: <command>" and extracts
    just the command portion for forbidden command checking.

    Args:
        cmdlog_path: Path to cmdlog.txt file

    Returns:
        List of command strings
    """
    commands: list[str] = []
    cmdlog = cmdlog_path.read_text()

    for line in cmdlog.split("\n"):
        if "] CMD: " in line:
            # Extract command after "CMD: "
            cmd_start = line.find("] CMD: ") + 7
            command = line[cmd_start:].strip()
            if command:
                commands.append(command)

    return commands
