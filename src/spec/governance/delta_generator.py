"""Build delta generator: LLM-assisted build_delta drafting.

Given a spec's expectations and the current build.yaml, uses an LLM
to generate a build_delta dict for human review.
"""

from __future__ import annotations

from typing import Any

import yaml

from spec.core.exceptions import SpecwrightError


class DeltaGenerationError(SpecwrightError):
    """Failed to generate a build_delta."""

    exit_code = 5


_SYSTEM_PROMPT = """\
You are a build.yaml maintenance assistant for the specwright governance system.

A build.yaml describes a project's structure: layout (source directories),
modules (logical units), boundaries (external interfaces), kernel surfaces
(CLI entrypoints), and decisions (ADRs).

A build_delta describes structural changes a spec makes to its target build.yaml.
It has three operations:
- adds: new entries to append to sections
- modifies: existing entries to update (matched by key field — "name" for modules/boundaries/surfaces, "path" for layout, "id" for decisions)
- removes: existing entries to delete (matched by key field)

Section keys: layout, modules, boundaries, decisions, kernel_surfaces (maps to kernel.surfaces in the YAML).

For modifies, array fields (like entrypoints, provides, depends_on) are appended to, not replaced.
"""

_USER_PROMPT_TEMPLATE = """\
Generate a build_delta for the following spec.

## Target build.yaml
```yaml
{build_yaml_content}
```

## Spec expectations
{expectations}

## Target path
{target_path}

## Instructions
Produce a YAML build_delta object with these fields:
- target: "{target_path}" (the path to the build.yaml relative to governor root)
- summary: one-line description of structural changes
- adds: new entries (only things that don't already exist in the build.yaml)
- modifies: updates to existing entries (only things that already exist)
- removes: entries to delete (only things that currently exist)

Only include sections that actually change. Omit empty sections entirely.
Match the style and field names used in the existing build.yaml.

Respond with YAML only, no markdown code fences, no explanation text.
"""


class DeltaGenerator:
    """Generate a build_delta from spec expectations using LLM.

    Usage::

        generator = DeltaGenerator(
            expectations=["Add governance module", "New validate commands"],
            build_yaml_content="...",
            target_path="projects/specwright/specwright.build.yaml",
        )
        delta = generator.generate()
    """

    def __init__(
        self,
        expectations: list[str],
        build_yaml_content: str,
        target_path: str,
        model_name: str | None = None,
    ) -> None:
        self.expectations = expectations
        self.build_yaml_content = build_yaml_content
        self.target_path = target_path
        self.model_name = model_name

    def build_prompt(self) -> tuple[str, str]:
        """Construct the system and user prompts.

        Returns:
            (system_prompt, user_prompt) tuple.
        """
        expectations_text = "\n".join(f"- {e}" for e in self.expectations)

        user_prompt = _USER_PROMPT_TEMPLATE.format(
            build_yaml_content=self.build_yaml_content,
            expectations=expectations_text,
            target_path=self.target_path,
        )

        return _SYSTEM_PROMPT, user_prompt

    def generate(self) -> dict[str, Any]:
        """Call LLM to generate a build_delta dict.

        Returns:
            Parsed build_delta dict.

        Raises:
            DeltaGenerationError: On LLM or parsing failure.
        """
        from spec.llm.client import LLMClient, LLMExecutionError
        from spec.llm.config import require_llm_enabled

        config = require_llm_enabled()

        # Get model name: explicit > config file > default
        model = self.model_name
        if model is None:
            model = _get_config_model()
        if model is None:
            raise DeltaGenerationError(
                "No model configured. Set llm.model in "
                "~/.local/local-governor/config.yaml or pass --model"
            )

        system_prompt, user_prompt = self.build_prompt()

        try:
            client = LLMClient(config, model)
            response = client.prompt_with_system(system_prompt, user_prompt)
        except LLMExecutionError as e:
            raise DeltaGenerationError(f"LLM generation failed: {e}") from e

        return self._parse_response(response)

    def _parse_response(self, response: str) -> dict[str, Any]:
        """Parse LLM YAML response into a build_delta dict.

        Strips markdown fences, parses YAML, validates structure.

        Raises:
            DeltaGenerationError: If response can't be parsed.
        """
        text = response.strip()

        # Strip markdown code fences if present
        if text.startswith("```yaml"):
            text = text[7:]
        elif text.startswith("```yml"):
            text = text[6:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise DeltaGenerationError(
                f"Failed to parse LLM response as YAML:\n{e}\n\nRaw response:\n{text[:1000]}"
            ) from e

        if not isinstance(data, dict):
            raise DeltaGenerationError(
                f"Expected YAML dict, got {type(data).__name__}.\n\nRaw response:\n{text[:1000]}"
            )

        # Validate required fields
        if "target" not in data:
            data["target"] = self.target_path
        if "summary" not in data:
            raise DeltaGenerationError(
                f"LLM response missing 'summary' field.\n\nParsed:\n{data}"
            )

        # Ensure operations are dicts (not None)
        for key in ("adds", "modifies", "removes"):
            if key in data and data[key] is None:
                data[key] = {}

        return data


def _get_config_model() -> str | None:
    """Read llm.model from governor config.yaml.

    Returns model name or None if not set.
    """
    from spec.llm.config import get_governor_config_path

    config_path = get_governor_config_path()
    if not config_path.exists():
        return None

    try:
        raw = yaml.safe_load(config_path.read_text())
        if isinstance(raw, dict):
            llm_section = raw.get("llm", {})
            if isinstance(llm_section, dict):
                return llm_section.get("model")
    except Exception:
        pass
    return None
