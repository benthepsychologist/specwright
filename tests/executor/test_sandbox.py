"""
Tests for git sandbox enforcement and capture.
"""

import subprocess
from pathlib import Path

import pytest

from spec.executor.sandbox import (
    PolicyViolation,
    SandboxEnforcer,
    check_command,
)
from spec.executor.sandbox.capture import (
    GitCaptureError,
    capture_git_state,
    generate_patch,
    get_changed_files,
    get_current_branch,
    get_current_commit,
    get_git_status,
    is_detached_head,
    is_working_tree_dirty,
    validate_base_commit,
    validate_branch,
)
from spec.executor.sandbox.enforcer import (
    _is_git_checkout_branch,
    _is_git_merge,
    _is_git_push,
)
from spec.executor.schemas import GitCapture, Policy

# =============================================================================
# Enforcer Tests
# =============================================================================


class TestPolicyViolation:
    """Tests for PolicyViolation exception."""

    def test_basic_violation(self):
        exc = PolicyViolation(
            "Push not allowed",
            command="git push origin main",
            policy_rule="allow_push",
        )
        assert "Push not allowed" in str(exc)
        assert exc.command == "git push origin main"
        assert exc.policy_rule == "allow_push"

    def test_violation_with_repo_path(self):
        exc = PolicyViolation(
            "Push not allowed",
            command="git push",
            policy_rule="allow_push",
            repo_path=Path("/workspace/myrepo"),
        )
        assert "/workspace/myrepo" in str(exc)


class TestGitCommandDetection:
    """Tests for git command pattern detection."""

    def test_is_git_push_basic(self):
        assert _is_git_push("git push") is True
        assert _is_git_push("git push origin main") is True
        assert _is_git_push("git push --force") is True

    def test_is_git_push_with_flags(self):
        assert _is_git_push("git -C /path/to/repo push") is True
        assert _is_git_push("git -c core.autocrlf=false push origin") is True

    def test_is_git_push_false_positives(self):
        assert _is_git_push("git status") is False
        assert _is_git_push("git commit") is False
        # Note: "echo git push" now returns True because unquoted args
        # could be piped to a shell. Use quoted strings for safe echo.
        assert _is_git_push("echo 'git push'") is False
        assert _is_git_push("# git push") is False

    def test_is_git_merge_basic(self):
        assert _is_git_merge("git merge") is True
        assert _is_git_merge("git merge feature-branch") is True
        assert _is_git_merge("git merge --no-ff feature") is True

    def test_is_git_merge_with_flags(self):
        assert _is_git_merge("git -C /path merge branch") is True

    def test_is_git_merge_false_positives(self):
        assert _is_git_merge("git status") is False
        # Note: "echo git merge" now returns True - use quoted strings
        assert _is_git_merge("echo 'git merge'") is False

    def test_is_git_checkout_branch(self):
        # Should detect branch switching
        assert _is_git_checkout_branch("git checkout main") is True
        assert _is_git_checkout_branch("git checkout -b new-branch") is True
        assert _is_git_checkout_branch("git checkout -B new-branch") is True

    def test_is_git_checkout_file_allowed(self):
        # File checkouts should be allowed
        assert _is_git_checkout_branch("git checkout -- file.txt") is False
        assert _is_git_checkout_branch("git checkout HEAD -- file.txt") is False

    def test_is_git_checkout_not_checkout(self):
        assert _is_git_checkout_branch("git status") is False
        assert _is_git_checkout_branch("git commit") is False


class TestEvasionAttempts:
    """Tests for command evasion attempt detection."""

    def test_command_chaining_blocked(self):
        """Command chaining should be detected."""
        policy = Policy()
        assert check_command("echo foo && git push", policy).allowed is False
        assert check_command("echo foo; git push", policy).allowed is False
        assert check_command("echo foo | git push", policy).allowed is False

    def test_subshell_blocked(self):
        """Subshell execution should be detected."""
        policy = Policy()
        assert check_command("(git push)", policy).allowed is False
        assert check_command("$(git push)", policy).allowed is False
        assert check_command("`git push`", policy).allowed is False

    def test_shell_exec_blocked(self):
        """Shell -c execution should be detected."""
        policy = Policy()
        assert check_command("bash -c 'git push'", policy).allowed is False
        assert check_command("sh -c 'git push'", policy).allowed is False

    def test_path_variations_blocked(self):
        """Git with path prefix should be detected."""
        policy = Policy()
        assert check_command("/usr/bin/git push", policy).allowed is False
        assert check_command("./git push", policy).allowed is False
        assert check_command("../git push", policy).allowed is False

    def test_env_var_prefix_blocked(self):
        """Git with env var prefix should be detected."""
        policy = Policy()
        assert check_command("GIT_DIR=/tmp git push", policy).allowed is False
        assert check_command("env git push", policy).allowed is False

    def test_pipe_to_shell_blocked(self):
        """Piping dangerous commands to shell should be blocked."""
        policy = Policy()
        assert check_command("echo 'git push' | sh", policy).allowed is False
        assert check_command("echo 'git push' | bash", policy).allowed is False
        assert check_command("printf 'git push' | sh", policy).allowed is False

    def test_newline_injection_blocked(self):
        """Newline injection should be detected."""
        policy = Policy()
        assert check_command("git status\ngit push", policy).allowed is False

    def test_comments_allowed(self):
        """Comments should be ignored."""
        policy = Policy()
        assert check_command("# git push", policy).allowed is True

    def test_quoted_echo_allowed(self):
        """Echo with quoted string (not piped to shell) is safe."""
        policy = Policy()
        assert check_command("echo 'git push'", policy).allowed is True
        assert check_command('echo "git push"', policy).allowed is True

    def test_git_in_commit_message_allowed(self):
        """Git keywords in commit messages should be allowed."""
        policy = Policy()
        assert check_command("git commit -m 'push this later'", policy).allowed is True
        assert check_command("git commit -m 'merge changes'", policy).allowed is True


class TestCheckCommand:
    """Tests for check_command function."""

    def test_allowed_command(self):
        policy = Policy()
        result = check_command("git status", policy)
        assert result.allowed is True
        assert result.violation_reason is None

    def test_blocked_push(self):
        policy = Policy(allow_push=False)
        result = check_command("git push origin main", policy)
        assert result.allowed is False
        assert result.policy_rule == "allow_push"

    def test_allowed_push(self):
        policy = Policy(allow_push=True)
        result = check_command("git push origin main", policy)
        assert result.allowed is True

    def test_blocked_merge(self):
        policy = Policy(allow_merge=False)
        result = check_command("git merge feature", policy)
        assert result.allowed is False
        assert result.policy_rule == "allow_merge"

    def test_allowed_merge(self):
        policy = Policy(allow_merge=True)
        result = check_command("git merge feature", policy)
        assert result.allowed is True

    def test_blocked_commands_list(self):
        policy = Policy(blocked_commands=["rm -rf", "git push"])
        result = check_command("rm -rf /", policy)
        assert result.allowed is False
        assert result.policy_rule == "blocked_commands"

    def test_commit_allowed_by_default(self):
        policy = Policy()
        result = check_command("git commit -m 'test'", policy)
        assert result.allowed is True


class TestSandboxEnforcer:
    """Tests for SandboxEnforcer class."""

    def test_basic_check(self):
        policy = Policy()
        enforcer = SandboxEnforcer(
            policy=policy,
            repo_path=Path("/workspace/repo"),
            expected_branch="main",
        )
        result = enforcer.check("git status")
        assert result.allowed is True

    def test_enforce_raises_on_violation(self):
        policy = Policy(allow_push=False)
        enforcer = SandboxEnforcer(
            policy=policy,
            repo_path=Path("/workspace/repo"),
            expected_branch="main",
        )
        with pytest.raises(PolicyViolation) as exc_info:
            enforcer.enforce("git push origin main")
        assert "push" in str(exc_info.value).lower()

    def test_violations_tracked(self):
        policy = Policy(allow_push=False)
        enforcer = SandboxEnforcer(
            policy=policy,
            repo_path=Path("/workspace/repo"),
            expected_branch="main",
        )
        try:
            enforcer.enforce("git push")
        except PolicyViolation:
            pass
        assert len(enforcer.violations) == 1

    def test_branch_integrity_blocks_checkout(self):
        policy = Policy()
        enforcer = SandboxEnforcer(
            policy=policy,
            repo_path=Path("/workspace/repo"),
            expected_branch="feat/test",
        )
        with pytest.raises(PolicyViolation) as exc_info:
            enforcer.enforce_branch_integrity("git checkout main")
        assert "branch" in str(exc_info.value).lower()

    def test_branch_integrity_allows_file_checkout(self):
        policy = Policy()
        enforcer = SandboxEnforcer(
            policy=policy,
            repo_path=Path("/workspace/repo"),
            expected_branch="feat/test",
        )
        # Should not raise
        enforcer.enforce_branch_integrity("git checkout -- file.txt")

    def test_full_check(self):
        policy = Policy(allow_push=False)
        enforcer = SandboxEnforcer(
            policy=policy,
            repo_path=Path("/workspace/repo"),
            expected_branch="main",
        )

        # Should not raise
        enforcer.full_check("git status")

        # Should raise for push
        with pytest.raises(PolicyViolation):
            enforcer.full_check("git push origin main")


# =============================================================================
# Capture Tests (with mocked git)
# =============================================================================


class TestGitCaptureFunctions:
    """Tests for git capture functions using mocks."""

    def test_get_current_commit(self, tmp_path):
        """Test get_current_commit with a real git repo."""
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create initial commit
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        commit = get_current_commit(tmp_path)
        assert len(commit) == 40  # Full SHA

    def test_get_current_branch(self, tmp_path):
        """Test get_current_branch with a real git repo."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "-b", "main"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create initial commit so branch exists
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        branch = get_current_branch(tmp_path)
        assert branch == "main"

    def test_is_detached_head(self, tmp_path):
        """Test is_detached_head detection."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create initial commit
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Not detached initially
        assert is_detached_head(tmp_path) is False

        # Detach HEAD
        commit = get_current_commit(tmp_path)
        subprocess.run(
            ["git", "checkout", commit],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        assert is_detached_head(tmp_path) is True

    def test_get_git_status(self, tmp_path):
        """Test get_git_status."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

        # Empty status initially
        status = get_git_status(tmp_path)
        assert status == ""

        # Create untracked file
        (tmp_path / "new.txt").write_text("new file")
        status = get_git_status(tmp_path)
        assert "new.txt" in status

    def test_is_working_tree_dirty(self, tmp_path):
        """Test is_working_tree_dirty detection."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

        # Clean initially
        assert is_working_tree_dirty(tmp_path) is False

        # Add untracked file
        (tmp_path / "new.txt").write_text("content")
        assert is_working_tree_dirty(tmp_path) is True


class TestValidation:
    """Tests for validation functions."""

    def test_validate_branch_success(self, tmp_path):
        """Test validate_branch with correct branch."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "-b", "feat/test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create commit so branch exists
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Should not raise
        validate_branch(tmp_path, "feat/test")

    def test_validate_branch_mismatch(self, tmp_path):
        """Test validate_branch with wrong branch."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "-b", "main"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create commit
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        with pytest.raises(GitCaptureError) as exc_info:
            validate_branch(tmp_path, "feat/other")
        assert "mismatch" in str(exc_info.value).lower()

    def test_validate_branch_detached_head(self, tmp_path):
        """Test validate_branch in detached HEAD state."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create commit
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Detach HEAD
        commit = get_current_commit(tmp_path)
        subprocess.run(
            ["git", "checkout", commit],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        with pytest.raises(GitCaptureError) as exc_info:
            validate_branch(tmp_path, "main")
        assert "detached" in str(exc_info.value).lower()

    def test_validate_base_commit_success(self, tmp_path):
        """Test validate_base_commit with correct commit."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        commit = get_current_commit(tmp_path)

        # Should not raise
        validate_base_commit(tmp_path, commit)

        # Short SHA should also work
        validate_base_commit(tmp_path, commit[:7])

    def test_validate_base_commit_drifted(self, tmp_path):
        """Test validate_base_commit when commit has drifted."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        with pytest.raises(GitCaptureError) as exc_info:
            validate_base_commit(tmp_path, "0000000000000000000000000000000000000000")
        assert "drifted" in str(exc_info.value).lower()


class TestPatchGeneration:
    """Tests for patch generation."""

    def test_generate_patch_with_changes(self, tmp_path):
        """Test generate_patch with actual changes."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Initial commit
        (tmp_path / "file.txt").write_text("original")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        base_commit = get_current_commit(tmp_path)

        # Make change and commit
        (tmp_path / "file.txt").write_text("modified")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "modify"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        patch_content = generate_patch(tmp_path, base_commit)
        assert "original" in patch_content
        assert "modified" in patch_content
        assert "diff --git" in patch_content

    def test_generate_patch_empty(self, tmp_path):
        """Test generate_patch with no changes."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        (tmp_path / "file.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        base_commit = get_current_commit(tmp_path)

        patch_content = generate_patch(tmp_path, base_commit)
        assert patch_content == ""

    def test_generate_patch_to_file(self, tmp_path):
        """Test generate_patch writes to file."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        (tmp_path / "file.txt").write_text("original")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        base_commit = get_current_commit(tmp_path)

        (tmp_path / "file.txt").write_text("modified")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "modify"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        output_path = tmp_path / "output" / "changes.patch"
        patch_content = generate_patch(tmp_path, base_commit, output_path=output_path)

        assert output_path.exists()
        assert output_path.read_text() == patch_content


class TestChangedFiles:
    """Tests for changed files detection."""

    def test_get_changed_files(self, tmp_path):
        """Test get_changed_files with various change types."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Initial commit
        (tmp_path / "existing.txt").write_text("original")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        base_commit = get_current_commit(tmp_path)

        # Make changes: modify, add, delete
        (tmp_path / "existing.txt").write_text("modified")
        (tmp_path / "new.txt").write_text("new file")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "changes"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        changed = get_changed_files(tmp_path, base_commit)
        paths = [f.path for f in changed]

        assert "existing.txt" in paths
        assert "new.txt" in paths


class TestCaptureGitState:
    """Tests for capture_git_state function."""

    def test_capture_with_commit(self, tmp_path):
        """Test capture_git_state after a commit."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        (tmp_path / "file.txt").write_text("original")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        base_commit = get_current_commit(tmp_path)

        (tmp_path / "file.txt").write_text("modified")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "modify"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        capture = capture_git_state(tmp_path, base_commit)

        assert isinstance(capture, GitCapture)
        assert capture.base_commit == base_commit
        assert capture.commit_sha is not None
        assert capture.commit_sha != base_commit
        assert len(capture.changed_files) > 0
        assert capture.working_tree_dirty is False

    def test_capture_with_uncommitted_changes(self, tmp_path):
        """Test capture_git_state with uncommitted changes."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        (tmp_path / "file.txt").write_text("original")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        base_commit = get_current_commit(tmp_path)

        # Make uncommitted change
        (tmp_path / "file.txt").write_text("modified but not committed")

        capture = capture_git_state(tmp_path, base_commit)

        assert capture.commit_sha is None  # No new commit
        assert capture.working_tree_dirty is True

    def test_capture_empty_diff(self, tmp_path):
        """Test capture_git_state with no changes."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        (tmp_path / "file.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        base_commit = get_current_commit(tmp_path)

        capture = capture_git_state(tmp_path, base_commit)

        assert capture.commit_sha is None
        assert capture.working_tree_dirty is False
        assert len(capture.changed_files) == 0

    def test_capture_writes_patch_file(self, tmp_path):
        """Test capture_git_state writes patch to specified path."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        (tmp_path / "file.txt").write_text("original")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        base_commit = get_current_commit(tmp_path)

        (tmp_path / "file.txt").write_text("modified")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "modify"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        patch_path = tmp_path / "artifacts" / "changes.patch"
        capture = capture_git_state(tmp_path, base_commit, patch_output_path=patch_path)

        assert patch_path.exists()
        assert capture.patch_file == str(patch_path)
