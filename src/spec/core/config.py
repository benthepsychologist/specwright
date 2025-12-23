"""Configuration loading and management for Specwright.

This module handles loading and parsing of .specwright.yaml config files,
supporting both the new minimal v0.6 format and legacy v0.1 format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import]

if TYPE_CHECKING:
    from typing import Any


class ConfigError(Exception):
    """Base exception for configuration errors."""

    pass


class ConfigNotFoundError(ConfigError):
    """Raised when no config file is found."""

    def __init__(self, searched_paths: list[Path]) -> None:
        self.searched_paths = searched_paths
        paths_str = "\n  - ".join(str(p) for p in searched_paths)
        super().__init__(
            f"No .specwright.yaml found. Searched:\n  - {paths_str}\n\n"
            "Run 'spec init' to create a configuration file."
        )


class ConfigVersionError(ConfigError):
    """Raised when config version is unsupported."""

    def __init__(self, version: str, path: Path) -> None:
        self.version = version
        self.path = path
        super().__init__(
            f"Unsupported config version '{version}' in {path}\n\n"
            "Supported versions: 0.6 (recommended), 0.1 (legacy)\n"
            "Run 'spec migrate' to upgrade your configuration."
        )


@dataclass
class GovernorConfig:
    """Governor connection settings."""

    path: str = "~/.local/local-governor"

    def resolve_path(self) -> Path:
        """Resolve the governor path to an absolute path."""
        return Path(self.path).expanduser().resolve()


@dataclass
class AutogovConfig:
    """Autogov governance integration settings."""

    enabled: bool = False
    source: str | None = None


@dataclass
class LegacyPathsConfig:
    """Legacy paths configuration (v0.1)."""

    specs: str = ".specwright/specs"
    aips: str = ".specwright/aips"


@dataclass
class LegacyUserConfig:
    """Legacy user configuration (v0.1)."""

    default_owner: str | None = None
    default_tier: str | None = None


@dataclass
class LegacyCurrentConfig:
    """Legacy current pointer configuration (v0.1)."""

    spec: str | None = None
    aip: str | None = None


@dataclass
class SpecwrightConfig:
    """Specwright configuration."""

    version: str
    config_path: Path
    project_root: Path

    # v0.6 fields
    governor: GovernorConfig = field(default_factory=GovernorConfig)
    autogov: AutogovConfig = field(default_factory=AutogovConfig)

    # Legacy v0.1 fields (deprecated)
    paths: LegacyPathsConfig | None = None
    repo: dict[str, Any] = field(default_factory=dict)
    user: LegacyUserConfig | None = None
    current: LegacyCurrentConfig | None = None

    @property
    def is_legacy(self) -> bool:
        """Check if this is a legacy config."""
        return self.version == "0.1"

    def get_governor_path(self) -> Path:
        """Get the resolved governor path."""
        return self.governor.resolve_path()


def load_config(
    start_path: Path | None = None,
    *,
    require_config: bool = True,
) -> SpecwrightConfig:
    """Load configuration from .specwright.yaml.

    Walks up the directory tree from start_path to find the config file.

    Args:
        start_path: Starting directory (defaults to cwd)
        require_config: If True, raise ConfigNotFoundError when not found

    Returns:
        Loaded configuration

    Raises:
        ConfigNotFoundError: If no config file found and require_config is True
        ConfigVersionError: If config version is unsupported
    """
    if start_path is None:
        start_path = Path.cwd()

    config_path, raw_config = _find_config(start_path)

    if config_path is None:
        if require_config:
            # Build list of searched paths
            searched = []
            current = start_path
            while current != current.parent:
                searched.append(current / ".specwright.yaml")
                current = current.parent
            raise ConfigNotFoundError(searched)
        return _default_config(start_path)

    return _parse_config(config_path, raw_config)


def _find_config(start_path: Path) -> tuple[Path | None, dict[str, Any] | None]:
    """Walk up directory tree to find .specwright.yaml.

    Returns:
        Tuple of (config_path, parsed_config) or (None, None) if not found
    """
    current = start_path.resolve()

    while current != current.parent:
        config_path = current / ".specwright.yaml"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                raw_config = yaml.safe_load(f) or {}
            return config_path, raw_config
        current = current.parent

    return None, None


def _parse_config(config_path: Path, raw: dict[str, Any]) -> SpecwrightConfig:
    """Parse raw config dict into SpecwrightConfig.

    Args:
        config_path: Path to the config file
        raw: Raw config dictionary

    Returns:
        Parsed configuration

    Raises:
        ConfigVersionError: If version is unsupported
    """
    version = str(raw.get("version", "0.6"))

    # Validate version
    if version not in ("0.1", "0.6"):
        raise ConfigVersionError(version, config_path)

    project_root = config_path.parent

    if version == "0.6":
        return _parse_v05_config(config_path, project_root, raw)
    else:
        return _parse_v01_config(config_path, project_root, raw)


def _parse_v05_config(
    config_path: Path,
    project_root: Path,
    raw: dict[str, Any],
) -> SpecwrightConfig:
    """Parse v0.6 minimal config format."""
    governor_raw = raw.get("governor", {})
    autogov_raw = raw.get("autogov", {})

    return SpecwrightConfig(
        version="0.6",
        config_path=config_path,
        project_root=project_root,
        governor=GovernorConfig(
            path=governor_raw.get("path", "~/.local/local-governor"),
        ),
        autogov=AutogovConfig(
            enabled=autogov_raw.get("enabled", False),
            source=autogov_raw.get("source"),
        ),
    )


def _parse_v01_config(
    config_path: Path,
    project_root: Path,
    raw: dict[str, Any],
) -> SpecwrightConfig:
    """Parse legacy v0.1 config format."""
    paths_raw = raw.get("paths", {})
    user_raw = raw.get("user", {})
    current_raw = raw.get("current", {})
    autogov_raw = raw.get("autogov", {})

    return SpecwrightConfig(
        version="0.1",
        config_path=config_path,
        project_root=project_root,
        # Legacy configs don't have governor, use default
        governor=GovernorConfig(),
        autogov=AutogovConfig(
            enabled=autogov_raw.get("enabled", False),
            source=autogov_raw.get("source"),
        ),
        paths=LegacyPathsConfig(
            specs=paths_raw.get("specs", ".specwright/specs"),
            aips=paths_raw.get("aips", ".specwright/aips"),
        ),
        repo=raw.get("repo", {}),
        user=LegacyUserConfig(
            default_owner=user_raw.get("default_owner"),
            default_tier=user_raw.get("default_tier"),
        ),
        current=LegacyCurrentConfig(
            spec=current_raw.get("spec"),
            aip=current_raw.get("aip"),
        ),
    )


def _default_config(project_root: Path) -> SpecwrightConfig:
    """Create a default configuration when none found."""
    return SpecwrightConfig(
        version="0.6",
        config_path=project_root / ".specwright.yaml",
        project_root=project_root,
    )


def migrate_legacy_config(config: SpecwrightConfig) -> dict[str, Any]:
    """Convert a legacy config to v0.6 format.

    Args:
        config: Legacy configuration

    Returns:
        Dictionary ready to be written as v0.6 config
    """
    result: dict[str, Any] = {"version": "0.6"}

    # Keep governor config (may be default)
    result["governor"] = {"path": config.governor.path}

    # Migrate autogov settings
    if config.autogov.enabled:
        result["autogov"] = {
            "enabled": True,
            "source": config.autogov.source,
        }

    return result


def save_config(config: SpecwrightConfig) -> None:
    """Save configuration to file.

    Args:
        config: Configuration to save
    """
    data: dict[str, Any] = {"version": config.version}

    if config.version == "0.6":
        data["governor"] = {"path": config.governor.path}
        if config.autogov.enabled:
            data["autogov"] = {
                "enabled": True,
                "source": config.autogov.source,
            }
    else:
        # Legacy format
        if config.paths:
            data["paths"] = {
                "specs": config.paths.specs,
                "aips": config.paths.aips,
            }
        if config.repo:
            data["repo"] = config.repo
        if config.user:
            data["user"] = {
                "default_owner": config.user.default_owner,
                "default_tier": config.user.default_tier,
            }
        if config.current:
            data["current"] = {
                "spec": config.current.spec,
                "aip": config.current.aip,
            }
        if config.autogov.enabled:
            data["autogov"] = {
                "enabled": True,
                "source": config.autogov.source,
            }

    with open(config.config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)
