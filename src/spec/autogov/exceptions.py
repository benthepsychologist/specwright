"""Centralized exceptions with exit codes for CLI handling."""


class SpecwrightError(Exception):
    """Base exception with exit code for centralized CLI handling."""

    exit_code: int = 1

    def __init__(self, message: str, exit_code: int | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class AutogovNotInstalledError(SpecwrightError):
    """Autogov package is not installed or failed to import."""

    exit_code = 1


class GovernanceNotFoundError(SpecwrightError):
    """Governance artifact (policy/arch) not found in registry."""

    exit_code = 2


class GovernanceInvalidError(SpecwrightError):
    """Governance artifact is malformed or failed validation."""

    exit_code = 3


class RegistryConfigError(SpecwrightError):
    """Registry configuration is missing or invalid in .specwright.yaml."""

    exit_code = 4


class CLIUsageError(SpecwrightError):
    """CLI argument/option usage error."""

    exit_code = 5


class SepFileError(SpecwrightError):
    """SEP file is missing, malformed, or schema-invalid."""

    exit_code = 6


class SepMismatchError(SpecwrightError):
    """SEP does not match current AIP/step, or violates contract safety."""

    exit_code = 7
