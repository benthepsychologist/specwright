"""Tests for AIP splitting functionality."""

from pathlib import Path

from spec.governor.splitter import AIPSplitter, SplitAIP, compile_multi_repo_spec
from spec.governor.targets import RepoTarget


class TestSplitAIP:
    """Tests for SplitAIP dataclass."""

    def test_to_dict(self, tmp_path: Path) -> None:
        """Test SplitAIP serialization."""
        target = RepoTarget(
            name="my-repo",
            path=tmp_path,
            suggested_paths=["src/**"],
        )
        split_aip = SplitAIP(
            aip_id="AIP-001-my-repo-001",
            target=target,
            aip_data={"title": "Test AIP"},
            parent_spec_ref="specs/test.md",
        )

        result = split_aip.to_dict()

        assert result["aip_id"] == "AIP-001-my-repo-001"
        assert result["target"]["name"] == "my-repo"
        assert result["aip_data"] == {"title": "Test AIP"}
        assert result["parent_spec_ref"] == "specs/test.md"


class TestAIPSplitter:
    """Tests for AIPSplitter."""

    def test_split_single_target(self, tmp_path: Path) -> None:
        """Test splitting AIP for a single target."""
        target = RepoTarget(
            name="my-repo",
            path=tmp_path,
            suggested_paths=["src/**"],
        )
        aip_data = {
            "aip_id": "AIP-001",
            "title": "Test AIP",
            "plan": [{"step": 1, "action": "test"}],
        }

        splitter = AIPSplitter("specs/test.md")
        result = splitter.split(aip_data, [target])

        assert len(result) == 1
        assert result[0].aip_id == "AIP-001-my-repo-001"
        assert result[0].target == target
        assert result[0].parent_spec_ref == "specs/test.md"

    def test_split_multiple_targets(self, tmp_path: Path) -> None:
        """Test splitting AIP across multiple targets."""
        repo1 = tmp_path / "repo1"
        repo2 = tmp_path / "repo2"
        repo1.mkdir()
        repo2.mkdir()

        targets = [
            RepoTarget(name="repo1", path=repo1),
            RepoTarget(name="repo2", path=repo2),
        ]
        aip_data = {
            "aip_id": "AIP-001",
            "plan": [],
        }

        splitter = AIPSplitter("specs/multi.md")
        result = splitter.split(aip_data, targets)

        assert len(result) == 2
        assert result[0].aip_id == "AIP-001-repo1-001"
        assert result[1].aip_id == "AIP-001-repo2-002"
        assert result[0].target.name == "repo1"
        assert result[1].target.name == "repo2"

    def test_split_updates_repo_section(self, tmp_path: Path) -> None:
        """Test that split AIP has updated repo section."""
        target = RepoTarget(name="my-repo", path=tmp_path)
        aip_data = {"aip_id": "AIP-001"}

        splitter = AIPSplitter("specs/test.md")
        result = splitter.split(aip_data, [target])

        aip = result[0].aip_data
        assert aip["repo"]["path"] == str(tmp_path)
        assert aip["repo"]["name"] == "my-repo"
        assert aip["target_repo"] == "my-repo"
        assert aip["parent_spec"] == "specs/test.md"

    def test_split_adds_meta_info(self, tmp_path: Path) -> None:
        """Test that split AIP has meta information."""
        target = RepoTarget(name="my-repo", path=tmp_path)
        aip_data = {"aip_id": "AIP-001"}

        splitter = AIPSplitter("specs/test.md")
        result = splitter.split(aip_data, [target])

        aip = result[0].aip_data
        assert aip["meta"]["split_from"] == "AIP-001"
        assert aip["meta"]["split_index"] == 1
        assert "split_date" in aip["meta"]

    def test_split_applies_target_scope(self, tmp_path: Path) -> None:
        """Test that target scope is applied to plan steps (soft guidance only)."""
        target = RepoTarget(
            name="my-repo",
            path=tmp_path,
            suggested_paths=["src/**"],
        )
        aip_data = {
            "aip_id": "AIP-001",
            "plan": [
                {
                    "step": 1,
                    "scope": {},
                }
            ],
        }

        splitter = AIPSplitter("specs/test.md")
        result = splitter.split(aip_data, [target])

        step = result[0].aip_data["plan"][0]
        # v2: only suggested_paths (soft guidance), no enforced scope
        assert step["scope"]["suggested_paths"] == ["src/**"]

    def test_split_does_not_mutate_original(self, tmp_path: Path) -> None:
        """Test that splitting doesn't mutate original AIP data."""
        target = RepoTarget(name="my-repo", path=tmp_path)
        original_data = {
            "aip_id": "AIP-001",
            "plan": [{"step": 1}],
        }
        aip_data = {"aip_id": "AIP-001", "plan": [{"step": 1}]}

        splitter = AIPSplitter("specs/test.md")
        splitter.split(aip_data, [target])

        assert aip_data == original_data


class TestCompileMultiRepoSpec:
    """Tests for compile_multi_repo_spec convenience function."""

    def test_compile_multi_repo_spec(self, tmp_path: Path) -> None:
        """Test convenience function."""
        target = RepoTarget(name="my-repo", path=tmp_path)
        spec_data = {"aip_id": "AIP-001"}

        result = compile_multi_repo_spec(spec_data, [target], "specs/test.md")

        assert len(result) == 1
        assert result[0].aip_id == "AIP-001-my-repo-001"
        assert result[0].parent_spec_ref == "specs/test.md"
