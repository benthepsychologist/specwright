"""Tests for LLM config loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec.llm.config import LLMConfigError, load_llm_config, require_llm_enabled


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_llm_config_missing_file_returns_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    config = load_llm_config()
    assert config.enabled is False


def test_load_llm_config_empty_yaml_returns_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write(config_path, "")

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    config = load_llm_config()
    assert config.enabled is False


def test_load_llm_config_non_mapping_root_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write(config_path, "- not: a mapping\n")

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    with pytest.raises(LLMConfigError) as excinfo:
        load_llm_config()

    assert "expected mapping" in str(excinfo.value)
    assert excinfo.value.exit_code == 4


def test_load_llm_config_invalid_yaml_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write(config_path, "llm: [unterminated\n")

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    with pytest.raises(LLMConfigError) as excinfo:
        load_llm_config()

    assert "Failed to parse" in str(excinfo.value)
    assert excinfo.value.exit_code == 4


def test_load_llm_config_missing_llm_section_returns_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yaml"
    _write(config_path, "other: 123\n")

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    config = load_llm_config()
    assert config.enabled is False


def test_load_llm_config_llm_section_non_mapping_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write(config_path, "llm: true\n")

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    with pytest.raises(LLMConfigError) as excinfo:
        load_llm_config()

    assert "Invalid llm section" in str(excinfo.value)


def test_load_llm_config_enabled_wrong_type_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write(config_path, "llm:\n  enabled: 1\n")

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    with pytest.raises(LLMConfigError) as excinfo:
        load_llm_config()

    assert "llm.enabled" in str(excinfo.value)


def test_load_llm_config_timeout_wrong_type_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write(config_path, "llm:\n  enabled: true\n  timeout_s: 'slow'\n")

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    with pytest.raises(LLMConfigError) as excinfo:
        load_llm_config()

    assert "llm.timeout_s" in str(excinfo.value)


def test_require_llm_enabled_raises_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write(config_path, "llm:\n  enabled: false\n")

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    with pytest.raises(LLMConfigError) as excinfo:
        require_llm_enabled()

    message = str(excinfo.value)
    assert "LLM is not enabled" in message
    assert str(config_path) in message


def test_require_llm_enabled_returns_config_when_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write(config_path, "llm:\n  enabled: true\n  timeout_s: 5\n")

    monkeypatch.setattr("spec.llm.config.get_governor_config_path", lambda: config_path)

    config = require_llm_enabled()
    assert config.enabled is True
    assert config.timeout_s == 5
