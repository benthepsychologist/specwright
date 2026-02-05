"""Tests for spec validate spec CLI command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from spec.cli.spec import app

runner = CliRunner()


# Minimal valid spec with Phase format
VALID_SPEC_PHASE_FORMAT = """---
tier: B
title: Test Feature
owner: test@example.com
goal: Test goal for the feature
---

# Test Feature

## Phase 1: Setup

### Objective
Implement the core functionality.

### Files to Touch
- `src/foo.py` (create) — main module

### Verification
- `pytest tests/`
"""

# Legacy step format
VALID_SPEC_STEP_FORMAT = """---
tier: B
title: Test Feature
owner: test@example.com
goal: Test goal for the feature
---

# Test Feature

## Plan

### Step 1: Setup

**Prompt:**
Implement the core functionality.

**Outputs:**
- `src/foo.py`
"""

# Spec with build context for strict mode
VALID_SPEC_STRICT = """---
tier: B
title: Test Feature
owner: test@example.com
goal: Test goal for the feature
---

# Test Feature

## Current Capabilities

The system currently has X and Y.

## Proposed build_delta

```yaml
adds:
  layout:
    - path: src/new_module/
      adds:
        - __init__.py
modifies: {}
removes: {}
```

## Phase 1: Setup

### Objective
Implement the core functionality.

### Files to Touch
- `src/new_module/__init__.py` (create) — init module

### Verification
- `pytest tests/`
"""

# Spec missing phase subsections (will warn in default, error in strict)
SPEC_MISSING_SUBSECTIONS = """---
tier: B
title: Test Feature
owner: test@example.com
goal: Test goal for the feature
---

# Test Feature

## Phase 1: Setup

Just some content without proper subsections.
"""


class TestValidateSpecCommand:
    """Test spec validate spec CLI command."""

    def test_validate_phase_format_passes(self, tmp_path: Path) -> None:
        """Phase format spec passes default validation."""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text(VALID_SPEC_PHASE_FORMAT)

        result = runner.invoke(app, ["validate", "spec", str(spec_file), "--check"])
        assert result.exit_code == 0
        assert "Validation passed" in result.stdout

    def test_validate_step_format_passes(self, tmp_path: Path) -> None:
        """Legacy step format spec passes default validation."""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text(VALID_SPEC_STEP_FORMAT)

        result = runner.invoke(app, ["validate", "spec", str(spec_file), "--check"])
        assert result.exit_code == 0
        assert "Validation passed" in result.stdout

    def test_validate_missing_subsections_warns_default(self, tmp_path: Path) -> None:
        """Missing subsections produce warnings in default mode."""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text(SPEC_MISSING_SUBSECTIONS)

        result = runner.invoke(app, ["validate", "spec", str(spec_file), "--check"])
        assert result.exit_code == 0  # Warnings don't fail
        assert "Warning" in result.stdout

    def test_validate_missing_subsections_errors_strict(self, tmp_path: Path) -> None:
        """Missing subsections produce errors in strict mode."""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text(SPEC_MISSING_SUBSECTIONS)

        result = runner.invoke(app, ["validate", "spec", str(spec_file), "--check", "--strict"])
        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert "Error" in output
        assert "Validation failed" in output

    def test_validate_strict_requires_build_context(self, tmp_path: Path) -> None:
        """Strict mode requires Current Capabilities and build_delta."""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text(VALID_SPEC_PHASE_FORMAT)  # Has phases but no build context

        result = runner.invoke(app, ["validate", "spec", str(spec_file), "--check", "--strict"])
        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert "Current Capabilities" in output or "build_delta" in output

    def test_validate_strict_with_full_context_passes(self, tmp_path: Path) -> None:
        """Strict mode passes with full build context."""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text(VALID_SPEC_STRICT)

        result = runner.invoke(app, ["validate", "spec", str(spec_file), "--check", "--strict"])
        assert result.exit_code == 0
        assert "Strict validation passed" in result.stdout

    def test_validate_file_not_found(self, tmp_path: Path) -> None:
        """Missing file produces error."""
        result = runner.invoke(app, ["validate", "spec", str(tmp_path / "nonexistent.md")])
        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert "not found" in output

    def test_validate_non_md_file(self, tmp_path: Path) -> None:
        """Non-.md file produces error."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a spec")

        result = runner.invoke(app, ["validate", "spec", str(txt_file)])
        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert ".md file" in output

    def test_validate_writes_validated_flag(self, tmp_path: Path) -> None:
        """Without --check, writes validated: true to frontmatter."""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text(VALID_SPEC_PHASE_FORMAT)

        result = runner.invoke(app, ["validate", "spec", str(spec_file)])
        assert result.exit_code == 0
        assert "validated: true" in result.stdout

        # Check the file was updated
        content = spec_file.read_text()
        assert "validated: true" in content or "validated: True" in content

    def test_validate_check_does_not_modify(self, tmp_path: Path) -> None:
        """--check flag does not modify the file."""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text(VALID_SPEC_PHASE_FORMAT)
        original_content = spec_file.read_text()

        result = runner.invoke(app, ["validate", "spec", str(spec_file), "--check"])
        assert result.exit_code == 0

        # File should be unchanged
        assert spec_file.read_text() == original_content

    def test_validate_invalid_frontmatter(self, tmp_path: Path) -> None:
        """Invalid frontmatter produces error."""
        spec_file = tmp_path / "test-spec.md"
        spec_file.write_text("""---
tier: X
title: Missing fields
---
# Test
""")

        result = runner.invoke(app, ["validate", "spec", str(spec_file)])
        assert result.exit_code == 1
        output = result.stdout + (result.stderr or "")
        assert "Invalid" in output or "Missing" in output

    def test_validate_help_shows_strict(self) -> None:
        """--help shows --strict option."""
        result = runner.invoke(app, ["validate", "spec", "--help"])
        assert result.exit_code == 0
        assert "--strict" in result.stdout
