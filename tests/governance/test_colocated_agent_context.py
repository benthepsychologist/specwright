"""Tests for colocated agent context (t013-01).

Covers:
  - scaffolder always creates an epic AGENTS.md pointer + CLAUDE.md stub
  - AGENTS.md pointer shape (Skills + Docs sections; not a context dump)
  - sync materializes AGENTS.md/CLAUDE.md into the target repo (non-clobbering)
  - sync copies the skills AGENTS.md names into .claude/skills/ (SKILL.yaml-aware)
  - graceful degrade (missing build.yaml / unresolved skill name = partial sync)
  - non-clobber of the target repo's own AGENTS.md / CLAUDE.md
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from spec.governance.spec_scaffolder import (
    CLAUDE_STUB_CONTENT,
    render_agents_md_pointer,
    write_epic_context_files,
)
from spec.governance.sync_refs import (
    _parse_agents_md_skills,
    _resolve_skill_dir,
    _skill_library_roots,
    sync_refs,
)

# ---------------------------------------------------------------------------
# Scaffolder: AGENTS.md pointer + CLAUDE.md stub
# ---------------------------------------------------------------------------


class TestScaffoldAgentsAndStub:
    """write_epic_context_files / create_epic author the pointer + stub."""

    def test_scaffold_creates_agents_and_stub(self, tmp_path: Path) -> None:
        epic_dir = tmp_path / "t999-demo"
        written = write_epic_context_files(epic_dir, title="Demo Epic")

        agents = epic_dir / "AGENTS.md"
        claude = epic_dir / "CLAUDE.md"
        assert agents.exists()
        assert claude.exists()
        assert agents in written
        assert claude in written

    def test_claude_stub_points_to_agents(self, tmp_path: Path) -> None:
        epic_dir = tmp_path / "t999-demo"
        write_epic_context_files(epic_dir, title="Demo Epic")
        claude = (epic_dir / "CLAUDE.md").read_text()
        assert claude == CLAUDE_STUB_CONTENT
        assert "AGENTS.md" in claude
        # A stub is one line, not a context dump.
        assert len([ln for ln in claude.splitlines() if ln.strip()]) == 1

    def test_scaffold_does_not_clobber_existing(self, tmp_path: Path) -> None:
        epic_dir = tmp_path / "t999-demo"
        epic_dir.mkdir()
        (epic_dir / "AGENTS.md").write_text("# hand authored\n")
        written = write_epic_context_files(epic_dir, title="Demo Epic")
        # AGENTS.md preserved; only CLAUDE.md written
        assert (epic_dir / "AGENTS.md").read_text() == "# hand authored\n"
        assert (epic_dir / "CLAUDE.md") in written
        assert (epic_dir / "AGENTS.md") not in written

    def test_create_epic_writes_context_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_epic (the real epic-creation path) authors both files."""
        from spec.epic import loader, writer

        epics_root = tmp_path / "epics"

        def fake_get_epic_path(epic_id: str) -> Path:
            from spec.epic.loader import get_category_from_id

            category = get_category_from_id(epic_id) or "e"
            return epics_root / category / epic_id

        monkeypatch.setattr(loader, "get_epic_path", fake_get_epic_path)
        monkeypatch.setattr(writer, "get_epic_path", fake_get_epic_path)

        writer.create_epic(
            id="t999-demo",
            title="Demo Epic",
            owner="tester",
            goal="demo goal",
        )

        epic_dir = fake_get_epic_path("t999-demo")
        assert (epic_dir / "AGENTS.md").exists()
        assert (epic_dir / "CLAUDE.md").exists()


class TestScaffoldPointerShape:
    """AGENTS.md is a pointer: Skills + Docs sections, not an inline dump."""

    def test_pointer_has_skills_and_docs_sections(self) -> None:
        md = render_agents_md_pointer(
            title="Demo",
            skills=["spec-and-epic-authoring", "data-architecture"],
            docs=["DESIGN.md"],
        )
        assert "## Skills" in md
        assert "## Docs" in md
        assert "- spec-and-epic-authoring" in md
        assert "- data-architecture" in md
        assert "[DESIGN.md](DESIGN.md)" in md

    def test_pointer_is_not_a_context_dump(self) -> None:
        """A pointer names skills/docs; it must stay small (an index)."""
        md = render_agents_md_pointer(
            title="Demo",
            skills=["spec-and-epic-authoring"],
            docs=["DESIGN.md"],
        )
        # An index, not a dump: a handful of lines, no inlined skill bodies.
        assert len(md.splitlines()) < 30
        assert "pointer" in md.lower()

    def test_pointer_empty_sections_have_placeholders(self) -> None:
        md = render_agents_md_pointer(title="Demo")
        assert "## Skills" in md
        assert "## Docs" in md
        assert md.count("TODO") >= 2


# ---------------------------------------------------------------------------
# AGENTS.md skill-name parsing
# ---------------------------------------------------------------------------


class TestParseAgentsMdSkills:
    def test_parses_bare_names(self) -> None:
        md = "## Skills\n\n- alpha\n- beta\n\n## Docs\n\n- DESIGN.md\n"
        assert _parse_agents_md_skills(md) == ["alpha", "beta"]

    def test_parses_code_and_link_forms(self) -> None:
        md = "## Skills\n\n- `alpha`\n- [beta](skills/beta)\n"
        assert _parse_agents_md_skills(md) == ["alpha", "beta"]

    def test_stops_at_next_heading(self) -> None:
        md = "## Skills\n\n- alpha\n\n## Docs\n\n- gamma.md\n"
        assert _parse_agents_md_skills(md) == ["alpha"]

    def test_dedupes(self) -> None:
        md = "## Skills\n\n- alpha\n- alpha\n"
        assert _parse_agents_md_skills(md) == ["alpha"]

    def test_ignores_placeholder_is_token(self) -> None:
        # TODO placeholders are list items; they parse to a token but won't
        # resolve in the library (covered by graceful-degrade tests).
        md = "## Skills\n\n- TODO: name skills\n"
        assert _parse_agents_md_skills(md) == ["TODO:"]


# ---------------------------------------------------------------------------
# Skill library resolution (SKILL.yaml-aware)
# ---------------------------------------------------------------------------


class TestSkillLibraryResolution:
    def test_resolves_skill_yaml(self, tmp_path: Path) -> None:
        lib = tmp_path / "skills"
        (lib / "alpha").mkdir(parents=True)
        (lib / "alpha" / "SKILL.yaml").write_text("name: alpha\n")
        found = _resolve_skill_dir("alpha", [lib])
        assert found == lib / "alpha"

    def test_resolves_skill_md(self, tmp_path: Path) -> None:
        lib = tmp_path / "skills"
        (lib / "beta").mkdir(parents=True)
        (lib / "beta" / "SKILL.md").write_text("# beta\n")
        found = _resolve_skill_dir("beta", [lib])
        assert found == lib / "beta"

    def test_unresolved_returns_none(self, tmp_path: Path) -> None:
        lib = tmp_path / "skills"
        lib.mkdir()
        assert _resolve_skill_dir("missing", [lib]) is None

    def test_env_override_roots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        custom = tmp_path / "custom-skills"
        (custom / "alpha").mkdir(parents=True)
        (custom / "alpha" / "SKILL.yaml").write_text("name: alpha\n")
        monkeypatch.setenv("SPECWRIGHT_SKILL_LIBRARY", str(custom))
        roots = _skill_library_roots(None, None)
        assert custom in roots

    def test_walks_up_from_epic_dir(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        (root / "skills" / "alpha").mkdir(parents=True)
        (root / "skills" / "alpha" / "SKILL.yaml").write_text("name: alpha\n")
        epic_dir = root / "epics" / "t" / "t999"
        epic_dir.mkdir(parents=True)
        roots = _skill_library_roots(None, epic_dir)
        assert (root / "skills") in roots


# ---------------------------------------------------------------------------
# sync_refs: materialize epic context + copy named skills
# ---------------------------------------------------------------------------


def _make_governor(tmp_path: Path) -> Path:
    """A minimal governor root (no build.yaml needed for these tests)."""
    gov = tmp_path / "governor"
    (gov / "skills").mkdir(parents=True)
    (gov / "skills" / "skills.yaml").write_text(yaml.safe_dump({"skills": []}))
    return gov


def _make_epic_with_skill_library(tmp_path: Path, skill_names: list[str]) -> Path:
    """Create an epic folder with AGENTS.md naming skills + a sibling library."""
    proj = tmp_path / "cloud-governor"
    skills_lib = proj / "skills"
    for name in skill_names:
        sk = skills_lib / name
        (sk / "references").mkdir(parents=True)
        (sk / "SKILL.yaml").write_text(f"name: {name}\ndescription: test\n")
        (sk / "references" / "ref.md").write_text("reference body")

    epic_dir = proj / "epics" / "t" / "t999-demo"
    epic_dir.mkdir(parents=True)
    write_epic_context_files(epic_dir, title="Demo", skills=skill_names, docs=["DESIGN.md"])
    (epic_dir / "DESIGN.md").write_text("# Design\n")
    return epic_dir


class TestSyncColocatedContext:
    @pytest.fixture
    def gov(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        gov = _make_governor(tmp_path)
        monkeypatch.setattr(
            "spec.governance.sync_refs._governor_root", lambda: gov
        )
        return gov

    def test_sync_materializes_agents_and_stub(self, tmp_path: Path, gov: Path) -> None:
        epic_dir = _make_epic_with_skill_library(tmp_path, ["alpha"])
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "repo",
                "epic_dir": str(epic_dir),
            },
            repo_path=repo,
        )
        assert result["passed"] is True
        # Materialized under .claude/, not at repo root.
        assert (repo / ".claude" / "AGENTS.md").exists()
        assert (repo / ".claude" / "CLAUDE.md").exists()
        materialized = result["data"]["epic_context_materialized"]
        assert any("AGENTS.md" in p for p in materialized)
        assert any("CLAUDE.md" in p for p in materialized)

    def test_sync_copies_named_skills_skill_yaml_aware(
        self, tmp_path: Path, gov: Path
    ) -> None:
        epic_dir = _make_epic_with_skill_library(tmp_path, ["alpha", "beta"])
        repo = tmp_path / "repo"
        repo.mkdir()

        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "repo",
                "epic_dir": str(epic_dir),
            },
            repo_path=repo,
        )
        assert result["passed"] is True
        # Skills named in AGENTS.md copied into .claude/skills/ (full tree).
        assert (repo / ".claude" / "skills" / "alpha" / "SKILL.yaml").exists()
        assert (repo / ".claude" / "skills" / "alpha" / "references" / "ref.md").exists()
        assert (repo / ".claude" / "skills" / "beta" / "SKILL.yaml").exists()
        assert "alpha" in result["data"]["skills_projected"]
        assert "beta" in result["data"]["skills_projected"]

    def test_sync_does_not_copy_docs(self, tmp_path: Path, gov: Path) -> None:
        """Docs are referenced by path, never copied into the repo."""
        epic_dir = _make_epic_with_skill_library(tmp_path, ["alpha"])
        repo = tmp_path / "repo"
        repo.mkdir()

        sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "repo",
                "epic_dir": str(epic_dir),
            },
            repo_path=repo,
        )
        # DESIGN.md from the epic is not copied into the repo.
        assert not (repo / "DESIGN.md").exists()
        assert not (repo / ".claude" / "DESIGN.md").exists()

    def test_sync_codex_uses_agents_skills_dir(self, tmp_path: Path, gov: Path) -> None:
        epic_dir = _make_epic_with_skill_library(tmp_path, ["alpha"])
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={
                "agents": ["codex"],
                "project": "repo",
                "epic_dir": str(epic_dir),
            },
            repo_path=repo,
        )
        assert result["passed"] is True
        assert (repo / ".agents" / "skills" / "alpha" / "SKILL.yaml").exists()


class TestSyncGracefulDegrade:
    @pytest.fixture
    def gov(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        gov = _make_governor(tmp_path)
        monkeypatch.setattr(
            "spec.governance.sync_refs._governor_root", lambda: gov
        )
        return gov

    def test_sync_refs_unresolved_skill_graceful_partial_not_failure(
        self, tmp_path: Path, gov: Path
    ) -> None:
        # AGENTS.md names a skill that does not exist in the library.
        epic_dir = _make_epic_with_skill_library(tmp_path, ["alpha"])
        agents = epic_dir / "AGENTS.md"
        agents.write_text(agents.read_text() + "\n## Skills\n\n- ghost\n")

        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "repo",
                "epic_dir": str(epic_dir),
            },
            repo_path=repo,
        )
        # Partial sync: still passes, alpha copied, ghost skipped with a warning.
        assert result["passed"] is True
        assert (repo / ".claude" / "skills" / "alpha" / "SKILL.yaml").exists()
        assert "ghost" in result["data"]["skills_skipped"]
        assert any("ghost" in w for w in result["data"]["skills_warnings"])

    def test_sync_refs_missing_epic_dir_graceful_warning(
        self, tmp_path: Path, gov: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "repo",
                "epic_dir": str(tmp_path / "does-not-exist"),
            },
            repo_path=repo,
        )
        assert result["passed"] is True
        assert result["data"]["epic_context_materialized"] == []
        assert any("Epic folder not found" in w for w in result["data"]["skills_warnings"])

    def test_sync_refs_no_epic_dir_graceful_noop(self, tmp_path: Path, gov: Path) -> None:
        """Without epic_dir, behavior is unchanged (no materialization)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={"agents": ["claude-code"], "project": "repo"},
            repo_path=repo,
        )
        assert result["passed"] is True
        assert result["data"]["epic_context_materialized"] == []
        assert not (repo / ".claude" / "AGENTS.md").exists()

    def test_sync_refs_missing_agents_md_graceful_degrade(
        self, tmp_path: Path, gov: Path
    ) -> None:
        """Epic folder exists but has no AGENTS.md -> warn, partial sync."""
        epic_dir = tmp_path / "epic-no-agents"
        epic_dir.mkdir()
        repo = tmp_path / "repo"
        repo.mkdir()
        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "repo",
                "epic_dir": str(epic_dir),
            },
            repo_path=repo,
        )
        assert result["passed"] is True
        assert any("AGENTS.md not found" in w for w in result["data"]["skills_warnings"])


class TestSyncNonClobber:
    @pytest.fixture
    def gov(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        gov = _make_governor(tmp_path)
        monkeypatch.setattr(
            "spec.governance.sync_refs._governor_root", lambda: gov
        )
        return gov

    def test_sync_refs_non_clobber_repo_own_agents_and_claude(
        self, tmp_path: Path, gov: Path
    ) -> None:
        epic_dir = _make_epic_with_skill_library(tmp_path, ["alpha"])
        repo = tmp_path / "repo"
        repo.mkdir()
        # Repo's own files at the root.
        (repo / "AGENTS.md").write_text("REPO OWN AGENTS\n")
        (repo / "CLAUDE.md").write_text("REPO OWN CLAUDE\n")

        result = sync_refs(
            payload={
                "agents": ["claude-code"],
                "project": "repo",
                "epic_dir": str(epic_dir),
            },
            repo_path=repo,
        )
        assert result["passed"] is True
        # Root files untouched by epic materialization (the synced-context block
        # may be appended by the existing build-context sync, but the epic
        # pointer must land under .claude/, not replace these).
        assert "REPO OWN AGENTS" in (repo / "AGENTS.md").read_text()
        assert "REPO OWN CLAUDE" in (repo / "CLAUDE.md").read_text()
        # Epic pointer landed under .claude/.
        assert (repo / ".claude" / "AGENTS.md").read_text().startswith("# Demo")
