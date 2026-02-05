"""Tests for SpecValidator."""

import pytest

from spec.governance.spec_validator import SpecValidator, ValidationResult


def _make_spec(
    plan: list | None = None,
    sections: dict | None = None,
) -> dict:
    """Create a minimal spec structure for testing."""
    base: dict = {
        "title": "Test Spec",
        "tier": "B",
        "version": "2.0",
        "objective": {"goal": "Test goal"},
    }
    if plan is not None:
        base["plan"] = plan
    if sections is not None:
        base["sections"] = sections
    return base


def _make_phase(
    index: int = 1,
    title: str = "Test Phase",
    objective: str = "Test objective",
    files_to_touch: list | None = None,
    verification: list | None = None,
) -> dict:
    """Create a phase structure for testing."""
    return {
        "index": index,
        "title": title,
        "objective": objective,
        "files_to_touch": files_to_touch or [],
        "verification": verification or [],
    }


class TestPhaseValidation:
    """Test phase subsection validation."""

    def test_phase_with_all_subsections_passes(self) -> None:
        """Phase with all required subsections passes validation (default mode)."""
        spec = _make_spec(plan=[
            _make_phase(
                objective="Implement feature X",
                files_to_touch=[{"path": "src/foo.py", "action": "create"}],
                verification=["pytest tests/"],
            ),
        ])
        # Use default mode for phase-only validation
        result = SpecValidator(spec, strict=False).validate()
        assert result.passed
        assert len(result.errors) == 0

    def test_phase_missing_objective_warns_default(self) -> None:
        """Missing objective produces warning in default mode."""
        spec = _make_spec(plan=[
            _make_phase(objective="", files_to_touch=[{"path": "x.py", "action": "modify"}], verification=["test"]),
        ])
        result = SpecValidator(spec, strict=False).validate()
        assert result.passed  # Warnings don't fail
        assert any("missing Objective" in w for w in result.warnings)

    def test_phase_missing_objective_errors_strict(self) -> None:
        """Missing objective produces error in strict mode."""
        spec = _make_spec(plan=[
            _make_phase(objective="", files_to_touch=[{"path": "x.py", "action": "modify"}], verification=["test"]),
        ])
        result = SpecValidator(spec, strict=True).validate()
        assert not result.passed
        assert any("missing Objective" in e for e in result.errors)

    def test_phase_missing_files_to_touch_warns_default(self) -> None:
        """Missing files_to_touch produces warning in default mode."""
        spec = _make_spec(plan=[
            _make_phase(objective="Do something", files_to_touch=[], verification=["test"]),
        ])
        result = SpecValidator(spec, strict=False).validate()
        assert result.passed
        assert any("missing Files to Touch" in w for w in result.warnings)

    def test_phase_missing_files_to_touch_errors_strict(self) -> None:
        """Missing files_to_touch produces error in strict mode."""
        spec = _make_spec(plan=[
            _make_phase(objective="Do something", files_to_touch=[], verification=["test"]),
        ])
        result = SpecValidator(spec, strict=True).validate()
        assert not result.passed
        assert any("missing Files to Touch" in e for e in result.errors)

    def test_phase_missing_verification_warns_default(self) -> None:
        """Missing verification produces warning in default mode."""
        spec = _make_spec(plan=[
            _make_phase(objective="Do something", files_to_touch=[{"path": "x.py", "action": "modify"}], verification=[]),
        ])
        result = SpecValidator(spec, strict=False).validate()
        assert result.passed
        assert any("missing Verification" in w for w in result.warnings)

    def test_phase_missing_verification_errors_strict(self) -> None:
        """Missing verification produces error in strict mode."""
        spec = _make_spec(plan=[
            _make_phase(objective="Do something", files_to_touch=[{"path": "x.py", "action": "modify"}], verification=[]),
        ])
        result = SpecValidator(spec, strict=True).validate()
        assert not result.passed
        assert any("missing Verification" in e for e in result.errors)

    def test_files_to_touch_entry_missing_path_warns(self) -> None:
        """files_to_touch entry without path produces warning."""
        spec = _make_spec(plan=[
            _make_phase(
                objective="Do something",
                files_to_touch=[{"action": "create"}],  # Missing path
                verification=["test"],
            ),
        ])
        result = SpecValidator(spec, strict=True).validate()
        assert any("missing path" in w for w in result.warnings)

    def test_files_to_touch_entry_missing_action_warns(self) -> None:
        """files_to_touch entry without action produces warning."""
        spec = _make_spec(plan=[
            _make_phase(
                objective="Do something",
                files_to_touch=[{"path": "x.py"}],  # Missing action
                verification=["test"],
            ),
        ])
        result = SpecValidator(spec, strict=True).validate()
        assert any("missing action" in w for w in result.warnings)

    def test_no_phases_warns_default(self) -> None:
        """No phases produces warning in default mode."""
        spec = _make_spec(plan=[])
        result = SpecValidator(spec, strict=False).validate()
        assert result.passed
        assert any("No phases" in w for w in result.warnings)

    def test_no_phases_errors_strict(self) -> None:
        """No phases produces error in strict mode."""
        spec = _make_spec(plan=[])
        result = SpecValidator(spec, strict=True).validate()
        assert not result.passed
        assert any("No phases" in e for e in result.errors)


class TestBuildContextValidation:
    """Test build context validation (strict mode only)."""

    def test_build_context_not_checked_default_mode(self) -> None:
        """Build context not checked in default mode."""
        spec = _make_spec(
            plan=[_make_phase(
                objective="X",
                files_to_touch=[{"path": "x.py", "action": "modify"}],
                verification=["test"],
            )],
            sections={},  # No build context sections
        )
        result = SpecValidator(spec, strict=False).validate()
        assert result.passed

    def test_missing_current_capabilities_errors_strict(self) -> None:
        """Missing Current Capabilities section errors in strict mode."""
        spec = _make_spec(
            plan=[_make_phase(
                objective="X",
                files_to_touch=[{"path": "x.py", "action": "modify"}],
                verification=["test"],
            )],
            sections={
                "proposed build_delta": "```yaml\nadds: {}\n```",
            },
        )
        result = SpecValidator(spec, strict=True).validate()
        assert not result.passed
        assert any("Current Capabilities" in e for e in result.errors)

    def test_missing_build_delta_errors_strict(self) -> None:
        """Missing Proposed build_delta section errors in strict mode."""
        spec = _make_spec(
            plan=[_make_phase(
                objective="X",
                files_to_touch=[{"path": "x.py", "action": "modify"}],
                verification=["test"],
            )],
            sections={
                "current capabilities": "Some capabilities...",
            },
        )
        result = SpecValidator(spec, strict=True).validate()
        assert not result.passed
        assert any("build_delta" in e for e in result.errors)

    def test_build_delta_invalid_yaml_errors(self) -> None:
        """build_delta with invalid YAML errors."""
        spec = _make_spec(
            plan=[_make_phase(
                objective="X",
                files_to_touch=[{"path": "x.py", "action": "modify"}],
                verification=["test"],
            )],
            sections={
                "current capabilities": "Some capabilities...",
                "proposed build_delta": "```yaml\ninvalid: yaml: :\n```",
            },
        )
        result = SpecValidator(spec, strict=True).validate()
        assert not result.passed
        assert any("not valid YAML" in e for e in result.errors)

    def test_build_delta_empty_content_warns(self) -> None:
        """build_delta with empty adds/modifies/removes warns."""
        spec = _make_spec(
            plan=[_make_phase(
                objective="X",
                files_to_touch=[{"path": "x.py", "action": "modify"}],
                verification=["test"],
            )],
            sections={
                "current capabilities": "Some capabilities...",
                "proposed build_delta": "```yaml\nadds: {}\nmodifies: {}\nremoves: {}\n```",
            },
        )
        result = SpecValidator(spec, strict=True).validate()
        # Should still pass but with warning
        assert any("no adds, modifies, or removes" in w for w in result.warnings)

    def test_valid_build_context_passes_strict(self) -> None:
        """Valid build context passes strict validation."""
        spec = _make_spec(
            plan=[_make_phase(
                objective="X",
                files_to_touch=[{"path": "src/new_module/__init__.py", "action": "create"}],
                verification=["test"],
            )],
            sections={
                "current capabilities": "Some capabilities...",
                "proposed build_delta": """```yaml
adds:
  layout:
    - path: src/new_module/
      adds:
        - __init__.py
modifies: {}
removes: {}
```""",
            },
        )
        result = SpecValidator(spec, strict=True).validate()
        assert result.passed


class TestConsistencyValidation:
    """Test consistency between build_delta and files_to_touch."""

    def test_consistency_not_checked_default_mode(self) -> None:
        """Consistency not checked in default mode."""
        spec = _make_spec(
            plan=[_make_phase(
                objective="X",
                files_to_touch=[],  # No files but delta adds
                verification=["test"],
            )],
            sections={
                "current capabilities": "...",
                "proposed build_delta": """```yaml
adds:
  layout:
    - path: src/new_module/
```""",
            },
        )
        # In default mode, only phase validation runs
        result = SpecValidator(spec, strict=False).validate()
        # No consistency warning because not strict
        assert not any("build_delta adds" in w for w in result.warnings)

    def test_delta_adds_path_not_in_files_to_touch_warns(self) -> None:
        """build_delta adds path but no files_to_touch create files there."""
        spec = _make_spec(
            plan=[_make_phase(
                objective="X",
                files_to_touch=[{"path": "unrelated/file.py", "action": "create"}],
                verification=["test"],
            )],
            sections={
                "current capabilities": "...",
                "proposed build_delta": """```yaml
adds:
  layout:
    - path: src/new_module/
```""",
            },
        )
        result = SpecValidator(spec, strict=True).validate()
        assert any("build_delta adds" in w and "src/new_module" in w for w in result.warnings)

    def test_delta_matches_files_to_touch_no_warning(self) -> None:
        """build_delta.adds.layout matches files_to_touch - no warning."""
        spec = _make_spec(
            plan=[_make_phase(
                objective="X",
                files_to_touch=[{"path": "src/new_module/__init__.py", "action": "create"}],
                verification=["test"],
            )],
            sections={
                "current capabilities": "...",
                "proposed build_delta": """```yaml
adds:
  layout:
    - path: src/new_module/
```""",
            },
        )
        result = SpecValidator(spec, strict=True).validate()
        # No warning about mismatch
        assert not any("build_delta adds" in w for w in result.warnings)


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_result_passed_when_no_errors(self) -> None:
        """Result passed is True when no errors."""
        spec = _make_spec(plan=[
            _make_phase(
                objective="X",
                files_to_touch=[{"path": "x.py", "action": "modify"}],
                verification=["test"],
            ),
        ])
        # Use default mode - strict requires build context
        result = SpecValidator(spec, strict=False).validate()
        assert result.passed

    def test_result_not_passed_when_errors(self) -> None:
        """Result passed is False when errors present."""
        spec = _make_spec(plan=[])
        result = SpecValidator(spec, strict=True).validate()
        assert not result.passed
        assert len(result.errors) > 0

    def test_warnings_collected(self) -> None:
        """Warnings are collected in result."""
        spec = _make_spec(plan=[
            _make_phase(objective="", files_to_touch=[], verification=[]),
        ])
        result = SpecValidator(spec, strict=False).validate()
        assert len(result.warnings) > 0
