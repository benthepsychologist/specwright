"""LLM client module for interacting with language models.

This module provides the LLMClient class which wraps the llm package
to provide a consistent interface for prompt execution with timeout handling.
"""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING

from spec.autogov.exceptions import SpecwrightError

if TYPE_CHECKING:
    from spec.llm.config import LLMConfig


class LLMExecutionError(SpecwrightError):
    """LLM execution error."""

    exit_code = 5


class _TimeoutError(Exception):
    """Internal timeout error for signal handling."""

    pass


def _timeout_handler(signum: int, frame: object) -> None:
    """Signal handler for timeout."""
    raise _TimeoutError("LLM request timed out")


class LLMClient:
    """Client for interacting with LLM models.

    Uses the llm package to send prompts and receive responses.
    Handles timeouts using signal.SIGALRM.
    """

    def __init__(self, config: LLMConfig, model_name: str) -> None:
        """Initialize the LLM client.

        Args:
            config: LLM configuration with timeout settings.
            model_name: Name of the model to use (from check.model or epic.defaults.model).
        """
        self.config = config
        self.model_name = model_name
        self._model: object | None = None

    def _get_model(self) -> object:
        """Lazy-load the LLM model.

        Returns:
            The loaded LLM model.

        Raises:
            LLMExecutionError: If the llm package is not installed,
                the model is not found, or loading fails.
        """
        if self._model is None:
            try:
                import llm

                self._model = llm.get_model(self.model_name)
            except ImportError as e:
                raise LLMExecutionError(
                    "llm package not installed. Run: pip install llm",
                    exit_code=5,
                ) from e
            except Exception as e:
                # Check if it's an UnknownModelError by checking the exception type name
                # This avoids importing llm.UnknownModelError which may fail
                if type(e).__name__ == "UnknownModelError":
                    raise LLMExecutionError(
                        f"Model '{self.model_name}' not found. "
                        f"Run 'llm models' to see available models, or "
                        f"'llm install llm-<provider>' to add a provider.",
                        exit_code=5,
                    ) from e
                raise LLMExecutionError(
                    f"Failed to load model {self.model_name}: {e}"
                ) from e
        return self._model

    def prompt(self, text: str) -> str:
        """Send prompt to LLM and return response.

        Handles timeouts and translates errors to LLMExecutionError.

        Args:
            text: The prompt text to send.

        Returns:
            The LLM response text.

        Raises:
            LLMExecutionError: On timeout or other execution errors.
        """
        model = self._get_model()
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        try:
            signal.alarm(self.config.timeout_s)
            response = model.prompt(text)  # type: ignore[union-attr]
            return response.text()
        except _TimeoutError as e:
            raise LLMExecutionError(
                f"LLM request timed out after {self.config.timeout_s} seconds"
            ) from e
        except LLMExecutionError:
            raise
        except Exception as e:
            raise LLMExecutionError(f"LLM execution failed: {e}") from e
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    def prompt_with_system(self, system: str, user: str) -> str:
        """Send prompt with system message.

        Args:
            system: The system message to set context.
            user: The user prompt text.

        Returns:
            The LLM response text.

        Raises:
            LLMExecutionError: On timeout or other execution errors.
        """
        model = self._get_model()
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        try:
            signal.alarm(self.config.timeout_s)
            response = model.prompt(user, system=system)  # type: ignore[union-attr]
            return response.text()
        except _TimeoutError as e:
            raise LLMExecutionError(
                f"LLM request timed out after {self.config.timeout_s} seconds"
            ) from e
        except LLMExecutionError:
            raise
        except Exception as e:
            raise LLMExecutionError(f"LLM execution failed: {e}") from e
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
