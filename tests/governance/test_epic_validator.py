"""Tests for EpicValidator."""

from pathlib import Path

import pytest

from spec.governance.epic_validator import EpicValidator
from spec.governance.models import Category


@pytest.fixture
def epic_dir(tmp_path: Path) -> Path:
    """Create a mini epic directory."""
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "e001-01-core.md").write_text("# core\n")
    (specs / "e001-02-api.md").write_text("# api\n")
    return tmp_path


def _make_epic(targets=None, specs=None) -> dict:
    base: dict = {
        "id": "test-epic",
        "title": "Test Epic",
        "targets": targets or [],
        "specs": specs or [],
    }
    return base


class TestTargetValidation:
    def test_valid_target(self, epic_dir: Path) -> None:
        epic = _make_epic(targets=[
            {"id": "myrepo", "repo_path": str(epic_dir), "default_branch": "main"},
        ])
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        missing_repo = [f for f in report.findings if f.category == Category.missing_repo]
        assert len(missing_repo) == 0

    def test_missing_target_repo(self, epic_dir: Path) -> None:
        epic = _make_epic(targets=[
            {"id": "gone", "repo_path": "/nonexistent/repo", "default_branch": "main"},
        ])
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        assert any(f.category == Category.missing_repo for f in report.findings)


class TestSpecFileValidation:
    def test_spec_files_exist(self, epic_dir: Path) -> None:
        epic = _make_epic(specs=[
            {"id": "e001-01-core", "repo": "myrepo", "branch": "feat/core", "path": "specs/e001-01-core.md"},
            {"id": "e001-02-api", "repo": "myrepo", "branch": "feat/api", "path": "specs/e001-02-api.md"},
        ])
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        missing = [f for f in report.findings if f.category == Category.missing_path]
        assert len(missing) == 0

    def test_missing_spec_file(self, epic_dir: Path) -> None:
        epic = _make_epic(specs=[
            {"id": "e001-03-gone", "repo": "myrepo", "branch": "feat/gone", "path": "specs/e001-03-gone.md"},
        ])
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        assert any(f.category == Category.missing_path for f in report.findings)


class TestDependsOnValidation:
    def test_valid_deps(self, epic_dir: Path) -> None:
        epic = _make_epic(specs=[
            {"id": "s1", "repo": "r", "branch": "b"},
            {"id": "s2", "repo": "r", "branch": "b", "depends_on": ["s1"]},
        ])
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        unresolved = [f for f in report.findings if f.category == Category.unresolved_depends]
        assert len(unresolved) == 0

    def test_broken_dep(self, epic_dir: Path) -> None:
        epic = _make_epic(specs=[
            {"id": "s1", "repo": "r", "branch": "b", "depends_on": ["nonexistent"]},
        ])
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        assert any(f.category == Category.unresolved_depends for f in report.findings)


class TestBuildYamlValidation:
    def test_build_yaml_present(self, epic_dir: Path) -> None:
        epic = _make_epic(targets=[
            {"id": "myrepo", "repo_path": str(epic_dir), "default_branch": "main", "governor_project": "myrepo"},
        ])
        builds = {"myrepo": {"kind": "project.build"}}
        report = EpicValidator(epic, builds, epic_dir=epic_dir).validate()
        missing = [f for f in report.findings if f.category == Category.missing_build_yaml]
        assert len(missing) == 0

    def test_build_yaml_missing(self, epic_dir: Path) -> None:
        epic = _make_epic(targets=[
            {"id": "myrepo", "repo_path": str(epic_dir), "default_branch": "main", "governor_project": "myrepo"},
        ])
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        assert any(f.category == Category.missing_build_yaml for f in report.findings)


class TestSpecTargetRefs:
    def test_valid_target_ref(self, epic_dir: Path) -> None:
        epic = _make_epic(
            targets=[{"id": "myrepo", "repo_path": str(epic_dir), "default_branch": "main"}],
            specs=[{"id": "s1", "repo": "myrepo", "branch": "b"}],
        )
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        bad_refs = [f for f in report.findings if f.category == Category.missing_repo and "target" in f.message.lower()]
        assert len(bad_refs) == 0

    def test_invalid_target_ref(self, epic_dir: Path) -> None:
        epic = _make_epic(
            targets=[{"id": "myrepo", "repo_path": str(epic_dir), "default_branch": "main"}],
            specs=[{"id": "s1", "repo": "other_repo", "branch": "b"}],
        )
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        assert any(
            f.category == Category.missing_repo and "other_repo" in f.message
            for f in report.findings
        )


class TestExpectationsVsBuild:
    """Tests for spec expectations referencing modules in build.yaml."""

    def test_expectation_path_in_layout_ok(self, epic_dir: Path) -> None:
        """Expectation referencing a path in build.yaml layout produces no finding."""
        builds = {"myrepo": {
            "layout": [{"path": "src/workman/intent.py", "module": "intent", "role": "x"}],
            "modules": [],
        }}
        epic = _make_epic(
            targets=[{"id": "myrepo", "repo_path": str(epic_dir), "governor_project": "myrepo"}],
            specs=[{
                "id": "s1", "repo": "myrepo", "branch": "b",
                "expectations": ["Adds src/workman/intent.py for intent compilation"],
            }],
        )
        report = EpicValidator(epic, builds, epic_dir=epic_dir).validate()
        exp_findings = [f for f in report.findings if f.category == Category.expectation_module_missing]
        assert len(exp_findings) == 0

    def test_expectation_path_not_in_layout_warns(self, epic_dir: Path) -> None:
        """Expectation referencing a path NOT in build.yaml layout produces warning."""
        builds = {"myrepo": {
            "layout": [{"path": "src/workman/core.py", "module": "core", "role": "x"}],
            "modules": [],
        }}
        epic = _make_epic(
            targets=[{"id": "myrepo", "repo_path": str(epic_dir), "governor_project": "myrepo"}],
            specs=[{
                "id": "s1", "repo": "myrepo", "branch": "b",
                "expectations": ["Adds src/workman/intent.py for intent compilation"],
            }],
        )
        report = EpicValidator(epic, builds, epic_dir=epic_dir).validate()
        exp_findings = [f for f in report.findings if f.category == Category.expectation_module_missing]
        assert len(exp_findings) == 1
        assert "intent.py" in exp_findings[0].message

    def test_no_expectations_no_findings(self, epic_dir: Path) -> None:
        """Specs without expectations produce no expectation findings."""
        builds = {"myrepo": {"layout": [], "modules": []}}
        epic = _make_epic(
            targets=[{"id": "myrepo", "repo_path": str(epic_dir), "governor_project": "myrepo"}],
            specs=[{"id": "s1", "repo": "myrepo", "branch": "b"}],
        )
        report = EpicValidator(epic, builds, epic_dir=epic_dir).validate()
        exp_findings = [f for f in report.findings if f.category == Category.expectation_module_missing]
        assert len(exp_findings) == 0

    def test_no_build_yaml_skips_check(self, epic_dir: Path) -> None:
        """Expectations check skipped when no build.yaml available for target."""
        epic = _make_epic(
            targets=[{"id": "myrepo", "repo_path": str(epic_dir)}],
            specs=[{
                "id": "s1", "repo": "myrepo", "branch": "b",
                "expectations": ["Adds src/missing/thing.py"],
            }],
        )
        report = EpicValidator(epic, {}, epic_dir=epic_dir).validate()
        exp_findings = [f for f in report.findings if f.category == Category.expectation_module_missing]
        assert len(exp_findings) == 0


class TestBuildDeltaConflicts:
    """Tests for build_delta conflict detection."""

    def test_delta_adds_new_module_ok(self, epic_dir: Path) -> None:
        """Adding a module that doesn't exist in build.yaml is clean."""
        builds = {"workman": {
            "modules": [{"name": "core", "kind": "module"}],
            "layout": [],
        }}
        epic = _make_epic(specs=[{
            "id": "s1", "repo": "workman", "branch": "b",
            "build_delta": {
                "target": "projects/workman/workman.build.yaml",
                "summary": "Add intent",
                "adds": {"modules": [{"name": "intent", "kind": "module"}]},
            },
        }])
        report = EpicValidator(epic, builds, epic_dir=epic_dir).validate()
        delta_findings = [f for f in report.findings if f.category == Category.build_delta_conflict]
        assert len(delta_findings) == 0

    def test_delta_adds_existing_module_warns(self, epic_dir: Path) -> None:
        """Adding a module that already exists produces a warning."""
        builds = {"workman": {
            "modules": [{"name": "intent", "kind": "module"}],
            "layout": [],
        }}
        epic = _make_epic(specs=[{
            "id": "s1", "repo": "workman", "branch": "b",
            "build_delta": {
                "target": "projects/workman/workman.build.yaml",
                "summary": "Add intent",
                "adds": {"modules": [{"name": "intent", "kind": "module"}]},
            },
        }])
        report = EpicValidator(epic, builds, epic_dir=epic_dir).validate()
        delta_findings = [f for f in report.findings if f.category == Category.build_delta_conflict]
        assert len(delta_findings) == 1
        assert "already exists" in delta_findings[0].message

    def test_delta_modifies_nonexistent_module_errors(self, epic_dir: Path) -> None:
        """Modifying a module that doesn't exist is an error."""
        builds = {"workman": {
            "modules": [{"name": "core", "kind": "module"}],
            "layout": [],
        }}
        epic = _make_epic(specs=[{
            "id": "s1", "repo": "workman", "branch": "b",
            "build_delta": {
                "target": "projects/workman/workman.build.yaml",
                "summary": "Modify ghost",
                "modifies": {"modules": [{"name": "ghost", "kind": "module"}]},
            },
        }])
        report = EpicValidator(epic, builds, epic_dir=epic_dir).validate()
        delta_findings = [f for f in report.findings if f.category == Category.build_delta_conflict]
        assert len(delta_findings) == 1
        assert not report.passed  # Error-severity

    def test_delta_adds_existing_layout_warns(self, epic_dir: Path) -> None:
        """Adding a layout path that already exists produces a warning."""
        builds = {"workman": {
            "modules": [],
            "layout": [{"path": "src/workman/intent.py", "module": "intent", "role": "x"}],
        }}
        epic = _make_epic(specs=[{
            "id": "s1", "repo": "workman", "branch": "b",
            "build_delta": {
                "target": "projects/workman/workman.build.yaml",
                "summary": "Add intent",
                "adds": {"layout": [{"path": "src/workman/intent.py", "module": "intent"}]},
            },
        }])
        report = EpicValidator(epic, builds, epic_dir=epic_dir).validate()
        delta_findings = [f for f in report.findings if f.category == Category.build_delta_conflict]
        assert len(delta_findings) == 1
        assert "layout" in delta_findings[0].message

    def test_no_delta_no_findings(self, epic_dir: Path) -> None:
        """Specs without build_delta produce no delta findings."""
        builds = {"workman": {"modules": [], "layout": []}}
        epic = _make_epic(specs=[{"id": "s1", "repo": "workman", "branch": "b"}])
        report = EpicValidator(epic, builds, epic_dir=epic_dir).validate()
        delta_findings = [f for f in report.findings if f.category == Category.build_delta_conflict]
        assert len(delta_findings) == 0


class TestOpCatalogRefs:
    """Tests for op-catalog cross-reference in spec expectations."""

    def test_op_ref_in_catalog_ok(self, epic_dir: Path) -> None:
        """Op reference that exists in catalog produces no finding."""
        op_catalog = {"operations": [
            {"id": "pm.project.create", "status": "impl"},
        ]}
        epic = _make_epic(specs=[{
            "id": "s1", "repo": "r", "branch": "b",
            "expectations": ["pm.project.create operation is implemented"],
        }])
        report = EpicValidator(epic, {}, epic_dir=epic_dir, op_catalog=op_catalog).validate()
        op_findings = [f for f in report.findings if f.category == Category.op_catalog_missing]
        assert len(op_findings) == 0

    def test_op_ref_not_in_catalog_warns(self, epic_dir: Path) -> None:
        """Op reference NOT in catalog produces warning."""
        op_catalog = {"operations": [
            {"id": "pm.project.create", "status": "impl"},
        ]}
        epic = _make_epic(specs=[{
            "id": "s1", "repo": "r", "branch": "b",
            "expectations": ["pm.intent.compile operation is functional"],
        }])
        report = EpicValidator(epic, {}, epic_dir=epic_dir, op_catalog=op_catalog).validate()
        op_findings = [f for f in report.findings if f.category == Category.op_catalog_missing]
        assert len(op_findings) == 1
        assert "pm.intent.compile" in op_findings[0].message

    def test_no_catalog_skips_check(self, epic_dir: Path) -> None:
        """Without op-catalog, the check is skipped entirely."""
        epic = _make_epic(specs=[{
            "id": "s1", "repo": "r", "branch": "b",
            "expectations": ["pm.fake.op should work"],
        }])
        report = EpicValidator(epic, {}, epic_dir=epic_dir, op_catalog=None).validate()
        op_findings = [f for f in report.findings if f.category == Category.op_catalog_missing]
        assert len(op_findings) == 0

    def test_empty_catalog_no_crash(self, epic_dir: Path) -> None:
        """Empty op-catalog (no operations) doesn't crash."""
        op_catalog: dict = {"operations": []}
        epic = _make_epic(specs=[{
            "id": "s1", "repo": "r", "branch": "b",
            "expectations": ["pm.project.create works"],
        }])
        report = EpicValidator(epic, {}, epic_dir=epic_dir, op_catalog=op_catalog).validate()
        # No declared ops → nothing to match against → no findings
        op_findings = [f for f in report.findings if f.category == Category.op_catalog_missing]
        assert len(op_findings) == 0
