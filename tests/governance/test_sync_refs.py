"""Tests for agent.sync_refs callable."""

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from spec.governance.sync_refs import (
    AGENT_REF_TARGETS,
    AGENT_SKILLS_PATHS,
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


class TestAgentSkillsPaths:
    """Test AGENT_SKILLS_PATHS configuration."""

    def test_expected_agents_defined(self) -> None:
        """Skill-discovery mappings should cover known native paths."""
        assert AGENT_SKILLS_PATHS["claude-code"] == ".claude/skills"
        assert AGENT_SKILLS_PATHS["copilot"] == ".claude/skills"
        assert AGENT_SKILLS_PATHS["cursor"] == ".claude/skills"
        assert AGENT_SKILLS_PATHS["codex"] == ".agents/skills"


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
        skills_dir = gov_root / "skills"
        project_dir.mkdir(parents=True)
        skills_dir.mkdir(parents=True)

        build = {
            "kernel": {
                "description": "Test project for testing",
                "invariants": ["Always test"],
            },
            "boundaries": [{"name": "api", "type": "inbound", "contract": "REST"}],
            "decisions": [{"id": "adr-001", "title": "Test decision", "status": "accepted"}],
        }
        (project_dir / "testproj.build.yaml").write_text(yaml.dump(build))
        (skills_dir / "skills.yaml").write_text(
            yaml.safe_dump(
                {
                    "global": ["global-skill"],
                    "skills": [
                        {"name": "global-skill", "status": "active"},
                        {"name": "project-skill", "status": "active"},
                        {"name": "spec-skill", "status": "active"},
                    ],
                },
                sort_keys=False,
            )
        )
        for skill in ["global-skill", "project-skill", "spec-skill"]:
            skill_path = skills_dir / skill
            (skill_path / "references").mkdir(parents=True)
            (skill_path / "scripts").mkdir(parents=True)
            (skill_path / "SKILL.md").write_text(f"# {skill}\n")
            (skill_path / "references" / "ref.md").write_text("reference")
            (skill_path / "scripts" / "run.sh").write_text("#!/bin/sh\necho ok\n")

        # Patch _governor_root
        def mock_root():
            return gov_root

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", mock_root)
        return gov_root

    @pytest.fixture
    def mock_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Patch home dir for global skills projection assertions."""
        home = tmp_path / "home"
        home.mkdir(parents=True)

        def mock_home_dir() -> Path:
            return home

        monkeypatch.setattr("spec.governance.sync_refs._home_dir", mock_home_dir)
        return home

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
        """Should succeed gracefully when build.yaml doesn't exist."""
        gov_root = tmp_path / "governor"
        (gov_root / "skills").mkdir(parents=True)

        def mock_root():
            return gov_root

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", mock_root)

        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "nonexistent"},
            repo_path=tmp_path,
        )

        assert result["passed"] is True
        assert result["data"]["build_skipped"] is True
        assert result["data"]["synced_count"] == 1
        assert result["data"]["context_sections"] == []
        assert "No build.yaml" in result["data"]["skills_warnings"][0]
        assert (tmp_path / "CLAUDE.md").exists()
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "<!-- BEGIN SYNCED: nonexistent -->\n\n<!-- END SYNCED: nonexistent -->" in content

    def test_sync_no_build_yaml_with_spec(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spec block should still be injected when build.yaml is missing."""
        gov_root = tmp_path / "governor"
        (gov_root / "skills").mkdir(parents=True)

        def mock_root() -> Path:
            return gov_root

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", mock_root)
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "nonexistent",
                "spec_id": "s-1",
                "spec_md": "---\ngoal: test\n---\n\n## Acceptance Criteria\n- done",
            },
            repo_path=repo,
        )

        assert result["passed"] is True
        content = (repo / "CLAUDE.md").read_text()
        assert "<!-- BEGIN SYNCED: SPEC: s-1 -->" in content
        assert "## Acceptance Criteria" in content

    def test_sync_spec_stub_targets_requested_agent_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spec stubs should be injected into the selected agent reference file."""
        gov_root = tmp_path / "governor"
        (gov_root / "skills").mkdir(parents=True)

        def mock_root() -> Path:
            return gov_root

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", mock_root)
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={
                "agents": ["copilot"],
                "project": "nonexistent",
                "spec_id": "s-2",
                "spec_md": "---\ngoal: test\n---\n\n## Acceptance Criteria\n- done",
            },
            repo_path=repo,
        )

        assert result["passed"] is True
        assert (repo / "COPILOT.md").exists()
        assert "BEGIN SYNCED: SPEC: s-2" in (repo / "COPILOT.md").read_text()

    def test_governor_lookup_failure_still_syncs_spec_and_explicit_skill(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Governor lookup failures should degrade to spec/explicit-skill sync, not fail."""
        from spec.governor.locator import GovernorNotFoundError

        def broken_root() -> Path:
            raise GovernorNotFoundError(["default: ~/.local/local-governor"])

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", broken_root)

        direct_skill = tmp_path / "direct-skill" / "SKILL.md"
        direct_skill.parent.mkdir(parents=True)
        direct_skill.write_text("# direct-skill\n")

        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "missing",
                "spec_id": "s-3",
                "spec_md": "---\ngoal: test\n---\n\n## Acceptance Criteria\n- done",
                "skill": str(direct_skill),
                "skills": ["named-skill"],
            },
            repo_path=repo,
        )

        assert result["passed"] is True
        assert (repo / "CLAUDE.md").exists()
        assert "BEGIN SYNCED: SPEC: s-3" in (repo / "CLAUDE.md").read_text()
        assert (repo / ".claude" / "skills" / "direct-skill" / "SKILL.md").exists()
        assert any(
            "Governor unavailable" in w or "Governor root lookup failed" in w
            for w in result["data"]["skills_warnings"]
        )

    def test_sync_no_build_yaml_with_skills(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_home: Path
    ) -> None:
        """Missing build.yaml should not block skills projection."""
        gov_root = tmp_path / "governor"
        skills_dir = gov_root / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "skills.yaml").write_text(
            yaml.safe_dump(
                {"skills": [{"name": "spec-skill", "status": "active"}]},
                sort_keys=False,
            )
        )
        (skills_dir / "spec-skill").mkdir()
        (skills_dir / "spec-skill" / "SKILL.md").write_text("# spec-skill")

        def mock_root() -> Path:
            return gov_root

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", mock_root)
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={
                "agents": ["claude-code", "codex"],
                "project": "nonexistent",
                "skills": ["spec-skill"],
            },
            repo_path=repo,
        )

        assert result["passed"] is True
        assert "spec-skill" in result["data"]["skills_projected"]
        assert (repo / ".claude" / "skills" / "spec-skill" / "SKILL.md").exists()
        assert (repo / ".agents" / "skills" / "spec-skill" / "SKILL.md").exists()

    def test_skills_projected_to_claude_dir(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Skills should project to .claude/skills for claude-style agents."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj", "skills": ["spec-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert (repo / ".claude" / "skills" / "spec-skill" / "SKILL.md").exists()

    def test_skills_projected_to_agents_dir(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Skills should project to .agents/skills for codex."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["codex"], "project": "testproj", "skills": ["spec-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert (repo / ".agents" / "skills" / "spec-skill" / "SKILL.md").exists()

    def test_skills_full_directory_copied(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Projection should copy full skill directory tree."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj", "skills": ["spec-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        target = repo / ".claude" / "skills" / "spec-skill"
        assert (target / "SKILL.md").exists()
        assert (target / "references" / "ref.md").exists()
        assert (target / "scripts" / "run.sh").exists()

    def test_skills_global_loading(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Global skills from skills.yaml should always project."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj"},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert "global-skill" in result["data"]["skills_projected"]
        assert (repo / ".claude" / "skills" / "global-skill" / "SKILL.md").exists()
        assert (mock_home / ".claude" / "skills" / "global-skill" / "SKILL.md").exists()

    def test_skills_project_loading(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Project skills in build.yaml should project."""
        project_yaml = (
            mock_governor_root / "projects" / "testproj" / "testproj.build.yaml"
        )
        build = yaml.safe_load(project_yaml.read_text())
        build["skills"] = ["project-skill"]
        project_yaml.write_text(yaml.safe_dump(build, sort_keys=False))

        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj"},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert "project-skill" in result["data"]["skills_projected"]

    def test_skills_spec_loading(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Spec-level skills in payload should project."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj", "skills": ["spec-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert "spec-skill" in result["data"]["skills_projected"]

    def test_skill_filepath_projects_without_registry_entry(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Explicit skill paths should project even when not registered in skills.yaml."""
        direct_skill = tmp_path / "direct-skill" / "SKILL.md"
        direct_skill.parent.mkdir(parents=True)
        direct_skill.write_text("# direct-skill\n")
        (direct_skill.parent / "references").mkdir()
        (direct_skill.parent / "references" / "ref.md").write_text("reference")

        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "testproj",
                "skill": str(direct_skill),
            },
            repo_path=repo,
        )

        assert result["passed"] is True
        assert "direct-skill" in result["data"]["skills_projected"]
        assert (repo / ".claude" / "skills" / "direct-skill" / "SKILL.md").exists()
        assert (repo / ".claude" / "skills" / "direct-skill" / "references" / "ref.md").exists()

    def test_skill_filepath_missing_warns(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Missing explicit skill paths should warn and continue."""
        repo = tmp_path / "repo"
        repo.mkdir()
        missing_skill = tmp_path / "missing-skill" / "SKILL.md"

        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "testproj",
                "skill": str(missing_skill),
            },
            repo_path=repo,
        )

        assert result["passed"] is True
        assert "missing-skill" in result["data"]["skills_skipped"]
        assert any("Skill path not found" in w for w in result["data"]["skills_warnings"])

    def test_skills_dedup(self, tmp_path: Path, mock_governor_root: Path, mock_home: Path) -> None:
        """Same skill from multiple tiers should project once."""
        project_yaml = (
            mock_governor_root / "projects" / "testproj" / "testproj.build.yaml"
        )
        build = yaml.safe_load(project_yaml.read_text())
        build["skills"] = ["spec-skill"]
        project_yaml.write_text(yaml.safe_dump(build, sort_keys=False))

        skills_manifest_path = mock_governor_root / "skills" / "skills.yaml"
        manifest = yaml.safe_load(skills_manifest_path.read_text())
        manifest["global"] = ["spec-skill"]
        skills_manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj", "skills": ["spec-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert result["data"]["skills_projected"].count("spec-skill") == 1

    def test_skills_missing_dir_warns(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Missing skill directory should warn and continue."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj", "skills": ["missing-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert "missing-skill" in result["data"]["skills_skipped"]
        assert any("missing-skill" in w for w in result["data"]["skills_warnings"])

    def test_skills_retired_skipped(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Retired skills should be skipped."""
        skills_manifest_path = mock_governor_root / "skills" / "skills.yaml"
        manifest = yaml.safe_load(skills_manifest_path.read_text())
        manifest["skills"].append({"name": "retired-skill", "status": "retired"})
        skills_manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
        (mock_governor_root / "skills" / "retired-skill").mkdir()
        (mock_governor_root / "skills" / "retired-skill" / "SKILL.md").write_text("# retired")

        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj", "skills": ["retired-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert "retired-skill" in result["data"]["skills_skipped"]
        assert any("status 'retired'" in w for w in result["data"]["skills_warnings"])

    def test_skills_draft_skipped(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Draft skills should be skipped by registry status check."""
        skills_manifest_path = mock_governor_root / "skills" / "skills.yaml"
        manifest = yaml.safe_load(skills_manifest_path.read_text())
        manifest["skills"].append({"name": "draft-skill", "status": "draft"})
        skills_manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj", "skills": ["draft-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert "draft-skill" in result["data"]["skills_skipped"]
        assert any("status 'draft'" in w for w in result["data"]["skills_warnings"])
        assert all("directory not found" not in w for w in result["data"]["skills_warnings"])

    def test_skills_projection_idempotent(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Running projection twice should be idempotent."""
        repo = tmp_path / "repo"
        repo.mkdir()
        payload = {"agents": ["claude-code"], "project": "testproj", "skills": ["spec-skill"]}
        first = sync_refs(payload=payload, repo_path=repo)
        second = sync_refs(payload=payload, repo_path=repo)
        assert first["passed"] is True
        assert second["passed"] is True
        path = repo / ".claude" / "skills" / "spec-skill" / "SKILL.md"
        assert path.exists()
        assert path.read_text() == "# spec-skill\n"

    def test_skills_no_skills_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_home: Path
    ) -> None:
        """Missing skills.yaml should not fail projection."""
        gov_root = tmp_path / "governor"
        project_dir = gov_root / "projects" / "testproj"
        project_dir.mkdir(parents=True)
        (project_dir / "testproj.build.yaml").write_text(yaml.safe_dump({}))
        (gov_root / "skills" / "spec-skill").mkdir(parents=True)
        (gov_root / "skills" / "spec-skill" / "SKILL.md").write_text("# spec-skill")

        def mock_root() -> Path:
            return gov_root

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", mock_root)

        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj", "skills": ["spec-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert "spec-skill" in result["data"]["skills_projected"]

    def test_skills_empty_resolution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_home: Path
    ) -> None:
        """No skills at any tier should be a no-op."""
        gov_root = tmp_path / "governor"
        project_dir = gov_root / "projects" / "testproj"
        project_dir.mkdir(parents=True)
        (project_dir / "testproj.build.yaml").write_text(yaml.safe_dump({}))
        (gov_root / "skills").mkdir(parents=True)
        (gov_root / "skills" / "skills.yaml").write_text(yaml.safe_dump({"skills": []}))

        def mock_root() -> Path:
            return gov_root

        monkeypatch.setattr("spec.governance.sync_refs._governor_root", mock_root)
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj"},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert result["data"]["skills_projected"] == []
        assert result["data"]["skills_skipped"] == []

    def test_existing_synced_content_preserved(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Existing SYNCED and SPEC blocks should update in-place without duplication."""
        repo = tmp_path / "repo"
        repo.mkdir()
        claude = repo / "CLAUDE.md"
        claude.write_text(
            dedent(
                """\
                # Header
                <!-- BEGIN SYNCED: testproj -->
                old synced
                <!-- END SYNCED: testproj -->
                <!-- BEGIN SYNCED: SPEC: s-1 -->
                old spec
                <!-- END SYNCED: SPEC: s-1 -->
                # Footer
                """
            )
        )

        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "testproj",
                "spec_id": "s-1",
                "spec_md": "---\ngoal: refreshed\n---\n\n## Acceptance Criteria\n- one",
            },
            repo_path=repo,
        )
        assert result["passed"] is True
        updated = claude.read_text()
        assert updated.count("<!-- BEGIN SYNCED: testproj -->") == 1
        assert updated.count("<!-- BEGIN SYNCED: SPEC: s-1 -->") == 1
        assert "old synced" not in updated
        assert "old spec" not in updated
        assert "# Header" in updated
        assert "# Footer" in updated

    def test_only_requested_agents_get_skills(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """Projection should only target requested agents' paths."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "testproj", "skills": ["spec-skill"]},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert (repo / ".claude" / "skills" / "spec-skill" / "SKILL.md").exists()
        assert not (repo / ".agents" / "skills" / "spec-skill").exists()

    def test_shared_path_agents_dedup(
        self, tmp_path: Path, mock_governor_root: Path, mock_home: Path
    ) -> None:
        """claude-code + copilot should dedupe .claude/skills projection target."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={
                "agents": ["claude-code", "copilot"],
                "project": "testproj",
                "skills": ["spec-skill"],
            },
            repo_path=repo,
        )
        assert result["passed"] is True
        targets = result["data"]["projection_targets"]["spec-skill"]
        claude_targets = [p for p in targets if "/.claude/skills/spec-skill" in p]
        assert len(claude_targets) == 1

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
