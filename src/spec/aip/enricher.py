"""AIP v3 Enricher - LLM-powered step and guidance generation.

This module provides enrichment functionality that uses LLM to:
1. Generate steps from goal/expectations when steps are empty
2. Add guidance to existing steps (likely_files, patterns, approach, watch_out_for)
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from spec.autogov.exceptions import SpecwrightError

if TYPE_CHECKING:
    from spec.aip.models import AIPv3


class EnrichMode(str, Enum):
    """Enrichment mode."""

    SMART = "smart"  # Generate steps if empty, otherwise guidance only
    GUIDANCE_ONLY = "guidance_only"  # Never generate steps
    GENERATE_STEPS = "generate_steps"  # Generate steps even if present
    OVERWRITE_STEPS = "overwrite_steps"  # Destructive replace


class EnrichError(SpecwrightError):
    """Error during AIP enrichment."""

    exit_code = 5


@dataclass
class EnrichResult:
    """Result of enrichment operation."""

    aip: AIPv3
    steps_generated: bool
    guidance_added: bool
    warnings: list[str]


# Default prompts for AIP enrichment
DEFAULT_STEP_PLANNING_PROMPT = """\
You are a senior software engineer planning concrete, repo-grounded steps for a spec.

## Goal
{goal}

## Expectations (acceptance criteria)
{expectations}

## Constraints
{constraints}

## Workspace
Repository: {repo_path}
Branch: {branch}

## Existing files (sample)
{existing_files}

## Repo reality constraints (must follow)
- This project is Specwright; Python package code lives under src/spec/...
- AIP v3 uses dataclasses (NOT Pydantic).
- CLI commands for this work are currently namespaced as:
    - spec aip-compile
    - spec aip-enrich
    - spec aip-run
    - spec aip-status
    - spec aip-diff
- Do NOT invent modules or paths. Only reference files under src/spec/... (or tests/...) that either:
    (a) appear in the existing files sample, or
    (b) are obviously adjacent to those paths (e.g., src/spec/aip/foo.py).
- Prefer verification/dogfooding steps when likely already implemented; avoid "implement X" steps
    unless you can point to where it should live in src/spec/....
- Do NOT mention legacy namespaces like src/spec/governor/... or src/spec/executor/... unless explicitly asked.

## Instructions
Generate a list of implementation steps. Each step should be:
- Actionable and specific
- Logically ordered (dependencies before dependents)
- Verifiable with commands

Respond with JSON only (no markdown fences):
{{
  "steps": [
    {{
      "id": "step-1",
      "title": "Short title",
      "objective": "Detailed description of what this step accomplishes"
    }}
  ]
}}
"""

DEFAULT_STEP_GUIDANCE_PROMPT = """\
You are a senior software engineer providing repo-grounded implementation guidance for a step.

## Step
ID: {step_id}
Title: {step_title}
Objective: {step_objective}

## Context
Goal: {goal}
Repository: {repo_path}
Existing files (sample): {existing_files}

## Repo reality constraints (must follow)
- This project is Specwright; Python package code lives under src/spec/...
- AIP v3 uses dataclasses (NOT Pydantic).
- CLI commands for this work are currently namespaced as:
    - spec aip-compile
    - spec aip-enrich
    - spec aip-run
    - spec aip-status
    - spec aip-diff
- Do NOT suggest files outside this repo.
- Do NOT invent modules or paths. Prefer referencing files from the existing files sample.
- When suggesting new files, keep them adjacent to existing modules (e.g., src/spec/aip/<name>.py).
- Do NOT mention legacy namespaces like src/spec/governor/... or src/spec/executor/... unless explicitly asked.

## Instructions
Generate implementation guidance for this step. Include:
- likely_files: Files likely to be created or modified
- patterns_to_follow: Reference files with patterns to learn from
- approach: Recommended implementation approach (numbered steps)
- watch_out_for: Common pitfalls to avoid

Respond with JSON only (no markdown fences):
{{
  "likely_files": ["path/to/file.py"],
  "patterns_to_follow": [
    {{"file": "src/example.py", "note": "Pattern description"}}
  ],
  "approach": "1. First step\\n2. Second step",
  "watch_out_for": ["Pitfall 1", "Pitfall 2"]
}}
"""


def enrich_aip(
    aip: AIPv3,
    mode: EnrichMode = EnrichMode.SMART,
    model: str | None = None,
) -> EnrichResult:
    """Enrich an AIP with LLM-generated steps and guidance.

    Args:
        aip: The AIP to enrich
        mode: Enrichment mode
        model: LLM model to use (default: from config)

    Returns:
        EnrichResult with enriched AIP and status info

    Raises:
        EnrichError: On LLM failure (graceful degradation returns warnings)
    """

    warnings: list[str] = []
    enriched = deepcopy(aip)
    steps_generated = False
    guidance_added = False

    # Determine if we should generate phases
    should_generate_phases = False
    if mode == EnrichMode.SMART:
        should_generate_phases = len(enriched.phases) == 0
    elif mode == EnrichMode.GENERATE_STEPS:
        should_generate_phases = True
    elif mode == EnrichMode.OVERWRITE_STEPS:
        should_generate_phases = True
        enriched.phases = []  # Clear existing phases

    # Generate phases if needed
    if should_generate_phases:
        try:
            new_phases = _generate_steps(enriched, model)
            if new_phases:
                enriched.phases = new_phases
                steps_generated = True
        except Exception as e:
            warnings.append(f"Failed to generate phases: {e}")

    # Add guidance to phases when missing. Avoid overwriting existing guidance to
    # minimize post-run drift.
    if enriched.phases:
        for phase in enriched.phases:
            if phase.guidance is not None:
                continue

            try:
                guidance = _generate_guidance(enriched, phase, model)
                if guidance:
                    phase.guidance = guidance
                    guidance_added = True
            except Exception as e:
                warnings.append(f"Failed to generate guidance for {phase.id}: {e}")

    return EnrichResult(
        aip=enriched,
        steps_generated=steps_generated,
        guidance_added=guidance_added,
        warnings=warnings,
    )


def _generate_steps(aip: AIPv3, model: str | None) -> list:
    """Generate steps using LLM.

    Args:
        aip: The AIP to generate steps for
        model: LLM model to use

    Returns:
        List of AIPStep instances
    """
    from spec.aip.models import AIPStep
    from spec.llm.client import LLMClient
    from spec.llm.config import require_llm_enabled
    from spec.llm.prompts import load_prompts

    config = require_llm_enabled()
    model_name = model or "claude-sonnet"
    client = LLMClient(config, model_name)

    # Load custom prompt or use default
    prompts = load_prompts()
    template = prompts.get("aip_step_planning", DEFAULT_STEP_PLANNING_PROMPT)

    # Format expectations and constraints
    expectations_text = "\n".join(f"- {e}" for e in aip.expectations) or "(none)"
    constraints_text = "\n".join(f"- {c}" for c in aip.constraints) or "(none)"

    existing_files = _get_sample_files(aip.workspace.repo_path)

    # Nudge step generation away from retroactive "implement X" when the repo
    # already appears to contain the expected v2 modules.
    repo_state_hints = _infer_repo_state_hints(aip.workspace.repo_path)
    if repo_state_hints:
        if constraints_text == "(none)":
            constraints_text = repo_state_hints
        else:
            constraints_text = f"{constraints_text}\n{repo_state_hints}"

    prompt = template.format(
        goal=aip.goal,
        expectations=expectations_text,
        constraints=constraints_text,
        repo_path=aip.workspace.repo_path,
        branch=aip.workspace.branch,
        existing_files="\n".join(f"- {f}" for f in existing_files) or "(none)",
    )

    response = client.prompt(prompt)
    data = _parse_json_response(response)

    steps: list[AIPStep] = []
    for step_data in data.get("steps", []):
        steps.append(
            AIPStep(
                id=step_data.get("id", f"step-{len(steps) + 1}"),
                title=step_data.get("title", ""),
                objective=step_data.get("objective", ""),
            )
        )

    return steps


def _infer_repo_state_hints(repo_path: str) -> str:
    """Return additional constraint lines based on observed repo state.

    This is intentionally heuristic: it biases the LLM toward verification-
    oriented steps when key modules already exist.
    """
    from pathlib import Path

    repo = Path(repo_path)
    if not repo.exists():
        return ""

    markers = (
        "src/spec/aip/compiler.py",
        "src/spec/aip/enricher.py",
        "src/spec/aip/models.py",
        "src/spec/artifacts/storage.py",
        "src/spec/runner/background.py",
        "src/spec/cli/spec.py",
    )
    found = [m for m in markers if (repo / m).exists()]

    if len(found) >= 4:
        found_text = ", ".join(found)
        return (
            "- Repo state: Many v2 core modules already exist in this repo. "
            "Prefer verification/hardening/dogfooding steps over greenfield implementation.\n"
            f"- Repo state evidence: {found_text}"
        )

    return ""


def _generate_guidance(aip: AIPv3, step, model: str | None):
    """Generate guidance for a step using LLM.

    Args:
        aip: The parent AIP
        step: The step to generate guidance for
        model: LLM model to use

    Returns:
        AIPStepGuidance instance
    """
    from spec.aip.models import AIPStepGuidance, PatternReference
    from spec.llm.client import LLMClient
    from spec.llm.config import require_llm_enabled
    from spec.llm.prompts import load_prompts

    config = require_llm_enabled()
    model_name = model or "claude-sonnet"
    client = LLMClient(config, model_name)

    # Load custom prompt or use default
    prompts = load_prompts()
    template = prompts.get("aip_step_guidance", DEFAULT_STEP_GUIDANCE_PROMPT)

    # Get sample of existing files for context
    existing_files = _get_sample_files(aip.workspace.repo_path)

    prompt = template.format(
        step_id=step.id,
        step_title=step.title,
        step_objective=step.objective,
        goal=aip.goal,
        repo_path=aip.workspace.repo_path,
        existing_files=", ".join(existing_files) or "(none)",
    )

    response = client.prompt(prompt)
    data = _parse_json_response(response)

    patterns: list[PatternReference] = []
    for p in data.get("patterns_to_follow", []):
        if isinstance(p, dict):
            patterns.append(
                PatternReference(file=p.get("file", ""), note=p.get("note"))
            )

    return AIPStepGuidance(
        likely_files=data.get("likely_files", []),
        patterns_to_follow=patterns,
        approach=data.get("approach"),
        watch_out_for=data.get("watch_out_for", []),
    )


def _get_sample_files(repo_path: str, max_files: int = 40) -> list[str]:
    """Get a sample of files from the repository for context.

    Args:
        repo_path: Path to the repository
        max_files: Maximum number of files to return

    Returns:
        List of relative file paths
    """
    from pathlib import Path

    repo = Path(repo_path)
    if not repo.exists():
        return []

    files: list[str] = []

    def _add_if_exists(rel_path: str) -> None:
        p = repo / rel_path
        if p.exists():
            files.append(rel_path)

    try:
        # Seed with the most relevant modules first.
        for seed in (
            "src/spec/cli/spec.py",
            "src/spec/aip/models.py",
            "src/spec/aip/compiler.py",
            "src/spec/aip/enricher.py",
            "src/spec/artifacts/storage.py",
            "src/spec/artifacts/collector.py",
            "src/spec/runner/background.py",
            "src/spec/runner/interactive.py",
            "src/spec/llm/client.py",
            "src/spec/llm/prompts.py",
            "src/spec/schemas/aip-v3.schema.json",
            "tests/aip/test_compiler.py",
            "tests/aip/test_enricher.py",
            "tests/runner/test_background.py",
            "tests/artifacts/test_storage.py",
        ):
            _add_if_exists(seed)

        # Add a small set of additional files from src/spec and tests.
        for folder, pattern in ((repo / "src" / "spec", "*.py"), (repo / "tests", "test_*.py")):
            if not folder.exists():
                continue
            for f in folder.rglob(pattern):
                if len(files) >= max_files:
                    break
                rel = str(f.relative_to(repo))
                if rel not in files:
                    files.append(rel)
    except Exception:
        return files[:max_files]

    return files


def _parse_json_response(response: str) -> dict:
    """Parse LLM response as JSON.

    Args:
        response: Raw LLM response

    Returns:
        Parsed dictionary

    Raises:
        EnrichError: If parsing fails
    """
    response = response.strip()

    # Strip markdown code fences if present
    if response.startswith("```json"):
        response = response[7:]
    elif response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    response = response.strip()

    try:
        data = json.loads(response)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError as e:
        raise EnrichError(f"Failed to parse LLM response as JSON: {e}")

    raise EnrichError(f"Expected JSON object, got {type(data).__name__}")
