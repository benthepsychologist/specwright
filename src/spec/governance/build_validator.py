"""Build validator: compare project.build.yaml against repo filesystem.

Checks:
- layout[].path entries exist on disk
- Source files on disk not declared in layout (undeclared detection)
- slots[].path directories exist and contain matching files
- frozen[].path files exist
- rules.placement globs are enforced (forbid/allowlist)
- modules[].depends_on references resolve to declared module names
"""

from __future__ import annotations

from pathlib import Path

from spec.governance.models import (
    Category,
    Finding,
    Severity,
    ValidationReport,
)


def _glob_with_braces(directory: Path, pattern: str):
    """Expand brace patterns like *.{json,yaml} into separate globs.

    pathlib.glob does not support brace expansion. This helper splits
    patterns containing ``{a,b,...}`` into one glob per alternative.
    """
    import re
    m = re.search(r"\{([^}]+)\}", pattern)
    if m:
        alternatives = m.group(1).split(",")
        for alt in alternatives:
            expanded = pattern[: m.start()] + alt.strip() + pattern[m.end():]
            yield from directory.glob(expanded)
    else:
        yield from directory.glob(pattern)


class BuildValidator:
    """Validate a project.build.yaml against the repo filesystem."""

    def __init__(self, repo_path: Path, build_yaml: dict) -> None:
        self.repo_path = repo_path
        self.build = build_yaml

    def validate(self) -> ValidationReport:
        target = (self.build.get("metadata") or {}).get("name", str(self.repo_path))
        report = ValidationReport(target=target)

        self._check_layout(report)
        self._check_undeclared(report)
        self._check_slots(report)
        self._check_frozen(report)
        self._check_placement_rules(report)
        self._check_module_deps(report)

        return report

    def _check_layout(self, report: ValidationReport) -> None:
        """Check every layout[].path exists on disk."""
        layout = self.build.get("layout") or []
        for entry in layout:
            rel_path = entry.get("path")
            if not rel_path:
                report.findings.append(Finding(
                    severity=Severity.error,
                    category=Category.missing_path,
                    path="<no path>",
                    message=f"Layout entry missing 'path' key: {entry}",
                ))
                continue
            full = self.repo_path / rel_path
            if not full.exists():
                report.findings.append(Finding(
                    severity=Severity.error,
                    category=Category.missing_path,
                    path=rel_path,
                    message=f"Layout path does not exist: {rel_path}",
                ))

    def _check_undeclared(self, report: ValidationReport) -> None:
        """Detect source files on disk not declared in layout.

        Extracts the source root(s) from layout paths (e.g. ``src/workman/``,
        ``lorchestra/``), walks each root, and flags ``.py`` files that are not
        covered by any layout entry.  Directory entries in layout (paths ending
        with ``/``) cover all files beneath them.
        """
        layout = self.build.get("layout") or []
        if not layout:
            return

        # Collect declared paths and directory prefixes
        declared_files: set[str] = set()
        declared_dirs: list[str] = []
        for entry in layout:
            p = entry.get("path") or ""
            if not p:
                continue
            if p.endswith("/"):
                declared_dirs.append(p)
            else:
                declared_files.add(p)

        # Derive source roots: the package directory containing layout files.
        # e.g. ["src/workman/__init__.py", ...] → {"src/workman"}
        #      ["lorchestra/__init__.py", "lorchestra/handlers/"] → {"lorchestra"}
        source_roots: set[str] = set()
        for entry in layout:
            p = (entry.get("path") or "").rstrip("/")
            parent = str(Path(p).parent)
            if parent == ".":
                continue
            parts = parent.split("/")
            # For src/<pkg>/subdir, the root is src/<pkg>
            if parts[0] == "src" and len(parts) >= 2:
                source_roots.add("/".join(parts[:2]))
            else:
                source_roots.add(parts[0])

        # Deduplicate: if we have both "lorchestra" and "lorchestra/handlers",
        # keep only "lorchestra".  Sort shortest-first.
        root_list = sorted(source_roots, key=len)
        filtered: list[str] = []
        for r in root_list:
            if not any(r.startswith(existing + "/") for existing in filtered):
                filtered.append(r)

        def _is_covered(rel: str) -> bool:
            """Check if a relative path is covered by layout declarations."""
            if rel in declared_files:
                return True
            for d in declared_dirs:
                if rel.startswith(d) or (rel + "/").startswith(d):
                    return True
            return False

        for root in filtered:
            root_path = self.repo_path / root
            if not root_path.is_dir():
                continue
            for py_file in root_path.rglob("*.py"):
                rel = str(py_file.relative_to(self.repo_path))
                if not _is_covered(rel):
                    report.findings.append(Finding(
                        severity=Severity.warning,
                        category=Category.undeclared_path,
                        path=rel,
                        message=f"Source file not declared in layout: {rel}",
                    ))

    def _check_slots(self, report: ValidationReport) -> None:
        """Check slot directories exist and contain expected files."""
        slots = self.build.get("slots") or []
        for slot in slots:
            slot_path = slot.get("path") or ""
            full = self.repo_path / slot_path
            if not full.exists():
                if not slot.get("optional", False):
                    report.findings.append(Finding(
                        severity=Severity.error,
                        category=Category.missing_slot_dir,
                        path=slot_path,
                        message=f"Slot directory does not exist: {slot_path} (slot: {slot.get('name', '?')})",
                    ))
                continue

            # Check file_pattern matches at least one file
            pattern = slot.get("file_pattern")
            if pattern and full.is_dir():
                matched = list(_glob_with_braces(full, pattern))
                if not matched:
                    report.findings.append(Finding(
                        severity=Severity.warning,
                        category=Category.missing_slot_dir,
                        path=slot_path,
                        message=f"Slot '{slot.get('name', '?')}' has no files matching {pattern} in {slot_path}",
                    ))

    def _check_frozen(self, report: ValidationReport) -> None:
        """Check all frozen paths exist."""
        frozen = self.build.get("frozen") or []
        for entry in frozen:
            rel_path = entry.get("path") or ""
            full = self.repo_path / rel_path
            if not full.exists():
                report.findings.append(Finding(
                    severity=Severity.error,
                    category=Category.frozen_missing,
                    path=rel_path,
                    message=f"Frozen path does not exist: {rel_path} (reason: {entry.get('reason', '?')})",
                ))

    def _check_placement_rules(self, report: ValidationReport) -> None:
        """Enforce placement rules (forbid_glob_in with allowlist)."""
        rules = self.build.get("rules") or {}
        placement = rules.get("placement") or []

        for rule in placement:
            rule_id = rule.get("id", "?")
            severity = Severity(rule.get("severity", "error"))
            message = rule.get("message", f"Placement rule {rule_id} violated")

            # forbid_glob_in: files matching the glob are forbidden unless allowlisted
            forbid_globs = rule.get("forbid_glob_in") or []
            allowlist = set(rule.get("allowlist") or [])

            for glob_pattern in forbid_globs:
                for match in _glob_with_braces(self.repo_path, glob_pattern):
                    if match.is_file():
                        rel = match.relative_to(self.repo_path)
                        filename = rel.name
                        if filename not in allowlist:
                            report.findings.append(Finding(
                                severity=severity,
                                category=Category.placement_violation,
                                path=str(rel),
                                message=f"[{rule_id}] {message}",
                            ))

    def _check_module_deps(self, report: ValidationReport) -> None:
        """Check modules[].depends_on references resolve to declared modules."""
        modules = self.build.get("modules") or []
        declared = {m.get("name") for m in modules}

        for mod in modules:
            mod_name = mod.get("name", "?")
            for dep in mod.get("depends_on", []):
                if dep not in declared:
                    report.findings.append(Finding(
                        severity=Severity.error,
                        category=Category.module_ref_broken,
                        path=mod_name,
                        message=f"Module '{mod_name}' depends on '{dep}' which is not declared",
                    ))
