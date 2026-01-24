"""
llm backend: Call model APIs via the llm package.

Uses the llm package (https://llm.datasette.io/) which supports
multiple providers: OpenAI, Gemini, Anthropic, local models, etc.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec.executor.backends.base import BackendBase, BackendError

if TYPE_CHECKING:
    from spec.executor.schemas import Policy, StepCapture, StepManifest

# Default model - can be overridden in payload
DEFAULT_MODEL = "gemini/gemini-3-pro-preview"


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
        """Verify llm package is available."""
        try:
            import llm  # noqa: F401
        except ImportError as e:
            raise BackendError(
                "llm package not installed. Run: pip install llm",
                backend=self.name,
            ) from e

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

        # Extract payload fields
        prompt = payload.get("prompt")
        if not prompt:
            raise BackendError(
                "llm backend requires 'prompt' in payload",
                backend=self.name,
                step_id=manifest.step_id,
            )

        context = payload.get("context", "")
        model_name = payload.get("model", DEFAULT_MODEL)
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
