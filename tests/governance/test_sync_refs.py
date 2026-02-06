"""Tests for agent.sync_refs callable."""

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from spec.governance.sync_refs import (
    AGENT_REF_TARGETS,
    _extract_context,
    _format_consumers,
    _format_content,
    _format_markdown,
    _get_markers,
    _merge_content,
    sync_refs,
)


class TestAgentRefTargets:
    """Test AGENT_REF_TARGETS configuration."""

    def test_all_agents_defined(self) -> None:
        """All required agents should be in AGENT_REF_TARGETS."""
        required = {"claude-code", "cursor", "aider", "roo-code", "goose", "opencode"}
        assert required <= set(AGENT_REF_TARGETS.keys())

    def test_target_format(self) -> None:
        """Each target should have (filename, format_type) tuple."""
        valid_formats = {"markdown", "hash", "aider"}
        for agent, target in AGENT_REF_TARGETS.items():
            assert isinstance(target, tuple), f"{agent} target is not a tuple"
            assert len(target) == 2, f"{agent} target should have 2 elements"
            filename, fmt = target
            assert isinstance(filename, str), f"{agent} filename should be str"
            assert fmt in valid_formats, f"{agent} format '{fmt}' not in {valid_formats}"


class TestExtractContext:
    """Test _extract_context function."""

    def test_full_build(self) -> None:
        """Should extract all context sections."""
        build = {
            "kernel": {
                "description": "Test project",
                "invariants": ["Rule 1", "Rule 2"],
            },
            "boundaries": [{"name": "cli", "type": "inbound"}],
            "decisions": [{"id": "adr-001", "title": "Test decision"}],
        }

        context = _extract_context(build)
        assert context["description"] == "Test project"
        assert context["invariants"] == ["Rule 1", "Rule 2"]
        assert len(context["boundaries"]) == 1
        assert len(context["decisions"]) == 1

    def test_empty_build(self) -> None:
        """Should handle empty/missing sections gracefully."""
        context = _extract_context({})
        assert context["description"] == ""
        assert context["invariants"] == []
        assert context["boundaries"] == []
        assert context["decisions"] == []

    def test_partial_kernel(self) -> None:
        """Should handle partial kernel section."""
        build = {
            "kernel": {
                "description": "Only description",
            },
        }
        context = _extract_context(build)
        assert context["description"] == "Only description"
        assert context["invariants"] == []


class TestFormatConsumers:
    """Test _format_consumers helper."""

    def test_list_of_strings(self) -> None:
        """Should join list with commas."""
        assert _format_consumers(["a", "b", "c"]) == "a, b, c"

    def test_single_string(self) -> None:
        """Should return string as-is."""
        assert _format_consumers("developers") == "developers"

    def test_list_with_non_strings(self) -> None:
        """Should convert non-strings to strings."""
        assert _format_consumers([1, 2, 3]) == "1, 2, 3"

    def test_empty_list(self) -> None:
        """Should handle empty list."""
        assert _format_consumers([]) == ""


class TestFormatMarkdown:
    """Test _format_markdown function."""

    def test_formats_all_sections(self) -> None:
        """Should format all context sections."""
        context = {
            "description": "Test project description",
            "invariants": ["Never break API"],
            "boundaries": [{"name": "api", "type": "inbound", "contract": "REST"}],
            "decisions": [{"id": "adr-001", "title": "Use REST", "status": "accepted"}],
        }

        result = _format_markdown(context, "myproject")

        assert "# Myproject Project Context" in result
        assert "## Description" in result
        assert "Test project description" in result
        assert "## Invariants" in result
        assert "- Never break API" in result
        assert "## Boundaries" in result
        assert "### api" in result
        assert "## Architecture Decisions" in result
        assert "### adr-001: Use REST" in result

    def test_empty_context(self) -> None:
        """Should handle empty context gracefully."""
        context = {"description": "", "invariants": [], "boundaries": [], "decisions": []}
        result = _format_markdown(context, "empty")

        # Should still have header
        assert "# Empty Project Context" in result
        # Should not have empty section headers
        assert "## Invariants" not in result

    def test_consumers_as_string(self) -> None:
        """Should handle consumers as string (not list)."""
        context = {
            "description": "",
            "invariants": [],
            "boundaries": [{"name": "api", "consumers": "developers"}],
            "decisions": [],
        }
        result = _format_markdown(context, "test")
        assert "- Consumers: developers" in result

    def test_consumers_as_list(self) -> None:
        """Should handle consumers as list."""
        context = {
            "description": "",
            "invariants": [],
            "boundaries": [{"name": "api", "consumers": ["devs", "agents"]}],
            "decisions": [],
        }
        result = _format_markdown(context, "test")
        assert "- Consumers: devs, agents" in result


class TestFormatContent:
    """Test _format_content dispatcher."""

    def test_markdown_format(self) -> None:
        """Should return markdown for markdown format."""
        context = {"description": "Test", "invariants": [], "boundaries": [], "decisions": []}
        result = _format_content(context, "proj", "markdown")
        assert "# Proj Project Context" in result

    def test_hash_format(self) -> None:
        """Hash format should use markdown (readable as plain text)."""
        context = {"description": "Test", "invariants": [], "boundaries": [], "decisions": []}
        result = _format_content(context, "proj", "hash")
        assert "# Proj Project Context" in result

    def test_aider_format(self) -> None:
        """Aider format should comment out markdown."""
        context = {"description": "Test desc", "invariants": [], "boundaries": [], "decisions": []}
        result = _format_content(context, "proj", "aider")

        # Should have comment prefix on content lines
        assert "# Project context from build.yaml" in result
        # Markdown should be commented
        lines = result.split("\n")
        # All non-empty lines should start with #
        for line in lines:
            assert line.startswith("#") or line == "", f"Line not commented: {line}"


class TestGetMarkers:
    """Test _get_markers function."""

    def test_markdown_style(self) -> None:
        """Should return HTML comment markers for markdown."""
        begin, end = _get_markers("myproject", "markdown")
        assert begin == "<!-- BEGIN SYNCED: myproject -->"
        assert end == "<!-- END SYNCED: myproject -->"

    def test_hash_style(self) -> None:
        """Should return hash comment markers for hash format."""
        begin, end = _get_markers("myproject", "hash")
        assert begin == "# BEGIN SYNCED: myproject"
        assert end == "# END SYNCED: myproject"

    def test_aider_style(self) -> None:
        """Should return hash comment markers for aider format."""
        begin, end = _get_markers("myproject", "aider")
        assert begin == "# BEGIN SYNCED: myproject"
        assert end == "# END SYNCED: myproject"


class TestMergeContent:
    """Test _merge_content function."""

    def test_empty_file(self) -> None:
        """Should create new file with synced block."""
        result = _merge_content(
            "",
            "New content",
            "<!-- BEGIN SYNCED: proj -->",
            "<!-- END SYNCED: proj -->",
        )
        expected = dedent("""\
            <!-- BEGIN SYNCED: proj -->
            New content
            <!-- END SYNCED: proj -->
        """)
        assert result == expected

    def test_no_markers(self) -> None:
        """Should append synced block when no markers exist."""
        existing = "# My Custom Header\n\nSome user content.\n"
        result = _merge_content(
            existing,
            "Synced content",
            "<!-- BEGIN -->",
            "<!-- END -->",
        )

        # Should preserve existing content
        assert "# My Custom Header" in result
        assert "Some user content" in result
        # Should have synced block at end
        assert result.endswith("<!-- END -->\n")

    def test_replace_existing_markers(self) -> None:
        """Should replace content between existing markers."""
        existing = dedent("""\
            # User Header

            <!-- BEGIN SYNCED: proj -->
            Old synced content
            <!-- END SYNCED: proj -->

            # User Footer
        """)

        result = _merge_content(
            existing,
            "New synced content",
            "<!-- BEGIN SYNCED: proj -->",
            "<!-- END SYNCED: proj -->",
        )

        assert "# User Header" in result
        assert "New synced content" in result
        assert "Old synced content" not in result
        assert "# User Footer" in result

    def test_malformed_markers_end_before_begin(self) -> None:
        """Should append when end marker comes before begin."""
        existing = dedent("""\
            <!-- END SYNCED: proj -->
            Content
            <!-- BEGIN SYNCED: proj -->
        """)

        result = _merge_content(
            existing,
            "New content",
            "<!-- BEGIN SYNCED: proj -->",
            "<!-- END SYNCED: proj -->",
        )

        # Should append at end since markers are invalid
        assert result.strip().endswith("<!-- END SYNCED: proj -->")

    def test_idempotent(self) -> None:
        """Running twice should produce identical results."""
        existing = "# Header\n"
        content = "Synced data"
        begin = "<!-- BEGIN SYNCED: test -->"
        end = "<!-- END SYNCED: test -->"

        result1 = _merge_content(existing, content, begin, end)
        result2 = _merge_content(result1, content, begin, end)

        assert result1 == result2


class TestSyncRefs:
    """Test sync_refs callable."""

    @pytest.fixture
    def mock_governor_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Create a mock governor root with project build.yaml."""
        gov_root = tmp_path / "governor"
        project_dir = gov_root / "projects" / "testproj"
        project_dir.mkdir(parents=True)

        build = {
            "kernel": {
                "description": "Test project for testing",
                "invariants": ["Always test"],
            },
            "boundaries": [{"name": "api", "type": "inbound", "contract": "REST"}],
            "decisions": [{"id": "adr-001", "title": "Test decision", "status": "accepted"}],
        }
        (project_dir / "testproj.build.yaml").write_text(yaml.dump(build))

        # Patch _governor_root
        def mock_root():
            return gov_root

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", mock_root)
        return gov_root

    def test_basic_sync_single_agent(self, tmp_path: Path, mock_governor_root: Path) -> None:
        """Should sync build.yaml context to single agent reference file."""
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj"},
            repo_path=repo,
        )

        assert result["passed"] is True
        assert result["data"]["project"] == "testproj"
        assert result["data"]["agents"] == ["claude-code"]
        assert result["data"]["synced_count"] == 1

        # Check file was created
        target = repo / "CLAUDE.md"
        assert target.exists()
        content = target.read_text()
        assert "<!-- BEGIN SYNCED: testproj -->" in content
        assert "Test project for testing" in content
        assert "<!-- END SYNCED: testproj -->" in content

    def test_sync_multiple_agents(self, tmp_path: Path, mock_governor_root: Path) -> None:
        """Should sync to multiple agents in one call."""
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={"agents": ["claude-code", "goose", "cursor"], "project": "testproj"},
            repo_path=repo,
        )

        assert result["passed"] is True
        assert result["data"]["synced_count"] == 3

        # Check all files were created
        assert (repo / "CLAUDE.md").exists()
        assert (repo / ".goosehints").exists()
        assert (repo / ".cursorrules").exists()

    def test_goose_uses_hash_markers(self, tmp_path: Path, mock_governor_root: Path) -> None:
        """Should use hash comments for goose."""
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={"agents": ["goose"], "project": "testproj"},
            repo_path=repo,
        )

        assert result["passed"] is True
        target = repo / ".goosehints"
        assert target.exists()
        content = target.read_text()
        assert "# BEGIN SYNCED: testproj" in content
        assert "# END SYNCED: testproj" in content

    def test_aider_outputs_commented_markdown(
        self, tmp_path: Path, mock_governor_root: Path
    ) -> None:
        """Aider output should be markdown as comments."""
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={"agents": ["aider"], "project": "testproj"},
            repo_path=repo,
        )

        assert result["passed"] is True
        target = repo / ".aider.conf.yml"
        assert target.exists()

        content = target.read_text()
        # Should have markers
        assert "# BEGIN SYNCED: testproj" in content
        assert "# END SYNCED: testproj" in content
        # Content should be commented
        assert "# Project context from build.yaml" in content

    def test_preserves_existing_content(self, tmp_path: Path, mock_governor_root: Path) -> None:
        """Should preserve user content outside markers."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Create existing file with user content
        target = repo / "CLAUDE.md"
        target.write_text("# My Custom Instructions\n\nDo things my way.\n")

        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj"},
            repo_path=repo,
        )

        assert result["passed"] is True
        content = target.read_text()
        assert "# My Custom Instructions" in content
        assert "Do things my way" in content
        assert "Test project for testing" in content

    def test_updates_existing_synced_section(
        self, tmp_path: Path, mock_governor_root: Path
    ) -> None:
        """Should update existing synced section without duplicating."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Create file with existing synced section
        target = repo / "CLAUDE.md"
        target.write_text(dedent("""\
            # Header

            <!-- BEGIN SYNCED: testproj -->
            Old content
            <!-- END SYNCED: testproj -->

            # Footer
        """))

        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj"},
            repo_path=repo,
        )

        assert result["passed"] is True
        content = target.read_text()

        # Should have only one synced section
        assert content.count("<!-- BEGIN SYNCED: testproj -->") == 1
        assert content.count("<!-- END SYNCED: testproj -->") == 1

        # Should have new content, not old
        assert "Test project for testing" in content
        assert "Old content" not in content

        # Should preserve user sections
        assert "# Header" in content
        assert "# Footer" in content

    def test_missing_agents(self, tmp_path: Path) -> None:
        """Should fail when agents not provided."""
        result = sync_refs(
            payload={"project": "testproj"},
            repo_path=tmp_path,
        )

        assert result["passed"] is False
        assert "agents" in result["data"]["error"]

    def test_agents_not_list(self, tmp_path: Path) -> None:
        """Should fail when agents is not a list."""
        result = sync_refs(
            payload={"agents": "claude-code", "project": "testproj"},
            repo_path=tmp_path,
        )

        assert result["passed"] is False
        assert "list" in result["data"]["error"]

    def test_agents_empty_list(self, tmp_path: Path) -> None:
        """Should fail when agents is empty list."""
        result = sync_refs(
            payload={"agents": [], "project": "testproj"},
            repo_path=tmp_path,
        )

        assert result["passed"] is False
        assert "empty" in result["data"]["error"]

    def test_missing_project(self, tmp_path: Path) -> None:
        """Should fail when project not provided."""
        result = sync_refs(
            payload={"agents": ["claude-code"]},
            repo_path=tmp_path,
        )

        assert result["passed"] is False
        assert "project" in result["data"]["error"]

    def test_unknown_agent(self, tmp_path: Path) -> None:
        """Should fail for unknown agent type."""
        result = sync_refs(
            payload={"agents": ["unknown-agent"], "project": "testproj"},
            repo_path=tmp_path,
        )

        assert result["passed"] is False
        assert "Unknown agents" in result["data"]["error"]
        assert "available" in result["data"]

    def test_partial_unknown_agents(self, tmp_path: Path) -> None:
        """Should fail if any agent is unknown (validate upfront)."""
        result = sync_refs(
            payload={"agents": ["claude-code", "unknown"], "project": "testproj"},
            repo_path=tmp_path,
        )

        assert result["passed"] is False
        assert "unknown" in str(result["data"]["error"])

    def test_missing_build_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should fail when build.yaml doesn't exist."""
        gov_root = tmp_path / "governor"
        gov_root.mkdir()

        def mock_root():
            return gov_root

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", mock_root)

        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "nonexistent"},
            repo_path=tmp_path,
        )

        assert result["passed"] is False
        assert "build.yaml" in result["data"]["error"]

    def test_roo_code_creates_nested_directory(
        self, tmp_path: Path, mock_governor_root: Path
    ) -> None:
        """Should create nested directories for .roo/rules.md."""
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={"agents": ["roo-code"], "project": "testproj"},
            repo_path=repo,
        )

        assert result["passed"] is True
        target = repo / ".roo" / "rules.md"
        assert target.exists()

    def test_summary_no_emoji(self, tmp_path: Path, mock_governor_root: Path) -> None:
        """Summary should not contain emoji (per CLAUDE.md guidelines)."""
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={"agents": ["claude-code", "goose"], "project": "testproj"},
            repo_path=repo,
        )

        summary = result["summary"]
        # Should use [OK] not checkmark emoji
        assert "[OK]" in summary
        assert "✓" not in summary
        assert "✗" not in summary

    def test_summary_includes_all_agents(
        self, tmp_path: Path, mock_governor_root: Path
    ) -> None:
        """Summary should list all synced agents."""
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={"agents": ["claude-code", "goose"], "project": "testproj"},
            repo_path=repo,
        )

        summary = result["summary"]
        assert "claude-code" in summary
        assert "goose" in summary
        assert "2/2" in summary


class TestSyncRefsRegistration:
    """Test that agent.sync_refs is properly registered."""

    def test_callable_registered(self) -> None:
        """agent.sync_refs should be in the callable registry."""
        from spec.executor.backends.python import list_callables
        from spec.executor.backends.registry import _auto_register

        _auto_register()
        names = list_callables()
        assert "agent.sync_refs" in names

    def test_get_callable(self) -> None:
        """Should be able to retrieve the callable."""
        from spec.executor.backends.python import get_callable
        from spec.executor.backends.registry import _auto_register

        _auto_register()
        fn = get_callable("agent.sync_refs")
        assert fn is not None
        assert callable(fn)
