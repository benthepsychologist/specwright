"""Tests for LLM client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spec.llm.client import LLMClient, LLMExecutionError
from spec.llm.config import LLMConfig


class TestLLMExecutionError:
    """Tests for LLMExecutionError."""

    def test_exit_code_default(self) -> None:
        """Test that LLMExecutionError has exit_code 5 by default."""
        error = LLMExecutionError("test error")
        assert error.exit_code == 5

    def test_exit_code_override(self) -> None:
        """Test that exit_code can be overridden."""
        error = LLMExecutionError("test error", exit_code=10)
        assert error.exit_code == 10

    def test_message(self) -> None:
        """Test that error message is preserved."""
        error = LLMExecutionError("test error message")
        assert str(error) == "test error message"


class TestLLMClientInit:
    """Tests for LLMClient initialization."""

    def test_init_stores_config_and_model_name(self) -> None:
        """Test that config and model_name are stored."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "gpt-4")
        assert client.config is config
        assert client.model_name == "gpt-4"
        assert client._model is None


class TestLLMClientGetModel:
    """Tests for LLMClient._get_model()."""

    def test_get_model_imports_llm_and_gets_model(self) -> None:
        """Test that _get_model imports llm and calls get_model."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "gpt-4")

        mock_model = MagicMock()
        with patch.dict("sys.modules", {"llm": MagicMock()}):
            import sys

            sys.modules["llm"].get_model = MagicMock(return_value=mock_model)
            model = client._get_model()
            assert model is mock_model
            sys.modules["llm"].get_model.assert_called_once_with("gpt-4")

    def test_get_model_caches_model(self) -> None:
        """Test that _get_model caches the model."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "gpt-4")

        mock_model = MagicMock()
        with patch.dict("sys.modules", {"llm": MagicMock()}):
            import sys

            sys.modules["llm"].get_model = MagicMock(return_value=mock_model)
            model1 = client._get_model()
            model2 = client._get_model()
            assert model1 is model2
            # Should only be called once due to caching
            sys.modules["llm"].get_model.assert_called_once()

    def test_get_model_raises_on_import_error(self) -> None:
        """Test that _get_model raises LLMExecutionError on ImportError."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "gpt-4")

        import builtins
        import sys

        # Store original import and module state
        original_import = builtins.__import__
        original_modules = sys.modules.copy()

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "llm":
                raise ImportError("No module named 'llm'")
            return original_import(name, *args, **kwargs)

        try:
            # Remove llm from sys.modules to force re-import
            if "llm" in sys.modules:
                del sys.modules["llm"]
            builtins.__import__ = mock_import

            with pytest.raises(LLMExecutionError) as excinfo:
                client._get_model()

            assert "llm package not installed" in str(excinfo.value)
            assert excinfo.value.exit_code == 5
        finally:
            builtins.__import__ = original_import
            sys.modules.update(original_modules)

    def test_get_model_raises_on_unknown_model_error(self) -> None:
        """Test that _get_model raises LLMExecutionError for unknown model."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "unknown-model")

        # Create a mock UnknownModelError
        class UnknownModelError(Exception):
            pass

        mock_llm = MagicMock()
        mock_llm.get_model = MagicMock(side_effect=UnknownModelError("unknown-model"))

        with patch.dict("sys.modules", {"llm": mock_llm}):
            with pytest.raises(LLMExecutionError) as excinfo:
                client._get_model()

            assert "Model 'unknown-model' not found" in str(excinfo.value)
            assert "llm models" in str(excinfo.value)
            assert excinfo.value.exit_code == 5

    def test_get_model_raises_on_other_exception(self) -> None:
        """Test that _get_model wraps other exceptions."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "gpt-4")

        mock_llm = MagicMock()
        mock_llm.get_model = MagicMock(side_effect=RuntimeError("connection failed"))

        with patch.dict("sys.modules", {"llm": mock_llm}):
            with pytest.raises(LLMExecutionError) as excinfo:
                client._get_model()

            assert "Failed to load model gpt-4" in str(excinfo.value)
            assert "connection failed" in str(excinfo.value)


class TestLLMClientPrompt:
    """Tests for LLMClient.prompt()."""

    def test_prompt_returns_response_text(self) -> None:
        """Test that prompt returns the response text."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "gpt-4")

        mock_response = MagicMock()
        mock_response.text.return_value = "Hello, world!"
        mock_model = MagicMock()
        mock_model.prompt.return_value = mock_response
        client._model = mock_model

        result = client.prompt("Say hello")
        assert result == "Hello, world!"
        mock_model.prompt.assert_called_once_with("Say hello")

    def test_prompt_wraps_exception(self) -> None:
        """Test that prompt wraps exceptions in LLMExecutionError."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "gpt-4")

        mock_model = MagicMock()
        mock_model.prompt.side_effect = RuntimeError("API error")
        client._model = mock_model

        with pytest.raises(LLMExecutionError) as excinfo:
            client.prompt("Say hello")

        assert "LLM execution failed" in str(excinfo.value)
        assert "API error" in str(excinfo.value)


class TestLLMClientPromptWithSystem:
    """Tests for LLMClient.prompt_with_system()."""

    def test_prompt_with_system_returns_response_text(self) -> None:
        """Test that prompt_with_system returns the response text."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "gpt-4")

        mock_response = MagicMock()
        mock_response.text.return_value = "I am a helpful assistant."
        mock_model = MagicMock()
        mock_model.prompt.return_value = mock_response
        client._model = mock_model

        result = client.prompt_with_system("You are helpful.", "Who are you?")
        assert result == "I am a helpful assistant."
        mock_model.prompt.assert_called_once_with("Who are you?", system="You are helpful.")

    def test_prompt_with_system_wraps_exception(self) -> None:
        """Test that prompt_with_system wraps exceptions in LLMExecutionError."""
        config = LLMConfig(enabled=True, timeout_s=60)
        client = LLMClient(config, "gpt-4")

        mock_model = MagicMock()
        mock_model.prompt.side_effect = RuntimeError("API error")
        client._model = mock_model

        with pytest.raises(LLMExecutionError) as excinfo:
            client.prompt_with_system("System", "User")

        assert "LLM execution failed" in str(excinfo.value)
