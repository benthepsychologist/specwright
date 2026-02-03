"""LLM configuration module.

This module provides configuration loading for LLM integration,
reading settings from the local-governor config file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from spec.core.exceptions import SpecwrightError


class LLMConfigError(SpecwrightError):
    """LLM configuration error."""

    exit_code = 4


@dataclass
class LLMConfig:
    """LLM configuration settings.

    Note: model is NOT here - it comes from check.model or epic.defaults.model
    """

    enabled: bool = False
    timeout_s: int = 120


def get_governor_config_path() -> Path:
    """Return the path to the local-governor config file.

    Returns:
        Path to ~/.local/local-governor/config.yaml expanded.
    """
    return Path("~/.local/local-governor/config.yaml").expanduser()


def load_llm_config() -> LLMConfig:
    """Load LLM config from governor config.yaml.

    Returns:
        LLMConfig with settings from the config file.
        If file doesn't exist, returns LLMConfig with enabled=False.
        If file exists but llm section missing, returns disabled config.

    Raises:
        LLMConfigError: On parse error.
    """
    config_path = get_governor_config_path()

    if not config_path.exists():
        return LLMConfig(enabled=False)

    try:
        content = config_path.read_text(encoding="utf-8")
        raw = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise LLMConfigError(f"Failed to parse governor config: {e}") from e
    except OSError as e:
        raise LLMConfigError(f"Failed to read governor config: {e}") from e

    if raw is None:
        data: dict[str, Any] = {}
    elif isinstance(raw, dict):
        data = raw
    else:
        raise LLMConfigError(
            "Invalid governor config: expected mapping at top-level, got "
            f"{type(raw).__name__}"
        )

    llm_section = data.get("llm")
    if llm_section is None:
        return LLMConfig(enabled=False)

    if not isinstance(llm_section, dict):
        raise LLMConfigError(
            f"Invalid llm section in config: expected dict, got {type(llm_section).__name__}"
        )

    try:
        enabled = llm_section.get("enabled", False)
        if not isinstance(enabled, bool):
            raise LLMConfigError(
                f"Invalid llm.enabled value: expected bool, got {type(enabled).__name__}"
            )

        timeout_s = llm_section.get("timeout_s", 120)
        if not isinstance(timeout_s, int):
            raise LLMConfigError(
                f"Invalid llm.timeout_s value: expected int, got {type(timeout_s).__name__}"
            )

        return LLMConfig(enabled=enabled, timeout_s=timeout_s)
    except LLMConfigError:
        raise
    except Exception as e:
        raise LLMConfigError(f"Failed to parse llm config: {e}") from e


def require_llm_enabled() -> LLMConfig:
    """Load config and raise if LLM is not enabled.

    Returns:
        LLMConfig if LLM is enabled.

    Raises:
        LLMConfigError: If LLM is not enabled, with helpful message.
    """
    config = load_llm_config()

    if not config.enabled:
        config_path = get_governor_config_path()
        raise LLMConfigError(
            f"LLM is not enabled. To enable, add the following to {config_path}:\n\n"
            "llm:\n"
            "  enabled: true\n"
            "  timeout_s: 120  # optional, defaults to 120"
        )

    return config
