"""AIP v3 validation using JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema

if TYPE_CHECKING:
    from spec.aip.models import AIPv3


class AIPValidationError(Exception):
    """Raised when AIP validation fails."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"AIP validation failed: {'; '.join(errors)}")


def _get_schema() -> dict[str, Any]:
    """Load the AIP v3 JSON schema."""
    schema_path = Path(__file__).parent.parent / "schemas" / "aip-v3.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_aip(aip: AIPv3 | dict[str, Any]) -> list[str]:
    """Validate an AIP against the v3 schema.

    Args:
        aip: An AIPv3 instance or dictionary

    Returns:
        List of validation error messages (empty if valid)
    """
    if hasattr(aip, "to_dict"):
        data = aip.to_dict()
    else:
        data = aip

    schema = _get_schema()
    validator = jsonschema.Draft202012Validator(schema)

    errors: list[str] = []
    for error in validator.iter_errors(data):
        path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
        errors.append(f"{path}: {error.message}")

    return errors


def validate_aip_strict(aip: AIPv3 | dict[str, Any]) -> None:
    """Validate an AIP and raise if invalid.

    Args:
        aip: An AIPv3 instance or dictionary

    Raises:
        AIPValidationError: If validation fails
    """
    errors = validate_aip(aip)
    if errors:
        raise AIPValidationError(errors)
