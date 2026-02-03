"""Tests for EpicUpdater."""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from spec.governance.epic_updater import EpicUpdateError, EpicUpdater


def _make_epic(tmp_path: Path, specs: list[dict] | None = None) -> Path:
    """Create a minimal epic.yaml for testing."""
    if specs is None:
        specs = [
            {"id": "t-01-feat", "repo": "proj", "branch": "feat/a", "status": "active"},
            {"id": "t-02-fix", "repo": "proj", "branch": "feat/b", "status": "planned"},
        ]

    epic = {
        "version": "0.2",
        "kind": "epic",
        "id": "t-test",
        "title": "Test epic",
        "owner": "tester",
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
        "intent": {"goal": "Test"},
        "targets": [{"id": "proj", "repo_path": "/tmp/proj", "default_branch": "main"}],
        "specs": specs,
    }

    epic_path = tmp_path / "epic.yaml"
    yaml = YAML()
    yaml.preserve_quotes = True
    with epic_path.open("w") as f:
        yaml.dump(epic, f)
    return epic_path


def _load(path: Path) -> dict:
    yaml = YAML()
    with path.open() as f:
        return yaml.load(f)


class TestSetSpecStatus:
    def test_set_status_to_done(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        updater.set_spec_status("t-01-feat", "done")
        updater.save()

        data = _load(epic_path)
        spec = [s for s in data["specs"] if s["id"] == "t-01-feat"][0]
        assert spec["status"] == "done"

    def test_other_specs_unchanged(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        updater.set_spec_status("t-01-feat", "done")
        updater.save()

        data = _load(epic_path)
        spec2 = [s for s in data["specs"] if s["id"] == "t-02-fix"][0]
        assert spec2["status"] == "planned"

    def test_nonexistent_spec_raises(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        with pytest.raises(EpicUpdateError, match="not found"):
            updater.set_spec_status("nonexistent", "done")


class TestGetSpecEntry:
    def test_get_spec_entry_returns_raw_data(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        entry = updater.get_spec_entry("t-01-feat")
        assert entry["id"] == "t-01-feat"
        assert entry["status"] == "active"

    def test_get_spec_entry_is_live_reference(self, tmp_path: Path) -> None:
        """Mutations to the returned entry are reflected in save()."""
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        entry = updater.get_spec_entry("t-01-feat")
        entry["status"] = "done"
        updater.save()

        data = _load(epic_path)
        spec = [s for s in data["specs"] if s["id"] == "t-01-feat"][0]
        assert spec["status"] == "done"

    def test_get_spec_entry_nonexistent_raises(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        with pytest.raises(EpicUpdateError, match="not found"):
            updater.get_spec_entry("ghost")


class TestGetTarget:
    def test_get_target_found(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        target = updater.get_target("proj")
        assert target is not None
        assert target["repo_path"] == "/tmp/proj"

    def test_get_target_not_found(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        assert updater.get_target("nonexistent") is None


class TestGetSpecStatus:
    def test_get_existing_status(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        assert updater.get_spec_status("t-01-feat") == "active"
        assert updater.get_spec_status("t-02-fix") == "planned"

    def test_get_nonexistent_raises(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        with pytest.raises(EpicUpdateError, match="not found"):
            updater.get_spec_status("ghost")


class TestSetUpdated:
    def test_set_explicit_timestamp(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        updater.set_updated("2026-06-15T12:00:00Z")
        updater.save()

        data = _load(epic_path)
        assert data["updated"] == "2026-06-15T12:00:00Z"

    def test_set_auto_timestamp(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        updater.set_updated()
        updater.save()

        data = _load(epic_path)
        assert data["updated"] != "2026-01-01T00:00:00Z"
        assert "T" in data["updated"]  # ISO format


class TestAddBuildDelta:
    def test_add_delta_to_spec(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        delta = {
            "target": "projects/proj/proj.build.yaml",
            "summary": "Add new module",
            "adds": {"modules": [{"name": "new", "kind": "module"}]},
        }
        updater.add_build_delta("t-01-feat", delta)
        updater.save()

        data = _load(epic_path)
        spec = [s for s in data["specs"] if s["id"] == "t-01-feat"][0]
        assert spec["build_delta"]["summary"] == "Add new module"

    def test_add_delta_to_spec_with_existing_raises(self, tmp_path: Path) -> None:
        specs = [
            {
                "id": "t-01-feat",
                "repo": "proj",
                "branch": "feat/a",
                "status": "active",
                "build_delta": {"target": "x", "summary": "existing"},
            },
        ]
        epic_path = _make_epic(tmp_path, specs=specs)
        updater = EpicUpdater(epic_path)
        with pytest.raises(EpicUpdateError, match="already has"):
            updater.add_build_delta("t-01-feat", {"target": "y"})


class TestAtomicity:
    def test_save_is_atomic(self, tmp_path: Path) -> None:
        """Original file untouched if save not called."""
        epic_path = _make_epic(tmp_path)
        original = epic_path.read_text()

        updater = EpicUpdater(epic_path)
        updater.set_spec_status("t-01-feat", "done")
        # Don't call save()

        assert epic_path.read_text() == original

    def test_no_temp_files_after_save(self, tmp_path: Path) -> None:
        epic_path = _make_epic(tmp_path)
        updater = EpicUpdater(epic_path)
        updater.set_spec_status("t-01-feat", "done")
        updater.save()

        tmp_files = list(tmp_path.glob(".epic_update_*.tmp"))
        assert tmp_files == []


class TestRoundTrip:
    def test_comments_preserved(self, tmp_path: Path) -> None:
        """Comments in YAML are preserved after update."""
        epic_path = tmp_path / "epic.yaml"
        epic_path.write_text(
            "# Epic header comment\n"
            "version: '0.2'\n"
            "kind: epic\n"
            "id: t-test\n"
            "title: Test\n"
            "owner: tester\n"
            "created: '2026-01-01T00:00:00Z'\n"
            "updated: '2026-01-01T00:00:00Z'\n"
            "intent:\n"
            "  goal: Test\n"
            "targets:\n"
            "  - id: proj\n"
            "    repo_path: /tmp/proj\n"
            "    default_branch: main\n"
            "specs:\n"
            "  # This spec is important\n"
            "  - id: t-01-feat\n"
            "    repo: proj\n"
            "    branch: feat/a\n"
            "    status: active\n"
        )

        updater = EpicUpdater(epic_path)
        updater.set_spec_status("t-01-feat", "done")
        updater.save()

        content = epic_path.read_text()
        assert "# Epic header comment" in content
        assert "# This spec is important" in content
        assert "status: done" in content
