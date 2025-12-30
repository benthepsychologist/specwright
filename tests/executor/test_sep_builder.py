from pathlib import Path

import pytest

from spec.executor.contract import StepContract
from spec.executor.sep_builder import SEPBuilder


def make_contract(*, forbidden_paths: list[str] | None = None) -> StepContract:
    return StepContract(
        aip_id="AIP-test-2024-12-13-001",
        step_id="step-001",
        step_index=1,
        allowed_paths=["src/**", "tests/**"],
        forbidden_paths=forbidden_paths or [".git/**", ".env*", "secrets/**"],
        verification_commands=["pytest -q"],
    )


def test_build_sets_1_based_step_index_and_summarizes_objective() -> None:
    builder = SEPBuilder()
    aip = {
        "aip_id": "AIP-test-2024-12-13-001",
        "plan": [
            {
                "step_id": "step-001",
                "prompt": "Implement the SEP builder.\n\nCreate `src/spec/executor/sep_builder.py`.",
            }
        ],
    }

    sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

    assert sep.step_index == 1
    assert sep.step_id == "step-001"
    assert sep.objective == "Implement the SEP builder."
    assert len(sep.verification_steps) == 1
    assert sep.verification_steps[0].command == "pytest -q"


def test_extract_files_keeps_prompt_order_and_upgrades_action() -> None:
    builder = SEPBuilder()
    aip = {
        "aip_id": "AIP-test-2024-12-13-001",
        "plan": [
            {
                "step_id": "step-001",
                "prompt": "Create `a.py`. Update `b.py`. Delete `a.py`.",
            }
        ],
    }

    sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

    assert [fc.path for fc in sep.files_to_touch] == ["a.py", "b.py"]
    assert sep.files_to_touch[0].action == "delete"  # upgraded from create
    assert sep.files_to_touch[1].action == "modify"


def test_sensitive_path_prefix_pattern_triggers_review() -> None:
    builder = SEPBuilder()
    aip = {
        "aip_id": "AIP-test-2024-12-13-001",
        "plan": [
            {
                "step_id": "step-001",
                "prompt": "Update `.env.example`",
            }
        ],
    }

    sep = builder.build(
        aip=aip,
        step_idx=0,
        contract=make_contract(forbidden_paths=[".git/**", ".env*"]),
    )

    assert sep.requires_human_review is True


def test_sensitive_path_does_not_false_positive_on_dotgitignore() -> None:
    builder = SEPBuilder()
    aip = {
        "aip_id": "AIP-test-2024-12-13-001",
        "plan": [
            {
                "step_id": "step-001",
                "prompt": "Update `.gitignore`",
            }
        ],
    }

    sep = builder.build(
        aip=aip,
        step_idx=0,
        contract=make_contract(forbidden_paths=[".git/**"]),
    )

    assert sep.requires_human_review is False


def test_build_validates_step_idx_range() -> None:
    builder = SEPBuilder()
    aip = {"aip_id": "AIP-test-2024-12-13-001", "plan": [{"step_id": "step-001"}]}

    with pytest.raises(ValueError, match="out of range"):
        builder.build(aip=aip, step_idx=1, contract=make_contract())


def test_build_validates_plan_type() -> None:
    builder = SEPBuilder()
    aip = {"aip_id": "AIP-test-2024-12-13-001", "plan": "not-a-list"}

    with pytest.raises(ValueError, match="plan"):
        builder.build(aip=aip, step_idx=0, contract=make_contract())
