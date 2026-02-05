"""Shared data models for governance validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    error = "error"
    warning = "warning"


class Category(str, Enum):
    # build validation
    missing_path = "missing_path"
    undeclared_path = "undeclared_path"
    missing_slot_dir = "missing_slot_dir"
    frozen_missing = "frozen_missing"
    placement_violation = "placement_violation"
    module_ref_broken = "module_ref_broken"
    # epic validation
    unresolved_depends = "unresolved_depends"
    missing_repo = "missing_repo"
    missing_build_yaml = "missing_build_yaml"
    expectation_module_missing = "expectation_module_missing"
    build_delta_conflict = "build_delta_conflict"
    op_catalog_missing = "op_catalog_missing"
    # contract validation
    declared_not_registered = "declared_not_registered"
    registered_not_declared = "registered_not_declared"
    status_mismatch = "status_mismatch"


@dataclass
class Finding:
    severity: Severity
    category: Category
    path: str
    message: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "category": self.category.value,
            "path": self.path,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    target: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(f.severity == Severity.error for f in self.findings)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.error)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.warning)

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "findings": [f.to_dict() for f in self.findings],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
