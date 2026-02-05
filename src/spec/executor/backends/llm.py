"""
llm backend: Call model APIs via the llm package.

Uses the llm package (https://llm.datasette.io/) which supports
multiple providers: OpenAI, Gemini, Anthropic, local models, etc.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec.executor.backends.base import BackendBase, BackendError

if TYPE_CHECKING:
    from spec.executor.schemas import Policy, StepCapture, StepManifest

# Default model - can be overridden in payload or env.
# Use the short alias form accepted by `llm --model ...`.
DEFAULT_MODEL = "gemini-3-pro-preview"


class LlmBackend(BackendBase):
    """
    LLM API call backend using the llm package.

    Payload schema:
        prompt: str - The prompt to send to the model
        context: str | None - Additional context to prepend
        model: str | None - Model to use (default: gemini/gemini-3-pro-preview)
        system: str | None - System prompt
        schema: dict | None - JSON schema for structured output (model must support)
        options: dict | None - Model-specific options (temperature, max_tokens, etc.)
    """

    @property
    def name(self) -> str:
        return "llm"

    def verify(self) -> None:
        """Verify llm is installed and a usable model+key are configured.

        This is intentionally a *non-network* preflight: it checks that the
        model can be resolved and that required keys are present (via llm's
        standard key lookup), but does not make a provider API call.
        """
        import sys

        try:
            import llm
        except ImportError as e:
            raise BackendError(
                "llm package not installed. Install it in the active environment.",
                backend=self.name,
            ) from e

        model_name = os.environ.get("SPECWRIGHT_LLM_MODEL") or DEFAULT_MODEL
        model_name = self._normalize_model_name(model_name)

        # Validate model exists
        try:
            model = llm.get_model(model_name)
        except Exception as e:
            # Provide actionable context without requiring external commands.
            available = []
            try:
                models = list(llm.get_models())
                available = sorted({getattr(m, "model_id", str(m)) for m in models})
            except Exception:
                available = []

            gemini_like = [m for m in available if "gemini" in m.lower()]
            hint_lines = []
            if gemini_like:
                hint_lines.append("Gemini-like models visible to this env:")
                hint_lines.extend(f"- {m}" for m in gemini_like[:10])
            elif available:
                hint_lines.append("Some models visible to this env:")
                hint_lines.extend(f"- {m}" for m in available[:10])
            else:
                hint_lines.append("No models could be enumerated from llm.get_models().")

            user_dir = None
            try:
                user_dir = str(llm.user_dir())
            except Exception:
                user_dir = None

            details = [
                f"Requested model: {model_name}",
                f"Python: {sys.executable}",
            ]
            if user_dir:
                details.append(f"llm user dir: {user_dir}")

            msg = (
                "LLM model is not available in the active Python environment.\n"
                + "\n".join(details)
                + "\n\n"
                + "\n".join(hint_lines)
                + "\n\n"
                + "Fix: install the provider plugin in this environment and/or set SPECWRIGHT_LLM_MODEL to one of the visible models."
            )
            raise BackendError(msg, backend=self.name) from e

        # Validate key exists if needed
        needs_key = getattr(model, "needs_key", None)
        if needs_key:
            try:
                # Many llm provider plugins implement model.get_key()
                get_key = getattr(model, "get_key", None)
                key = get_key() if callable(get_key) else llm.get_key(alias=str(needs_key))
            except Exception:
                key = None

            if not key:
                env_var = getattr(model, "key_env_var", None) or "(provider-specific env var)"
                raise BackendError(
                    (
                        f"Missing LLM key for provider '{needs_key}'.\n"
                        f"Python: {sys.executable}\n"
                        f"Fix: set {env_var} or configure keys for '{needs_key}' via the llm key store in this environment."
                    ),
                    backend=self.name,
                )

        # Optional network preflight (disabled by default): performs a minimal
        # prompt to validate that the provider is reachable and credentials work.
        # Enable with: SPECWRIGHT_LLM_NETWORK_PREFLIGHT=1
        if self._is_truthy(os.environ.get("SPECWRIGHT_LLM_NETWORK_PREFLIGHT")):
            try:
                resp = model.prompt("Reply with exactly: OK")
                text = resp.text().strip() if resp is not None else ""
                if not text.startswith("OK"):
                    raise BackendError(
                        f"LLM network preflight returned unexpected output: {text[:80]!r}",
                        backend=self.name,
                    )
            except BackendError:
                raise
            except Exception as e:
                raise BackendError(
                    f"LLM network preflight failed: {e}",
                    backend=self.name,
                ) from e

    def _is_truthy(self, value: str | None) -> bool:
        if value is None:
            return False
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}

    def _normalize_model_name(self, model_name: str) -> str:
        if model_name.startswith("gemini/gemini-"):
            return model_name.removeprefix("gemini/")
        return model_name

    def dispatch(
        self,
        manifest: StepManifest,
        artifacts_dir: Path,
        policy: Policy,  # noqa: ARG002 - policy not used for LLM calls
        capture_patch: bool = False,  # noqa: ARG002 - LLM doesn't modify repo
    ) -> StepCapture:
        """Call LLM via llm package and capture response."""
        from spec.executor.schemas import AgentCapture, StepCapture

        payload = manifest.payload
        common = manifest.common

        # Handle prompt_type for dynamic prompt building
        prompt_type = payload.get("prompt_type")
        prompt = payload.get("prompt")

        if prompt_type and not prompt:
            prompt = self._build_prompt_for_type(
                prompt_type=prompt_type,
                aip_data=payload.get("aip"),
                epic_spec=payload.get("epic_spec"),
                repo_path=common.repo_path if common else None,
            )

        if not prompt:
            raise BackendError(
                "llm backend requires 'prompt' or 'prompt_type' in payload",
                backend=self.name,
                step_id=manifest.step_id,
            )

        context = payload.get("context", "")
        model_name = (
            payload.get("model")
            or os.environ.get("SPECWRIGHT_LLM_MODEL")
            or DEFAULT_MODEL
        )

        model_name = self._normalize_model_name(str(model_name))
        system = payload.get("system")
        schema = payload.get("schema")
        options = payload.get("options", {})

        # Ensure artifacts directory exists
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = artifacts_dir / "stdout.txt"
        stderr_path = artifacts_dir / "stderr.txt"

        # Build the full prompt
        full_prompt = f"{context}\n\n{prompt}" if context else prompt

        exit_code = 0

        try:
            response = self._call_llm(
                prompt=full_prompt,
                model_name=model_name,
                system=system,
                schema=schema,
                options=options,
            )

            # Write response to stdout
            if schema and isinstance(response, dict):
                # Structured output - write as JSON
                stdout_path.write_text(json.dumps(response, indent=2))
            else:
                # Text output
                stdout_path.write_text(str(response))

            stderr_path.write_text("")

        except Exception as e:
            exit_code = 1
            stdout_path.write_text("")
            stderr_path.write_text(f"LLM error: {e}\n")

        return StepCapture(
            step_n=manifest.step_n,
            step_id=manifest.step_id,
            agent=AgentCapture(
                stdout_file=stdout_path.name,
                stderr_file=stderr_path.name,
                exit_code=exit_code,
            ),
        )

    def _call_llm(
        self,
        prompt: str,
        model_name: str,
        system: str | None,
        schema: dict[str, Any] | None,
        options: dict[str, Any],
    ) -> str | dict[str, Any]:
        """
        Call the LLM via the llm package.

        Args:
            prompt: The prompt text
            model_name: Model name/alias (e.g., 'gemini-2.5-flash', 'gpt-5')
            system: Optional system prompt
            schema: Optional JSON schema for structured output
            options: Model-specific options

        Returns:
            Response text or structured dict
        """
        try:
            import llm
        except ImportError as e:
            raise BackendError(
                "llm package not installed. Run: pip install llm",
                backend=self.name,
            ) from e

        # Get the model
        try:
            model = llm.get_model(model_name)
        except llm.UnknownModelError as e:
            raise BackendError(
                f"Unknown model: {model_name}. Run 'llm models' to see available models.",
                backend=self.name,
            ) from e

        # Build prompt kwargs
        prompt_kwargs: dict[str, Any] = {}
        if system:
            prompt_kwargs["system"] = system

        # Add any model-specific options
        prompt_kwargs.update(options)

        # Execute prompt
        response = model.prompt(prompt, **prompt_kwargs)

        # Get response text
        response_text = response.text()

        # If schema requested, try to parse as JSON
        if schema:
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                # Return raw text if not valid JSON
                return response_text

        return response_text

    def _build_prompt_for_type(
        self,
        prompt_type: str,
        aip_data: dict | None,
        epic_spec: dict | None,
        repo_path: Path | None,
    ) -> str:
        """Build a prompt based on type.

        Args:
            prompt_type: The type of prompt to build
            aip_data: Optional AIP data
            epic_spec: Optional epic spec expectations
            repo_path: Optional repo path for reading the diff

        Returns:
            Built prompt string
        """
        if prompt_type == "acceptance_review":
            return self._build_acceptance_review_prompt(aip_data, epic_spec, repo_path)
        else:
            raise BackendError(
                f"Unknown prompt_type: {prompt_type}",
                backend=self.name,
            )

    def _build_acceptance_review_prompt(
        self,
        aip_data: dict | None,
        epic_spec: dict | None,
        repo_path: Path | None,
    ) -> str:
        """Build the acceptance review prompt with diff and expectations."""
        import subprocess

        parts = ["# Acceptance Criteria Review\n"]

        # Add expectations from AIP
        if aip_data:
            expectations = aip_data.get("expectations", [])
            if expectations:
                parts.append("## Acceptance Criteria (from AIP)\n")
                for i, exp in enumerate(expectations, 1):
                    parts.append(f"{i}. {exp}")
                parts.append("")

        # Add expectations from epic spec
        if epic_spec:
            epic_expectations = epic_spec.get("expectations", [])
            if epic_expectations:
                parts.append("## Epic Expectations (ground truth)\n")
                for i, exp in enumerate(epic_expectations, 1):
                    parts.append(f"{i}. {exp}")
                parts.append("")

        # Get the diff from the repo
        if repo_path and repo_path.exists():
            try:
                # Get diff from base branch
                result = subprocess.run(
                    ["git", "diff", "main...HEAD", "--stat"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    parts.append("## Changed Files\n```")
                    parts.append(result.stdout.strip())
                    parts.append("```\n")

                # Get the actual diff (truncated)
                result = subprocess.run(
                    ["git", "diff", "main...HEAD"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    diff = result.stdout.strip()
                    if len(diff) > 30000:
                        diff = diff[:30000] + "\n... (truncated)"
                    parts.append("## Code Changes (diff)\n```diff")
                    parts.append(diff)
                    parts.append("```\n")
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                parts.append("## Code Changes\n(Unable to retrieve diff)\n")

        # Add the review instructions
        parts.append("""## Instructions

Review the code changes against the acceptance criteria and provide:

1. **Criteria Checklist**: For each acceptance criterion, mark as:
   - [x] MET - criterion is fully satisfied
   - [ ] NOT MET - criterion is not satisfied (explain why)
   - [~] PARTIAL - criterion is partially met (explain gaps)

2. **Summary**: Brief assessment (2-3 sentences) of overall implementation quality

3. **Critical Issues**: Any blocking problems that must be fixed

4. **Recommendations**: Suggested improvements (non-blocking)

Be specific and reference file paths/line numbers where relevant.""")

        return "\n".join(parts)
