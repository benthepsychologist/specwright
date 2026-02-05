"""Spec structural validation beyond basic parsing.

Validates:
- Phase subsections (Objective, Files to Touch, Verification)
- Build context (Current Capabilities, Proposed build_delta) in strict mode
- Consistency between build_delta and files_to_touch in strict mode
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ValidationResult:
    """Result of spec validation."""

    passed: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SpecValidator:
    """Validate spec structure beyond basic parsing.

    Default mode: warn on missing sections, don't fail
    Strict mode: fail on missing sections (build_delta, phase subsections)
    """

    def __init__(self, parsed_spec: dict[str, Any], strict: bool = False):
        """Initialize validator.

        Args:
            parsed_spec: Output from SpecParser.parse()
            strict: If True, require full schema compliance
        """
        self.spec = parsed_spec
        self.strict = strict
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self._build_delta: dict[str, Any] | None = None

    def validate(self) -> ValidationResult:
        """Validate spec and return result."""
        self._validate_phases()
        if self.strict:
            self._validate_build_context()
            self._validate_consistency()

        return ValidationResult(
            passed=len(self.errors) == 0,
            warnings=self.warnings,
            errors=self.errors,
        )

    def _add_issue(self, message: str, warning: bool = False) -> None:
        """Add warning or error."""
        if warning:
            self.warnings.append(message)
        else:
            self.errors.append(message)

    def _validate_phases(self) -> None:
        """Validate phase subsections."""
        # plan_steps holds both phases (new format) and steps (legacy)
        phases = self.spec.get("plan", [])
        if not phases:
            self._add_issue("No phases found in plan", warning=not self.strict)
            return

        for i, phase in enumerate(phases, 1):
            # Use phase index if available, else use loop index
            phase_id = f"Phase {phase.get('index', i)}"
            phase_title = phase.get("title", phase.get("description", ""))
            if phase_title:
                phase_id = f"{phase_id}: {phase_title}"

            # Objective required
            objective = phase.get("objective", "")
            if not objective:
                self._add_issue(f"{phase_id} missing Objective", warning=not self.strict)

            # Files to Touch
            files_to_touch = phase.get("files_to_touch", [])
            if not files_to_touch:
                self._add_issue(f"{phase_id} missing Files to Touch", warning=not self.strict)
            else:
                self._validate_files_to_touch(phase_id, files_to_touch)

            # Verification
            verification = phase.get("verification", phase.get("verification_steps", []))
            if not verification:
                self._add_issue(f"{phase_id} missing Verification", warning=not self.strict)

    def _validate_files_to_touch(self, phase_id: str, files: list) -> None:
        """Validate files_to_touch entries."""
        for f in files:
            if isinstance(f, dict):
                if not f.get("path"):
                    self._add_issue(f"{phase_id}: files_to_touch entry missing path", warning=True)
                if not f.get("action"):
                    self._add_issue(f"{phase_id}: files_to_touch entry missing action", warning=True)
            elif isinstance(f, str):
                # String-only entries are allowed but less informative
                pass

    def _validate_build_context(self) -> None:
        """Validate build.yaml context sections (strict mode only).

        Checks for Current Capabilities and Proposed build_delta sections.
        """
        sections = self.spec.get("sections", {})

        # Normalize section keys (lowercase)
        section_keys = {k.lower(): k for k in sections.keys()}

        # Check Current Capabilities
        current_cap_key = None
        for key in section_keys:
            if "current capabilities" in key:
                current_cap_key = section_keys[key]
                break

        if not current_cap_key:
            self._add_issue("Missing 'Current Capabilities' section", warning=False)

        # Check Proposed build_delta
        build_delta_key = None
        for key in section_keys:
            if "build_delta" in key or "build delta" in key:
                build_delta_key = section_keys[key]
                break

        if not build_delta_key:
            self._add_issue("Missing 'Proposed build_delta' section", warning=False)
        else:
            delta_content = sections[build_delta_key]
            delta = self._parse_build_delta(delta_content)
            if delta is None:
                self._add_issue("build_delta is not valid YAML", warning=False)
            elif not any([
                delta.get("adds"),
                delta.get("modifies"),
                delta.get("removes"),
            ]):
                self._add_issue(
                    "build_delta has no adds, modifies, or removes",
                    warning=True  # Might be a no-op spec
                )
            else:
                self._build_delta = delta

    def _parse_build_delta(self, content: str) -> dict[str, Any] | None:
        """Extract YAML from build_delta section.

        Looks for ```yaml ... ``` code blocks.
        """
        # Find ```yaml ... ``` or ```yml ... ``` block
        match = re.search(r'```ya?ml\n(.*?)\n```', content, re.DOTALL)
        if not match:
            return None

        try:
            return yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return None

    def _validate_consistency(self) -> None:
        """Check build_delta aligns with files_to_touch (strict mode only)."""
        if not self._build_delta:
            return  # No delta to check, already reported

        # Collect paths from build_delta.adds.layout
        delta_layout_paths = set()
        adds = self._build_delta.get("adds", {})
        layout_adds = adds.get("layout", [])

        for item in layout_adds:
            if isinstance(item, dict):
                path = item.get("path", "")
                if path:
                    delta_layout_paths.add(path.rstrip("/"))
                # Also check for nested 'adds' in layout entries
                nested_adds = item.get("adds", [])
                for nested in nested_adds:
                    if isinstance(nested, str):
                        # Combine parent path with nested file
                        parent = path.rstrip("/")
                        delta_layout_paths.add(f"{parent}/{nested}")
            elif isinstance(item, str):
                delta_layout_paths.add(item.rstrip("/"))

        if not delta_layout_paths:
            return  # No layout additions to check

        # Collect parent directories from files_to_touch (create actions)
        files_dirs = set()
        plan = self.spec.get("plan", [])
        for phase in plan:
            for f in phase.get("files_to_touch", []):
                if isinstance(f, dict) and f.get("action") == "create":
                    path = f.get("path", "")
                    parent = str(Path(path).parent)
                    files_dirs.add(parent.rstrip("/"))
                    # Also add the path itself if it's a directory
                    if not Path(path).suffix:
                        files_dirs.add(path.rstrip("/"))

        # Check: if delta adds layout paths, files_to_touch should create files there
        for delta_path in delta_layout_paths:
            # Check if any files_to_touch path is under this delta path
            matches = [d for d in files_dirs if d.startswith(delta_path) or delta_path.startswith(d)]
            if not matches:
                self._add_issue(
                    f"build_delta adds '{delta_path}' but no files_to_touch create files there",
                    warning=True  # Warning — might be filled in later during implementation
                )
