"""
llm backend: Call model APIs via the llm package.

Uses the llm package (https://llm.datasette.io/) which supports
multiple providers: OpenAI, Gemini, Anthropic, local models, etc.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

from spec.executor.backends.base import BackendBase, BackendError

if TYPE_CHECKING:
    from spec.executor.schemas import Policy, StepCapture, StepManifest

# Default model - can be overridden in payload or env.
# Use the short alias form accepted by `llm --model ...`.
DEFAULT_MODEL = "gemini-3-pro-preview"
FALLBACK_MODEL = "azure-gpt52"


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

        Tries the primary model first.  If any check fails (resolution, key,
        or network preflight), falls back to FALLBACK_MODEL.  If the fallback
        also fails, the *primary* error is raised.
        """
        try:
            import llm  # noqa: F401
        except ImportError as e:
            raise BackendError(
                "llm package not installed. Install it in the active environment.",
                backend=self.name,
            ) from e

        model_name = os.environ.get("SPECWRIGHT_LLM_MODEL") or DEFAULT_MODEL
        model_name = self._normalize_model_name(model_name)
        fallback_name = os.environ.get("SPECWRIGHT_LLM_FALLBACK") or FALLBACK_MODEL
        do_network = self._is_truthy(os.environ.get("SPECWRIGHT_LLM_NETWORK_PREFLIGHT"))

        # Try primary model
        primary_err = self._verify_model(model_name, network=do_network)
        if primary_err is None:
            return

        # Primary failed — try fallback
        if model_name == fallback_name:
            raise primary_err

        log.warning(
            "Primary model %s failed verification (%s), trying fallback %s",
            model_name,
            primary_err,
            fallback_name,
        )

        fallback_err = self._verify_model(fallback_name, network=do_network)
        if fallback_err is None:
            # Fallback verified — pin it so dispatch uses it too.
            os.environ["SPECWRIGHT_LLM_MODEL"] = fallback_name
            log.info("Fallback model %s verified; set as active model", fallback_name)
            return

        # Both failed — log fallback error, raise combined error.
        log.warning(
            "Fallback model %s also failed verification: %s",
            fallback_name,
            fallback_err,
        )
        raise BackendError(
            f"Primary model ({model_name}) and fallback ({fallback_name}) both failed.\n"
            f"  Primary: {primary_err}\n"
            f"  Fallback: {fallback_err}",
            backend=self.name,
        )

    def _verify_model(self, model_name: str, *, network: bool = False) -> BackendError | None:
        """Verify a single model.  Returns None on success, BackendError on failure."""
        import sys

        import llm

        # --- resolve model ---
        try:
            model = llm.get_model(model_name)
        except Exception as e:
            available = []
            try:
                available = sorted(
                    {getattr(m, "model_id", str(m)) for m in llm.get_models()}
                )
            except Exception:
                pass

            hint = available[:10] if available else ["(none enumerated)"]
            return BackendError(
                f"Model {model_name!r} not available.\n"
                f"  Python: {sys.executable}\n"
                f"  visible models: {', '.join(hint)}",
                backend=self.name,
            )

        # --- check key ---
        needs_key = getattr(model, "needs_key", None)
        if needs_key:
            try:
                get_key = getattr(model, "get_key", None)
                key = get_key() if callable(get_key) else llm.get_key(alias=str(needs_key))
            except Exception:
                key = None
            if not key:
                env_var = getattr(model, "key_env_var", None) or "(provider-specific env var)"
                return BackendError(
                    f"Missing LLM key for provider {needs_key!r} (model {model_name}).\n"
                    f"  Fix: set {env_var} or configure via llm key store.",
                    backend=self.name,
                )

        # --- optional network preflight ---
        if network:
            try:
                resp = model.prompt("Reply with exactly: OK")
                text = resp.text().strip() if resp is not None else ""
                if not text.startswith("OK"):
                    return BackendError(
                        f"Network preflight for {model_name} returned unexpected output: {text[:80]!r}",
                        backend=self.name,
                    )
            except Exception as e:
                return BackendError(
                    f"Network preflight failed for {model_name}: {e}",
                    backend=self.name,
                )

        return None

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
                spec_md=payload.get("spec_md"),
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
            stderr_path.write_text(str(e))

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

        # Build request context for error reporting
        model_id = getattr(model, "model_id", model_name)
        api_url = None
        try:
            # Gemini models build their URL from gemini_model_id
            gemini_id = getattr(model, "gemini_model_id", None)
            if gemini_id:
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_id}:streamGenerateContent"
            # OpenAI-compatible models expose api_base
            if not api_url:
                api_base = getattr(model, "api_base", None)
                if isinstance(api_base, str):
                    api_url = api_base
        except Exception:
            pass

        # Execute prompt with fallback
        response_text = self._call_with_fallback(
            model=model,
            model_name=model_name,
            model_id=model_id,
            api_url=api_url,
            prompt=prompt,
            prompt_kwargs=prompt_kwargs,
            system=system,
            options=options,
        )

        # If schema requested, try to parse as JSON
        if schema:
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                # Return raw text if not valid JSON
                return response_text

        return response_text

    def _call_with_fallback(
        self,
        *,
        model: Any,
        model_name: str,
        model_id: str,
        api_url: str | None,
        prompt: str,
        prompt_kwargs: dict[str, Any],
        system: str | None,
        options: dict[str, Any],
    ) -> str:
        """Try the primary model; on failure, retry with FALLBACK_MODEL."""
        import llm

        try:
            response = model.prompt(prompt, **prompt_kwargs)
            return response.text()
        except Exception as primary_err:
            # If we're already on the fallback model, don't recurse.
            fallback_name = os.environ.get("SPECWRIGHT_LLM_FALLBACK") or FALLBACK_MODEL
            if model_name == fallback_name:
                self._raise_llm_error(primary_err, model_id, api_url, prompt, system, options)

            log.warning(
                "Primary model %s failed (%s), falling back to %s",
                model_name,
                primary_err,
                fallback_name,
            )

            try:
                fallback = llm.get_model(fallback_name)
            except Exception:
                # Fallback model not available — raise original error.
                self._raise_llm_error(primary_err, model_id, api_url, prompt, system, options)

            try:
                response = fallback.prompt(prompt, **prompt_kwargs)
                text = response.text()
                log.info("Fallback model %s succeeded", fallback_name)
                return text
            except Exception as fallback_err:
                # Both failed — report both errors.
                prompt_preview = prompt[:300] + "..." if len(prompt) > 300 else prompt
                error_lines = [
                    f"Primary model ({model_name}) and fallback ({fallback_name}) both failed.",
                    "",
                    f"--- primary error ({model_name}) ---",
                    f"  {primary_err}",
                    "",
                    f"--- fallback error ({fallback_name}) ---",
                    f"  {fallback_err}",
                    "",
                    "--- request context ---",
                    f"  prompt_length: {len(prompt)}",
                    f"  prompt_preview: {prompt_preview!r}",
                ]
                raise RuntimeError("\n".join(error_lines)) from fallback_err

    def _raise_llm_error(
        self,
        err: Exception,
        model_id: str,
        api_url: str | None,
        prompt: str,
        system: str | None,
        options: dict[str, Any],
    ) -> None:
        """Raise a RuntimeError with detailed request context."""
        prompt_preview = prompt[:300] + "..." if len(prompt) > 300 else prompt
        error_lines = [
            f"LLM error: {err}",
            "",
            "--- request context ---",
            f"  model: {model_id}",
            f"  endpoint: {api_url or 'unknown'}",
            f"  exception: {type(err).__module__}.{type(err).__qualname__}",
            f"  system: {system[:200]!r}" if system else "  system: None",
            f"  options: {options!r}",
            f"  prompt_length: {len(prompt)}",
            f"  prompt_preview: {prompt_preview!r}",
        ]
        raise RuntimeError("\n".join(error_lines)) from err

    def _build_prompt_for_type(
        self,
        prompt_type: str,
        aip_data: dict | None,
        epic_spec: dict | None,
        repo_path: Path | None,
        spec_md: str | None = None,
    ) -> str:
        """Build a prompt based on type.

        Args:
            prompt_type: The type of prompt to build
            aip_data: Optional AIP data
            epic_spec: Optional epic spec expectations
            repo_path: Optional repo path for reading the diff
            spec_md: Optional full spec markdown content

        Returns:
            Built prompt string
        """
        if prompt_type == "acceptance_review":
            return self._build_acceptance_review_prompt(aip_data, epic_spec, repo_path, spec_md)
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
        spec_md: str | None = None,
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

        # Add full spec if provided
        if spec_md:
            parts.append("## Full Spec (Acceptance Criteria Ground Truth)\n")
            parts.append(spec_md)
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
