"""Autogov integration for governance-enriched specs and execution contracts.

This module provides lazy loading of autogov artifacts to keep the rest of
specwright functional even if autogov is not installed or broken.

Only exceptions and the GovernanceLoader/GovernanceBundle are exported.
No autogov imports happen at module load time.
"""

from .context_builder import SpecContextBuilder
from .exceptions import (
    AutogovNotInstalledError,
    CLIUsageError,
    GovernanceInvalidError,
    GovernanceNotFoundError,
    RegistryConfigError,
    SpecwrightError,
)
from .loader import GovernanceBundle, GovernanceLoader

__all__ = [
    # Exceptions
    "SpecwrightError",
    "AutogovNotInstalledError",
    "GovernanceNotFoundError",
    "GovernanceInvalidError",
    "RegistryConfigError",
    "CLIUsageError",
    # Loader
    "GovernanceLoader",
    "GovernanceBundle",
    # Context Builder
    "SpecContextBuilder",
]
