"""LLM prompt loading and rendering module.

This module provides functions for loading prompts from the external
prompts.yaml configuration file and rendering them with variables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from spec.autogov.exceptions import SpecwrightError
from spec.llm.config import get_governor_config_path


class PromptLoadError(SpecwrightError):
    """Error loading or parsing prompts."""

    exit_code = 4


# Default prompts used when prompts.yaml doesn't exist
DEFAULT_SEP_GENERATION_PROMPT = """\
You are a spec execution planner. Generate a StepExecutionPlan (SEP) for the following step.

## AIP Context
{aip_context}

## Step Index
{step_index}

## Contract
{contract_text}

## Instructions
Generate a YAML SEP with the following structure:
- objective: Clear statement of what this step accomplishes
- files_to_touch: List of files with path, action (create|modify|delete), and description
- verification_steps: List of commands to verify success with expected outcomes
- allowed_paths: Glob patterns for files this step may modify
- forbidden_paths: Glob patterns for files this step must not modify
- estimated_complexity: low|medium|high
- requires_human_review: boolean

IMPORTANT: Quote all glob patterns containing special characters like *, ?, [, etc.
For example, use "*.lock" not *.lock (unquoted asterisks are YAML aliases).

Respond with valid YAML only, no markdown code fences.
"""

DEFAULT_PATCH_VERIFICATION_PROMPT = """\
You are a code review assistant. Verify that the patch aligns with the SEP constraints.

## Step Execution Plan (SEP)
{sep_yaml}

## Patch Content
```diff
{patch_content}
```

## Instructions
Analyze whether the patch:
1. Modifies only files listed in allowed_paths
2. Does not modify any files in forbidden_paths
3. Achieves the stated objective
4. Makes changes consistent with files_to_touch descriptions

Respond with JSON only:
{{"status": "pass" | "fail", "rationale": "explanation"}}
"""


def get_prompts_path() -> Path:
    """Return the path to the prompts.yaml file.

    Returns:
        Path to ~/.local/local-governor/prompts.yaml expanded.
    """
    governor_dir = get_governor_config_path().parent
    return governor_dir / "prompts.yaml"


def load_prompts() -> dict[str, Any]:
    """Load prompts from prompts.yaml.

    Returns:
        Dictionary of prompt templates. Returns empty dict if file doesn't exist.

    Raises:
        PromptLoadError: On parse error.
    """
    prompts_path = get_prompts_path()

    if not prompts_path.exists():
        return {}

    try:
        content = prompts_path.read_text(encoding="utf-8")
        raw = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise PromptLoadError(f"Failed to parse prompts.yaml: {e}") from e
    except OSError as e:
        raise PromptLoadError(f"Failed to read prompts.yaml: {e}") from e

    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw

    raise PromptLoadError(
        f"Invalid prompts.yaml: expected mapping at top-level, got {type(raw).__name__}"
    )


def render_sep_generation_prompt(
    aip_context: str,
    step_index: int,
    contract_text: str,
) -> str:
    """Render the SEP generation prompt with variables.

    Args:
        aip_context: Context from the AIP (title, goal, etc.)
        step_index: 0-based step index
        contract_text: The step contract as YAML or text

    Returns:
        Rendered prompt string ready to send to LLM.
    """
    prompts = load_prompts()
    template = prompts.get("sep_generation", DEFAULT_SEP_GENERATION_PROMPT)

    return template.format(
        aip_context=aip_context,
        step_index=step_index,
        contract_text=contract_text,
    )


def render_patch_verification_prompt(
    sep_yaml: str,
    patch_content: str,
) -> str:
    """Render the patch verification prompt with variables.

    Args:
        sep_yaml: The SEP as YAML string
        patch_content: The patch.diff content

    Returns:
        Rendered prompt string ready to send to LLM.
    """
    prompts = load_prompts()
    template = prompts.get("patch_verification", DEFAULT_PATCH_VERIFICATION_PROMPT)

    return template.format(
        sep_yaml=sep_yaml,
        patch_content=patch_content,
    )
