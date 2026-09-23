"""The improvements-staging step must not build its command from model prose.

hf-11-01: aip-1's ``stage.improvements`` step used to interpolate the previous
step's raw model output into the shell command it runs. The cmd backend scans
that command string, so a model that wrote a git command inside markdown
backticks got the whole step blocked (exit 126, branch-switch refusal). These
tests read the real bundled job definition and run the real cmd backend.
"""

import subprocess
from pathlib import Path

import pytest

from spec.executor.backends.cmd import CmdBackend
from spec.executor.engine import resolve_variables
from spec.executor.jobdefs import load_job_def_from_path
from spec.executor.schemas import Backend, Common, Policy, StepManifest

AIP1_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "spec" / "templates" / "jobdefs" / "aip-1.yaml"
)
SUGGEST_REF = "@run.steps.analyze.suggest_improvements.stdout"
PROSE_WITH_BACKTICKED_GIT = (
    "## Agent Instructions\n"
    "- Confidence: high\n"
    "- Remind the agent to run `git checkout main` only from the harness.\n"
)


@pytest.fixture
def stage_step():
    job_def = load_job_def_from_path(AIP1_PATH)
    return next(s for s in job_def.steps if s.step_id == "stage.improvements")


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    for args in (
        ["git", "init", "-b", "spec/x"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "T"],
    ):
        subprocess.run(args, cwd=repo_path, check=True, capture_output=True)
    (repo_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo_path, check=True, capture_output=True
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_path, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    return repo_path, commit


def _run_stage(stage_step, repo, tmp_path, monkeypatch, suggest_stdout):
    """Resolve the step's payload the way the engine does, then dispatch it."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    repo_path, commit = repo
    run_ctx = {
        "run_id": "run-1",
        "branch": "spec/x",
        "steps": {"analyze.suggest_improvements": {"stdout": suggest_stdout}},
    }
    payload = resolve_variables(
        stage_step.payload, {}, {"spec_id": "hf-11-01"}, run=run_ctx, allow_run=True
    )
    manifest = StepManifest(
        step_n=13,
        step_id="stage.improvements",
        backend=Backend.cmd,
        common=Common(
            repo_path=repo_path, branch="spec/x", base_commit=commit, timeout_s=30
        ),
        payload=payload,
    )
    capture = CmdBackend().dispatch(manifest, tmp_path / "artifacts", Policy())
    staged = home / ".local/local-governor/improvements/pending/hf-11-01.md"
    return capture, staged, tmp_path / "artifacts"


@pytest.mark.parametrize(
    "prose",
    [
        PROSE_WITH_BACKTICKED_GIT,
        "- Never run `git push origin main` from a step.\n",
        "- Do not `git merge develop` by hand.\n",
    ],
    ids=["checkout", "push", "merge"],
)
def test_staging_step_survives_backticked_git_command(
    stage_step, repo, tmp_path, monkeypatch, prose
):
    capture, staged, artifacts = _run_stage(
        stage_step, repo, tmp_path, monkeypatch, prose
    )

    stderr = (artifacts / capture.agent.stderr_file).read_text()
    assert capture.agent.exit_code == 0, stderr
    assert "Policy violation" not in stderr
    assert staged.exists()

    body = staged.read_text()
    assert body.startswith("# Improvement Suggestions: hf-11-01\n# Run: run-1\n")
    assert "# Branch: spec/x\n# Status: PENDING REVIEW\n" in body
    # The model's prose lands in the file byte-for-byte, backticks and all.
    assert prose in body


def test_staging_step_keeps_prose_that_would_end_a_heredoc(
    stage_step, repo, tmp_path, monkeypatch
):
    """Prose is data now, so a line reading EOF or a quote can't truncate it."""
    prose = "before\nEOF\n$(echo injected) 'quoted' \"double\" $HOME\nafter\n"
    capture, staged, artifacts = _run_stage(
        stage_step, repo, tmp_path, monkeypatch, prose
    )

    assert capture.agent.exit_code == 0, (artifacts / capture.agent.stderr_file).read_text()
    assert prose in staged.read_text()


def test_staging_command_carries_no_model_output(stage_step):
    """Structural half: the command string that is executed and scanned no
    longer interpolates the previous step's output, in any spelling."""
    command = stage_step.payload["command"]
    assert "analyze.suggest_improvements" not in command
    assert "@run.steps" not in command
    # The output travels as an environment value instead.
    assert stage_step.payload["env"] == {"IMPROVEMENTS_BODY": SUGGEST_REF}
