"""AIP v3 - Context Packet models and utilities.

This package provides the core data structures and operations for AIP v3,
the epic-driven execution model that replaces the old step-gating executor.
"""

from spec.aip.compiler import (
    CompileError,
    SpecNotFoundError,
    compile_from_aip_file,
    compile_from_epic,
    get_aip_storage_path,
    load_compiled_aip,
    save_compiled_aip,
)
from spec.aip.enricher import (
    EnrichError,
    EnrichMode,
    EnrichResult,
    enrich_aip,
)
from spec.aip.models import (
    AIPExecution,
    AIPMetadata,
    AIPStep,
    AIPStepGuidance,
    AIPv3,
    AIPVerification,
    AIPWorkspace,
    PatternReference,
    WorkspaceMode,
)
from spec.aip.validation import validate_aip

__all__ = [
    # Models
    "AIPv3",
    "AIPExecution",
    "AIPMetadata",
    "AIPStep",
    "AIPStepGuidance",
    "AIPVerification",
    "AIPWorkspace",
    "PatternReference",
    "WorkspaceMode",
    # Validation
    "validate_aip",
    # Compiler
    "CompileError",
    "SpecNotFoundError",
    "compile_from_aip_file",
    "compile_from_epic",
    "get_aip_storage_path",
    "load_compiled_aip",
    "save_compiled_aip",
    # Enricher
    "EnrichError",
    "EnrichMode",
    "EnrichResult",
    "enrich_aip",
]
