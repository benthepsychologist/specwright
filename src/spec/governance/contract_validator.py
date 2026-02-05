"""Contract validator: compare op-catalog.yaml against code registrations.

Uses AST parsing to extract registered operation IDs from code catalogs
and cross-references them against the declared operations in op-catalog.yaml.

Checks:
- Operations with status=impl in catalog but not registered in code
- Operations registered in code but not declared in catalog
- Status mismatches (registered in code but catalog status is not impl)
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml  # type: ignore[import]

from spec.governance.models import (
    Category,
    Finding,
    Severity,
    ValidationReport,
)


class ContractValidator:
    """Validate op-catalog.yaml against code registrations."""

    def __init__(self, catalog_path: Path, code_catalog_path: Path) -> None:
        self.catalog_path = catalog_path
        self.code_catalog_path = code_catalog_path

    def validate(self) -> ValidationReport:
        report = ValidationReport(target="contracts")

        declared = self._load_declared_ops()
        registered = self._extract_registered_ops()

        # Only compare ops that are marked as implemented
        impl_declared = {op_id for op_id, status in declared.items() if status == "impl"}

        # Declared (impl) but not registered in code
        for op_id in sorted(impl_declared - registered):
            report.findings.append(Finding(
                severity=Severity.error,
                category=Category.declared_not_registered,
                path=str(self.code_catalog_path),
                message=f"Op '{op_id}' is declared as impl in op-catalog but not registered in code",
            ))

        # Registered in code but not declared in catalog at all
        all_declared = set(declared.keys())
        for op_id in sorted(registered - all_declared):
            report.findings.append(Finding(
                severity=Severity.error,
                category=Category.registered_not_declared,
                path=str(self.catalog_path),
                message=f"Op '{op_id}' is registered in code but not declared in op-catalog",
            ))

        # Registered in code but declared with non-impl status (planned, draft, etc.)
        for op_id in sorted(registered & (all_declared - impl_declared)):
            status = declared[op_id]
            report.findings.append(Finding(
                severity=Severity.warning,
                category=Category.status_mismatch,
                path=op_id,
                message=f"Op '{op_id}' is registered in code but catalog status is '{status}' (not impl)",
            ))

        return report

    def _load_declared_ops(self) -> dict[str, str]:
        """Load op IDs and their status from op-catalog.yaml.

        Returns:
            Dict mapping op_id → status (e.g., "impl", "planned", "draft").
        """
        catalog = yaml.safe_load(self.catalog_path.read_text())
        ops = catalog.get("operations", [])
        return {
            op.get("id", ""): op.get("status", "planned")
            for op in ops
            if op.get("id")
        }

    def _extract_registered_ops(self) -> set[str]:
        """Extract registered operation IDs from the OP_CATALOG dict.

        Finds the ``OP_CATALOG = {...}`` assignment via AST and extracts
        its string keys.  Only that dict is inspected — other dicts in the
        file are ignored.
        """
        source = self.code_catalog_path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise ValueError(
                f"Cannot parse {self.code_catalog_path}: {e}"
            ) from e

        # Find OP_CATALOG = { ... } assignment
        catalog_dict: ast.Dict | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "OP_CATALOG":
                        if isinstance(node.value, ast.Dict):
                            catalog_dict = node.value
                            break
            if catalog_dict is not None:
                break

        if catalog_dict is None:
            return set()

        ops: set[str] = set()
        for key in catalog_dict.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                ops.add(key.value)

        return ops
