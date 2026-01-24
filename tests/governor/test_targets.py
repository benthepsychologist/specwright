"""Tests for multi-repo target resolution."""

from pathlib import Path

import pytest

from spec.governor.targets import RepoTarget, TargetResolutionError, TargetResolver


class TestRepoTarget:
    """Tests for RepoTarget dataclass."""

    def test_to_dict(self, tmp_path: Path) -> None:
        """Test RepoTarget serialization."""
        target = RepoTarget(
            name="my-repo",
            path=tmp_path,
            suggested_paths=["src/**"],
        )

        result = target.to_dict()

        assert result["name"] == "my-repo"
        assert result["path"] == str(tmp_path)
        assert result["suggested_paths"] == ["src/**"]

    def test_from_dict(self, tmp_path: Path) -> None:
        """Test RepoTarget deserialization."""
        data = {
            "name": "my-repo",
            "path": str(tmp_path),
            "suggested_paths": ["src/**"],
        }

        target = RepoTarget.from_dict(data)

        assert target.name == "my-repo"
        assert target.path == tmp_path
        assert target.suggested_paths == ["src/**"]


class TestTargetResolver:
    """Tests for TargetResolver."""

    def test_resolve_explicit_path(self, tmp_path: Path) -> None:
        """Test resolving target with explicit path."""
        repo_path = tmp_path / "my-repo"
        repo_path.mkdir()

        targets_block = [
            {
                "repo": "my-repo",
                "path": str(repo_path),
                "suggested_paths": ["src/**"],
            }
        ]

        resolver = TargetResolver()
        resolved = resolver.resolve(targets_block)

        assert len(resolved) == 1
        assert resolved[0].name == "my-repo"
        assert resolved[0].path == repo_path
        assert resolved[0].suggested_paths == ["src/**"]

    def test_resolve_from_registry(self, tmp_path: Path) -> None:
        """Test resolving target from registry."""
        repo_path = tmp_path / "registered-repo"
        repo_path.mkdir()

        targets_block = [{"repo": "registered-repo"}]

        resolver = TargetResolver(registry={"registered-repo": repo_path})
        resolved = resolver.resolve(targets_block)

        assert len(resolved) == 1
        assert resolved[0].name == "registered-repo"
        assert resolved[0].path == repo_path

    def test_resolve_multiple_targets(self, tmp_path: Path) -> None:
        """Test resolving multiple targets."""
        repo1 = tmp_path / "repo1"
        repo2 = tmp_path / "repo2"
        repo1.mkdir()
        repo2.mkdir()

        targets_block = [
            {"repo": "repo1", "path": str(repo1)},
            {"repo": "repo2", "path": str(repo2)},
        ]

        resolver = TargetResolver()
        resolved = resolver.resolve(targets_block)

        assert len(resolved) == 2
        assert resolved[0].name == "repo1"
        assert resolved[1].name == "repo2"

    def test_resolve_missing_name_raises(self) -> None:
        """Test that missing repo name raises error."""
        targets_block = [{"path": "/some/path"}]

        resolver = TargetResolver()

        with pytest.raises(TargetResolutionError, match="missing 'repo' or 'name'"):
            resolver.resolve(targets_block)

    def test_resolve_unregistered_no_path_raises(self) -> None:
        """Test that unregistered repo without path raises error."""
        targets_block = [{"repo": "unknown-repo"}]

        resolver = TargetResolver()

        with pytest.raises(TargetResolutionError, match="Cannot resolve target"):
            resolver.resolve(targets_block)

    def test_resolve_nonexistent_path_raises(self, tmp_path: Path) -> None:
        """Test that nonexistent path raises error."""
        targets_block = [
            {
                "repo": "my-repo",
                "path": str(tmp_path / "nonexistent"),
            }
        ]

        resolver = TargetResolver()

        with pytest.raises(TargetResolutionError, match="does not exist"):
            resolver.resolve(targets_block)

    def test_resolve_default_scope(self, tmp_path: Path) -> None:
        """Test that default scope is applied when not specified."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        targets_block = [{"repo": "repo", "path": str(repo_path)}]

        resolver = TargetResolver()
        resolved = resolver.resolve(targets_block)

        assert resolved[0].suggested_paths == ["**/*"]

    def test_validate_scopes_existing_paths(self, tmp_path: Path) -> None:
        """Test scope validation with existing paths."""
        repo_path = tmp_path / "repo"
        (repo_path / "src").mkdir(parents=True)

        target = RepoTarget(
            name="repo",
            path=repo_path,
            suggested_paths=["src"],
        )

        resolver = TargetResolver()
        warnings = resolver.validate_scopes([target])

        assert len(warnings) == 0

    def test_validate_scopes_missing_paths(self, tmp_path: Path) -> None:
        """Test scope validation with missing paths."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        target = RepoTarget(
            name="repo",
            path=repo_path,
            suggested_paths=["nonexistent"],
        )

        resolver = TargetResolver()
        warnings = resolver.validate_scopes([target])

        assert len(warnings) == 1
        assert "does not exist" in warnings[0]

    def test_validate_scopes_skips_globs(self, tmp_path: Path) -> None:
        """Test that glob patterns are skipped during validation."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        target = RepoTarget(
            name="repo",
            path=repo_path,
            suggested_paths=["src/**/*.py"],  # Glob pattern
        )

        resolver = TargetResolver()
        warnings = resolver.validate_scopes([target])

        # Should not warn about glob patterns
        assert len(warnings) == 0

    def test_resolve_with_name_field(self, tmp_path: Path) -> None:
        """Test resolving target using 'name' field instead of 'repo'."""
        repo_path = tmp_path / "my-repo"
        repo_path.mkdir()

        targets_block = [
            {
                "name": "my-repo",
                "path": str(repo_path),
            }
        ]

        resolver = TargetResolver()
        resolved = resolver.resolve(targets_block)

        assert len(resolved) == 1
        assert resolved[0].name == "my-repo"
