"""Tests for ContractValidator."""

from pathlib import Path

import pytest
import yaml

from spec.governance.contract_validator import ContractValidator
from spec.governance.models import Category


@pytest.fixture
def catalog_file(tmp_path: Path) -> Path:
    catalog = {
        "catalog_version": "0.1",
        "operations": [
            {"id": "pm.project.create", "status": "impl"},
            {"id": "pm.project.close", "status": "impl"},
            {"id": "pm.task.create", "status": "planned"},
            {"id": "pm.task.complete", "status": "draft"},
        ],
    }
    p = tmp_path / "op-catalog.yaml"
    p.write_text(yaml.dump(catalog))
    return p


@pytest.fixture
def code_file(tmp_path: Path) -> Path:
    code = '''
OP_CATALOG = {
    "pm.project.create": {"op": "pm.project.create"},
    "pm.project.close": {"op": "pm.project.close"},
}
'''
    p = tmp_path / "catalog.py"
    p.write_text(code)
    return p


class TestContractValidation:
    def test_clean_match(self, catalog_file: Path, code_file: Path) -> None:
        report = ContractValidator(catalog_file, code_file).validate()
        assert report.passed
        assert report.error_count == 0

    def test_declared_not_registered(self, catalog_file: Path, tmp_path: Path) -> None:
        # Code only has project.create, missing project.close
        code = '''
OP_CATALOG = {
    "pm.project.create": {"op": "pm.project.create"},
}
'''
        code_path = tmp_path / "catalog.py"
        code_path.write_text(code)

        report = ContractValidator(catalog_file, code_path).validate()
        assert not report.passed
        missing = [f for f in report.findings if f.category == Category.declared_not_registered]
        assert len(missing) == 1
        assert "pm.project.close" in missing[0].message

    def test_registered_not_declared(self, catalog_file: Path, tmp_path: Path) -> None:
        # Code has an op not in catalog
        code = '''
OP_CATALOG = {
    "pm.project.create": {},
    "pm.project.close": {},
    "pm.rogue.op": {},
}
'''
        code_path = tmp_path / "catalog.py"
        code_path.write_text(code)

        report = ContractValidator(catalog_file, code_path).validate()
        assert not report.passed
        rogue = [f for f in report.findings if f.category == Category.registered_not_declared]
        assert len(rogue) == 1
        assert "pm.rogue.op" in rogue[0].message

    def test_planned_ops_not_flagged(self, catalog_file: Path, code_file: Path) -> None:
        # pm.task.create is planned, pm.task.complete is draft — neither should error
        report = ContractValidator(catalog_file, code_file).validate()
        errors = [f for f in report.findings if f.category == Category.declared_not_registered]
        assert not any("pm.task" in f.message for f in errors)

    def test_status_mismatch_warns(self, catalog_file: Path, tmp_path: Path) -> None:
        # Code implements a "planned" op — should warn
        code = '''
OP_CATALOG = {
    "pm.project.create": {},
    "pm.project.close": {},
    "pm.task.create": {},
}
'''
        code_path = tmp_path / "catalog.py"
        code_path.write_text(code)

        report = ContractValidator(catalog_file, code_path).validate()
        assert report.passed  # Warnings don't fail
        warnings = [f for f in report.findings if f.category == Category.status_mismatch]
        assert len(warnings) == 1
        assert "pm.task.create" in warnings[0].message
