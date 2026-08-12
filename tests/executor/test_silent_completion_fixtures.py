"""
Replay tests for hf-03-01-silent-completion-detection: frozen fixtures from
four real specwright runs on disk (snapshotted, not read live -- see
tests/executor/fixtures/silent_completion/).

Two are the incidents named in the spec objective and must now classify as
non-clean:
  - run-e040-e040-06-sqlite-write-gate-20260812-194157-f0f7a5
  - run-t021-t021-04-lorchestra-roster-sweep-20260803-203328-5ecda2

Two are genuine successes named in the spec objective and must be unaffected:
  - run-adhoc-hf-01-01-identity-and-enum-fix-20260812-203334-b06173
  - run-adhoc-hf-02-01-object-create-name-leak-20260812-210717-4da728

Each fixture file is the actual changes.patch captured by the real run for
one capture_patch=True agent step (agent.run_spec / agent.drift_fix /
agent.drift_verify at steps 3, 5, 7 of the aip-1 job template) -- these are
cumulative diffs from the run's base commit, exactly what
capture.git.patch_file holds on disk today.

engine.py's own wiring compares a fresh pre-dispatch/post-dispatch snapshot
per step (see _run_steps in engine.py). This replay instead walks each
run's real, already-captured cumulative snapshots in step order -- starting
from an implicit empty baseline before the first capture_patch step -- and
feeds each consecutive pair through the same two reusable functions engine.py
calls (incremental_diff_text, diff_has_substantive_change). This is a faithful
replay of "the new logic" against frozen, real diff content, without a live
dependency on ~/.local/specwright/runs or a reconstructed git repo.
"""

from pathlib import Path

from spec.executor.diff_substantive import (
    diff_has_substantive_change,
    incremental_diff_text,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "silent_completion"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _step_verdicts(checkpoints: list[str]) -> list[bool]:
    """
    Replay a run's ordered sequence of cumulative capture_patch snapshots.

    Returns one bool per checkpoint: True if that step's own incremental
    contribution (vs. the previous checkpoint, or empty baseline for the
    first) was substantive.
    """
    verdicts = []
    previous = ""
    for checkpoint in checkpoints:
        delta = incremental_diff_text(previous, checkpoint)
        verdicts.append(diff_has_substantive_change(delta))
        previous = checkpoint
    return verdicts


class TestHistoricalIncidentsCaught:
    """AC4: the two named incident runs replay as non-clean."""

    def test_e040_06_sqlite_write_gate_is_non_clean(self):
        checkpoints = [
            _load("e040-06-step3.patch"),
            _load("e040-06-step5.patch"),
            _load("e040-06-step7.patch"),
        ]
        verdicts = _step_verdicts(checkpoints)
        # All three agent passes (run_spec, drift_fix, drift_verify) touched
        # nothing but the refs.sync marker block -- a fully silent run.
        assert verdicts == [False, False, False], (
            f"expected every agent step to be flagged no-change, got {verdicts}"
        )
        assert False in verdicts, "run must classify as non-clean"

    def test_t021_04_lorchestra_roster_sweep_is_non_clean(self):
        checkpoints = [
            _load("t021-04-step3.patch"),
            _load("t021-04-step5.patch"),
            _load("t021-04-step7.patch"),
        ]
        verdicts = _step_verdicts(checkpoints)
        # run_spec (step 3) did real work (STATE.md + epic rosters); drift_fix
        # and drift_verify (steps 5, 7) found nothing further to do.
        assert verdicts == [True, False, False], (
            f"expected run_spec substantive and both drift passes no-change, got {verdicts}"
        )
        assert False in verdicts, "run must classify as non-clean"


class TestRealSuccessesUnaffected:
    """AC5: the two named successful runs replay as fully clean."""

    def test_hf_01_01_identity_and_enum_fix_is_clean(self):
        checkpoints = [_load("hf-01-01-step3.patch")]
        verdicts = _step_verdicts(checkpoints)
        assert verdicts == [True]
        assert all(verdicts), "no step should be flagged no-change"

    def test_hf_02_01_object_create_name_leak_is_clean(self):
        checkpoints = [_load("hf-02-01-step3.patch")]
        verdicts = _step_verdicts(checkpoints)
        assert verdicts == [True]
        assert all(verdicts), "no step should be flagged no-change"
