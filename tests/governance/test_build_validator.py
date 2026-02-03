"""Tests for BuildValidator."""

from pathlib import Path

import pytest

from spec.governance.build_validator import BuildValidator
from spec.governance.models import Category


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure for testing."""
    (tmp_path / "src" / "mymod").mkdir(parents=True)
    (tmp_path / "src" / "mymod" / "__init__.py").write_text("")
    (tmp_path / "src" / "mymod" / "core.py").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text("")
    return tmp_path


def _make_build(
    layout=None, modules=None, slots=None, frozen=None, rules=None,
) -> dict:
    base: dict = {
        "kind": "project.build",
        "version": "0.1",
        "metadata": {"name": "mymod", "semver": "0.1.0"},
        "kernel": {"description": "test"},
    }
    if layout is not None:
        base["layout"] = layout
    if modules is not None:
        base["modules"] = modules
    if slots is not None:
        base["slots"] = slots
    if frozen is not None:
        base["frozen"] = frozen
    if rules is not None:
        base["rules"] = rules
    return base


class TestLayoutValidation:
    def test_clean_layout(self, tmp_repo: Path) -> None:
        build = _make_build(layout=[
            {"path": "src/mymod/__init__.py", "module": "public", "role": "entry"},
            {"path": "src/mymod/core.py", "module": "core", "role": "core logic"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed
        assert report.error_count == 0

    def test_missing_layout_path(self, tmp_repo: Path) -> None:
        build = _make_build(layout=[
            {"path": "src/mymod/__init__.py", "module": "public", "role": "entry"},
            {"path": "src/mymod/missing.py", "module": "missing", "role": "gone"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert not report.passed
        assert report.error_count == 1
        assert report.findings[0].category == Category.missing_path
        assert "missing.py" in report.findings[0].message

    def test_empty_layout_is_clean(self, tmp_repo: Path) -> None:
        build = _make_build(layout=[])
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_no_layout_section(self, tmp_repo: Path) -> None:
        build = _make_build()
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed


class TestSlotValidation:
    def test_slot_dir_exists(self, tmp_repo: Path) -> None:
        build = _make_build(slots=[
            {"name": "tests", "path": "tests", "file_pattern": "*.py"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_slot_dir_missing(self, tmp_repo: Path) -> None:
        build = _make_build(slots=[
            {"name": "plugins", "path": "plugins/"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert not report.passed
        assert report.findings[0].category == Category.missing_slot_dir

    def test_slot_optional_missing_ok(self, tmp_repo: Path) -> None:
        build = _make_build(slots=[
            {"name": "plugins", "path": "plugins/", "optional": True},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_slot_no_matching_files_warns(self, tmp_repo: Path) -> None:
        (tmp_repo / "empty_slot").mkdir()
        build = _make_build(slots=[
            {"name": "empty", "path": "empty_slot", "file_pattern": "*.py"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed  # Warning, not error
        assert report.warning_count == 1


class TestFrozenValidation:
    def test_frozen_exists(self, tmp_repo: Path) -> None:
        build = _make_build(frozen=[
            {"path": "src/mymod/__init__.py", "reason": "public API"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_frozen_missing(self, tmp_repo: Path) -> None:
        build = _make_build(frozen=[
            {"path": "src/mymod/gone.py", "reason": "was important"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert not report.passed
        assert report.findings[0].category == Category.frozen_missing


class TestPlacementRules:
    def test_no_violation(self, tmp_repo: Path) -> None:
        build = _make_build(rules={
            "placement": [{
                "id": "no-extra",
                "forbid_glob_in": ["src/mymod/*.py"],
                "allowlist": ["__init__.py", "core.py"],
                "message": "No extra files",
                "severity": "error",
            }],
        })
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_violation_detected(self, tmp_repo: Path) -> None:
        # Add an un-allowlisted file
        (tmp_repo / "src" / "mymod" / "rogue.py").write_text("")
        build = _make_build(rules={
            "placement": [{
                "id": "no-extra",
                "forbid_glob_in": ["src/mymod/*.py"],
                "allowlist": ["__init__.py", "core.py"],
                "message": "No extra files",
                "severity": "error",
            }],
        })
        report = BuildValidator(tmp_repo, build).validate()
        assert not report.passed
        assert report.findings[0].category == Category.placement_violation
        assert "no-extra" in report.findings[0].message


class TestModuleDeps:
    def test_valid_deps(self, tmp_repo: Path) -> None:
        build = _make_build(modules=[
            {"name": "core", "kind": "module", "provides": ["CoreClass"]},
            {"name": "api", "kind": "entrypoint", "provides": ["app"], "depends_on": ["core"]},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_broken_dep(self, tmp_repo: Path) -> None:
        build = _make_build(modules=[
            {"name": "api", "kind": "entrypoint", "provides": ["app"], "depends_on": ["nonexistent"]},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert not report.passed
        assert report.findings[0].category == Category.module_ref_broken


class TestUndeclaredFiles:
    def test_undeclared_file_warned(self, tmp_repo: Path) -> None:
        """Files on disk not in layout should produce a warning."""
        build = _make_build(layout=[
            {"path": "src/mymod/__init__.py", "module": "public", "role": "entry"},
            # core.py exists on disk but is NOT declared
        ])
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed  # Warnings don't fail
        undeclared = [f for f in report.findings if f.category == Category.undeclared_path]
        assert len(undeclared) == 1
        assert "core.py" in undeclared[0].path

    def test_no_undeclared_when_all_declared(self, tmp_repo: Path) -> None:
        """No undeclared warnings when all files are in layout."""
        build = _make_build(layout=[
            {"path": "src/mymod/__init__.py", "module": "public", "role": "entry"},
            {"path": "src/mymod/core.py", "module": "core", "role": "logic"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        undeclared = [f for f in report.findings if f.category == Category.undeclared_path]
        assert len(undeclared) == 0

    def test_directory_layout_covers_children(self, tmp_repo: Path) -> None:
        """A directory entry in layout should cover all files beneath it."""
        # Create some files under a handlers/ directory
        (tmp_repo / "src" / "mymod" / "handlers").mkdir()
        (tmp_repo / "src" / "mymod" / "handlers" / "base.py").write_text("")
        (tmp_repo / "src" / "mymod" / "handlers" / "http.py").write_text("")

        build = _make_build(layout=[
            {"path": "src/mymod/__init__.py", "module": "public", "role": "entry"},
            {"path": "src/mymod/core.py", "module": "core", "role": "logic"},
            {"path": "src/mymod/handlers/", "module": "handlers", "role": "handlers"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        undeclared = [f for f in report.findings if f.category == Category.undeclared_path]
        assert len(undeclared) == 0

    def test_undeclared_in_subdirectory(self, tmp_repo: Path) -> None:
        """Undeclared files in subdirectories should also be caught."""
        (tmp_repo / "src" / "mymod" / "utils").mkdir()
        (tmp_repo / "src" / "mymod" / "utils" / "helpers.py").write_text("")

        build = _make_build(layout=[
            {"path": "src/mymod/__init__.py", "module": "public", "role": "entry"},
            {"path": "src/mymod/core.py", "module": "core", "role": "logic"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        undeclared = [f for f in report.findings if f.category == Category.undeclared_path]
        assert len(undeclared) == 1
        assert "helpers.py" in undeclared[0].path

    def test_empty_layout_skips_undeclared(self, tmp_repo: Path) -> None:
        """Empty layout should not trigger undeclared checks."""
        build = _make_build(layout=[])
        report = BuildValidator(tmp_repo, build).validate()
        undeclared = [f for f in report.findings if f.category == Category.undeclared_path]
        assert len(undeclared) == 0

    def test_flat_package_layout(self, tmp_path: Path) -> None:
        """Works for flat-package layouts (e.g., lorchestra/ not src/lorchestra/)."""
        (tmp_path / "mypkg").mkdir()
        (tmp_path / "mypkg" / "__init__.py").write_text("")
        (tmp_path / "mypkg" / "core.py").write_text("")
        (tmp_path / "mypkg" / "rogue.py").write_text("")

        build = _make_build(layout=[
            {"path": "mypkg/__init__.py", "module": "public", "role": "entry"},
            {"path": "mypkg/core.py", "module": "core", "role": "logic"},
        ])
        report = BuildValidator(tmp_path, build).validate()
        undeclared = [f for f in report.findings if f.category == Category.undeclared_path]
        assert len(undeclared) == 1
        assert "rogue.py" in undeclared[0].path


class TestNullSections:
    """Build YAML sections can be explicitly null."""

    def test_null_layout(self, tmp_repo: Path) -> None:
        build = _make_build(layout=None)
        # Simulate YAML parsing returning None for "layout: null"
        build["layout"] = None
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_null_slots(self, tmp_repo: Path) -> None:
        build = _make_build()
        build["slots"] = None
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_null_frozen(self, tmp_repo: Path) -> None:
        build = _make_build()
        build["frozen"] = None
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_null_modules(self, tmp_repo: Path) -> None:
        build = _make_build()
        build["modules"] = None
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed

    def test_null_rules(self, tmp_repo: Path) -> None:
        build = _make_build()
        build["rules"] = None
        report = BuildValidator(tmp_repo, build).validate()
        assert report.passed


class TestReportSerialization:
    def test_to_json(self, tmp_repo: Path) -> None:
        build = _make_build(layout=[
            {"path": "src/mymod/missing.py", "module": "m", "role": "r"},
            {"path": "src/mymod/__init__.py", "module": "pub", "role": "entry"},
            {"path": "src/mymod/core.py", "module": "core", "role": "logic"},
        ])
        report = BuildValidator(tmp_repo, build).validate()
        import json
        data = json.loads(report.to_json())
        assert data["passed"] is False
        errors = [f for f in data["findings"] if f["severity"] == "error"]
        assert len(errors) == 1
        assert errors[0]["category"] == "missing_path"
