"""Tests for DeltaGenerator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spec.governance.delta_generator import DeltaGenerationError, DeltaGenerator

SAMPLE_BUILD_YAML = """\
kind: project.build
version: "0.1"
metadata:
  name: testproj
kernel:
  surfaces:
    - name: cli
      entrypoints:
        - command: "test run"
layout:
  - path: src/core/
    module: core
    role: Core module
modules:
  - name: core
    kind: module
    provides: ["core logic"]
"""


class TestBuildPrompt:
    def test_prompt_includes_expectations(self) -> None:
        gen = DeltaGenerator(
            expectations=["Add governance module", "New validate commands"],
            build_yaml_content=SAMPLE_BUILD_YAML,
            target_path="projects/testproj/testproj.build.yaml",
        )
        system, user = gen.build_prompt()

        assert "Add governance module" in user
        assert "New validate commands" in user

    def test_prompt_includes_build_yaml(self) -> None:
        gen = DeltaGenerator(
            expectations=["Something"],
            build_yaml_content=SAMPLE_BUILD_YAML,
            target_path="projects/testproj/testproj.build.yaml",
        )
        _, user = gen.build_prompt()

        assert "testproj" in user
        assert "core" in user

    def test_prompt_includes_target_path(self) -> None:
        gen = DeltaGenerator(
            expectations=["Something"],
            build_yaml_content=SAMPLE_BUILD_YAML,
            target_path="projects/testproj/testproj.build.yaml",
        )
        _, user = gen.build_prompt()

        assert "projects/testproj/testproj.build.yaml" in user

    def test_system_prompt_describes_build_delta(self) -> None:
        gen = DeltaGenerator(
            expectations=["Something"],
            build_yaml_content=SAMPLE_BUILD_YAML,
            target_path="projects/testproj/testproj.build.yaml",
        )
        system, _ = gen.build_prompt()

        assert "build_delta" in system
        assert "adds" in system
        assert "modifies" in system
        assert "removes" in system


class TestParseResponse:
    def test_parse_clean_yaml(self) -> None:
        gen = DeltaGenerator(
            expectations=[],
            build_yaml_content="",
            target_path="projects/x/x.build.yaml",
        )
        response = """\
target: projects/x/x.build.yaml
summary: Add governance module
adds:
  modules:
    - name: governance
      kind: module
"""
        result = gen._parse_response(response)
        assert result["summary"] == "Add governance module"
        assert result["adds"]["modules"][0]["name"] == "governance"

    def test_parse_strips_code_fences(self) -> None:
        gen = DeltaGenerator(
            expectations=[],
            build_yaml_content="",
            target_path="projects/x/x.build.yaml",
        )
        response = """\
```yaml
target: projects/x/x.build.yaml
summary: Test
adds: {}
```"""
        result = gen._parse_response(response)
        assert result["summary"] == "Test"

    def test_parse_fills_missing_target(self) -> None:
        gen = DeltaGenerator(
            expectations=[],
            build_yaml_content="",
            target_path="projects/x/x.build.yaml",
        )
        response = "summary: Test\nadds: {}"
        result = gen._parse_response(response)
        assert result["target"] == "projects/x/x.build.yaml"

    def test_parse_rejects_missing_summary(self) -> None:
        gen = DeltaGenerator(
            expectations=[],
            build_yaml_content="",
            target_path="projects/x/x.build.yaml",
        )
        with pytest.raises(DeltaGenerationError, match="summary"):
            gen._parse_response("target: x\nadds: {}")

    def test_parse_normalizes_null_sections(self) -> None:
        gen = DeltaGenerator(
            expectations=[],
            build_yaml_content="",
            target_path="projects/x/x.build.yaml",
        )
        response = "target: x\nsummary: Test\nadds:\nmodifies:\nremoves:"
        result = gen._parse_response(response)
        assert result["adds"] == {}
        assert result["modifies"] == {}
        assert result["removes"] == {}

    def test_parse_rejects_non_dict(self) -> None:
        gen = DeltaGenerator(
            expectations=[],
            build_yaml_content="",
            target_path="projects/x/x.build.yaml",
        )
        with pytest.raises(DeltaGenerationError, match="Expected YAML dict"):
            gen._parse_response("- just\n- a\n- list")

    def test_parse_rejects_invalid_yaml(self) -> None:
        gen = DeltaGenerator(
            expectations=[],
            build_yaml_content="",
            target_path="projects/x/x.build.yaml",
        )
        with pytest.raises(DeltaGenerationError, match="Failed to parse"):
            gen._parse_response("{{{{invalid yaml")


class TestGenerate:
    def test_generate_end_to_end_with_mock_llm(self) -> None:
        """Test that generate() calls LLM client and parses result."""
        llm_response = (
            "target: projects/x/x.build.yaml\n"
            "summary: Add governance\n"
            "adds:\n"
            "  modules:\n"
            "    - name: governance\n"
            "      kind: module\n"
        )

        gen = DeltaGenerator(
            expectations=["Add governance"],
            build_yaml_content=SAMPLE_BUILD_YAML,
            target_path="projects/x/x.build.yaml",
            model_name="test-model",
        )

        mock_client = MagicMock()
        mock_client.prompt_with_system.return_value = llm_response

        with (
            patch("spec.llm.config.require_llm_enabled") as mock_req,
            patch("spec.llm.client.LLMClient", return_value=mock_client),
        ):
            mock_req.return_value = MagicMock(enabled=True, timeout_s=120)
            result = gen.generate()

        assert result["summary"] == "Add governance"
        assert result["adds"]["modules"][0]["name"] == "governance"
        mock_client.prompt_with_system.assert_called_once()

    def test_generate_requires_model(self) -> None:
        """generate() fails if no model configured."""
        gen = DeltaGenerator(
            expectations=["Something"],
            build_yaml_content=SAMPLE_BUILD_YAML,
            target_path="projects/x/x.build.yaml",
        )

        with (
            patch("spec.llm.config.require_llm_enabled") as mock_req,
            patch("spec.governance.delta_generator._get_config_model") as mock_model,
        ):
            mock_req.return_value = MagicMock(enabled=True, timeout_s=120)
            mock_model.return_value = None
            with pytest.raises(DeltaGenerationError, match="No model"):
                gen.generate()
