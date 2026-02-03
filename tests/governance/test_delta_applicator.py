"""Tests for BuildDeltaApplicator."""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from spec.governance.delta_applicator import (
    BuildDeltaApplicator,
    DeltaConflictError,
)


@pytest.fixture
def build_yaml(tmp_path: Path) -> Path:
    """Create a minimal build.yaml for testing."""
    content = {
        "kind": "project.build",
        "version": "0.1",
        "metadata": {"name": "testproj", "semver": "1.0.0"},
        "kernel": {
            "description": "Test project",
            "surfaces": [
                {
                    "name": "cli",
                    "entrypoints": [
                        {"command": "test run", "usage": "test run <path>"},
                    ],
                },
            ],
        },
        "layout": [
            {"path": "src/core/", "module": "core", "role": "Core module"},
        ],
        "modules": [
            {"name": "core", "kind": "module", "provides": ["core logic"]},
        ],
        "boundaries": [
            {"name": "api", "type": "inbound", "contract": "REST API"},
        ],
        "decisions": [
            {
                "id": "adr-001",
                "title": "Use REST",
                "status": "accepted",
                "decision": "REST over GraphQL",
            },
        ],
    }

    build_path = tmp_path / "test.build.yaml"
    yaml = YAML()
    yaml.preserve_quotes = True
    with build_path.open("w") as f:
        yaml.dump(content, f)
    return build_path


def _load(path: Path) -> dict:
    yaml = YAML()
    with path.open() as f:
        return yaml.load(f)


# ── adds ──────────────────────────────────────────────────────────────


class TestAdds:
    def test_add_layout_entry(self, build_yaml: Path) -> None:
        delta = {
            "adds": {
                "layout": [
                    {"path": "src/new/", "module": "new", "role": "New module"},
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        paths = [e["path"] for e in data["layout"]]
        assert "src/new/" in paths

    def test_add_module(self, build_yaml: Path) -> None:
        delta = {
            "adds": {
                "modules": [
                    {"name": "new", "kind": "module", "provides": ["new stuff"]},
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        names = [m["name"] for m in data["modules"]]
        assert "new" in names

    def test_add_boundary(self, build_yaml: Path) -> None:
        delta = {
            "adds": {
                "boundaries": [
                    {"name": "db", "type": "dependency", "contract": "PostgreSQL"},
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        names = [b["name"] for b in data["boundaries"]]
        assert "db" in names

    def test_add_to_nonexistent_section_creates_it(self, build_yaml: Path) -> None:
        delta = {
            "adds": {
                "slots": [
                    {"name": "plugins", "path": "src/plugins/"},
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        assert data["slots"][0]["name"] == "plugins"

    def test_add_existing_entry_conflicts(self, build_yaml: Path) -> None:
        delta = {
            "adds": {
                "modules": [
                    {"name": "core", "kind": "module"},  # already exists
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        with pytest.raises(DeltaConflictError, match="already exists"):
            applicator.apply()

    def test_add_kernel_surfaces(self, build_yaml: Path) -> None:
        delta = {
            "adds": {
                "kernel_surfaces": [
                    {"name": "python_api", "entrypoints": []},
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        names = [s["name"] for s in data["kernel"]["surfaces"]]
        assert "python_api" in names
        assert "cli" in names  # original still there


# ── modifies ──────────────────────────────────────────────────────────


class TestModifies:
    def test_modify_scalar_field(self, build_yaml: Path) -> None:
        delta = {
            "modifies": {
                "modules": [
                    {"name": "core", "kind": "module_group"},
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        core = [m for m in data["modules"] if m["name"] == "core"][0]
        assert core["kind"] == "module_group"
        # provides should be untouched
        assert core["provides"] == ["core logic"]

    def test_modify_appends_to_array(self, build_yaml: Path) -> None:
        """Modifying an array field appends rather than replacing."""
        delta = {
            "modifies": {
                "kernel_surfaces": [
                    {
                        "name": "cli",
                        "entrypoints": [
                            {"command": "test validate", "usage": "test validate <path>"},
                        ],
                    },
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        cli = [s for s in data["kernel"]["surfaces"] if s["name"] == "cli"][0]
        commands = [e["command"] for e in cli["entrypoints"]]
        # Original preserved, new appended
        assert "test run" in commands
        assert "test validate" in commands

    def test_modify_nonexistent_entry_conflicts(self, build_yaml: Path) -> None:
        delta = {
            "modifies": {
                "modules": [
                    {"name": "nonexistent", "kind": "module"},
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        with pytest.raises(DeltaConflictError, match="does not exist"):
            applicator.apply()

    def test_modify_adds_new_field_to_entry(self, build_yaml: Path) -> None:
        delta = {
            "modifies": {
                "modules": [
                    {"name": "core", "depends_on": ["config"]},
                ],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        core = [m for m in data["modules"] if m["name"] == "core"][0]
        assert core["depends_on"] == ["config"]
        # existing fields untouched
        assert core["kind"] == "module"
        assert core["provides"] == ["core logic"]


# ── removes ───────────────────────────────────────────────────────────


class TestRemoves:
    def test_remove_boundary(self, build_yaml: Path) -> None:
        delta = {
            "removes": {
                "boundaries": [{"name": "api"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        assert data["boundaries"] == []

    def test_remove_layout_entry(self, build_yaml: Path) -> None:
        delta = {
            "removes": {
                "layout": [{"path": "src/core/"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)
        assert data["layout"] == []

    def test_remove_nonexistent_entry_conflicts(self, build_yaml: Path) -> None:
        delta = {
            "removes": {
                "modules": [{"name": "nonexistent"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        with pytest.raises(DeltaConflictError, match="does not exist"):
            applicator.apply()


# ── combined operations ───────────────────────────────────────────────


class TestCombined:
    def test_add_modify_remove_in_one_delta(self, build_yaml: Path) -> None:
        delta = {
            "summary": "Restructure project",
            "adds": {
                "layout": [
                    {"path": "src/governance/", "module": "governance", "role": "Validation"},
                ],
                "modules": [
                    {"name": "governance", "kind": "module", "provides": ["validation"]},
                ],
            },
            "modifies": {
                "kernel_surfaces": [
                    {
                        "name": "cli",
                        "entrypoints": [
                            {"command": "test validate build"},
                        ],
                    },
                ],
            },
            "removes": {
                "boundaries": [{"name": "api"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        data = _load(build_yaml)

        # adds applied
        layout_paths = [e["path"] for e in data["layout"]]
        assert "src/governance/" in layout_paths
        assert "src/core/" in layout_paths  # original still there

        module_names = [m["name"] for m in data["modules"]]
        assert "governance" in module_names

        # modifies applied (append)
        cli = [s for s in data["kernel"]["surfaces"] if s["name"] == "cli"][0]
        commands = [e["command"] for e in cli["entrypoints"]]
        assert "test run" in commands
        assert "test validate build" in commands

        # removes applied
        assert data["boundaries"] == []

    def test_empty_delta_is_noop(self, build_yaml: Path) -> None:
        original = _load(build_yaml)

        delta: dict = {}
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        after = _load(build_yaml)
        assert original == after

    def test_empty_sections_is_noop(self, build_yaml: Path) -> None:
        original = _load(build_yaml)

        delta = {"adds": {}, "modifies": {}, "removes": {}}
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        after = _load(build_yaml)
        assert original == after


# ── validation / preview ──────────────────────────────────────────────


class TestValidate:
    def test_validate_clean_delta(self, build_yaml: Path) -> None:
        delta = {
            "adds": {
                "modules": [{"name": "new", "kind": "module"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        conflicts = applicator.validate()
        assert conflicts == []

    def test_validate_catches_add_conflict(self, build_yaml: Path) -> None:
        delta = {
            "adds": {
                "modules": [{"name": "core", "kind": "module"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        conflicts = applicator.validate()
        assert len(conflicts) == 1
        assert "already exists" in conflicts[0]

    def test_validate_catches_modify_missing(self, build_yaml: Path) -> None:
        delta = {
            "modifies": {
                "modules": [{"name": "ghost", "kind": "module"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        conflicts = applicator.validate()
        assert len(conflicts) == 1
        assert "does not exist" in conflicts[0]

    def test_validate_catches_remove_missing(self, build_yaml: Path) -> None:
        delta = {
            "removes": {
                "boundaries": [{"name": "ghost"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        conflicts = applicator.validate()
        assert len(conflicts) == 1
        assert "does not exist" in conflicts[0]

    def test_validate_unknown_section(self, build_yaml: Path) -> None:
        delta = {
            "adds": {"bogus_section": [{"name": "x"}]},
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        conflicts = applicator.validate()
        assert any("Unknown section" in c for c in conflicts)


class TestPreview:
    def test_preview_shows_summary(self, build_yaml: Path) -> None:
        delta = {
            "summary": "Add governance module",
            "adds": {
                "modules": [{"name": "governance", "kind": "module"}],
            },
            "removes": {
                "boundaries": [{"name": "api"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        preview = applicator.preview()
        assert "governance" in preview
        assert "Add governance module" in preview
        assert "remove" in preview
        assert "api" in preview

    def test_preview_empty_delta(self, build_yaml: Path) -> None:
        applicator = BuildDeltaApplicator(build_yaml, {})
        preview = applicator.preview()
        assert "no changes" in preview


# ── string-list sections (key_field=None) ─────────────────────────────


class TestStringListSections:
    """Test sections like kernel_invariants that are plain string lists."""

    def test_add_invariant(self, build_yaml: Path) -> None:
        # Add kernel.invariants section first
        yaml = YAML()
        yaml.preserve_quotes = True
        with build_yaml.open() as f:
            data = yaml.load(f)
        data["kernel"]["invariants"] = ["Existing invariant"]
        with build_yaml.open("w") as f:
            yaml.dump(data, f)

        delta = {"adds": {"kernel_invariants": ["New invariant"]}}
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        result = _load(build_yaml)
        assert "Existing invariant" in result["kernel"]["invariants"]
        assert "New invariant" in result["kernel"]["invariants"]

    def test_add_duplicate_invariant_conflicts(self, build_yaml: Path) -> None:
        yaml = YAML()
        yaml.preserve_quotes = True
        with build_yaml.open() as f:
            data = yaml.load(f)
        data["kernel"]["invariants"] = ["Existing invariant"]
        with build_yaml.open("w") as f:
            yaml.dump(data, f)

        delta = {"adds": {"kernel_invariants": ["Existing invariant"]}}
        applicator = BuildDeltaApplicator(build_yaml, delta)
        with pytest.raises(DeltaConflictError, match="already exists"):
            applicator.apply()

    def test_remove_invariant(self, build_yaml: Path) -> None:
        yaml = YAML()
        yaml.preserve_quotes = True
        with build_yaml.open() as f:
            data = yaml.load(f)
        data["kernel"]["invariants"] = ["Keep this", "Remove this"]
        with build_yaml.open("w") as f:
            yaml.dump(data, f)

        delta = {"removes": {"kernel_invariants": ["Remove this"]}}
        applicator = BuildDeltaApplicator(build_yaml, delta)
        applicator.apply()

        result = _load(build_yaml)
        assert result["kernel"]["invariants"] == ["Keep this"]

    def test_remove_nonexistent_invariant_conflicts(self, build_yaml: Path) -> None:
        yaml = YAML()
        yaml.preserve_quotes = True
        with build_yaml.open() as f:
            data = yaml.load(f)
        data["kernel"]["invariants"] = ["Existing"]
        with build_yaml.open("w") as f:
            yaml.dump(data, f)

        delta = {"removes": {"kernel_invariants": ["Not here"]}}
        applicator = BuildDeltaApplicator(build_yaml, delta)
        with pytest.raises(DeltaConflictError, match="does not exist"):
            applicator.apply()

    def test_modify_invariant_rejected(self, build_yaml: Path) -> None:
        yaml = YAML()
        yaml.preserve_quotes = True
        with build_yaml.open() as f:
            data = yaml.load(f)
        data["kernel"]["invariants"] = ["Existing"]
        with build_yaml.open("w") as f:
            yaml.dump(data, f)

        delta = {"modifies": {"kernel_invariants": ["Replacement"]}}
        applicator = BuildDeltaApplicator(build_yaml, delta)
        conflicts = applicator.validate()
        assert len(conflicts) == 1
        assert "cannot modify" in conflicts[0]


# ── atomicity ─────────────────────────────────────────────────────────


class TestAtomicity:
    def test_original_unchanged_on_conflict(self, build_yaml: Path) -> None:
        """If apply() fails due to conflict, original file is untouched."""
        original_content = build_yaml.read_text()

        delta = {
            "adds": {
                "modules": [{"name": "core", "kind": "module"}],  # conflict
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        with pytest.raises(DeltaConflictError):
            applicator.apply()

        assert build_yaml.read_text() == original_content

    def test_no_temp_files_left_on_failure(self, build_yaml: Path) -> None:
        """No .tmp files left behind after failed apply."""
        delta = {
            "adds": {
                "modules": [{"name": "core", "kind": "module"}],
            },
        }
        applicator = BuildDeltaApplicator(build_yaml, delta)
        with pytest.raises(DeltaConflictError):
            applicator.apply()

        tmp_files = list(build_yaml.parent.glob(".build_delta_*.tmp"))
        assert tmp_files == []
