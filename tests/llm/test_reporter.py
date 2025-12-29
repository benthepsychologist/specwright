"""Tests for check report writing and verdict parsing."""

import tempfile
from datetime import datetime
from pathlib import Path

from spec.llm.reporter import (
    VALID_VERDICTS,
    CheckReport,
    parse_verdict,
    write_report,
)


class TestCheckReport:
    """Tests for CheckReport dataclass."""

    def test_create_minimal_report(self) -> None:
        """Test creating a report with minimal fields."""
        report = CheckReport(
            check_id="CHECK-001",
            epic_id="e001-test-epic",
            spec_id=None,
            model="stub",
            timestamp=datetime(2025, 12, 26, 14, 30, 0),
            inputs=["epic.yaml"],
            verdict="PASS",
            content="All checks passed.",
        )

        assert report.check_id == "CHECK-001"
        assert report.epic_id == "e001-test-epic"
        assert report.spec_id is None
        assert report.model == "stub"
        assert report.verdict == "PASS"

    def test_create_full_report(self) -> None:
        """Test creating a report with all fields."""
        report = CheckReport(
            check_id="CHECK-002",
            epic_id="e001-test-epic",
            spec_id="e001-01-core",
            model="gpt-4o",
            timestamp=datetime(2025, 12, 26, 14, 30, 0),
            inputs=["epic.yaml", "specs/spec.md"],
            verdict="WARN",
            content="Some warnings found.\n\n## Details\n- Issue 1",
        )

        assert report.check_id == "CHECK-002"
        assert report.spec_id == "e001-01-core"
        assert report.model == "gpt-4o"
        assert len(report.inputs) == 2


class TestWriteReport:
    """Tests for write_report function."""

    def test_creates_reports_directory(self) -> None:
        """Test that reports directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            report = CheckReport(
                check_id="CHECK-001",
                epic_id="e001-test",
                spec_id=None,
                model="stub",
                timestamp=datetime(2025, 12, 26, 14, 30, 0),
                inputs=["epic.yaml"],
                verdict="PASS",
                content="Test content",
            )

            write_report(report, epic_path)

            assert (epic_path / "reports").exists()
            assert (epic_path / "reports").is_dir()

    def test_filename_format(self) -> None:
        """Test that filename follows YYYYMMDD-HHMM-<check_id>.md format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            report = CheckReport(
                check_id="CHECK-001",
                epic_id="e001-test",
                spec_id=None,
                model="stub",
                timestamp=datetime(2025, 12, 26, 14, 30, 0),
                inputs=["epic.yaml"],
                verdict="PASS",
                content="Test content",
            )

            result_path = write_report(report, epic_path)

            assert result_path.name == "20251226-1430-CHECK-001.md"

    def test_returns_correct_path(self) -> None:
        """Test that the returned path is correct."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            report = CheckReport(
                check_id="CHECK-001",
                epic_id="e001-test",
                spec_id=None,
                model="stub",
                timestamp=datetime(2025, 12, 26, 14, 30, 0),
                inputs=["epic.yaml"],
                verdict="PASS",
                content="Test content",
            )

            result_path = write_report(report, epic_path)

            assert result_path.exists()
            assert result_path.parent == epic_path / "reports"

    def test_frontmatter_without_spec_id(self) -> None:
        """Test frontmatter when spec_id is None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            report = CheckReport(
                check_id="CHECK-001",
                epic_id="e001-test",
                spec_id=None,
                model="stub",
                timestamp=datetime(2025, 12, 26, 14, 30, 0),
                inputs=["epic.yaml"],
                verdict="PASS",
                content="Test content",
            )

            result_path = write_report(report, epic_path)
            content = result_path.read_text()

            assert "---" in content
            assert "check_id: CHECK-001" in content
            assert "epic_id: e001-test" in content
            assert "spec_id:" not in content
            assert "model: stub" in content
            assert "verdict: PASS" in content

    def test_frontmatter_with_spec_id(self) -> None:
        """Test frontmatter when spec_id is provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            report = CheckReport(
                check_id="CHECK-001",
                epic_id="e001-test",
                spec_id="e001-01-core",
                model="gpt-4o",
                timestamp=datetime(2025, 12, 26, 14, 30, 0),
                inputs=["epic.yaml", "specs/spec.md"],
                verdict="WARN",
                content="Some warnings",
            )

            result_path = write_report(report, epic_path)
            content = result_path.read_text()

            assert "spec_id: e001-01-core" in content

    def test_inputs_in_frontmatter(self) -> None:
        """Test that inputs are listed in frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            report = CheckReport(
                check_id="CHECK-001",
                epic_id="e001-test",
                spec_id=None,
                model="stub",
                timestamp=datetime(2025, 12, 26, 14, 30, 0),
                inputs=["epic.yaml", "projects/specwright/specs/spec.md"],
                verdict="PASS",
                content="Test content",
            )

            result_path = write_report(report, epic_path)
            content = result_path.read_text()

            assert "inputs:" in content
            assert "  - epic.yaml" in content
            assert "  - projects/specwright/specs/spec.md" in content

    def test_timestamp_format(self) -> None:
        """Test that timestamp is in ISO format with Z suffix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            report = CheckReport(
                check_id="CHECK-001",
                epic_id="e001-test",
                spec_id=None,
                model="stub",
                timestamp=datetime(2025, 12, 26, 14, 30, 0),
                inputs=["epic.yaml"],
                verdict="PASS",
                content="Test content",
            )

            result_path = write_report(report, epic_path)
            content = result_path.read_text()

            assert "timestamp: 2025-12-26T14:30:00Z" in content

    def test_content_after_frontmatter(self) -> None:
        """Test that content appears after frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            markdown_content = "## Analysis\n\nThis is the analysis.\n\n### Section 1\n\nDetails here."
            report = CheckReport(
                check_id="CHECK-001",
                epic_id="e001-test",
                spec_id=None,
                model="gpt-4o",
                timestamp=datetime(2025, 12, 26, 14, 30, 0),
                inputs=["epic.yaml"],
                verdict="PASS",
                content=markdown_content,
            )

            result_path = write_report(report, epic_path)
            content = result_path.read_text()

            # Content should appear after the closing ---
            parts = content.split("---")
            assert len(parts) >= 3  # Before first ---, between ---, after second ---
            assert markdown_content in parts[-1]

    def test_full_report_format(self) -> None:
        """Test complete report format matches specification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            report = CheckReport(
                check_id="CHECK-xxx",
                epic_id="e001-epic-system",
                spec_id="e001-01-epic-core",
                model="gpt-4o",
                timestamp=datetime(2025, 12, 26, 14, 30, 0),
                inputs=["epic.yaml", "projects/specwright/specs/spec.md"],
                verdict="WARN",
                content="<markdown body from response>",
            )

            result_path = write_report(report, epic_path)
            content = result_path.read_text()

            expected_lines = [
                "---",
                "check_id: CHECK-xxx",
                "epic_id: e001-epic-system",
                "spec_id: e001-01-epic-core",
                "model: gpt-4o",
                "timestamp: 2025-12-26T14:30:00Z",
                "inputs:",
                "  - epic.yaml",
                "  - projects/specwright/specs/spec.md",
                "verdict: WARN",
                "---",
                "<markdown body from response>",
            ]

            for line in expected_lines:
                assert line in content, f"Expected '{line}' in content"


class TestParseVerdict:
    """Tests for parse_verdict function."""

    def test_parse_pass_verdict(self) -> None:
        """Test parsing PASS verdict."""
        response = "Some analysis here.\n\nVERDICT: PASS"
        assert parse_verdict(response) == "PASS"

    def test_parse_warn_verdict(self) -> None:
        """Test parsing WARN verdict."""
        response = "Some analysis here.\n\nVERDICT: WARN"
        assert parse_verdict(response) == "WARN"

    def test_parse_fail_verdict(self) -> None:
        """Test parsing FAIL verdict."""
        response = "Some analysis here.\n\nVERDICT: FAIL"
        assert parse_verdict(response) == "FAIL"

    def test_parse_error_verdict(self) -> None:
        """Test parsing ERROR verdict."""
        response = "Some analysis here.\n\nVERDICT: ERROR"
        assert parse_verdict(response) == "ERROR"

    def test_parse_not_run_verdict(self) -> None:
        """Test parsing NOT_RUN verdict."""
        response = "Some analysis here.\n\nVERDICT: NOT_RUN"
        assert parse_verdict(response) == "NOT_RUN"

    def test_verdict_at_start_of_line(self) -> None:
        """Test that VERDICT: must be at start of line."""
        response = "VERDICT: PASS\nMore content"
        assert parse_verdict(response) == "PASS"

    def test_verdict_with_leading_whitespace(self) -> None:
        """Test verdict with leading whitespace on line."""
        response = "Analysis\n  VERDICT: PASS"
        assert parse_verdict(response) == "PASS"

    def test_verdict_with_trailing_content(self) -> None:
        """Test verdict with trailing content is handled."""
        response = "VERDICT: PASS - all checks succeeded"
        assert parse_verdict(response) == "PASS"

    def test_no_verdict_stub_returns_not_run(self) -> None:
        """Test that missing verdict in stub returns NOT_RUN."""
        response = "No verdict line here"
        assert parse_verdict(response, is_stub=True) == "NOT_RUN"

    def test_no_verdict_real_llm_returns_error(self) -> None:
        """Test that missing verdict in real LLM response returns ERROR."""
        response = "No verdict line here"
        assert parse_verdict(response, is_stub=False) == "ERROR"

    def test_empty_response_stub(self) -> None:
        """Test empty response with stub."""
        assert parse_verdict("", is_stub=True) == "NOT_RUN"

    def test_empty_response_real_llm(self) -> None:
        """Test empty response with real LLM."""
        assert parse_verdict("", is_stub=False) == "ERROR"

    def test_invalid_verdict_value_stub(self) -> None:
        """Test invalid verdict value with stub."""
        response = "VERDICT: INVALID"
        assert parse_verdict(response, is_stub=True) == "NOT_RUN"

    def test_invalid_verdict_value_real_llm(self) -> None:
        """Test invalid verdict value with real LLM."""
        response = "VERDICT: INVALID"
        assert parse_verdict(response, is_stub=False) == "ERROR"

    def test_verdict_colon_no_value_stub(self) -> None:
        """Test VERDICT: with no value in stub."""
        response = "VERDICT:"
        assert parse_verdict(response, is_stub=True) == "NOT_RUN"

    def test_verdict_colon_no_value_real_llm(self) -> None:
        """Test VERDICT: with no value in real LLM."""
        response = "VERDICT:"
        assert parse_verdict(response, is_stub=False) == "ERROR"

    def test_case_sensitivity(self) -> None:
        """Test that verdict values are case-sensitive."""
        response = "VERDICT: pass"
        assert parse_verdict(response, is_stub=False) == "ERROR"

    def test_first_verdict_wins(self) -> None:
        """Test that first VERDICT line is used."""
        response = "VERDICT: PASS\nSome more content\nVERDICT: FAIL"
        assert parse_verdict(response) == "PASS"

    def test_verdict_in_middle_of_response(self) -> None:
        """Test verdict can appear in middle of response."""
        response = "## Analysis\n\nVERDICT: WARN\n\n## Details\nMore info"
        assert parse_verdict(response) == "WARN"


class TestValidVerdicts:
    """Tests for VALID_VERDICTS constant."""

    def test_contains_all_expected_verdicts(self) -> None:
        """Test that all expected verdicts are present."""
        expected = {"PASS", "WARN", "FAIL", "ERROR", "NOT_RUN"}
        assert VALID_VERDICTS == expected

    def test_is_frozen(self) -> None:
        """Test that VALID_VERDICTS is immutable."""
        assert isinstance(VALID_VERDICTS, frozenset)
