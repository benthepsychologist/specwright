import re
from pathlib import Path

import pytest

from spec.executor.sep import (
    FileChange,
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
