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
    from spec.epic.schema import Epic


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


# Default prompts for AIP enrichment - parameterized for any target repo
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

## Existing files (sample from target repo)
{existing_files}

{repo_context}

## Instructions
Generate a list of implementation steps. Each step should be:
- Actionable and specific
- Logically ordered (dependencies before dependents)
- Verifiable with commands
- Grounded in the actual file paths shown in "Existing files" above

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

{repo_context}

## Instructions
Generate implementation guidance for this step. Include:
- likely_files: Files likely to be created or modified (use paths consistent with the repo structure shown above)
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


def _build_repo_context(epic: Epic | None, spec_id: str | None) -> str:
    """Build repo-specific context for enrichment prompts.

    Args:
        epic: The epic containing target repo info and spec expectations
        spec_id: The spec ID to get expectations/constraints from

    Returns:
        Formatted context string for the prompt
    """
    if epic is None:
        return ""

    lines = ["## Repo Structure & Epic Expectations"]

    # Get spec info
    spec = epic.get_spec(spec_id) if spec_id else None
    if spec:
        # Get target repo info
        target = epic.get_target(spec.repo)
        if target:
            lines.append(f"- Target project: {target.id}")
            lines.append(f"- Target repo path: {target.repo_path}")

        # Add epic expectations as explicit file path hints
        if spec.expectations:
            lines.append("\n### Expected File Locations (from epic)")
            lines.append("These paths are specified in the epic - use them as authoritative guidance:")
            for exp in spec.expectations:
                lines.append(f"- {exp}")

        # Add constraints
        if spec.constraints:
            lines.append("\n### Constraints (from epic)")
            for con in spec.constraints:
                lines.append(f"- {con}")

    # Extract file paths from checks that apply to this spec
    check_paths = _extract_check_file_paths(epic, spec_id)
    if check_paths:
        lines.append("\n### Verification Check Paths (files that will be checked)")
        lines.append("The following files will be verified - ensure they exist at these exact paths:")
        for path in check_paths:
            lines.append(f"- {path}")

    lines.append("\n## Path Constraints")
    lines.append("- Do NOT invent modules or paths. Only reference files that:")
    lines.append("    (a) appear in the existing files sample, or")
    lines.append("    (b) are explicitly mentioned in the epic expectations above, or")
    lines.append("    (c) are obviously adjacent to existing paths")
    lines.append("- File paths in your steps MUST match the epic expectations above")

    return "\n".join(lines)


def _extract_check_file_paths(epic: Epic, spec_id: str | None) -> list[str]:
    """Extract expected file paths from epic checks for a spec.

    Args:
        epic: The epic containing checks
        spec_id: The spec ID to filter checks for

    Returns:
        List of file paths that checks will verify
    """
    paths = []

    spec = epic.get_spec(spec_id) if spec_id else None
    if not spec:
        return paths

    # Get checks that apply to this spec
    for check_id in spec.checks:
        check = epic.get_check(check_id)
        if check:
            for inp in check.inputs:
                if inp.type == "file" and inp.path:
                    # Resolve path with target repo
                    target = epic.get_target(inp.target) if inp.target else None
                    if target:
                        paths.append(f"{inp.path} (in {target.id})")
                    else:
                        paths.append(inp.path)
                elif inp.type == "directory" and inp.path:
                    target = epic.get_target(inp.target) if inp.target else None
                    if target:
                        paths.append(f"{inp.path}/ (directory in {target.id})")
                    else:
                        paths.append(f"{inp.path}/")

    return paths


def enrich_aip(
    aip: AIPv3,
    mode: EnrichMode = EnrichMode.SMART,
    model: str | None = None,
    epic: Epic | None = None,
) -> EnrichResult:
    """Enrich an AIP with LLM-generated steps and guidance.

    Args:
        aip: The AIP to enrich
        mode: Enrichment mode
        model: LLM model to use (default: from config)
        epic: The epic containing target repo info and expectations (required for
              correct path generation when enriching specs for non-specwright repos)

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
            new_phases = _generate_steps(enriched, model, epic)
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
                guidance = _generate_guidance(enriched, phase, model, epic)
                if guidance:
                    phase.guidance = guidance
                    guidance_added = True
            except Exception as e:
                warnings.append(f"Failed to generate guidance for {phase.id}: {e}")

    # Validate generated paths against epic expectations
    if epic and (steps_generated or guidance_added):
        path_errors = _validate_aip_paths(enriched, epic)
        if path_errors:
            for err in path_errors:
                warnings.append(f"Path validation: {err}")

    return EnrichResult(
        aip=enriched,
        steps_generated=steps_generated,
        guidance_added=guidance_added,
        warnings=warnings,
    )


def _generate_steps(aip: AIPv3, model: str | None, epic: Epic | None = None) -> list:
    """Generate steps using LLM.

    Args:
        aip: The AIP to generate steps for
        model: LLM model to use
        epic: The epic containing target repo info and expectations

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

    # Get target repo path from epic if available, otherwise use AIP workspace
    target_repo_path = _get_target_repo_path(aip, epic)
    existing_files = _get_sample_files(target_repo_path, epic)

    # Nudge step generation away from retroactive "implement X" when the repo
    # already appears to contain the expected v2 modules.
    repo_state_hints = _infer_repo_state_hints(target_repo_path)
    if repo_state_hints:
        if constraints_text == "(none)":
            constraints_text = repo_state_hints
        else:
            constraints_text = f"{constraints_text}\n{repo_state_hints}"

    # Build repo-specific context from epic
    spec_id = aip.metadata.spec_id if hasattr(aip, 'metadata') and aip.metadata else None
    repo_context = _build_repo_context(epic, spec_id)

    prompt = template.format(
        goal=aip.goal,
        expectations=expectations_text,
        constraints=constraints_text,
        repo_path=target_repo_path,
        branch=aip.workspace.branch,
        existing_files="\n".join(f"- {f}" for f in existing_files) or "(none)",
        repo_context=repo_context,
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


def _get_target_repo_path(aip: AIPv3, epic: Epic | None) -> str:
    """Get the target repository path from epic or AIP.

    Args:
        aip: The AIP with workspace info
        epic: The epic with target definitions

    Returns:
        Path to the target repository
    """
    if epic and hasattr(aip, 'metadata') and aip.metadata:
        spec = epic.get_spec(aip.metadata.spec_id)
        if spec:
            target = epic.get_target(spec.repo)
            if target:
                return target.repo_path

    return aip.workspace.repo_path


def _infer_repo_state_hints(repo_path: str) -> str:
    """Return additional constraint lines based on observed repo state.

    This is intentionally heuristic: it biases the LLM toward verification-
    oriented steps when many Python files already exist.
    """
    from pathlib import Path

    repo = Path(repo_path)
    if not repo.exists():
        return ""

    # Count Python files to detect mature codebases
    try:
        py_files = list(repo.rglob("*.py"))
        # Filter out common non-source directories
        py_files = [
            f for f in py_files
            if not any(part.startswith(".") or part in ("__pycache__", "node_modules", ".venv", "venv", "build", "dist")
                       for part in f.parts)
        ]

        if len(py_files) >= 20:
            # Mature codebase - suggest verification over greenfield
            return (
                "- Repo state: This appears to be a mature codebase with existing code. "
                "Prefer verification/hardening steps over greenfield implementation when features may already exist.\n"
                f"- Repo state evidence: Found {len(py_files)} Python files"
            )
    except Exception:
        pass

    return ""


def _generate_guidance(aip: AIPv3, step, model: str | None, epic: Epic | None = None):
    """Generate guidance for a step using LLM.

    Args:
        aip: The parent AIP
        step: The step to generate guidance for
        model: LLM model to use
        epic: The epic containing target repo info and expectations

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

    # Get target repo path from epic if available
    target_repo_path = _get_target_repo_path(aip, epic)

    # Get sample of existing files for context from target repo
    existing_files = _get_sample_files(target_repo_path, epic)

    # Build repo-specific context from epic
    spec_id = aip.metadata.spec_id if hasattr(aip, 'metadata') and aip.metadata else None
    repo_context = _build_repo_context(epic, spec_id)

    prompt = template.format(
        step_id=step.id,
        step_title=step.title,
        step_objective=step.objective,
        goal=aip.goal,
        repo_path=target_repo_path,
        existing_files=", ".join(existing_files) or "(none)",
        repo_context=repo_context,
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


def _get_sample_files(repo_path: str, epic: Epic | None = None, max_files: int = 40) -> list[str]:
    """Get a sample of files from the repository for context.

    Args:
        repo_path: Path to the repository
        epic: The epic (unused, but kept for consistency)
        max_files: Maximum number of files to return

    Returns:
        List of relative file paths
    """
    from pathlib import Path

    repo = Path(repo_path)
    if not repo.exists():
        return []

    files: list[str] = []

    # Directories to skip
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", "build", "dist", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "egg-info"}

    def should_skip(path: Path) -> bool:
        return any(part in skip_dirs or part.startswith(".") for part in path.parts)

    try:
        # First pass: collect Python files organized by directory depth
        # This gives us a good cross-section of the codebase
        py_files: list[tuple[int, Path]] = []

        for f in repo.rglob("*.py"):
            if should_skip(f.relative_to(repo)):
                continue
            depth = len(f.relative_to(repo).parts)
            py_files.append((depth, f))

        # Sort by depth (shallower first) to get top-level structure first
        py_files.sort(key=lambda x: (x[0], x[1].name))

        # Add files, preferring __init__.py and key modules at each level
        seen_dirs: set[str] = set()
        for _, f in py_files:
            if len(files) >= max_files:
                break

            rel = str(f.relative_to(repo))
            parent_dir = str(f.parent.relative_to(repo))

            # Always include __init__.py to show package structure
            if f.name == "__init__.py":
                files.append(rel)
                seen_dirs.add(parent_dir)
            # Include first file from each directory for variety
            elif parent_dir not in seen_dirs:
                files.append(rel)
                seen_dirs.add(parent_dir)
            # Then fill in with other files
            elif rel not in files:
                files.append(rel)

        # Also include test files for completeness
        if len(files) < max_files:
            test_dirs = [repo / "tests", repo / "test"]
            for test_dir in test_dirs:
                if not test_dir.exists():
                    continue
                for f in test_dir.rglob("test_*.py"):
                    if len(files) >= max_files:
                        break
                    if should_skip(f.relative_to(repo)):
                        continue
                    rel = str(f.relative_to(repo))
                    if rel not in files:
                        files.append(rel)

    except Exception:
        return files[:max_files]

    return files[:max_files]


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


def _validate_aip_paths(aip: AIPv3, epic: Epic) -> list[str]:
    """Validate that AIP paths match epic expectations.

    Args:
        aip: The enriched AIP to validate
        epic: The epic with expected file paths

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    spec_id = aip.metadata.spec_id if hasattr(aip, 'metadata') and aip.metadata else None
    if not spec_id:
        return errors

    spec = epic.get_spec(spec_id)
    if not spec:
        return errors

    # Get expected paths from epic check inputs
    expected_paths: set[str] = set()
    for check_id in spec.checks:
        check = epic.get_check(check_id)
        if check:
            for inp in check.inputs:
                if inp.type == "file" and inp.path:
                    expected_paths.add(inp.path)
                elif inp.type == "directory" and inp.path:
                    expected_paths.add(inp.path.rstrip("/"))

    if not expected_paths:
        return errors

    # Extract paths mentioned in AIP phases/guidance
    aip_paths: set[str] = set()
    for phase in aip.phases:
        if phase.guidance and phase.guidance.likely_files:
            for f in phase.guidance.likely_files:
                aip_paths.add(f)

    # Check for obvious mismatches (e.g., src/spec/ when lorchestra/ is expected)
    for aip_path in aip_paths:
        # Check if AIP path uses specwright's structure for a non-specwright target
        if aip_path.startswith("src/spec/"):
            target = epic.get_target(spec.repo)
            if target and "specwright" not in target.repo_path.lower():
                errors.append(
                    f"AIP suggests '{aip_path}' but target repo is '{target.id}', "
                    f"not specwright. Expected paths like: {list(expected_paths)[:3]}"
                )

    return errors
