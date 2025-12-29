"""Tests for prompt resolution from checks directory."""

import tempfile
from pathlib import Path

import pytest

from spec.checks.resolver import PromptNotFoundError, resolve_prompt


class TestResolvePrompt:
    """Tests for resolve_prompt function."""

    def test_resolve_prompt_from_checks_directory(self) -> None:
        """Test that prompt is resolved from checks/ directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()

            prompt_content = "# Check Prompt\n\nAnalyze the code."
            prompt_file = checks_dir / "code-review.md"
            prompt_file.write_text(prompt_content)

            result = resolve_prompt("checks/code-review.md", epic_path)

            assert result == prompt_content

    def test_resolve_prompt_nested_path(self) -> None:
        """Test resolving prompt from nested path within epic directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            nested_dir = epic_path / "checks" / "security"
            nested_dir.mkdir(parents=True)

            prompt_content = "# Security Check\n\nCheck for vulnerabilities."
            prompt_file = nested_dir / "vuln-scan.md"
            prompt_file.write_text(prompt_content)

            result = resolve_prompt("checks/security/vuln-scan.md", epic_path)

            assert result == prompt_content

    def test_resolve_prompt_preserves_content(self) -> None:
        """Test that prompt content is preserved exactly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()

            prompt_content = """# Multi-line Prompt

## Instructions

1. Step one
2. Step two

```yaml
example: value
```

Special characters: <>&"'
"""
            prompt_file = checks_dir / "complex.md"
            prompt_file.write_text(prompt_content)

            result = resolve_prompt("checks/complex.md", epic_path)

            assert result == prompt_content

    def test_missing_prompt_raises_error(self) -> None:
        """Test that missing prompt file raises PromptNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()

            with pytest.raises(PromptNotFoundError) as exc_info:
                resolve_prompt("checks/nonexistent.md", epic_path)

            assert "Prompt file not found" in str(exc_info.value)
            assert "nonexistent.md" in str(exc_info.value)

    def test_missing_prompt_error_has_exit_code_2(self) -> None:
        """Test that PromptNotFoundError has exit_code 2."""
        assert PromptNotFoundError.exit_code == 2

    def test_resolve_prompt_from_root_of_epic(self) -> None:
        """Test resolving prompt from root of epic directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            prompt_content = "# Root Prompt"
            prompt_file = epic_path / "prompt.md"
            prompt_file.write_text(prompt_content)

            result = resolve_prompt("prompt.md", epic_path)

            assert result == prompt_content

    def test_resolve_prompt_empty_file(self) -> None:
        """Test resolving an empty prompt file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()

            prompt_file = checks_dir / "empty.md"
            prompt_file.write_text("")

            result = resolve_prompt("checks/empty.md", epic_path)

            assert result == ""

    def test_missing_directory_raises_error(self) -> None:
        """Test that missing directory raises PromptNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            # Don't create the checks directory

            with pytest.raises(PromptNotFoundError) as exc_info:
                resolve_prompt("checks/missing.md", epic_path)

            assert "Prompt file not found" in str(exc_info.value)
