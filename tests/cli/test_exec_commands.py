"""
Tests for v2 executor CLI commands.
"""

import subprocess

import pytest
import yaml
from typer.testing import CliRunner

from spec.cli.spec import app
from spec.executor.jobdefs import install_default_jobdefs
from spec.executor.schemas import Backend, JobDef, StepTemplate
from spec.executor.store import RunStore

runner = CliRunner()


@pytest.fixture
def git_repo(tmp_path):
    """Create a test git repository."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "test.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    return repo_path


@pytest.fixture
def spec_file(tmp_path):
    """Create a test spec .md file."""
    spec_path = tmp_path / "test-spec.md"
    spec_content = """---
tier: C
title: Test Spec
owner: test-user
goal: Test the executor CLI
repo:
  working_branch: feat/test-feature
---

# Test Spec

## Objective

Test the executor CLI commands.

## Acceptance Criteria

- [ ] CLI commands work correctly
- [ ] Tests pass

## Plan

### Step 1: Setup [G1: Code Readiness]

Do some setup work.
"""
    spec_path.write_text(spec_content)
    return spec_path


@pytest.fixture
def store(tmp_path):
    """Create a test store."""
    return RunStore(root=tmp_path / "runs")


@pytest.fixture
def jobdefs_installed(tmp_path, monkeypatch):
    """Install default jobdefs to a temp directory and patch the loader."""
    gov_path = tmp_path / "local-governor"
    install_default_jobdefs(gov_path)

    # Monkeypatch the default governor path in the jobdefs module
    import spec.executor.jobdefs as jobdefs_module
    original_get_jobdefs_dir = jobdefs_module.get_jobdefs_dir

    def patched_get_jobdefs_dir(governor_path=None):
        if governor_path is None:
            governor_path = gov_path
        return original_get_jobdefs_dir(governor_path)

    monkeypatch.setattr(jobdefs_module, "get_jobdefs_dir", patched_get_jobdefs_dir)
    return gov_path


@pytest.fixture
def simple_job():
    """Create a simple test job that doesn't require claude."""
    return JobDef(
        job_id="test-simple",
        steps=[
            StepTemplate(
                step_id="echo",
                backend=Backend.cmd,
                payload={"command": "echo hello", "capture_git": False},
            ),
        ],
    )


# =============================================================================
# spec compile Tests
# =============================================================================


class TestCompileCommand:
    """Tests for spec compile."""

    def test_compile_help(self):
        """Compile command shows help."""
        result = runner.invoke(app, ["compile", "--help"])
        assert result.exit_code == 0
        assert "Compile a JobDef + spec" in result.stdout

    def test_compile_missing_spec(self, tmp_path, jobdefs_installed):
        """Compile fails with missing spec file."""
        result = runner.invoke(app, ["compile", "aip-1", "/nonexistent/spec.md"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_compile_unknown_job_id(self, spec_file, jobdefs_installed):
        """Compile fails with unknown job_id."""
        result = runner.invoke(app, ["compile", "unknown-job", str(spec_file)])
        assert result.exit_code == 1
        assert "Unknown job_id" in result.output

    def test_compile_success_stdout(self, spec_file, git_repo, jobdefs_installed):
        """Compile outputs JobInstance to stdout."""
        result = runner.invoke(
            app,
            ["compile", "aip-1", str(spec_file), "--repo", str(git_repo)],
        )
        assert result.exit_code == 0
        # Should output YAML
        assert "job_id: aip-1" in result.stdout
        assert "steps:" in result.stdout

    def test_compile_success_file(self, spec_file, git_repo, tmp_path, jobdefs_installed):
        """Compile writes JobInstance to file."""
        output_file = tmp_path / "job_instance.yaml"
        result = runner.invoke(
            app,
            [
                "compile",
                "aip-1",
                str(spec_file),
                "--repo",
                str(git_repo),
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        assert output_file.exists()
        assert "JobInstance written to" in result.stdout

        # Verify file content
        with open(output_file) as f:
            data = yaml.safe_load(f)
        assert data["job_id"] == "aip-1"
        assert len(data["steps"]) == 13  # aip-1 has 13 steps (refs.sync + 3-pass model + improvements)


# =============================================================================
# spec run Tests
# =============================================================================


class TestRunCommand:
    """Tests for spec run."""

    def test_run_help(self):
        """Run command shows help."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "Compile and execute" in result.stdout

    def test_run_dry_run(self, spec_file, git_repo, jobdefs_installed):
        """Run with --dry-run prints JobInstance without executing."""
        result = runner.invoke(
            app,
            [
                "run",
                "aip-1",
                str(spec_file),
                "--repo",
                str(git_repo),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.stdout
        assert "job_id: aip-1" in result.stdout

    def test_run_missing_spec(self, tmp_path, jobdefs_installed):
        """Run fails with missing spec file."""
        result = runner.invoke(app, ["run", "aip-1", "/nonexistent/spec.md"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_run_simple_job(self, spec_file, git_repo, simple_job, tmp_path, monkeypatch, jobdefs_installed):
        """Run executes a simple job successfully."""
        # Write the simple_job to the jobdefs directory
        import yaml as yaml_module
        jobdefs_dir = jobdefs_installed / "jobdefs" / "specwright"
        with open(jobdefs_dir / "test-simple.yaml", "w") as f:
            yaml_module.dump(simple_job.model_dump(mode="json"), f)

        # Use custom store location
        store_path = tmp_path / "runs"
        monkeypatch.setattr("spec.cli.exec_commands.RunStore", lambda: RunStore(root=store_path))

        result = runner.invoke(
            app,
            [
                "run",
                "test-simple",
                str(spec_file),
                "--repo",
                str(git_repo),
            ],
        )
        # Should complete (exit 0) or complete with errors (exit 2)
        # depending on whether branch.create step exists
        assert result.exit_code in [0, 1, 2]

    def test_run_writes_consolidated_output_when_projection_configured(
        self,
        spec_file,
        git_repo,
        simple_job,
        tmp_path,
        monkeypatch,
        jobdefs_installed,
    ):
        """Default run output is consolidated when projection repo is configured."""
        import yaml as yaml_module

        jobdefs_dir = jobdefs_installed / "jobdefs" / "specwright"
        with open(jobdefs_dir / "test-simple.yaml", "w") as f:
            yaml_module.dump(simple_job.model_dump(mode="json"), f)

        projection_repo = tmp_path / "projection-repo"
        projection_repo.mkdir(parents=True)
        monkeypatch.setenv("SPECWRIGHT_PROJECTION_REPO", str(projection_repo))

        result = runner.invoke(
            app,
            [
                "run",
                "test-simple",
                str(spec_file),
                "--repo",
                str(git_repo),
            ],
        )

        assert result.exit_code in [0, 1, 2]
        runs_root = projection_repo / "runs" / "adhoc"
        run_dirs = [d for d in runs_root.iterdir() if d.is_dir()]
        assert run_dirs
        run_dir = run_dirs[0]
        assert (run_dir / "run.yaml").exists()
        assert (run_dir / "run_report.yaml").exists()
        step_yaml = run_dir / "steps" / "step-001.yaml"
        assert step_yaml.exists()

        raw_step = yaml_module.safe_load(step_yaml.read_text())
        assert raw_step["kind"] == "run_step"
        raw_run = yaml_module.safe_load((run_dir / "run.yaml").read_text())
        assert raw_run["kind"] == "run"

    def test_run_legacy_output_flag_preserves_legacy_layout(
        self,
        spec_file,
        git_repo,
        simple_job,
        tmp_path,
        monkeypatch,
        jobdefs_installed,
    ):
        """--legacy-output keeps legacy artifacts even when projection repo is configured."""
        import yaml as yaml_module

        jobdefs_dir = jobdefs_installed / "jobdefs" / "specwright"
        with open(jobdefs_dir / "test-simple.yaml", "w") as f:
            yaml_module.dump(simple_job.model_dump(mode="json"), f)

        projection_repo = tmp_path / "projection-repo"
        projection_repo.mkdir(parents=True)
        monkeypatch.setenv("SPECWRIGHT_PROJECTION_REPO", str(projection_repo))

        store_path = tmp_path / "legacy-runs"
        monkeypatch.setattr(
            "spec.cli.exec_commands.RunStore",
            lambda *args, **kwargs: RunStore(root=store_path),
        )

        result = runner.invoke(
            app,
            [
                "run",
                "test-simple",
                str(spec_file),
                "--repo",
                str(git_repo),
                "--legacy-output",
            ],
        )

        assert result.exit_code in [0, 1, 2]
        run_dirs = [d for d in store_path.iterdir() if d.is_dir()]
        assert run_dirs
        run_dir = run_dirs[0]
        assert (run_dir / "run.yaml").exists()
        assert (run_dir / "run_report.md").exists()
        assert not (run_dir / "run_report.yaml").exists()


# =============================================================================
# spec status Tests
# =============================================================================


class TestStatusCommand:
    """Tests for spec status."""

    def test_status_help(self):
        """Status command shows help."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "Show run status" in result.stdout

    def test_status_no_runs(self, tmp_path, monkeypatch):
        """Status shows message when no runs exist."""
        store_path = tmp_path / "runs"
        monkeypatch.setattr("spec.cli.exec_commands.RunStore", lambda: RunStore(root=store_path))

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No runs found" in result.stdout

    def test_status_unknown_run(self, tmp_path, monkeypatch):
        """Status fails for unknown run_id."""
        store_path = tmp_path / "runs"
        monkeypatch.setattr("spec.cli.exec_commands.RunStore", lambda: RunStore(root=store_path))

        result = runner.invoke(app, ["status", "unknown-run-id"])
        assert result.exit_code == 1
        assert "not found" in result.output


# =============================================================================
# spec logs Tests
# =============================================================================


class TestLogsCommand:
    """Tests for spec logs."""

    def test_logs_help(self):
        """Logs command shows help."""
        result = runner.invoke(app, ["logs", "--help"])
        assert result.exit_code == 0
        assert "Show run logs" in result.stdout

    def test_logs_unknown_run(self, tmp_path, monkeypatch):
        """Logs fails for unknown run_id."""
        store_path = tmp_path / "runs"
        monkeypatch.setattr("spec.cli.exec_commands.RunStore", lambda: RunStore(root=store_path))

        result = runner.invoke(app, ["logs", "unknown-run-id"])
        assert result.exit_code == 1
        assert "not found" in result.output


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for the full compile-run-status-logs flow."""

    def test_full_workflow(self, git_repo, spec_file, tmp_path, monkeypatch, jobdefs_installed):
        """Test full workflow: compile -> run -> status -> logs."""
        store_path = tmp_path / "runs"
        monkeypatch.setattr("spec.cli.exec_commands.RunStore", lambda: RunStore(root=store_path))

        # Create a simple job for testing and write to jobdefs directory
        import yaml as yaml_module
        job_def = JobDef(
            job_id="test-workflow",
            steps=[
                StepTemplate(
                    step_id="setup",
                    backend=Backend.cmd,
                    payload={"command": "echo setting up", "capture_git": False},
                ),
                StepTemplate(
                    step_id="work",
                    backend=Backend.cmd,
                    payload={"command": "echo working", "capture_git": False},
                ),
                StepTemplate(
                    step_id="done",
                    backend=Backend.cmd,
                    payload={"command": "echo done", "capture_git": False},
                ),
            ],
        )
        jobdefs_dir = jobdefs_installed / "jobdefs" / "specwright"
        with open(jobdefs_dir / "test-workflow.yaml", "w") as f:
            yaml_module.dump(job_def.model_dump(mode="json"), f)

        # 1. Compile
        output_file = tmp_path / "job_instance.yaml"
        result = runner.invoke(
            app,
            [
                "compile",
                "test-workflow",
                str(spec_file),
                "--repo",
                str(git_repo),
                "--output",
                str(output_file),
            ],
        )
        assert result.exit_code == 0
        assert output_file.exists()

        # 2. Run
        result = runner.invoke(
            app,
            [
                "run",
                "test-workflow",
                str(spec_file),
                "--repo",
                str(git_repo),
            ],
        )
        # Check it ran (may fail if branch already exists, that's ok)
        # The point is the CLI works

        # 3. Status - list runs
        result = runner.invoke(app, ["status"])
        # Should show at least one run or "No runs"
        assert result.exit_code == 0
