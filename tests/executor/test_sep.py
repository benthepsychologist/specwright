import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from spec.executor.sep import (
    FileChange,
    SepError,
    SepLoadError,
    SepValidationError,
    StepExecutionPlan,
    VerificationStep,
    load_sep,
    save_sep,
)


def test_save_sep_is_deterministic_and_no_aliases(tmp_path: Path) -> None:
    sep = StepExecutionPlan(
        aip_id="AIP-test-2024-12-13-001",
        step_id="step-001",
        step_index=1,
        created_at="2025-01-01T00:00:00+00:00",
        objective="Do the thing",
        files_to_touch=[
            FileChange(
                path="src/spec/executor/sep.py",
                action="modify",
                description="Update SEP serialization",
                estimated_lines=42,
            ),
            FileChange(
                path="tests/executor/test_sep.py",
                action="create",
                description="Add SEP tests",
                estimated_lines=100,
            ),
        ],
        verification_steps=[
            VerificationStep(
                command="pytest -q tests/executor/test_sep.py",
                expected_outcome="All tests pass",
                required=True,
            )
        ],
        allowed_paths=["src/**", "tests/**"],
        forbidden_paths=[".git/**"],
        estimated_complexity="medium",
        requires_human_review=False,
    )

    path1 = tmp_path / "sep1.yaml"
    path2 = tmp_path / "sep2.yaml"

    save_sep(sep, path1)
    save_sep(sep, path2)

    content1 = path1.read_text(encoding="utf-8")
    content2 = path2.read_text(encoding="utf-8")

    assert content1 == content2
    assert content1.endswith("\n")

    # Ensure we don't emit YAML anchors/aliases (a determinism footgun).
    assert not re.search(r"(^|\s)&[A-Za-z0-9_-]+", content1)
    assert not re.search(r"(^|\s)\*[A-Za-z0-9_-]+", content1)


def test_roundtrip_load_sep(tmp_path: Path) -> None:
    sep = StepExecutionPlan(
        aip_id="AIP-test-2024-12-13-001",
        step_id="step-001",
        step_index=1,
        created_at="2025-01-01T00:00:00+00:00",
        objective="",
        files_to_touch=[],
        verification_steps=[],
        allowed_paths=["src/**"],
        forbidden_paths=[".git/**"],
    )

    path = tmp_path / "sep.yaml"
    save_sep(sep, path)

    loaded = load_sep(path)

    assert loaded.aip_id == sep.aip_id
    assert loaded.step_id == sep.step_id
    assert loaded.step_index == sep.step_index
    assert loaded.created_at == sep.created_at
    assert loaded.allowed_paths == ["src/**"]
    assert loaded.forbidden_paths == [".git/**"]


def test_load_sep_empty_file_raises_load_error(tmp_path: Path) -> None:
    path = tmp_path / "sep.yaml"
    path.write_text("", encoding="utf-8")

    with pytest.raises(SepLoadError, match="empty"):
        load_sep(path)


def test_load_sep_invalid_yaml_raises_load_error(tmp_path: Path) -> None:
    path = tmp_path / "sep.yaml"
    path.write_text("aip_id: [unterminated\n", encoding="utf-8")

    with pytest.raises(SepLoadError, match="Invalid YAML"):
        load_sep(path)


def test_load_sep_missing_required_key_raises_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "sep.yaml"
    path.write_text(
        """step_id: step-001
step_index: 1
""",
        encoding="utf-8",
    )

    with pytest.raises(SepValidationError, match="Missing required key: aip_id"):
        load_sep(path)


def test_load_sep_wrong_type_raises_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-2024-12-13-001
step_id: step-001
step_index: "0"
""",
        encoding="utf-8",
    )

    with pytest.raises(SepValidationError, match="step_index"):
        load_sep(path)


# ==== Additional SEP Dataclass Serialization Tests ====


def test_sep_post_init_sets_created_at_if_missing() -> None:
    """StepExecutionPlan sets created_at timestamp in __post_init__ if empty."""
    before = datetime.now(UTC)
    sep = StepExecutionPlan(
        aip_id="AIP-test-001",
        step_id="step-001",
        step_index=1,
    )
    after = datetime.now(UTC)

    # Should have auto-generated created_at
    assert sep.created_at != ""
    created_dt = datetime.fromisoformat(sep.created_at)
    assert before <= created_dt <= after


def test_sep_post_init_preserves_provided_created_at() -> None:
    """StepExecutionPlan preserves provided created_at if non-empty."""
    fixed_time = "2024-01-01T00:00:00+00:00"
    sep = StepExecutionPlan(
        aip_id="AIP-test-001",
        step_id="step-001",
        step_index=1,
        created_at=fixed_time,
    )

    assert sep.created_at == fixed_time


def test_save_sep_creates_parent_directories(tmp_path: Path) -> None:
    """save_sep creates parent directories if they don't exist."""
    sep = StepExecutionPlan(
        aip_id="AIP-test-001",
        step_id="step-001",
        step_index=1,
        created_at="2025-01-01T00:00:00+00:00",
    )

    nested_path = tmp_path / "deep" / "nested" / "dir" / "sep.yaml"
    assert not nested_path.parent.exists()

    save_sep(sep, nested_path)

    assert nested_path.exists()
    assert nested_path.parent.exists()


def test_save_sep_sorts_path_lists(tmp_path: Path) -> None:
    """save_sep outputs allowed_paths and forbidden_paths in sorted order."""
    sep = StepExecutionPlan(
        aip_id="AIP-test-001",
        step_id="step-001",
        step_index=1,
        created_at="2025-01-01T00:00:00+00:00",
        allowed_paths=["tests/**", "src/**", "docs/**"],
        forbidden_paths=[".git/**", "*.lock", ".env*"],
    )

    path = tmp_path / "sep.yaml"
    save_sep(sep, path)

    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    # Should be sorted alphabetically
    assert data["allowed_paths"] == ["docs/**", "src/**", "tests/**"]
    assert data["forbidden_paths"] == ["*.lock", ".env*", ".git/**"]


def test_save_sep_omits_optional_estimated_lines_when_none(tmp_path: Path) -> None:
    """save_sep omits estimated_lines from file changes when None."""
    sep = StepExecutionPlan(
        aip_id="AIP-test-001",
        step_id="step-001",
        step_index=1,
        created_at="2025-01-01T00:00:00+00:00",
        files_to_touch=[
            FileChange(
                path="src/foo.py",
                action="create",
                description="Create foo",
                estimated_lines=None,
            )
        ],
    )

    path = tmp_path / "sep.yaml"
    save_sep(sep, path)

    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    assert "estimated_lines" not in data["files_to_touch"][0]


def test_save_sep_includes_estimated_lines_when_present(tmp_path: Path) -> None:
    """save_sep includes estimated_lines in file changes when provided."""
    sep = StepExecutionPlan(
        aip_id="AIP-test-001",
        step_id="step-001",
        step_index=1,
        created_at="2025-01-01T00:00:00+00:00",
        files_to_touch=[
            FileChange(
                path="src/foo.py",
                action="create",
                description="Create foo",
                estimated_lines=42,
            )
        ],
    )

    path = tmp_path / "sep.yaml"
    save_sep(sep, path)

    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    assert data["files_to_touch"][0]["estimated_lines"] == 42


def test_save_sep_omits_required_true_in_verification_steps(tmp_path: Path) -> None:
    """save_sep omits required=True (the default) from verification steps."""
    sep = StepExecutionPlan(
        aip_id="AIP-test-001",
        step_id="step-001",
        step_index=1,
        created_at="2025-01-01T00:00:00+00:00",
        verification_steps=[
            VerificationStep(
                command="pytest",
                expected_outcome="All tests pass",
                required=True,
            )
        ],
    )

    path = tmp_path / "sep.yaml"
    save_sep(sep, path)

    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    assert "required" not in data["verification_steps"][0]


def test_save_sep_includes_required_false_in_verification_steps(tmp_path: Path) -> None:
    """save_sep includes required=False in verification steps."""
    sep = StepExecutionPlan(
        aip_id="AIP-test-001",
        step_id="step-001",
        step_index=1,
        created_at="2025-01-01T00:00:00+00:00",
        verification_steps=[
            VerificationStep(
                command="lint",
                expected_outcome="No warnings",
                required=False,
            )
        ],
    )

    path = tmp_path / "sep.yaml"
    save_sep(sep, path)

    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    assert data["verification_steps"][0]["required"] is False


def test_roundtrip_with_all_fields(tmp_path: Path) -> None:
    """Full roundtrip with all fields populated."""
    sep = StepExecutionPlan(
        aip_id="AIP-test-2024-12-13-001",
        step_id="step-003",
        step_index=3,
        created_at="2025-06-15T10:30:00+00:00",
        objective="Implement user authentication with OAuth2 support.",
        files_to_touch=[
            FileChange(
                path="src/auth/oauth.py",
                action="create",
                description="OAuth2 authentication handler",
                estimated_lines=150,
            ),
            FileChange(
                path="src/auth/__init__.py",
                action="modify",
                description="Export OAuth handler",
            ),
            FileChange(
                path="src/auth/legacy.py",
                action="delete",
                description="Remove legacy auth",
            ),
        ],
        verification_steps=[
            VerificationStep(
                command="pytest tests/auth/",
                expected_outcome="All auth tests pass",
                required=True,
            ),
            VerificationStep(
                command="mypy src/auth/",
                expected_outcome="No type errors",
                required=False,
            ),
        ],
        allowed_paths=["src/auth/**", "tests/auth/**"],
        forbidden_paths=[".git/**", "*.lock", ".env*", "secrets/**"],
        estimated_complexity="high",
        requires_human_review=True,
    )

    path = tmp_path / "sep.yaml"
    save_sep(sep, path)
    loaded = load_sep(path)

    assert loaded.aip_id == sep.aip_id
    assert loaded.step_id == sep.step_id
    assert loaded.step_index == sep.step_index
    assert loaded.created_at == sep.created_at
    assert loaded.objective == sep.objective
    assert loaded.estimated_complexity == sep.estimated_complexity
    assert loaded.requires_human_review == sep.requires_human_review

    # Check file changes
    assert len(loaded.files_to_touch) == 3
    assert loaded.files_to_touch[0].path == "src/auth/oauth.py"
    assert loaded.files_to_touch[0].action == "create"
    assert loaded.files_to_touch[0].estimated_lines == 150
    assert loaded.files_to_touch[1].estimated_lines is None  # Not provided
    assert loaded.files_to_touch[2].action == "delete"

    # Check verification steps
    assert len(loaded.verification_steps) == 2
    assert loaded.verification_steps[0].required is True
    assert loaded.verification_steps[1].required is False

    # Note: paths are sorted in output
    assert loaded.allowed_paths == ["src/auth/**", "tests/auth/**"]


def test_load_sep_handles_datetime_object_in_created_at(tmp_path: Path) -> None:
    """load_sep handles datetime object (YAML parses ISO dates as datetime)."""
    # Some YAML parsers auto-convert ISO dates to datetime objects
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 1
created_at: 2025-01-01T00:00:00+00:00
""",
        encoding="utf-8",
    )

    loaded = load_sep(path)

    # Should convert datetime back to string
    assert isinstance(loaded.created_at, str)
    assert "2025-01-01" in loaded.created_at


def test_load_sep_handles_null_objective(tmp_path: Path) -> None:
    """load_sep handles null/None objective gracefully."""
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 1
objective: null
""",
        encoding="utf-8",
    )

    loaded = load_sep(path)

    assert loaded.objective == ""


def test_load_sep_uses_default_complexity_when_missing(tmp_path: Path) -> None:
    """load_sep uses 'medium' as default complexity when not specified."""
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 1
""",
        encoding="utf-8",
    )

    loaded = load_sep(path)

    assert loaded.estimated_complexity == "medium"


def test_load_sep_uses_default_requires_human_review_when_missing(tmp_path: Path) -> None:
    """load_sep uses False as default requires_human_review when not specified."""
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 1
""",
        encoding="utf-8",
    )

    loaded = load_sep(path)

    assert loaded.requires_human_review is False


def test_load_sep_validation_step_index_must_be_positive(tmp_path: Path) -> None:
    """load_sep raises SepValidationError if step_index < 1."""
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 0
""",
        encoding="utf-8",
    )

    with pytest.raises(SepValidationError, match="step_index.*>= 1"):
        load_sep(path)


def test_load_sep_validates_file_change_has_required_fields(tmp_path: Path) -> None:
    """load_sep raises SepValidationError if file change missing required fields."""
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 1
files_to_touch:
  - path: src/foo.py
    action: create
""",
        encoding="utf-8",
    )

    with pytest.raises(SepValidationError, match="files_to_touch.*description"):
        load_sep(path)


def test_load_sep_validates_verification_step_has_required_fields(tmp_path: Path) -> None:
    """load_sep raises SepValidationError if verification step missing required fields."""
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 1
verification_steps:
  - command: pytest
""",
        encoding="utf-8",
    )

    with pytest.raises(SepValidationError, match="verification_steps.*expected_outcome"):
        load_sep(path)


def test_load_sep_file_not_found_raises_load_error(tmp_path: Path) -> None:
    """load_sep raises SepLoadError if file doesn't exist."""
    path = tmp_path / "nonexistent.yaml"

    with pytest.raises(SepLoadError, match="Failed to read SEP file"):
        load_sep(path)


def test_load_sep_non_mapping_at_top_level_raises_load_error(tmp_path: Path) -> None:
    """load_sep raises SepLoadError if top-level is not a mapping."""
    path = tmp_path / "sep.yaml"
    path.write_text("- item1\n- item2\n", encoding="utf-8")

    with pytest.raises(SepLoadError, match="must contain a YAML mapping"):
        load_sep(path)


def test_load_sep_validates_files_to_touch_item_is_mapping(tmp_path: Path) -> None:
    """load_sep raises SepValidationError if files_to_touch item is not a mapping."""
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 1
files_to_touch:
  - "just a string"
""",
        encoding="utf-8",
    )

    with pytest.raises(SepValidationError, match="files_to_touch.*list\\[mapping\\]"):
        load_sep(path)


def test_load_sep_validates_verification_steps_item_is_mapping(tmp_path: Path) -> None:
    """load_sep raises SepValidationError if verification_steps item is not a mapping."""
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 1
verification_steps:
  - "just a string"
""",
        encoding="utf-8",
    )

    with pytest.raises(SepValidationError, match="verification_steps.*list\\[mapping\\]"):
        load_sep(path)


def test_load_sep_validates_allowed_paths_is_list_of_strings(tmp_path: Path) -> None:
    """load_sep raises SepValidationError if allowed_paths contains non-strings."""
    path = tmp_path / "sep.yaml"
    path.write_text(
        """aip_id: AIP-test-001
step_id: step-001
step_index: 1
allowed_paths:
  - 123
  - "src/**"
""",
        encoding="utf-8",
    )

    with pytest.raises(SepValidationError, match="allowed_paths.*list\\[str\\]"):
        load_sep(path)


def test_sep_exception_hierarchy() -> None:
    """Test SEP exception hierarchy."""
    assert issubclass(SepLoadError, SepError)
    assert issubclass(SepValidationError, SepError)

    # Both can be caught as SepError
    with pytest.raises(SepError):
        raise SepLoadError("test")

    with pytest.raises(SepError):
        raise SepValidationError("test")
