"""Tests for prompt builder helpers used by drift passes."""

from spec.executor.engine import (
    _build_drift_verify_prompt,
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
