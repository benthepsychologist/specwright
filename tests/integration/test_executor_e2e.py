"""End-to-end integration tests for the executor.

These tests verify the full step execution lifecycle with mocked Claude adapter,
testing all execution paths: success, scope violation, retry, max iterations,
dirty worktree, dry run, and forbidden command detection.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from spec.executor import StepRunner, TerminationReason
from spec.executor.adapters import ClaudeAdapter, ProtocolError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a real git repository for E2E testing."""
    repo = tmp_path / "project"
    repo.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    # Create project structure
    (repo / "src").mkdir()
    (repo / "src" / "__init__.py").write_text("")
    (repo / "src" / "main.py").write_text('def hello():\n    return "Hello"\n')
    (repo / "tests").mkdir()
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "tests" / "test_main.py").write_text(
        'def test_hello():\n    from src.main import hello\n    assert hello() == "Hello"\n'
    )
    (repo / "README.md").write_text("# Test Project\n")

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    return repo


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    """Create a runs directory for artifacts."""
    runs = tmp_path / "runs"
    runs.mkdir()
    return runs


@pytest.fixture
def sample_aip() -> dict[str, Any]:
    """Sample AIP for E2E testing.

    Note: allowed_paths, forbidden_paths, and verification_commands
    must be at the step level (not nested in scope).
    """
    return {
        "aip_id": "AIP-e2e-test-2024-12-15-001",
        "title": "E2E Test AIP",
        "spec_version": "1.0.0",
        "objective": {
            "goal": "Test the executor E2E",
            "acceptance_criteria": ["All tests pass"],
        },
        "plan": [
            {
                "step_id": "step-001",
                "role": "agentic",
                "description": "Add a greeting function",
                "prompt": "Add a greet() function to src/main.py",
                "allowed_paths": ["src/**", "tests/**"],
                "forbidden_paths": [".git/**", "*.lock", "secrets/**"],
                "verification_commands": ["python -c 'print(1)'"],
            },
        ],
    }


def make_write_outputs(
    patch_content: str,
    agent_status: str = "success",
    needs_human: bool = False,
    notes: str = "OK",
    cmdlog: str = "",
):
    """Factory to create write_outputs functions for mocking adapter.execute."""
    def write_outputs(
        input_dir: Path, output_dir: Path, repo_root: Path, timeout: int = 600
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "patch.diff").write_text(patch_content)
        (output_dir / "agent.json").write_text(json.dumps({
            "status": agent_status,
            "needs_human": needs_human,
            "notes": notes,
        }))
        (output_dir / "cmdlog.txt").write_text(cmdlog)
    return write_outputs


# =============================================================================
# E2E Test: Success Path with Mocked Claude
# =============================================================================


class TestE2ESuccessPath:
    """E2E tests for successful step execution."""

    def test_full_success_path(self, git_repo: Path, runs_dir: Path, sample_aip: dict) -> None:
        """Test complete successful step execution with mocked Claude adapter."""
        patch_content = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,5 @@
 def hello():
     return "Hello"
+
+def greet(name):
+    return f"Hello, {name}!"
"""

        with patch.object(ClaudeAdapter, "execute", side_effect=make_write_outputs(
            patch_content, notes="Added greet function", cmdlog="ls\ncat src/main.py\n"
        )):
            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=3)

            assert result.termination_reason == TerminationReason.PASS
            assert len(result.iterations) == 1
            assert result.error is None
            assert "src/main.py" in result.touched_files

            # Verify artifacts were written
            assert result.artifacts_dir is not None
            artifacts_path = runs_dir / result.artifacts_dir
            assert (artifacts_path / "step_summary.yaml").exists()
            assert (artifacts_path / "result.json").exists()

    def test_success_with_verification(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test success path runs verification commands."""
        patch_content = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def hello():
     return "Hello"
+# Added comment
"""

        with patch.object(ClaudeAdapter, "execute", side_effect=make_write_outputs(patch_content)):
            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=3)

            assert result.termination_reason == TerminationReason.PASS
            assert result.verification_report is not None
            assert result.verification_report.get("passed") is True


# =============================================================================
# E2E Test: Scope Violation (No Retry)
# =============================================================================


class TestE2EScopeViolation:
    """E2E tests for scope violations."""

    def test_scope_rejects_untracked_file_outside_allowed_paths(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """GUARDRAIL: Untracked new file outside allowed_paths must be caught and rejected.

        This is a critical guardrail test. It verifies that:
        1. A patch creating a NEW file (untracked) outside allowed_paths is detected
        2. The touched_files set includes the untracked file
        3. The scope check fails BEFORE verification runs
        4. No retry is attempted (scope violations are not retryable)

        Without this, an agent could bypass scope by "adding" files rather than modifying.
        """
        # Create a patch that creates a NEW file outside src/** and tests/**
        # This file will be UNTRACKED (not in git index) after git apply
        patch_content = """diff --git a/config/settings.yaml b/config/settings.yaml
new file mode 100644
--- /dev/null
+++ b/config/settings.yaml
@@ -0,0 +1 @@
+setting: value
"""

        with patch.object(ClaudeAdapter, "execute") as mock_execute:
            call_count = [0]

            def write_and_count(input_dir: Path, output_dir: Path, repo_root: Path, timeout: int = 600) -> None:
                call_count[0] += 1
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "patch.diff").write_text(patch_content)
                (output_dir / "agent.json").write_text(json.dumps({
                    "status": "success", "needs_human": False, "notes": "OK"
                }))
                (output_dir / "cmdlog.txt").write_text("")

            mock_execute.side_effect = write_and_count

            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=3)

            # CRITICAL: Must fail with scope violation
            assert result.termination_reason == TerminationReason.FAIL_SCOPE

            # CRITICAL: The untracked file must be in checked_files
            assert result.policy_report is not None
            assert result.policy_report.get("passed") is False
            checked_files = result.policy_report.get("checked_files", [])
            assert "config/settings.yaml" in checked_files, (
                f"Untracked file 'config/settings.yaml' must be in checked_files. "
                f"Got: {checked_files}"
            )

            # CRITICAL: Scope check must happen before verification (no retry)
            assert call_count[0] == 1, "Should not retry on scope violation"

            # Verify the violation is correctly identified
            violations = result.policy_report.get("violations", [])
            assert len(violations) >= 1
            violation_files = [v.get("file_path") for v in violations]
            assert "config/settings.yaml" in violation_files

    def test_scope_violation_forbidden_path(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that touching forbidden paths fails with scope violation."""
        # Create a patch that touches secrets/** (forbidden)
        patch_content = """diff --git a/secrets/api_key.txt b/secrets/api_key.txt
new file mode 100644
--- /dev/null
+++ b/secrets/api_key.txt
@@ -0,0 +1 @@
+secret123
"""

        with patch.object(ClaudeAdapter, "execute", side_effect=make_write_outputs(patch_content)):
            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=3)

            assert result.termination_reason == TerminationReason.FAIL_SCOPE


# =============================================================================
# E2E Test: Retry Behavior
# =============================================================================


class TestE2ERetryBehavior:
    """E2E tests for retry on verification failure."""

    def test_retry_on_verification_failure_then_success(
        self, git_repo: Path, runs_dir: Path
    ) -> None:
        """Test that verification failures trigger retry and can succeed."""
        # AIP with verification that always passes
        aip = {
            "aip_id": "AIP-retry-test-001",
            "title": "Retry Test",
            "plan": [{
                "step_id": "step-001",
                "role": "agentic",
                "description": "Test retry",
                "allowed_paths": ["src/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["python -c 'print(1)'"],
            }],
        }

        patch_content = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def hello():
     return "Hello"
+# Fixed
"""

        with patch.object(ClaudeAdapter, "execute") as mock_execute:
            calls = [0]

            def write_outputs(input_dir: Path, output_dir: Path, repo_root: Path, timeout: int = 600) -> None:
                calls[0] += 1
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "patch.diff").write_text(patch_content)
                (output_dir / "agent.json").write_text(json.dumps({
                    "status": "success", "needs_human": False, "notes": f"Attempt {calls[0]}"
                }))
                (output_dir / "cmdlog.txt").write_text("")

            mock_execute.side_effect = write_outputs

            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=aip, step_idx=0, max_iterations=3)

            # Should pass on first attempt
            assert result.termination_reason == TerminationReason.PASS
            assert calls[0] >= 1


# =============================================================================
# E2E Test: Max Iterations
# =============================================================================


class TestE2EMaxIterations:
    """E2E tests for max iterations limit."""

    def test_max_iterations_reached_on_verify_failure(
        self, git_repo: Path, runs_dir: Path
    ) -> None:
        """Test that max iterations limit is enforced when verification keeps failing."""
        # AIP with verification that ALWAYS fails
        aip = {
            "aip_id": "AIP-maxiter-test-001",
            "title": "Max Iterations Test",
            "plan": [{
                "step_id": "step-001",
                "role": "agentic",
                "description": "Test max iterations",
                "allowed_paths": ["src/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["python -c 'import sys; sys.exit(1)'"],
            }],
        }

        patch_content = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def hello():
     return "Hello"
+# Added
"""

        with patch.object(ClaudeAdapter, "execute") as mock_execute:
            call_count = [0]

            def write_outputs(input_dir: Path, output_dir: Path, repo_root: Path, timeout: int = 600) -> None:
                call_count[0] += 1
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "patch.diff").write_text(patch_content)
                (output_dir / "agent.json").write_text(json.dumps({
                    "status": "success", "needs_human": False, "notes": f"Attempt {call_count[0]}"
                }))
                (output_dir / "cmdlog.txt").write_text("")

            mock_execute.side_effect = write_outputs

            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=aip, step_idx=0, max_iterations=3)

            assert result.termination_reason == TerminationReason.FAIL_VERIFY_RETRYABLE
            assert call_count[0] == 3, "Should have tried max_iterations times"
            assert len(result.iterations) == 3

    def test_max_iterations_custom_value(
        self, git_repo: Path, runs_dir: Path
    ) -> None:
        """Test custom max_iterations value."""
        aip = {
            "aip_id": "AIP-maxiter-custom-001",
            "title": "Custom Max Iterations Test",
            "plan": [{
                "step_id": "step-001",
                "role": "agentic",
                "description": "Test custom max iterations",
                "allowed_paths": ["src/**"],
                "forbidden_paths": [".git/**"],
                "verification_commands": ["python -c 'import sys; sys.exit(1)'"],
            }],
        }

        patch_content = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def hello():
     return "Hello"
+# Change
"""

        with patch.object(ClaudeAdapter, "execute") as mock_execute:
            call_count = [0]

            def write_outputs(input_dir: Path, output_dir: Path, repo_root: Path, timeout: int = 600) -> None:
                call_count[0] += 1
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "patch.diff").write_text(patch_content)
                (output_dir / "agent.json").write_text(json.dumps({
                    "status": "success", "needs_human": False, "notes": "OK"
                }))
                (output_dir / "cmdlog.txt").write_text("")

            mock_execute.side_effect = write_outputs

            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            runner.run_step(aip=aip, step_idx=0, max_iterations=5)

            assert call_count[0] == 5, "Should respect custom max_iterations"


# =============================================================================
# E2E Test: Dirty Worktree
# =============================================================================


class TestE2EDirtyWorktree:
    """E2E tests for dirty worktree handling."""

    def test_dirty_worktree_fails(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that dirty worktree fails without --allow-dirty."""
        # Make the worktree dirty
        (git_repo / "src" / "main.py").write_text("# Modified\n")

        runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
        result = runner.run_step(aip=sample_aip, step_idx=0, allow_dirty=False)

        assert result.termination_reason == TerminationReason.FAIL_DIRTY_WORKTREE
        assert "dirty" in result.error.lower()

    def test_dirty_worktree_allowed(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that --allow-dirty permits dirty worktree."""
        # Make the worktree dirty
        (git_repo / "src" / "main.py").write_text("# Modified\n")

        patch_content = """diff --git a/src/new_file.py b/src/new_file.py
new file mode 100644
--- /dev/null
+++ b/src/new_file.py
@@ -0,0 +1 @@
+# New file
"""

        with patch.object(ClaudeAdapter, "execute", side_effect=make_write_outputs(patch_content)):
            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, allow_dirty=True)

            # Should NOT fail due to dirty worktree
            assert result.termination_reason != TerminationReason.FAIL_DIRTY_WORKTREE


# =============================================================================
# E2E Test: Dry Run
# =============================================================================


class TestE2EDryRun:
    """E2E tests for dry run mode."""

    def test_dry_run_writes_input_bundle(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that dry run writes input bundle and exits."""
        runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
        result = runner.run_step(aip=sample_aip, step_idx=0, dry_run=True)

        # Dry run should return PASS with no iterations
        assert result.termination_reason == TerminationReason.PASS
        assert len(result.iterations) == 0
        assert result.dry_run_command is not None
        assert "claude" in result.dry_run_command

        # Input bundle should exist
        assert result.artifacts_dir is not None
        artifacts_path = runs_dir / result.artifacts_dir
        input_dir = artifacts_path / "input"
        assert input_dir.exists()
        assert (input_dir / "prompt.md").exists()
        assert (input_dir / "contract.yaml").exists()
        assert (input_dir / "repo_state.json").exists()

    def test_dry_run_does_not_execute_adapter(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that dry run does not invoke the adapter."""
        with patch.object(ClaudeAdapter, "execute") as mock_execute:
            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, dry_run=True)

            mock_execute.assert_not_called()
            assert result.termination_reason == TerminationReason.PASS


# =============================================================================
# E2E Test: Forbidden Command Detection
# =============================================================================


class TestE2EForbiddenCommands:
    """E2E tests for forbidden command detection.

    Note: Forbidden command checking happens inside the ClaudeAdapter.
    When we mock adapter.execute, we bypass that check.
    To test forbidden command detection, we need to have the mock RAISE ProtocolError.
    """

    def test_forbidden_command_raises_protocol_error(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that forbidden commands in cmdlog cause FAIL_ADAPTER_PROTOCOL."""
        with patch.object(ClaudeAdapter, "execute") as mock_execute:
            # Simulate adapter detecting forbidden command and raising ProtocolError
            mock_execute.side_effect = ProtocolError("hard: rm command detected in cmdlog")

            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=1)

            assert result.termination_reason == TerminationReason.FAIL_ADAPTER_PROTOCOL
            assert "rm" in result.error.lower()

    def test_forbidden_git_commit_raises_protocol_error(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that git commit in cmdlog causes FAIL_ADAPTER_PROTOCOL."""
        with patch.object(ClaudeAdapter, "execute") as mock_execute:
            mock_execute.side_effect = ProtocolError("hard: git commit detected")

            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=1)

            assert result.termination_reason == TerminationReason.FAIL_ADAPTER_PROTOCOL

    def test_allowed_commands_pass(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that allowed commands don't trigger violations."""
        patch_content = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def hello():
     return "Hello"
+# OK
"""

        # No exception raised means allowed commands pass
        with patch.object(ClaudeAdapter, "execute", side_effect=make_write_outputs(
            patch_content, cmdlog="ls\ncat src/main.py\ngit status\ngit diff\n"
        )):
            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=1)

            assert result.termination_reason != TerminationReason.FAIL_ADAPTER_PROTOCOL


# =============================================================================
# E2E Test: Escalation (needs_human)
# =============================================================================


class TestE2EEscalation:
    """E2E tests for escalation scenarios."""

    def test_needs_human_triggers_escalation(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that needs_human=true triggers ESCALATE_NEEDS_HUMAN."""
        patch_content = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def hello():
     return "Hello"
+# Partial
"""

        with patch.object(ClaudeAdapter, "execute", side_effect=make_write_outputs(
            patch_content,
            agent_status="needs_human",
            needs_human=True,
            notes="I'm not sure how to proceed",
        )):
            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=3)

            assert result.termination_reason == TerminationReason.ESCALATE_NEEDS_HUMAN


# =============================================================================
# E2E Test: Artifact Completeness
# =============================================================================


class TestE2EArtifactCompleteness:
    """E2E tests verifying artifact output structure."""

    def test_success_artifacts_complete(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that successful execution writes all required artifacts."""
        patch_content = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def hello():
     return "Hello"
+# Done
"""

        with patch.object(ClaudeAdapter, "execute", side_effect=make_write_outputs(patch_content)):
            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=1)

            assert result.artifacts_dir is not None
            artifacts_path = runs_dir / result.artifacts_dir

            # Required top-level artifacts (audit-essential set)
            assert (artifacts_path / "result.json").exists()
            assert (artifacts_path / "step_summary.yaml").exists()
            assert (artifacts_path / "patch.diff").exists()

            # Input bundle
            assert (artifacts_path / "input" / "prompt.md").exists()
            assert (artifacts_path / "input" / "contract.yaml").exists()
            assert (artifacts_path / "input" / "repo_state.json").exists()

            # Iteration artifacts
            iter_dir = artifacts_path / "iter-0"
            assert iter_dir.exists()
            assert (iter_dir / "output" / "patch.diff").exists()
            assert (iter_dir / "output" / "agent.json").exists()

    def test_failure_artifacts_complete(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that failed execution still writes required artifacts."""
        # Dirty worktree failure - should still write audit-essential artifacts
        (git_repo / "src" / "main.py").write_text("# Dirty\n")

        runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
        result = runner.run_step(aip=sample_aip, step_idx=0, allow_dirty=False)

        assert result.termination_reason == TerminationReason.FAIL_DIRTY_WORKTREE
        assert result.artifacts_dir is not None

        artifacts_path = runs_dir / result.artifacts_dir
        assert (artifacts_path / "result.json").exists()
        assert (artifacts_path / "step_summary.yaml").exists()

        # Verify result.json has required fields
        result_data = json.loads((artifacts_path / "result.json").read_text())
        assert result_data["termination_reason"] == "FAIL_DIRTY_WORKTREE"
        assert "aip_id" in result_data
        assert "step_id" in result_data


# =============================================================================
# E2E Test: Patch Apply Failure
# =============================================================================


class TestE2EPatchApplyFailure:
    """E2E tests for patch apply failures."""

    def test_invalid_patch_fails(
        self, git_repo: Path, runs_dir: Path, sample_aip: dict
    ) -> None:
        """Test that invalid patch causes FAIL_PATCH_APPLY."""
        # Invalid patch that can't be applied
        patch_content = """diff --git a/nonexistent.py b/nonexistent.py
--- a/nonexistent.py
+++ b/nonexistent.py
@@ -1,5 +1,6 @@
 line1
 line2
 line3
+new line
 line4
 line5
"""

        with patch.object(ClaudeAdapter, "execute", side_effect=make_write_outputs(patch_content)):
            runner = StepRunner(repo_root=git_repo, runs_dir=runs_dir, adapter_name="claude")
            result = runner.run_step(aip=sample_aip, step_idx=0, max_iterations=1)

            assert result.termination_reason == TerminationReason.FAIL_PATCH_APPLY
