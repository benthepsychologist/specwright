"""Tests for spec init command with autogov configuration."""

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

    def test_default_config_no_autogov(self) -> None:
        """Default config (v0.6) does not include autogov section."""
        config = get_default_config()

        assert "autogov" not in config
        # v0.6 format: governor-based (new default)
        assert config["version"] == "0.6"
        assert "governor" in config
        assert config["governor"]["path"] == "~/.local/local-governor"

    def test_legacy_config_has_paths(self) -> None:
        """Legacy config (v0.1) has paths and user sections."""
        config = get_default_config(legacy=True)

        assert "autogov" not in config
        assert config["version"] == "0.1"
        assert "paths" in config
        assert "user" in config


class TestConfigLoading:
    """Tests for config loading with autogov section."""

    def test_config_loading_with_autogov_section(self, tmp_path: Path) -> None:
        """Config with autogov section loads correctly."""
        config_path = tmp_path / ".specwright.yaml"
        config = {
            "version": "0.1",
            "paths": {"specs": ".specwright/specs", "aips": ".specwright/aips"},
            "user": {"default_owner": "test", "default_tier": "B"},
            "autogov": {
                "enabled": True,
                "source": "org",
            },
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            found_path, loaded_config = find_config()

            assert found_path == config_path
            assert "autogov" in loaded_config
            assert loaded_config["autogov"]["enabled"] is True
            assert loaded_config["autogov"]["source"] == "org"
        finally:
            os.chdir(original_dir)

    def test_config_loading_without_autogov_section(self, tmp_path: Path) -> None:
        """Config without autogov section loads correctly (enabled defaults to false)."""
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
            # autogov section should not exist, and enabled defaults to False
            autogov_cfg = loaded_config.get("autogov", {})
            autogov_enabled = autogov_cfg.get("enabled", False)
            assert autogov_enabled is False
        finally:
            os.chdir(original_dir)

    def test_autogov_enabled_missing_source_fails_on_create(
        self, tmp_path: Path
    ) -> None:
        """autogov.enabled: true but missing source raises RegistryConfigError on create."""
        config_path = tmp_path / ".specwright.yaml"
        config = {
            "version": "0.1",
            "paths": {"specs": ".specwright/specs", "aips": ".specwright/aips"},
            "user": {"default_owner": "test", "default_tier": "B"},
            "autogov": {
                "enabled": True,
                # source is missing
            },
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        (tmp_path / ".specwright" / "specs").mkdir(parents=True)

        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(
                app,
                ["create", "Test Feature", "--autogov", "myproject"],
            )

            # Should exit with code 4 (RegistryConfigError)
            assert result.exit_code == 4
            assert "Missing autogov.source" in result.output
        finally:
            os.chdir(original_dir)


class TestSpecInitAutogov:
    """Tests for spec init with autogov configuration."""

    def test_init_without_autogov(self, temp_empty_dir: Path) -> None:
        """spec init without --autogov creates config without autogov section."""
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

    def test_init_with_autogov_org(self, temp_empty_dir: Path) -> None:
        """spec init --autogov prompts for source, creates config with autogov section."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_empty_dir)
            # Simulate user typing "org" at the prompt
            result = runner.invoke(
                app,
                ["init", "--no-claude", "--autogov"],
                input="org\n",
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "Autogov enabled with source: org" in result.output

            config_path = temp_empty_dir / ".specwright.yaml"
            with open(config_path) as f:
                config = yaml.safe_load(f)

            assert "autogov" in config
            assert config["autogov"]["enabled"] is True
            assert config["autogov"]["source"] == "org"
        finally:
            os.chdir(original_dir)

    def test_init_with_autogov_patterns(self, temp_empty_dir: Path) -> None:
        """spec init --autogov with patterns source creates config with patterns source."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_empty_dir)
            # Simulate user typing "patterns" at the prompt
            result = runner.invoke(
                app,
                ["init", "--no-claude", "--autogov"],
                input="patterns\n",
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "Autogov enabled with source: patterns" in result.output

            config_path = temp_empty_dir / ".specwright.yaml"
            with open(config_path) as f:
                config = yaml.safe_load(f)

            assert config["autogov"]["source"] == "patterns"
        finally:
            os.chdir(original_dir)

    def test_init_autogov_uses_default_source(self, temp_empty_dir: Path) -> None:
        """spec init --autogov defaults to 'org' when user presses enter."""
        original_dir = os.getcwd()
        try:
            os.chdir(temp_empty_dir)
            # Simulate user pressing enter (accept default)
            result = runner.invoke(
                app,
                ["init", "--no-claude", "--autogov"],
                input="\n",
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "Autogov enabled with source: org" in result.output

            config_path = temp_empty_dir / ".specwright.yaml"
            with open(config_path) as f:
                config = yaml.safe_load(f)

            assert config["autogov"]["source"] == "org"
        finally:
            os.chdir(original_dir)
