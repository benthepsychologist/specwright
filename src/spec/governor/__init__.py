"""Governor integration module for local-governor interaction.

This module provides the L0 integration layer for Specwright, enabling
read/write access to the local-governor centralized storage for specs,
AIPs, errors, and provenance records.

Key components:
- GovernorLocator: Find and validate local-governor path
- GovernorReader: Read specs and AIPs from local-governor
- GovernorWriter: Write specs, AIPs, errors, and provenance to local-governor
- Materializer: Copy AIPs to repo workspaces for execution
- ErrorRecord: Structured error record dataclass
- ProvenanceSnapshot: Execution provenance dataclass
- TargetResolver: Resolve multi-repo targets from specs
- AIPSplitter: Split multi-repo specs into repo-scoped AIPs
- MultiRepoCoordinator: Coordinate cross-repo execution
"""

from spec.governor.coordinator import (
    MultiRepoCoordinator,
    MultiRepoExecutionResult,
    RepoExecutionResult,
)
from spec.governor.errors import ErrorRecord, ErrorType
from spec.governor.locator import (
    GovernorLocator,
    GovernorNotFoundError,
    GovernorPaths,
    GovernorValidationError,
)
from spec.governor.materializer import Materializer
from spec.governor.provenance import GovernanceSnapshot, ProvenanceSnapshot, RunStatus
from spec.governor.reader import GovernorReader
from spec.governor.splitter import AIPSplitter, SplitAIP, compile_multi_repo_spec
from spec.governor.targets import RepoTarget, TargetResolutionError, TargetResolver
from spec.governor.writer import GovernorWriter

__all__ = [
    # Locator
    "GovernorLocator",
    "GovernorPaths",
    "GovernorNotFoundError",
    "GovernorValidationError",
    # Reader/Writer
    "GovernorReader",
    "GovernorWriter",
    # Materializer
    "Materializer",
    # Error Records
    "ErrorRecord",
    "ErrorType",
    # Provenance
    "ProvenanceSnapshot",
    "GovernanceSnapshot",
    "RunStatus",
    # Multi-repo support
    "TargetResolver",
    "TargetResolutionError",
    "RepoTarget",
    "AIPSplitter",
    "SplitAIP",
    "compile_multi_repo_spec",
    "MultiRepoCoordinator",
    "MultiRepoExecutionResult",
    "RepoExecutionResult",
]
