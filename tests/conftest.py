"""Repo-wide test guards.

Gated emission (spec.executor.gate_emission) writes governed rows to the
live prod DB through lorchestra/storacle. Tests must NEVER do that, so the
CLI emission hook is stubbed out for every test, and the scratch root is
redirected into tmp_path so tests never touch ~/.local/specwright.

Tests that want to assert emission behavior can request the
``gate_emission_calls`` fixture and inspect the recorded calls.
Unit tests for gate_emission itself call its functions directly with fakes.

t019-04 added claim + incremental-step emission call sites directly inside
exec_commands.run_command and engine._run_steps — unlike the finalize hook
above, those are NOT wrapped by a single stubbable choke point (engine.py
in particular is exercised by many existing tests). Their real-write path
is gated on LIFEOS_CLOUD_DB being set in the ambient environment (see
gate_emission._lifeos_db_path), so clearing it here is the safety net that
makes that gate a no-op regardless of the invoking shell's own env.
"""

import pytest


class _EmissionCalls(list):
    """Recorded CLI emission calls.

    A plain list of call kwargs (existing tests assert on it as one), plus
    the un-stubbed wrapper: a test that needs the REAL
    _emit_gated_run_records path — sw-01-02's emission-failure report
    amendment — can restore it, since the autouse stub below has already
    replaced the module attribute by the time any test body runs.
    """

    real_emit_gated_run_records = None


@pytest.fixture(autouse=True)
def gate_emission_calls(monkeypatch, tmp_path):
    """Stub CLI gate emission + redirect scratch root; record calls."""
    from spec.cli import exec_commands

    calls = _EmissionCalls()
    calls.real_emit_gated_run_records = exec_commands._emit_gated_run_records

    def _fake_emit(*, store, run_id):
        calls.append({"store": store, "run_id": run_id})

    monkeypatch.setattr(
        "spec.cli.exec_commands._emit_gated_run_records", _fake_emit, raising=True
    )
    monkeypatch.setenv(
        "SPECWRIGHT_SCRATCH_ROOT", str(tmp_path / "specwright-scratch")
    )
    # Belt-and-suspenders for the claim/incremental-step paths (see module
    # docstring): never let a developer's real LIFEOS_CLOUD_DB leak into a
    # test process and trigger a live governed write.
    monkeypatch.delenv("LIFEOS_CLOUD_DB", raising=False)
    return calls
