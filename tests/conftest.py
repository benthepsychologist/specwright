"""Repo-wide test guards.

Gated emission (spec.executor.gate_emission) writes governed rows to the
live prod DB through lorchestra/storacle. Tests must NEVER do that, so the
CLI emission hook is stubbed out for every test, and the scratch root is
redirected into tmp_path so tests never touch ~/.local/specwright.

Tests that want to assert emission behavior can request the
``gate_emission_calls`` fixture and inspect the recorded calls.
Unit tests for gate_emission itself call its functions directly with fakes.
"""

import pytest


@pytest.fixture(autouse=True)
def gate_emission_calls(monkeypatch, tmp_path):
    """Stub CLI gate emission + redirect scratch root; record calls."""
    calls: list[dict] = []

    def _fake_emit(*, store, run_id):
        calls.append({"store": store, "run_id": run_id})

    monkeypatch.setattr(
        "spec.cli.exec_commands._emit_gated_run_records", _fake_emit, raising=True
    )
    monkeypatch.setenv(
        "SPECWRIGHT_SCRATCH_ROOT", str(tmp_path / "specwright-scratch")
    )
    return calls
