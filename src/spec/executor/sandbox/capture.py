"""
Git state capture: captures git state before and after step execution.

Provides:
- Current commit SHA
- Changed files list with before/after hashes
- Unified diff (patch) generation
- Full GitCapture model creation
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from spec.executor.schemas.capture import GitCapture


class GitCaptureError(Exception):
    """Error during git state capture."""

    def __init__(self, message: str, *, repo_path: Path | None = None):
        super().__init__(message)
        self.repo_path = repo_path


@dataclass
class ChangedFile:
    """A file changed between two commits."""

    path: str
    before_hash: str | None  # None if file is new
    after_hash: str | None  # None if file is deleted
    status: str  # M, A, D, R, C, etc.


def _run_git(
    args: list[str], repo_path: Path, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """
    Run a git command in the specified repo.

    Args:
        args: Git command arguments (without 'git' prefix)
        repo_path: Path to the repository
        check: Whether to raise on non-zero exit

    Returns:
        CompletedProcess result

    Raises:
        GitCaptureError: If command fails and check=True
    """
    cmd = ["git", "-C", str(repo_path), *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )
        return result
    except subprocess.CalledProcessError as e:
        raise GitCaptureError(
            f"Git command failed: {' '.join(cmd)}\nstderr: {e.stderr}",
            repo_path=repo_path,
        ) from e


def get_current_commit(repo_path: Path) -> str:
    """
    Get the current HEAD commit SHA.

    Args:
        repo_path: Path to the repository

    Returns:
        The full SHA of HEAD

    Raises:
        GitCaptureError: If not a git repo or HEAD is invalid
    """
    result = _run_git(["rev-parse", "HEAD"], repo_path)
    return result.stdout.strip()


def get_current_branch(repo_path: Path) -> str | None:
    """
    Get the current branch name.

    Args:
        repo_path: Path to the repository

    Returns:
        Branch name, or None if in detached HEAD state

    Raises:
        GitCaptureError: If not a git repo
    """
    result = _run_git(["symbolic-ref", "--short", "HEAD"], repo_path, check=False)
    if result.returncode != 0:
        # Detached HEAD state
        return None
    return result.stdout.strip()


def is_detached_head(repo_path: Path) -> bool:
    """
    Check if the repo is in detached HEAD state.

    Args:
        repo_path: Path to the repository

    Returns:
        True if in detached HEAD state
    """
    return get_current_branch(repo_path) is None


def get_git_status(repo_path: Path) -> str:
    """
    Get git status output (porcelain format).

    Args:
        repo_path: Path to the repository

    Returns:
        Git status output
    """
    result = _run_git(["status", "--porcelain"], repo_path)
    return result.stdout


def is_working_tree_dirty(repo_path: Path) -> bool:
    """
    Check if working tree has uncommitted changes.

    Args:
        repo_path: Path to the repository

    Returns:
        True if there are uncommitted changes
    """
    status = get_git_status(repo_path)
    return bool(status.strip())


def get_changed_files(
    repo_path: Path, base_commit: str, head_commit: str | None = None
) -> list[ChangedFile]:
    """
    Get list of files changed between two commits.

    Args:
        repo_path: Path to the repository
        base_commit: The base commit SHA
        head_commit: The head commit SHA (defaults to HEAD)

    Returns:
        List of ChangedFile objects
    """
    head = head_commit or "HEAD"

    # Get diff with file hashes
    result = _run_git(
        ["diff", "--name-status", "--no-renames", f"{base_commit}..{head}"],
        repo_path,
    )

    changed_files: list[ChangedFile] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 2:
            continue

        status = parts[0]
        path = parts[1]

        # Get before hash (from base commit)
        before_result = _run_git(
            ["rev-parse", f"{base_commit}:{path}"],
            repo_path,
            check=False,
        )
        before_hash = (
            before_result.stdout.strip() if before_result.returncode == 0 else None
        )

        # Get after hash (from head)
        after_result = _run_git(
            ["rev-parse", f"{head}:{path}"],
            repo_path,
            check=False,
        )
        after_hash = (
            after_result.stdout.strip() if after_result.returncode == 0 else None
        )

        changed_files.append(
            ChangedFile(
                path=path,
                before_hash=before_hash,
                after_hash=after_hash,
                status=status,
            )
        )

    return changed_files


def get_uncommitted_changed_files(repo_path: Path) -> list[ChangedFile]:
    """
    Get list of files with uncommitted changes.

    Args:
        repo_path: Path to the repository

    Returns:
        List of ChangedFile objects for uncommitted changes
    """
    # Get staged and unstaged changes
    result = _run_git(["diff", "--name-status", "HEAD"], repo_path, check=False)

    changed_files: list[ChangedFile] = []

    # If there are no commits yet or other error, try without HEAD
    if result.returncode != 0:
        result = _run_git(["status", "--porcelain"], repo_path)
        for line in result.stdout.strip().split("\n"):
            if not line or len(line) < 4:
                continue
            status = line[0:2].strip() or "M"
            path = line[3:]
            changed_files.append(
                ChangedFile(
                    path=path,
                    before_hash=None,
                    after_hash=None,
                    status=status,
                )
            )
        return changed_files

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 2:
            continue

        status = parts[0]
        path = parts[1]

        # For uncommitted changes, get hashes where possible
        head_result = _run_git(
            ["rev-parse", f"HEAD:{path}"],
            repo_path,
            check=False,
        )
        before_hash = (
            head_result.stdout.strip() if head_result.returncode == 0 else None
        )

        changed_files.append(
            ChangedFile(
                path=path,
                before_hash=before_hash,
                after_hash=None,  # Working tree, no hash
                status=status,
            )
        )

    return changed_files


def generate_working_tree_diff(repo_path: Path, base_commit: str) -> str:
    """
    Generate a unified diff from `base_commit` to the current working tree.

    Unlike generate_patch() (which diffs two fixed commits and misses
    anything not yet committed), this diffs a single commit against the
    live working tree -- so it always reflects the full accumulated change
    since base_commit regardless of whether it has been committed yet.
    Used to snapshot repo state immediately before and after a step
    dispatch, so the two snapshots can be compared to isolate what that
    step actually changed.

    Args:
        repo_path: Path to the repository
        base_commit: The commit SHA to diff against

    Returns:
        The unified diff content

    Raises:
        GitCaptureError: If the git command fails
    """
    result = _run_git(["diff", "--unified=3", base_commit], repo_path)
    return result.stdout


def generate_patch(
    repo_path: Path,
    base_commit: str,
    head_commit: str | None = None,
    output_path: Path | None = None,
) -> str:
    """
    Generate a unified diff (patch) between two commits.

    Args:
        repo_path: Path to the repository
        base_commit: The base commit SHA
        head_commit: The head commit SHA (defaults to HEAD)
        output_path: Optional path to write the patch file

    Returns:
        The unified diff content
    """
    head = head_commit or "HEAD"

    result = _run_git(
        ["diff", "--unified=3", f"{base_commit}..{head}"],
        repo_path,
    )

    patch_content = result.stdout

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(patch_content)

    return patch_content


def generate_uncommitted_patch(
    repo_path: Path,
    output_path: Path | None = None,
) -> str:
    """
    Generate a unified diff for uncommitted changes.

    Includes both staged and unstaged changes.

    Args:
        repo_path: Path to the repository
        output_path: Optional path to write the patch file

    Returns:
        The unified diff content
    """
    # Get both staged and unstaged changes
    result = _run_git(["diff", "--unified=3", "HEAD"], repo_path, check=False)

    patch_content = result.stdout if result.returncode == 0 else ""

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(patch_content)

    return patch_content


def validate_branch(repo_path: Path, expected_branch: str) -> None:
    """
    Validate that we're on the expected branch.

    Args:
        repo_path: Path to the repository
        expected_branch: The branch we expect to be on

    Raises:
        GitCaptureError: If not on expected branch or in detached HEAD
    """
    current = get_current_branch(repo_path)

    if current is None:
        raise GitCaptureError(
            "Repository is in detached HEAD state. Cannot proceed with execution.",
            repo_path=repo_path,
        )

    if current != expected_branch:
        raise GitCaptureError(
            f"Branch mismatch: expected '{expected_branch}', but on '{current}'",
            repo_path=repo_path,
        )


def validate_base_commit(repo_path: Path, expected_commit: str) -> None:
    """
    Validate that the base commit hasn't drifted.

    Args:
        repo_path: Path to the repository
        expected_commit: The commit SHA we expect

    Raises:
        GitCaptureError: If current HEAD doesn't match expected
    """
    current = get_current_commit(repo_path)

    # Allow prefix matching (short SHA)
    if not current.startswith(expected_commit) and not expected_commit.startswith(
        current
    ):
        raise GitCaptureError(
            f"Base commit drifted: expected '{expected_commit[:12]}', "
            f"but HEAD is '{current[:12]}'",
            repo_path=repo_path,
        )


def capture_pre_step_state(
    repo_path: Path,
    expected_branch: str,
    base_commit: str,
    *,
    validate: bool = True,
) -> dict[str, str]:
    """
    Capture git state before step execution.

    Args:
        repo_path: Path to the repository
        expected_branch: The branch we expect to be on
        base_commit: The base commit SHA
        validate: Whether to validate branch and commit

    Returns:
        Dict with pre_status, base_commit, current_branch

    Raises:
        GitCaptureError: If validation fails
    """
    if validate:
        validate_branch(repo_path, expected_branch)
        validate_base_commit(repo_path, base_commit)

    return {
        "pre_status": get_git_status(repo_path),
        "base_commit": base_commit,
        "current_branch": get_current_branch(repo_path) or "DETACHED",
    }


def capture_git_state(
    repo_path: Path,
    base_commit: str,
    patch_output_path: Path | None = None,
) -> GitCapture:
    """
    Capture full git state after step execution.

    Args:
        repo_path: Path to the repository
        base_commit: The base commit at step start
        patch_output_path: Optional path to write patch file

    Returns:
        GitCapture model with all state captured
    """
    current_commit = get_current_commit(repo_path)
    post_status = get_git_status(repo_path)
    working_dirty = is_working_tree_dirty(repo_path)

    # Check if there was a new commit
    commit_sha = current_commit if current_commit != base_commit else None

    # Get changed files between base and current commit
    if commit_sha:
        changed = get_changed_files(repo_path, base_commit, current_commit)
        patch = generate_patch(repo_path, base_commit, current_commit, patch_output_path)
    else:
        # No new commit - check for uncommitted changes
        changed = get_uncommitted_changed_files(repo_path)
        patch = generate_uncommitted_patch(repo_path, patch_output_path)

    # Format changed files for schema
    changed_files = [
        {
            "path": f.path,
            "before": f.before_hash or "",
            "after": f.after_hash or "",
            "status": f.status,
        }
        for f in changed
    ]

    # Determine patch_file as relative filename
    # Always create the patch file (even if empty) for consistency
    if patch_output_path:
        if not patch:
            # Write empty patch file
            patch_output_path.write_text("")
        patch_file = patch_output_path.name
    else:
        patch_file = None

    return GitCapture(
        base_commit=base_commit,
        pre_status="",  # Should be filled by caller from pre-step capture
        post_status=post_status,
        patch_file=patch_file,
        changed_files=changed_files,
        commit_sha=commit_sha,
        working_tree_dirty=working_dirty,
    )
