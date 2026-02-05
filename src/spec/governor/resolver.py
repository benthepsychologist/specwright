"""Epic and spec resolver with prefix matching.

The local-governor layout is epic-centric:
  epics/{epic_id}/epic.yaml
  epics/{epic_id}/specs/{spec_id}.md

Naming convention is hierarchical:
  Epic dirs:  t004-specwright-governance
  Spec files: t004-01-validation-commands.md

A short prefix like "t004" resolves to the epic, "t004-01" resolves to
the spec within it. This module provides prefix-based resolution with
unambiguous matching — if multiple candidates match, the caller gets
a clear list to choose from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ResolveError(Exception):
    """Resolution failed — not found or ambiguous."""

    def __init__(self, query: str, candidates: list[str] | None = None) -> None:
        self.query = query
        self.candidates = candidates or []
        if self.candidates:
            options = "\n  ".join(self.candidates)
            msg = f"Ambiguous prefix '{query}', matches:\n  {options}"
        else:
            msg = f"No match for '{query}'"
        super().__init__(msg)


@dataclass(frozen=True)
class ResolvedEpic:
    """A resolved epic directory."""

    epic_id: str
    epic_dir: Path
    epic_yaml: Path


@dataclass(frozen=True)
class ResolvedSpec:
    """A resolved spec file within an epic."""

    epic: ResolvedEpic
    spec_id: str
    spec_path: Path


def _get_governor_root() -> Path:
    """Get governor root via the standard locator (env → config → default)."""
    from spec.governor.locator import GovernorLocator

    try:
        return GovernorLocator().find(ensure_dirs=False).root
    except Exception:
        # Fallback: locator may fail if projects/ dir doesn't exist yet.
        # Use the same env var the locator checks, then the default.
        env_root = os.environ.get(GovernorLocator.ENV_VAR)
        if env_root:
            return Path(env_root).expanduser().resolve()
        return GovernorLocator.DEFAULT_PATH


def _epics_dir(governor_root: Path | None = None) -> Path:
    root = governor_root or _get_governor_root()
    return root / "epics"


def _iter_epic_dirs(epics_root: Path):
    """Yield all epic directories under an epics/ root.

    Supports multiple layouts, including:
    - Flat: epics/t004-specwright-governance/epic.yaml
    - Letter-grouped: epics/t/t004-specwright-governance/epic.yaml
    - Domain/grouped: epics/t-tooling/t005-vmctl-docker-isolation/epic.yaml

    Implementation detail: we treat any directory containing an epic.yaml
    anywhere under epics/ as an epic directory.
    """
    if not epics_root.exists():
        return

    seen: set[Path] = set()
    for epic_yaml in sorted(epics_root.rglob("epic.yaml")):
        epic_dir = epic_yaml.parent
        if not epic_dir.is_dir() or epic_dir in seen:
            continue
        seen.add(epic_dir)
        yield epic_dir


def resolve_epic(prefix: str, governor_root: Path | None = None) -> ResolvedEpic:
    """Resolve a prefix to a single epic directory.

    Args:
        prefix: Short prefix like "t004" or full ID like "t004-specwright-governance".
        governor_root: Override governor root (for testing).

    Returns:
        ResolvedEpic with paths.

    Raises:
        ResolveError: If no match or ambiguous.
    """
    epics = _epics_dir(governor_root)
    if not epics.exists():
        raise ResolveError(prefix)

    candidates: list[Path] = []
    for d in _iter_epic_dirs(epics):
        if d.name.startswith(prefix):
            candidates.append(d)

    if len(candidates) == 0:
        raise ResolveError(prefix)
    if len(candidates) == 1:
        d = candidates[0]
        return ResolvedEpic(epic_id=d.name, epic_dir=d, epic_yaml=d / "epic.yaml")

    # Exact match takes priority over prefix matches
    for d in candidates:
        if d.name == prefix:
            return ResolvedEpic(epic_id=d.name, epic_dir=d, epic_yaml=d / "epic.yaml")

    raise ResolveError(prefix, [d.name for d in candidates])


def resolve_spec(query: str, governor_root: Path | None = None) -> ResolvedSpec:
    """Resolve a combined epic+spec query to a spec file.

    The query can be:
    - A spec prefix like "t004-01" — finds the epic by the first segment,
      then the spec by full prefix match.
    - A full spec ID like "t004-01-validation-commands".

    The resolver splits the query to find the epic prefix. It tries
    progressively shorter prefixes until it finds exactly one epic,
    then searches for the spec within it.

    Args:
        query: Spec prefix or full ID.
        governor_root: Override governor root (for testing).

    Returns:
        ResolvedSpec with epic and spec paths.

    Raises:
        ResolveError: If no match or ambiguous.
    """
    root = governor_root or _get_governor_root()

    # Strategy: try to resolve the query as an epic prefix first.
    # If it resolves to one epic, look for specs inside it matching the query.
    # If not, progressively shorten the query to find the epic.
    #
    # For "t004-01-validation-commands":
    #   Try epic "t004-01-validation-commands" → no match
    #   Try epic "t004-01-validation" → no match
    #   Try epic "t004-01" → no match
    #   Try epic "t004" → match! → search specs for "t004-01-validation-commands"

    parts = query.split("-")
    epic_resolved = None

    # Try longest-to-shortest prefix for the epic
    for i in range(len(parts), 0, -1):
        epic_prefix = "-".join(parts[:i])
        try:
            epic_resolved = resolve_epic(epic_prefix, root)
            break
        except ResolveError:
            continue

    if epic_resolved is None:
        raise ResolveError(query)

    # Now find the spec within this epic
    specs_dir = epic_resolved.epic_dir / "specs"
    if not specs_dir.exists():
        raise ResolveError(query)

    spec_candidates: list[Path] = []
    for f in sorted(specs_dir.iterdir()):
        if f.is_file() and f.suffix == ".md" and f.stem.startswith(query):
            spec_candidates.append(f)

    if len(spec_candidates) == 0:
        # List available specs for the error message
        available = [f.stem for f in sorted(specs_dir.glob("*.md")) if f.stem != "README"]
        raise ResolveError(query, available)
    if len(spec_candidates) == 1:
        f = spec_candidates[0]
        return ResolvedSpec(epic=epic_resolved, spec_id=f.stem, spec_path=f)

    # Exact match takes priority
    for f in spec_candidates:
        if f.stem == query:
            return ResolvedSpec(epic=epic_resolved, spec_id=f.stem, spec_path=f)

    raise ResolveError(query, [f.stem for f in spec_candidates])


def list_epics(governor_root: Path | None = None) -> list[str]:
    """List all epic IDs.

    Returns:
        Sorted list of epic directory names.
    """
    epics = _epics_dir(governor_root)
    if not epics.exists():
        return []
    return sorted(d.name for d in _iter_epic_dirs(epics))


def list_specs_in_epic(
    epic_prefix: str, governor_root: Path | None = None,
) -> list[str]:
    """List all spec IDs within an epic.

    Args:
        epic_prefix: Epic prefix or full ID.
        governor_root: Override governor root.

    Returns:
        Sorted list of spec stems.
    """
    epic = resolve_epic(epic_prefix, governor_root)
    specs_dir = epic.epic_dir / "specs"
    if not specs_dir.exists():
        return []
    return sorted(
        f.stem for f in specs_dir.glob("*.md")
        if f.is_file() and f.stem != "README"
    )
