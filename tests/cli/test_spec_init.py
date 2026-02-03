"""Tests for spec init command configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from spec.cli.spec import app, find_config, get_default_config

runner = CliRunner()


@pytest.fixture
def temp_empty_dir(tmp_path: Path) -> Path:
    """Create an empty temporary directory."""
    return tmp_path


class TestDefaultConfig:
    """Tests for default configuration."""

    def test_default_config_v06(self) -> None:
        """Default config (v0.6) is governor-based."""
        config = get_default_config()

        assert config["version"] == "0.6"
        assert "governor" in config
        assert config["governor"]["path"] == "~/.local/local-governor"

    def test_legacy_config_has_paths(self) -> None:
        """Legacy config (v0.1) has paths and user sections."""
        config = get_default_config(legacy=True)

        assert config["version"] == "0.1"
        assert "paths" in config
        assert "user" in config


class TestConfigLoading:
    """Tests for config loading."""

    def test_config_loading_basic(self, tmp_path: Path) -> None:
        """Config loads correctly."""
        config_path = tmp_path / ".specwright.yaml"
        config = {
            "version": "0.1",
            "paths": {"specs": ".specwright/specs", "aips": ".specwright/aips"},
            "user": {"default_owner": "test", "default_tier": "B"},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            found_path, loaded_config = find_config()

            assert found_path == config_path
            assert loaded_config["version"] == "0.1"
            assert loaded_config["user"]["default_owner"] == "test"
        finally:
            os.chdir(original_dir)


class TestSpecInit:
    """Tests for spec init command."""

    def test_init_creates_config(self, temp_empty_dir: Path) -> None:
        """spec init creates config without autogov section."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_empty_dir)
            result = runner.invoke(
                app,
                ["init", "--no-claude"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "Created" in result.output

            config_path = temp_empty_dir / ".specwright.yaml"
            assert config_path.exists()

            with open(config_path) as f:
                config = yaml.safe_load(f)

            assert "autogov" not in config
        finally:
            os.chdir(original_dir)
