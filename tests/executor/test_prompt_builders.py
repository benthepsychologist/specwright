"""Tests for prompt builder helpers used by drift passes."""

from spec.executor.engine import (
  _build_execute_spec_prompt,
    _build_drift_verify_prompt,
  _format_spec_ground_truth,
    _extract_forbidden_legacy_semantics,
)


def test_extract_forbidden_legacy_semantics_from_yaml_native_spec() -> None:
    spec_md = """name: e033-03
document:
  acceptance_criteria:
    - status: pending
      text: Example criterion
  forbidden_legacy_semantics:
    - bq.upsert must not remain an admission method
    - sqlite.mirror must not remain active sync naming
"""

    assert _extract_forbidden_legacy_semantics(spec_md) == [
        "bq.upsert must not remain an admission method",
        "sqlite.mirror must not remain active sync naming",
    ]


def test_build_drift_verify_prompt_includes_forbidden_legacy_semantics() -> None:
    spec_md = """name: e033-03
document:
  acceptance_criteria:
    - status: pending
      text: Example criterion
  forbidden_legacy_semantics:
    - bq.upsert must not remain an admission method
"""

    prompt = _build_drift_verify_prompt(spec_md=spec_md)

    assert "Forbidden Legacy Semantics" in prompt
    assert "bq.upsert must not remain an admission method" in prompt
    assert "Do not treat passing tests alone as sufficient evidence" in prompt


def test_format_spec_ground_truth_extracts_yaml_native_sections() -> None:
    spec_md = """spec_id: test
goal: Keep the raw-table contract
objective: Preserve the existing 4-step ingest pattern
document:
  acceptance_criteria:
    - status: pending
      text: Generic job has 4 steps
  constraints:
    - kind: structural
      text: No create_objects step is allowed
  touch_list:
    - path: /tmp/example.yaml
      action: create
      reason: Add the generic job
  steps:
    - id: 1
      description: Add the job
      files:
        - /tmp/example.yaml
      verification: pytest -q
  body: |
    ## Notes
    Preserve the current raw-table shape.
"""

    prompt = _format_spec_ground_truth(spec_md, include_body_excerpt=True)

    assert "Goal" in prompt
    assert "Generic job has 4 steps" in prompt
    assert "No create_objects step is allowed" in prompt
    assert "/tmp/example.yaml" in prompt
    assert "pytest -q" in prompt


def test_build_execute_spec_prompt_warns_against_inventing_architecture() -> None:
    spec_md = """spec_id: test
document:
  acceptance_criteria:
    - status: pending
      text: Preserve the current 4-step shape
  constraints:
    - kind: ground-truth
      text: The existing ingest fleet has exactly 4 steps, not 5
"""

    prompt = _build_execute_spec_prompt(spec_md=spec_md)

    assert "Follow the spec literally" in prompt
    assert "Do NOT invent a cleaner architecture" in prompt
    assert "4-step shape" in prompt
