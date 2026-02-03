"""Tests for spec finish CLI command."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from spec.cli.spec import app

runner = CliRunner()


def _make_governor(tmp_path: Path, build_delta: dict | None = None) -> dict:
    """Create a minimal governor filesystem for testing.

    Returns dict with paths:
        governor_root, epic_yaml, build_yaml, specs_dir
    """
    gov = tmp_path / "governor"
    gov.mkdir()
    (gov / "projects").mkdir()
    (gov / "contracts").mkdir()
    (gov / "epics" / "t" / "t-test-epic").mkdir(parents=True)

    # Build.yaml
    proj_dir = gov / "projects" / "testproj"
    proj_dir.mkdir()
    build_data = {
        "kind": "project.build",
        "version": "0.1",
        "metadata": {"name": "testproj", "semver": "1.0.0"},
        "kernel": {
            "description": "Test",
            "surfaces": [
                {"name": "cli", "entrypoints": [{"command": "test run"}]},
            ],
        },
        "layout": [
            {"path": "src/core/", "module": "core", "role": "Core"},
        ],
        "modules": [
            {"name": "core", "kind": "module", "provides": ["core"]},
        ],
        "boundaries": [
            {"name": "old_api", "type": "inbound", "contract": "REST"},
        ],
    }
    build_path = proj_dir / "testproj.build.yaml"
    yaml = YAML()
    yaml.preserve_quotes = True
    with build_path.open("w") as f:
        yaml.dump(build_data, f)

    # Epic + specs dir
    epic_dir = gov / "epics" / "t" / "t-test-epic"
    specs_dir = epic_dir / "specs"
    specs_dir.mkdir()

    spec_entry = {
        "id": "t-test-01-feat",
        "repo": "testproj",
        "branch": "feat/a",
        "status": "active",
    }
    if build_delta is not None:
        spec_entry["build_delta"] = build_delta

    epic_data = {
        "version": "0.2",
        "kind": "epic",
        "id": "t-test-epic",
        "title": "Test epic",
        "owner": "tester",
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
        "intent": {"goal": "Test"},
        "targets": [
            {"id": "testproj", "repo_path": "/tmp/proj", "default_branch": "main"},
        ],
        "specs": [
            spec_entry,
            {
                "id": "t-test-02-fix",
                "repo": "testproj",
                "branch": "feat/b",
                "status": "planned",
            },
        ],
    }
    epic_path = epic_dir / "epic.yaml"
    with epic_path.open("w") as f:
        yaml.dump(epic_data, f)

    # Spec markdown file (so resolver can find it)
    (specs_dir / "t-test-01-feat.md").write_text("# t-test-01-feat\n")
    (specs_dir / "t-test-02-fix.md").write_text("# t-test-02-fix\n")

    return {
        "governor_root": gov,
        "epic_yaml": epic_path,
        "build_yaml": build_path,
        "specs_dir": specs_dir,
    }


def _load(path: Path) -> dict:
    yaml = YAML()
    with path.open() as f:
        return yaml.load(f)


class TestFinishNoDelta:
    """Test spec finish on specs without build_delta — status-only update."""

    def test_finish_updates_status(self, tmp_path: Path) -> None:
        paths = _make_governor(tmp_path)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        result = runner.invoke(app, ["finish", "t-test-01"], env=env)
        assert result.exit_code == 0
        assert "done" in result.output

        data = _load(paths["epic_yaml"])
        spec = [s for s in data["specs"] if s["id"] == "t-test-01-feat"][0]
        assert spec["status"] == "done"

    def test_finish_updates_timestamp(self, tmp_path: Path) -> None:
        paths = _make_governor(tmp_path)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        runner.invoke(app, ["finish", "t-test-01"], env=env)

        data = _load(paths["epic_yaml"])
        assert data["updated"] != "2026-01-01T00:00:00Z"

    def test_other_specs_unchanged(self, tmp_path: Path) -> None:
        paths = _make_governor(tmp_path)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        runner.invoke(app, ["finish", "t-test-01"], env=env)

        data = _load(paths["epic_yaml"])
        spec2 = [s for s in data["specs"] if s["id"] == "t-test-02-fix"][0]
        assert spec2["status"] == "planned"

    def test_finish_already_done_rejected(self, tmp_path: Path) -> None:
        paths = _make_governor(tmp_path)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        # Finish once
        runner.invoke(app, ["finish", "t-test-01"], env=env)
        # Try again
        result = runner.invoke(app, ["finish", "t-test-01"], env=env)
        assert result.exit_code == 1
        assert "already done" in result.output

    def test_finish_already_done_with_force(self, tmp_path: Path) -> None:
        paths = _make_governor(tmp_path)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        runner.invoke(app, ["finish", "t-test-01"], env=env)
        result = runner.invoke(app, ["finish", "t-test-01", "--force"], env=env)
        assert result.exit_code == 0


class TestFinishWithDelta:
    """Test spec finish with build_delta — applies to build.yaml."""

    def test_finish_applies_adds(self, tmp_path: Path) -> None:
        delta = {
            "target": "projects/testproj/testproj.build.yaml",
            "summary": "Add governance module",
            "adds": {
                "modules": [
                    {"name": "governance", "kind": "module", "provides": ["validation"]},
                ],
                "layout": [
                    {"path": "src/governance/", "module": "governance", "role": "Validation"},
                ],
            },
        }
        paths = _make_governor(tmp_path, build_delta=delta)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        result = runner.invoke(app, ["finish", "t-test-01"], env=env)
        assert result.exit_code == 0
        assert "Applied build_delta" in result.output

        data = _load(paths["build_yaml"])
        module_names = [m["name"] for m in data["modules"]]
        assert "governance" in module_names
        layout_paths = [e["path"] for e in data["layout"]]
        assert "src/governance/" in layout_paths

    def test_finish_applies_modifies(self, tmp_path: Path) -> None:
        delta = {
            "target": "projects/testproj/testproj.build.yaml",
            "summary": "Add entrypoints",
            "modifies": {
                "kernel_surfaces": [
                    {
                        "name": "cli",
                        "entrypoints": [{"command": "test validate"}],
                    },
                ],
            },
        }
        paths = _make_governor(tmp_path, build_delta=delta)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        result = runner.invoke(app, ["finish", "t-test-01"], env=env)
        assert result.exit_code == 0

        data = _load(paths["build_yaml"])
        cli = [s for s in data["kernel"]["surfaces"] if s["name"] == "cli"][0]
        commands = [e["command"] for e in cli["entrypoints"]]
        assert "test run" in commands  # original
        assert "test validate" in commands  # added

    def test_finish_applies_removes(self, tmp_path: Path) -> None:
        delta = {
            "target": "projects/testproj/testproj.build.yaml",
            "summary": "Remove old boundary",
            "removes": {
                "boundaries": [{"name": "old_api"}],
            },
        }
        paths = _make_governor(tmp_path, build_delta=delta)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        result = runner.invoke(app, ["finish", "t-test-01"], env=env)
        assert result.exit_code == 0

        data = _load(paths["build_yaml"])
        assert data["boundaries"] == []

    def test_finish_conflict_rejects(self, tmp_path: Path) -> None:
        delta = {
            "target": "projects/testproj/testproj.build.yaml",
            "summary": "Add existing module",
            "adds": {
                "modules": [{"name": "core", "kind": "module"}],  # already exists
            },
        }
        paths = _make_governor(tmp_path, build_delta=delta)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        result = runner.invoke(app, ["finish", "t-test-01"], env=env)
        assert result.exit_code == 3  # DeltaConflictError.exit_code
        assert "conflict" in result.output.lower() or "already exists" in result.output.lower()

        # Build.yaml unchanged
        data = _load(paths["build_yaml"])
        assert len(data["modules"]) == 1

        # Epic status unchanged
        epic_data = _load(paths["epic_yaml"])
        spec = [s for s in epic_data["specs"] if s["id"] == "t-test-01-feat"][0]
        assert spec["status"] == "active"

    def test_force_finish_does_not_bypass_conflicts(self, tmp_path: Path) -> None:
        """--force bypasses status check, but NOT build_delta conflicts."""
        delta = {
            "target": "projects/testproj/testproj.build.yaml",
            "summary": "Add existing module",
            "adds": {
                "modules": [{"name": "core", "kind": "module"}],  # conflict
            },
        }
        paths = _make_governor(tmp_path, build_delta=delta)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        result = runner.invoke(app, ["finish", "t-test-01", "--force"], env=env)
        assert result.exit_code == 3  # DeltaConflictError.exit_code
        assert "conflict" in result.output.lower() or "already exists" in result.output.lower()

        # Build.yaml and epic unchanged
        data = _load(paths["build_yaml"])
        assert len(data["modules"]) == 1
        epic_data = _load(paths["epic_yaml"])
        spec = [s for s in epic_data["specs"] if s["id"] == "t-test-01-feat"][0]
        assert spec["status"] == "active"


class TestDryRun:
    def test_dry_run_no_changes(self, tmp_path: Path) -> None:
        delta = {
            "target": "projects/testproj/testproj.build.yaml",
            "summary": "Add governance",
            "adds": {
                "modules": [{"name": "governance", "kind": "module"}],
            },
        }
        paths = _make_governor(tmp_path, build_delta=delta)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        original_build = paths["build_yaml"].read_text()
        original_epic = paths["epic_yaml"].read_text()

        result = runner.invoke(app, ["finish", "t-test-01", "--dry-run"], env=env)
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "governance" in result.output

        # Nothing changed
        assert paths["build_yaml"].read_text() == original_build
        assert paths["epic_yaml"].read_text() == original_epic

    def test_dry_run_json(self, tmp_path: Path) -> None:
        paths = _make_governor(tmp_path)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        result = runner.invoke(
            app, ["finish", "t-test-01", "--dry-run", "--json"], env=env
        )
        assert result.exit_code == 0

        import json
        data = json.loads(result.output)
        assert data["spec_id"] == "t-test-01-feat"
        assert data["new_status"] == "done"

    def test_dry_run_shows_conflicts(self, tmp_path: Path) -> None:
        delta = {
            "target": "projects/testproj/testproj.build.yaml",
            "summary": "Conflict",
            "adds": {
                "modules": [{"name": "core", "kind": "module"}],
            },
        }
        paths = _make_governor(tmp_path, build_delta=delta)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        result = runner.invoke(app, ["finish", "t-test-01", "--dry-run"], env=env)
        assert result.exit_code == 0  # dry-run always exits 0
        assert "Conflict" in result.output or "already exists" in result.output


class TestJsonOutput:
    def test_finish_json(self, tmp_path: Path) -> None:
        paths = _make_governor(tmp_path)
        env = {"SPECWRIGHT_GOVERNOR_ROOT": str(paths["governor_root"])}

        result = runner.invoke(app, ["finish", "t-test-01", "--json"], env=env)
        assert result.exit_code == 0

        import json
        data = json.loads(result.output)
        assert data["spec_id"] == "t-test-01-feat"
        assert data["status"] == "done"
