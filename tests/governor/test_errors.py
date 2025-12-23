"""Tests for error records module."""

from datetime import datetime
from pathlib import Path

from spec.governor.errors import (
    ErrorContext,
    ErrorRecord,
    ErrorRecordGenerator,
    ErrorType,
)


class TestErrorRecord:
    """Tests for ErrorRecord dataclass."""

    def test_to_dict_required_fields(self) -> None:
        """Required fields are included in dict."""
        error = ErrorRecord(
            error_id="ERR-2025-12-22-001",
            error_type=ErrorType.FAIL_VERIFY,
            message="Test failed",
            timestamp=datetime(2025, 12, 22, 12, 0, 0),
            repo="test-repo",
            aip_ref="aips/AIP-001.yaml",
        )

        d = error.to_dict()

        assert d["error_id"] == "ERR-2025-12-22-001"
        assert d["error_type"] == "FAIL_VERIFY"
        assert d["message"] == "Test failed"
        assert "2025-12-22" in d["timestamp"]
        assert d["repo"] == "test-repo"
        assert d["aip_ref"] == "aips/AIP-001.yaml"

    def test_to_dict_optional_fields(self) -> None:
        """Optional fields are included when set."""
        error = ErrorRecord(
            error_id="ERR-2025-12-22-001",
            error_type=ErrorType.FAIL_SCOPE,
            message="Scope violation",
            timestamp=datetime(2025, 12, 22, 12, 0, 0),
            repo="test-repo",
            aip_ref="aips/AIP-001.yaml",
            spec_ref="specs/feature.md",
            step=3,
            step_id="step-003",
            iteration=2,
        )

        d = error.to_dict()

        assert d["spec_ref"] == "specs/feature.md"
        assert d["step"] == 3
        assert d["step_id"] == "step-003"
        assert d["iteration"] == 2

    def test_to_dict_with_context(self) -> None:
        """Context is included when present."""
        error = ErrorRecord(
            error_id="ERR-2025-12-22-001",
            error_type=ErrorType.FAIL_VERIFY,
            message="Test failed",
            timestamp=datetime.now(),
            repo="test-repo",
            aip_ref="aips/AIP-001.yaml",
            context=ErrorContext(
                command="pytest -q",
                exit_code=1,
                output_snippet="FAILED test_foo.py",
                files_touched=["src/foo.py"],
            ),
        )

        d = error.to_dict()

        assert "context" in d
        assert d["context"]["command"] == "pytest -q"
        assert d["context"]["exit_code"] == 1
        assert d["context"]["output_snippet"] == "FAILED test_foo.py"
        assert d["context"]["files_touched"] == ["src/foo.py"]

    def test_to_dict_omits_none_optional_fields(self) -> None:
        """None optional fields are not included."""
        error = ErrorRecord(
            error_id="ERR-2025-12-22-001",
            error_type=ErrorType.COMPILE_ERROR,
            message="Compile error",
            timestamp=datetime.now(),
            repo="test-repo",
            aip_ref="aips/AIP-001.yaml",
        )

        d = error.to_dict()

        assert "spec_ref" not in d
        assert "step" not in d
        assert "context" not in d


class TestErrorContext:
    """Tests for ErrorContext dataclass."""

    def test_to_dict_omits_empty(self) -> None:
        """Empty optional fields are not included."""
        context = ErrorContext(command="pytest")

        d = context.to_dict()

        assert d == {"command": "pytest"}
        assert "exit_code" not in d
        assert "files_touched" not in d

    def test_to_dict_includes_all_when_set(self) -> None:
        """All fields included when set."""
        context = ErrorContext(
            command="pytest",
            exit_code=1,
            output_snippet="FAILED",
            files_touched=["a.py", "b.py"],
            scope_violations=["c.py"],
            adapter="claude",
            agent_response_id="resp-123",
        )

        d = context.to_dict()

        assert d["command"] == "pytest"
        assert d["exit_code"] == 1
        assert d["output_snippet"] == "FAILED"
        assert d["files_touched"] == ["a.py", "b.py"]
        assert d["scope_violations"] == ["c.py"]
        assert d["adapter"] == "claude"
        assert d["agent_response_id"] == "resp-123"


class TestErrorRecordGenerator:
    """Tests for ErrorRecordGenerator class."""

    def test_generate_id_format(self, tmp_path: Path) -> None:
        """Generated ID follows correct format."""
        generator = ErrorRecordGenerator(tmp_path)
        error_id = generator.generate_id()

        assert error_id.startswith("ERR-")
        # Format: ERR-YYYY-MM-DD-NNN (5 parts when split by -)
        parts = error_id.split("-")
        assert len(parts) == 5
        assert parts[0] == "ERR"
        assert len(parts[1]) == 4  # Year
        assert len(parts[2]) == 2  # Month
        assert len(parts[3]) == 2  # Day
        assert len(parts[4]) == 3  # Sequence number

    def test_generate_id_sequential(self, tmp_path: Path) -> None:
        """Sequential IDs increment correctly."""
        generator = ErrorRecordGenerator(tmp_path)

        # Create some existing error files
        today = datetime.now().strftime("%Y-%m-%d")
        repo_dir = tmp_path / "test-repo" / today
        repo_dir.mkdir(parents=True)
        (repo_dir / f"ERR-{today}-001.yaml").write_text("error_id: 1")
        (repo_dir / f"ERR-{today}-002.yaml").write_text("error_id: 2")

        error_id = generator.generate_id("test-repo")

        assert error_id.endswith("-003")

    def test_create_record_auto_id(self, tmp_path: Path) -> None:
        """create_record generates ID automatically."""
        generator = ErrorRecordGenerator(tmp_path)

        record = generator.create_record(
            error_type=ErrorType.FAIL_VERIFY,
            message="Test failed",
            repo="test-repo",
            aip_ref="aips/AIP-001.yaml",
        )

        assert record.error_id.startswith("ERR-")
        assert record.error_type == ErrorType.FAIL_VERIFY
        assert record.message == "Test failed"
        assert record.repo == "test-repo"
        assert record.timestamp is not None

    def test_create_record_with_context(self, tmp_path: Path) -> None:
        """create_record includes context when provided."""
        generator = ErrorRecordGenerator(tmp_path)
        context = ErrorContext(command="pytest", exit_code=1)

        record = generator.create_record(
            error_type=ErrorType.FAIL_VERIFY,
            message="Test failed",
            repo="test-repo",
            aip_ref="aips/AIP-001.yaml",
            context=context,
        )

        assert record.context is not None
        assert record.context.command == "pytest"
