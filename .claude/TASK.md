---
id: t004-05-spec-validation-enhancement
title: "Spec validation: enforce schema compliance with build_delta and phases"
tier: B
owner: benthepsychologist
goal: "Enhance spec validate spec to enforce full schema including phases, build_delta, and consistency checks"
branch: feat/spec-validation-v2
status: draft
---

# t004-05: spec validate spec — Enforce schema compliance with build_delta

**Epic:** t004-specwright-governance
**Branch:** `feat/spec-validation-v2`
**Tier:** B

## Objective

Enhance `spec validate spec` to enforce the full spec schema including:
1. Phase structure (not just "Step")
2. Required phase subsections: Objective, Files to Touch, Verification
3. Current Capabilities section (build.yaml context)
4. Proposed build_delta section
5. Consistency between build_delta and files_to_touch

This ensures specs produced by `spec draft` stay valid, and manually-written specs meet the same quality bar.

## Problem

1. **Current validation is too loose.** `spec validate spec` checks frontmatter and "Plan" section exists, but doesn't validate:
   - Phase structure (schema uses `## Phase N:`, not `### Step N:`)
   - Required subsections per phase
   - build_delta presence
   - Consistency between delta and implementation

2. **Schema drift.** The `spec-v1.0.schema.json` defines phases with `files_to_touch`, `verification`, etc., but the parser validates against a different structure (`### Step N:`).

3. **No build.yaml linkage.** Specs should reference what exists (Current Capabilities) and what changes (build_delta). Nothing enforces this.

## Current Capabilities (from specwright.build.yaml)

### kernel.surfaces

```yaml
- command: "spec validate spec"
  usage: "spec validate spec ./my-feature.md [--check]"
```

### modules

```yaml
- name: compiler
  kind: module
  provides: ["spec markdown parsing", "v1 YAML compilation"]
  depends_on: [core]
- name: governance
  kind: module
  provides: ["build validation", "epic validation", "contract validation"]
  depends_on: [governor, epic]
```

### layout

```yaml
- path: src/spec/compiler/
  module: compiler
  role: "Spec markdown parser and v1 compiler (legacy)"
- path: src/spec/governance/
  module: governance
  role: "Build, epic, and contract validation"
```

## Proposed build_delta

```yaml
build_delta:
  target: "projects/specwright/specwright.build.yaml"
  summary: "Enhance spec validation to enforce schema compliance with build_delta requirements"

  adds:
    layout:
      - path: src/spec/governance/
        adds:
          - spec_validator.py    # NEW - dedicated validation logic

  modifies:
    modules:
      - name: governance
        provides:
          - "build validation"
          - "epic validation"
          - "contract validation"
          - "spec scaffolding"
          - "intent parsing"
          - "spec schema validation"     # NEW

    kernel_surfaces:
      - command: "spec validate spec"
        usage: "spec validate spec ./my-feature.md [--check] [--strict]"
        description: "Validate spec structure, phases, build_delta (--strict enforces full schema)"

  removes: {}
```

## Acceptance Criteria

**Frontmatter validation (existing):**
- [ ] Required fields: tier, title, owner, goal
- [ ] tier is A, B, or C
- [ ] All fields are non-empty strings

**Phase validation (new):**
- [ ] Accepts both `## Phase N:` and `### Step N:` formats (backward compat)
- [ ] Each phase has `### Objective` subsection
- [ ] Each phase has `### Files to Touch` subsection (warning if missing, error with --strict)
- [ ] Each phase has `### Verification` subsection (warning if missing, error with --strict)
- [ ] files_to_touch entries have path and action (create/modify/delete)

**Build context validation (new, --strict only):**
- [ ] `## Current Capabilities` section exists
- [ ] `## Proposed build_delta` section exists
- [ ] build_delta is valid YAML
- [ ] build_delta has `adds`, `modifies`, or `removes` (at least one non-empty)

**Consistency validation (new, --strict only):**
- [ ] Paths in files_to_touch are consistent with build_delta.adds.layout
- [ ] If build_delta adds a module, files_to_touch should include files in that module's path

**CLI flags:**
- [ ] `--check` — validate without writing `validated: true` (existing)
- [ ] `--strict` — enforce build_delta and full phase structure (new)
- [ ] Default mode: warn on missing sections, don't fail
- [ ] Strict mode: fail on missing sections

## Constraints

- Backward compatible: existing specs pass default validation
- --strict is opt-in initially; becomes default after migration
- Warnings in default mode, errors in strict mode
- No LLM calls — pure structural validation

## Context

### Current parser structure (SpecParser)

```python
# src/spec/compiler/parser.py
REQUIRED_FRONTMATTER = {"tier", "title", "owner", "goal"}

def _validate_frontmatter(self):
    missing = self.REQUIRED_FRONTMATTER - set(self.frontmatter.keys())
    if missing:
        raise ValueError(f"Missing required frontmatter keys: {missing}")

def _parse_plan(self):
    plan_text = self.sections.get("plan", "")
    if not plan_text:
        raise ValueError("Plan section is required")
    # Looks for ### Step N: pattern
```

### What needs to change

1. **Accept Phase format**: `## Phase N:` in addition to `### Step N:`
2. **Validate phase subsections**: Objective, Files to Touch, Verification
3. **Parse build_delta**: Extract YAML from `## Proposed build_delta` section
4. **Cross-check**: build_delta.adds.layout paths match files_to_touch paths

### Why two modes?

- **Default mode**: Backward compatible. Existing specs pass. Warns about missing sections.
- **Strict mode**: Full enforcement. Used for new specs from `spec draft`. Required for CI gates.

The migration path:
1. `spec draft` produces specs that pass `--strict`
2. Old specs pass default validation (warnings only)
3. Over time, update old specs to pass `--strict`
4. Eventually make `--strict` the default

---

## Phase 1: Phase format support

### Objective
Update parser to accept `## Phase N:` format alongside `### Step N:`.

### Files to Touch
- `src/spec/compiler/parser.py` (modify) — add phase pattern matching alongside step pattern
- `tests/compiler/test_parser.py` (modify) — add tests for phase format

### Implementation Notes

```python
import re

# Add alongside existing step_pattern
PHASE_PATTERN = re.compile(
    r'^##\s+Phase\s+(\d+):\s*(.+?)$',
    re.MULTILINE
)

def _parse_plan(self):
    """Parse Plan section into structured steps/phases."""
    plan_text = self.sections.get("plan", "")

    # Also look for phases directly in body (not under Plan section)
    if not plan_text:
        plan_text = self._extract_phases_from_body()

    if not plan_text:
        raise ValueError("Plan section or Phase sections required")

    # Try phases first (new format)
    phases = self._parse_phases(plan_text)
    if phases:
        self.plan_steps = phases
        return

    # Fall back to steps (legacy format)
    self._parse_steps(plan_text)

def _extract_phases_from_body(self) -> str:
    """Extract all content from ## Phase N: sections."""
    matches = list(PHASE_PATTERN.finditer(self.content_body))
    if not matches:
        return ""
    # Return content from first phase to end
    return self.content_body[matches[0].start():]

def _parse_phases(self, text: str) -> list[dict]:
    """Parse ## Phase N: sections into structured data."""
    phases = []
    for match in PHASE_PATTERN.finditer(text):
        phase_num = int(match.group(1))
        phase_title = match.group(2).strip()

        # Extract phase body (until next phase or end)
        start = match.end()
        next_match = PHASE_PATTERN.search(text, start)
        end = next_match.start() if next_match else len(text)
        phase_body = text[start:end].strip()

        phases.append({
            "index": phase_num,
            "title": phase_title,
            "objective": self._extract_subsection(phase_body, "Objective"),
            "files_to_touch": self._extract_files_to_touch(phase_body),
            "implementation_notes": self._extract_subsection(phase_body, "Implementation Notes"),
            "verification": self._extract_verification(phase_body),
        })

    return sorted(phases, key=lambda p: p["index"])
```

### Verification
- `pytest tests/compiler/test_parser.py -v -k phase`
- Spec with `## Phase 1:` format → parses successfully, extracts subsections
- Spec with `### Step 1:` format → still works (backward compat)
- Spec with no phases or steps → raises ValueError

---

## Phase 2: Phase subsection validation

### Objective
Validate that each phase has required subsections: Objective, Files to Touch, Verification.

### Files to Touch
- `src/spec/governance/spec_validator.py` (create) — SpecValidator class with phase validation
- `src/spec/governance/__init__.py` (modify) — export SpecValidator
- `tests/governance/test_spec_validator.py` (create) — validation tests

### Implementation Notes

```python
"""Spec structural validation beyond basic parsing."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml
import re


@dataclass
class ValidationResult:
    """Result of spec validation."""
    passed: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SpecValidator:
    """Validate spec structure beyond basic parsing."""

    def __init__(self, parsed_spec: dict[str, Any], strict: bool = False):
        self.spec = parsed_spec
        self.strict = strict
        self.warnings: list[str] = []
        self.errors: list[str] = []

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
        phases = self.spec.get("phases", self.spec.get("plan_steps", []))
        if not phases:
            self._add_issue("No phases found", warning=not self.strict)
            return

        for i, phase in enumerate(phases, 1):
            phase_id = f"Phase {phase.get('index', i)}"

            # Objective required
            if not phase.get("objective"):
                self._add_issue(f"{phase_id} missing Objective", warning=not self.strict)

            # Files to Touch
            if not phase.get("files_to_touch"):
                self._add_issue(f"{phase_id} missing Files to Touch", warning=not self.strict)
            else:
                self._validate_files_to_touch(phase_id, phase["files_to_touch"])

            # Verification
            if not phase.get("verification"):
                self._add_issue(f"{phase_id} missing Verification", warning=not self.strict)

    def _validate_files_to_touch(self, phase_id: str, files: list) -> None:
        """Validate files_to_touch entries."""
        for f in files:
            if isinstance(f, dict):
                if not f.get("path"):
                    self._add_issue(f"{phase_id}: files_to_touch entry missing path", warning=True)
                if not f.get("action"):
                    self._add_issue(f"{phase_id}: files_to_touch entry missing action", warning=True)
```

### Verification
- `pytest tests/governance/test_spec_validator.py -v`
- `python -c "from spec.governance.spec_validator import SpecValidator; print('OK')"`
- Phase with all subsections → passes
- Phase missing Objective → warning (default) or error (strict)
- Phase missing Files to Touch → warning (default) or error (strict)
- Phase missing Verification → warning (default) or error (strict)

---

## Phase 3: Build context validation

### Objective
Validate Current Capabilities and Proposed build_delta sections in strict mode.

### Files to Touch
- `src/spec/governance/spec_validator.py` (modify) — add _validate_build_context method
- `src/spec/compiler/parser.py` (modify) — extract build_delta YAML from section
- `tests/governance/test_spec_validator.py` (modify) — add build context tests

### Implementation Notes

```python
def _validate_build_context(self) -> None:
    """Validate build.yaml context sections (strict mode only)."""
    sections = self.spec.get("sections", {})

    # Normalize section keys (lowercase)
    section_keys = {k.lower(): k for k in sections.keys()}

    # Check Current Capabilities
    if "current capabilities" not in section_keys:
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

def _parse_build_delta(self, content: str) -> dict | None:
    """Extract YAML from build_delta section."""
    # Find ```yaml ... ``` block
    match = re.search(r'```ya?ml\n(.*?)\n```', content, re.DOTALL)
    if not match:
        return None

    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
```

### Verification
- `pytest tests/governance/test_spec_validator.py -v -k build_context`
- Spec with Current Capabilities + build_delta → passes strict
- Spec missing Current Capabilities → fails strict
- Spec missing build_delta → fails strict
- build_delta with invalid YAML → error
- build_delta with empty adds/modifies/removes → warning

---

## Phase 4: Consistency validation

### Objective
Cross-check build_delta against files_to_touch to ensure they're aligned.

### Files to Touch
- `src/spec/governance/spec_validator.py` (modify) — add _validate_consistency method
- `tests/governance/test_spec_validator.py` (modify) — add consistency tests

### Implementation Notes

```python
def _validate_consistency(self) -> None:
    """Check build_delta aligns with files_to_touch (strict mode only)."""
    if not hasattr(self, "_build_delta") or not self._build_delta:
        return  # No delta to check, already reported

    # Collect paths from build_delta.adds.layout
    delta_layout_paths = set()
    adds = self._build_delta.get("adds", {})
    for item in adds.get("layout", []):
        if isinstance(item, dict) and "path" in item:
            delta_layout_paths.add(item["path"].rstrip("/"))
        elif isinstance(item, str):
            delta_layout_paths.add(item.rstrip("/"))

    # Collect parent directories from files_to_touch (create actions)
    files_dirs = set()
    phases = self.spec.get("phases", self.spec.get("plan_steps", []))
    for phase in phases:
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
        matches = [d for d in files_dirs if d.startswith(delta_path) or delta_path.startswith(d)]
        if not matches:
            self._add_issue(
                f"build_delta adds '{delta_path}/' but no files_to_touch create files there",
                warning=True  # Warning — might be filled in later during implementation
            )
```

### Verification
- `pytest tests/governance/test_spec_validator.py -v -k consistency`
- build_delta adds `compose/life/`, files_to_touch has `compose/life/docker-compose.yaml` → passes
- build_delta adds `src/new_module/`, files_to_touch has `src/new_module/__init__.py` → passes
- build_delta adds path not in files_to_touch → warning (not error)

---

## Phase 5: CLI integration

### Objective
Wire SpecValidator into `spec validate spec` CLI command with `--strict` flag.

### Files to Touch
- `src/spec/cli/governance.py` (modify) — add --strict flag, integrate SpecValidator
- `tests/cli/test_validate_spec.py` (create) — CLI integration tests

### Implementation Notes

```python
@validate_app.command("spec")
def validate_spec(
    spec_path: Path = typer.Argument(
        None,
        help="Path to spec .md file (uses current if omitted)",
    ),
    check_only: bool = typer.Option(
        False, "--check", "-c",
        help="Check only, don't write validated flag",
    ),
    strict: bool = typer.Option(
        False, "--strict", "-s",
        help="Enforce build_delta and full phase structure",
    ),
) -> None:
    """Validate a spec markdown file structure.

    Validates YAML frontmatter (required: tier, title, owner, goal),
    phase structure, and optionally build_delta context.

    Default mode warns about missing sections. Strict mode (--strict)
    requires full schema compliance including Current Capabilities
    and Proposed build_delta sections.

    Examples:
        spec validate spec ./my-feature.md
        spec validate spec ./my-feature.md --check
        spec validate spec ./my-feature.md --strict
    """
    # ... existing path resolution and parsing ...

    from spec.compiler.parser import SpecParser
    from spec.governance.spec_validator import SpecValidator

    try:
        content = spec_path.read_text()
        parser = SpecParser(content, source_path=spec_path)
        parsed = parser.parse()
        typer.secho("Spec parsing OK", fg=typer.colors.GREEN)
    except ValueError as e:
        typer.secho(f"Parse error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    # Run structural validation
    validator = SpecValidator(parsed, strict=strict)
    result = validator.validate()

    # Print warnings
    for w in result.warnings:
        typer.secho(f"  Warning: {w}", fg=typer.colors.YELLOW)

    # Print errors
    for e in result.errors:
        typer.secho(f"  Error: {e}", fg=typer.colors.RED)

    if not result.passed:
        typer.secho("Validation failed", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if strict:
        typer.secho("Strict validation passed", fg=typer.colors.GREEN)
    else:
        typer.secho("Validation passed", fg=typer.colors.GREEN)

    # ... existing validated flag writing ...
```

### Verification
- `spec validate spec --help` → shows --strict flag
- `spec validate spec t004-04-spec-draft.md` → passes, may show warnings
- `spec validate spec t004-04-spec-draft.md --strict` → passes (it has all sections)
- `spec validate spec thin-spec.md` → warns about missing sections
- `spec validate spec thin-spec.md --strict` → fails with errors
- `ruff check src/spec/cli/governance.py` → clean
- `pytest tests/cli/test_validate_spec.py -v` → passes
