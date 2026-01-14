"""Tests for Scope Checker."""

import json

import pytest

from spec.executor.contract import StepContract
from spec.executor.scope import (
    PathTraversalError,
    ScopeResult,
    ScopeViolation,
    ViolationType,
    check_scope,
    generate_policy_report,
)


def make_contract(
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
) -> StepContract:
    """Helper to create a contract with specified paths."""
    return StepContract(
        aip_id="AIP-test-2024-12-13-001",
        step_id="step-001",
        step_index=1,
        allowed_paths=allowed_paths or ["src/**", "tests/**"],
        forbidden_paths=forbidden_paths or [".git/**", "secrets/**"],
    )


class TestAllowedPathMatching:
    """Tests for allowed path matching."""

    def test_file_in_allowed_directory(self) -> None:
        """Test that files in allowed directories pass."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["src/spec/executor/scope.py"]

        result = check_scope(touched, contract)

        assert result.passed
        assert len(result.violations) == 0

    def test_file_not_in_allowed_directory(self) -> None:
        """Test that files outside allowed directories fail."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["docs/README.md"]

        result = check_scope(touched, contract)

        assert not result.passed
        assert len(result.violations) == 1
        assert result.violations[0].violation_type == ViolationType.NOT_ALLOWED

    def test_multiple_allowed_paths(self) -> None:
        """Test matching against multiple allowed path patterns."""
        contract = make_contract(allowed_paths=["src/**", "tests/**", "docs/**"])
        touched = ["src/main.py", "tests/test_main.py", "docs/guide.md"]

        result = check_scope(touched, contract)

        assert result.passed

    def test_nested_path_matching(self) -> None:
        """Test deeply nested paths match correctly."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["src/spec/executor/adapters/claude.py"]

        result = check_scope(touched, contract)

        assert result.passed

    def test_root_level_file_with_explicit_pattern(self) -> None:
        """Test root-level files match explicit patterns."""
        contract = make_contract(allowed_paths=["README.md", "*.txt"])
        touched = ["README.md", "notes.txt"]

        result = check_scope(touched, contract)

        assert result.passed

    def test_root_level_file_not_matching(self) -> None:
        """Test root-level files fail if not explicitly allowed."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["pyproject.toml"]

        result = check_scope(touched, contract)

        assert not result.passed


class TestForbiddenPathMatching:
    """Tests for forbidden path rejection."""

    def test_file_in_forbidden_directory(self) -> None:
        """Test that files in forbidden directories are rejected."""
        contract = make_contract(
            allowed_paths=["**"],  # Allow everything
            forbidden_paths=[".git/**"],
        )
        touched = [".git/config"]

        result = check_scope(touched, contract)

        assert not result.passed
        assert len(result.violations) == 1
        assert result.violations[0].violation_type == ViolationType.FORBIDDEN

    def test_forbidden_wins_over_allowed(self) -> None:
        """Test that forbidden paths override allowed paths."""
        contract = make_contract(
            allowed_paths=["src/**"],
            forbidden_paths=["src/spec/compiler/**"],
        )
        touched = ["src/spec/compiler/main.py"]

        result = check_scope(touched, contract)

        assert not result.passed
        assert result.violations[0].violation_type == ViolationType.FORBIDDEN
        assert result.violations[0].matched_pattern == "src/spec/compiler/**"

    def test_forbidden_pattern_matching(self) -> None:
        """Test various forbidden pattern matching."""
        contract = make_contract(
            allowed_paths=["**"],
            forbidden_paths=["*.lock", ".env*", "secrets/**"],
        )
        # Note: *.lock matches yarn.lock, not package-lock.json (which ends in .json)
        touched = ["yarn.lock", ".env.local", "secrets/api_key.txt"]

        result = check_scope(touched, contract)

        assert not result.passed
        assert len(result.violations) == 3

    def test_file_allowed_when_not_forbidden(self) -> None:
        """Test that files not matching forbidden patterns pass."""
        contract = make_contract(
            allowed_paths=["src/**"],
            forbidden_paths=["src/generated/**"],
        )
        touched = ["src/spec/executor/scope.py"]

        result = check_scope(touched, contract)

        assert result.passed


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_touched_list(self) -> None:
        """Test that empty touched list passes."""
        contract = make_contract()
        touched: list[str] = []

        result = check_scope(touched, contract)

        assert result.passed
        assert len(result.violations) == 0

    def test_path_normalization_leading_dot_slash(self) -> None:
        """Test that paths with ./ prefix are normalized."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["./src/main.py"]

        result = check_scope(touched, contract)

        assert result.passed

    def test_path_normalization_backslashes(self) -> None:
        """Test that Windows-style paths are normalized."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["src\\spec\\executor\\scope.py"]

        result = check_scope(touched, contract)

        assert result.passed

    def test_whitespace_in_paths(self) -> None:
        """Test that paths with whitespace are handled."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["  src/main.py  "]

        result = check_scope(touched, contract)

        assert result.passed

    def test_path_traversal_rejected(self) -> None:
        """Test that path traversal is rejected."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["../etc/passwd"]

        with pytest.raises(PathTraversalError):
            check_scope(touched, contract)

    def test_absolute_path_rejected(self) -> None:
        """Test that absolute paths are rejected."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["/etc/passwd"]

        with pytest.raises(PathTraversalError):
            check_scope(touched, contract)

    def test_hidden_traversal_rejected(self) -> None:
        """Test that hidden path traversal is rejected."""
        contract = make_contract(allowed_paths=["src/**"])
        touched = ["src/../../../etc/passwd"]

        with pytest.raises(PathTraversalError):
            check_scope(touched, contract)

    def test_multiple_violations(self) -> None:
        """Test that all violations are collected."""
        contract = make_contract(
            allowed_paths=["src/**"],
            forbidden_paths=["secrets/**"],
        )
        touched = ["docs/README.md", "secrets/api.key", "config/app.yaml"]

        result = check_scope(touched, contract)

        assert not result.passed
        assert len(result.violations) == 3

    def test_mixed_pass_and_fail(self) -> None:
        """Test with some files passing and some failing."""
        contract = make_contract(allowed_paths=["src/**", "tests/**"])
        touched = ["src/main.py", "docs/README.md", "tests/test_main.py"]

        result = check_scope(touched, contract)

        assert not result.passed
        assert len(result.violations) == 1
        assert result.violations[0].file_path == "docs/README.md"


class TestViolationMessages:
    """Tests for violation message generation."""

    def test_not_allowed_message(self) -> None:
        """Test message for files not in allowed paths."""
        violation = ScopeViolation(
            file_path="docs/README.md",
            violation_type=ViolationType.NOT_ALLOWED,
        )

        assert "not in any allowed path" in violation.message

    def test_forbidden_message(self) -> None:
        """Test message for files in forbidden paths."""
        violation = ScopeViolation(
            file_path=".git/config",
            violation_type=ViolationType.FORBIDDEN,
            matched_pattern=".git/**",
        )

        assert "forbidden pattern" in violation.message
        assert ".git/**" in violation.message


class TestPolicyReport:
    """Tests for policy report generation."""

    def test_report_structure(self) -> None:
        """Test that report has correct structure."""
        result = ScopeResult(
            passed=True,
            violations=[],
            checked_files=["src/main.py"],
        )

        report = generate_policy_report(result)

        assert "passed" in report
        assert "timestamp" in report
        assert "summary" in report
        assert "checked_files" in report
        assert "violations" in report

    def test_report_is_json_serializable(self) -> None:
        """Test that report can be serialized to JSON."""
        result = ScopeResult(
            passed=False,
            violations=[
                ScopeViolation(
                    file_path="secrets/key.txt",
                    violation_type=ViolationType.FORBIDDEN,
                    matched_pattern="secrets/**",
                )
            ],
            checked_files=["secrets/key.txt"],
        )

        report = generate_policy_report(result)

        # Should not raise
        json_str = json.dumps(report)
        assert "secrets/key.txt" in json_str

    def test_report_summary(self) -> None:
        """Test report summary fields."""
        result = ScopeResult(
            passed=False,
            violations=[
                ScopeViolation("a.txt", ViolationType.NOT_ALLOWED),
                ScopeViolation("b.txt", ViolationType.FORBIDDEN, "secrets/**"),
            ],
            checked_files=["a.txt", "b.txt", "src/c.py"],
        )

        report = generate_policy_report(result)

        assert report["summary"]["total_files"] == 3
        assert report["summary"]["violations_count"] == 2

    def test_violation_details_in_report(self) -> None:
        """Test that violation details are included in report."""
        result = ScopeResult(
            passed=False,
            violations=[
                ScopeViolation(
                    file_path=".git/config",
                    violation_type=ViolationType.FORBIDDEN,
                    matched_pattern=".git/**",
                )
            ],
            checked_files=[".git/config"],
        )

        report = generate_policy_report(result)

        assert len(report["violations"]) == 1
        v = report["violations"][0]
        assert v["file_path"] == ".git/config"
        assert v["violation_type"] == "forbidden"
        assert v["matched_pattern"] == ".git/**"
        assert "message" in v

    def test_report_with_touched_metadata(self) -> None:
        """Test that touched file metadata is included in report summary."""
        result = ScopeResult(
            passed=True,
            violations=[],
            checked_files=["src/main.py", "src/utils.py", "config/new.yaml"],
        )

        # Metadata from runner's _get_touched_files
        touched_metadata = {
            "touched_total": 3,
            "touched_tracked": 2,  # Modified existing files
            "touched_untracked": 1,  # New file created by patch
            "touched_excluded_artifacts": 5,  # Filtered out runs/ artifacts
        }

        report = generate_policy_report(result, touched_metadata)

        # Verify metadata is in summary
        assert report["summary"]["total_files"] == 3
        assert report["summary"]["touched_tracked"] == 2
        assert report["summary"]["touched_untracked"] == 1
        assert report["summary"]["touched_excluded_artifacts"] == 5

    def test_report_without_touched_metadata(self) -> None:
        """Test that report works without metadata (backwards compatible)."""
        result = ScopeResult(
            passed=True,
            violations=[],
            checked_files=["src/main.py"],
        )

        # No metadata provided
        report = generate_policy_report(result)

        # Should still have basic summary
        assert report["summary"]["total_files"] == 1
        assert "touched_tracked" not in report["summary"]
        assert "touched_untracked" not in report["summary"]


class TestGlobPatterns:
    """Tests for specific glob pattern matching."""

    def test_double_star_at_end(self) -> None:
        """Test src/** matches all files under src/."""
        contract = make_contract(allowed_paths=["src/**"])

        assert check_scope(["src/a.py"], contract).passed
        assert check_scope(["src/foo/b.py"], contract).passed
        assert check_scope(["src/foo/bar/c.py"], contract).passed

    def test_double_star_with_extension(self) -> None:
        """Test **/*.py matches all Python files."""
        contract = make_contract(allowed_paths=["**/*.py"])

        assert check_scope(["main.py"], contract).passed
        assert check_scope(["src/main.py"], contract).passed
        assert check_scope(["src/spec/main.py"], contract).passed

    def test_single_star_in_directory(self) -> None:
        """Test patterns like src/*/config.py."""
        contract = make_contract(allowed_paths=["src/*/config.py"])

        assert check_scope(["src/app/config.py"], contract).passed
        assert not check_scope(["src/app/foo/config.py"], contract).passed

    def test_question_mark_wildcard(self) -> None:
        """Test ? matches single character."""
        contract = make_contract(allowed_paths=["test?.py"])

        assert check_scope(["test1.py"], contract).passed
        assert check_scope(["testX.py"], contract).passed
        assert not check_scope(["test12.py"], contract).passed

    def test_extension_glob(self) -> None:
        """Test *.lock matches lock files."""
        contract = make_contract(
            allowed_paths=["**"],
            forbidden_paths=["*.lock"],
        )

        # *.lock matches files ending in .lock, not .json
        assert check_scope(["package-lock.json"], contract).passed  # Ends in .json, not .lock
        assert not check_scope(["yarn.lock"], contract).passed  # Ends in .lock
        assert not check_scope(["poetry.lock"], contract).passed  # Ends in .lock
        assert check_scope(["lockfile.txt"], contract).passed  # Ends in .txt

    def test_env_pattern(self) -> None:
        """Test .env* matches environment files."""
        contract = make_contract(
            allowed_paths=["**"],
            forbidden_paths=[".env*"],
        )

        assert not check_scope([".env"], contract).passed
        assert not check_scope([".env.local"], contract).passed
        assert not check_scope([".envrc"], contract).passed
        assert check_scope(["env.py"], contract).passed


class TestAbsolutePathPatterns:
    """Tests for absolute path patterns in allowed_paths (multi-repo support)."""

    def test_absolute_allowed_path_with_repo_root(self) -> None:
        """Test that absolute allowed paths work when repo_root is provided."""
        from pathlib import Path

        contract = make_contract(
            allowed_paths=["/home/developer/.local/registry/schemas/**"],
        )
        # Touched file is relative, will be converted to /workspace/test/schemas/foo.json
        touched = ["schemas/foo.json"]
        repo_root = Path("/home/developer/.local/registry")

        result = check_scope(touched, contract, repo_root=repo_root)

        assert result.passed
        assert len(result.violations) == 0

    def test_absolute_allowed_path_mismatch(self) -> None:
        """Test that absolute paths don't match files in different repos."""
        from pathlib import Path

        contract = make_contract(
            allowed_paths=["/home/developer/.local/registry/schemas/**"],
        )
        # File is in /workspace/life, not /home/developer/.local/registry
        touched = ["schemas/foo.json"]
        repo_root = Path("/workspace/life")

        result = check_scope(touched, contract, repo_root=repo_root)

        assert not result.passed
        assert len(result.violations) == 1
        assert result.violations[0].violation_type == ViolationType.NOT_ALLOWED

    def test_mixed_absolute_and_relative_allowed_paths(self) -> None:
        """Test that mixed absolute and relative patterns work together."""
        from pathlib import Path

        contract = make_contract(
            allowed_paths=[
                "src/**",  # Relative pattern
                "/external/registry/schemas/**",  # Absolute pattern
            ],
        )
        repo_root = Path("/workspace/myrepo")

        # Relative path matches relative pattern
        result1 = check_scope(["src/main.py"], contract, repo_root=repo_root)
        assert result1.passed

        # File not matching any pattern
        result2 = check_scope(["docs/readme.md"], contract, repo_root=repo_root)
        assert not result2.passed

    def test_absolute_allowed_path_without_repo_root(self) -> None:
        """Test that absolute patterns don't match without repo_root."""
        contract = make_contract(
            allowed_paths=["/home/developer/.local/registry/schemas/**"],
        )
        touched = ["schemas/foo.json"]

        # Without repo_root, absolute patterns can't be matched
        result = check_scope(touched, contract, repo_root=None)

        assert not result.passed  # No match possible without repo_root
