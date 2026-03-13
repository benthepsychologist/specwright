"""Epic validator: cross-reference epic specs against targets and build.yamls.

Checks:
- Target repo paths exist on disk
- Spec files exist in the epic specs/ directory
- depends_on references resolve to declared spec IDs
- Target repos have a matching build.yaml in the governor
- Specs reference valid targets
- Spec expectations reference modules that exist in target build.yaml
- build_delta adds/modifies/removes don't conflict with current build.yaml
- Op-catalog references in spec expectations are valid (if op-catalog exists)
"""

from __future__ import annotations

import re
from pathlib import Path

from spec.governance.models import (
    Category,
    Finding,
    Severity,
    ValidationReport,
)


class EpicValidator:
    """Validate an epic's cross-references and consistency."""

    def __init__(
        self,
        epic_yaml: dict,
        build_yamls: dict[str, dict],
        epic_dir: Path | None = None,
        op_catalog: dict | None = None,
    ) -> None:
        self.epic = epic_yaml
        self.builds = build_yamls
        self.epic_dir = epic_dir
        self.op_catalog = op_catalog

    def validate(self) -> ValidationReport:
        epic_id = self.epic.get("id", "unknown")
        report = ValidationReport(target=epic_id)

        self._check_targets(report)
        self._check_spec_files(report)
        self._check_depends_on(report)
        self._check_target_build_yamls(report)
        self._check_spec_target_refs(report)
        self._check_expectations_vs_build(report)
        self._check_build_deltas(report)
        self._check_op_catalog_refs(report)

        return report

    def _check_targets(self, report: ValidationReport) -> None:
        """Check target repo paths exist on disk."""
        targets = self.epic.get("targets") or []
        for target in targets:
            repo_path = target.get("repo_path", "")
            if repo_path and not Path(repo_path).exists():
                report.findings.append(Finding(
                    severity=Severity.error,
                    category=Category.missing_repo,
                    path=repo_path,
                    message=f"Target '{target.get('id', '?')}' repo_path does not exist: {repo_path}",
                ))

    def _check_spec_files(self, report: ValidationReport) -> None:
        """Check that spec files exist in the epic specs/ directory."""
        if self.epic_dir is None:
            return

        specs_dir = self.epic_dir / "specs"
        if not specs_dir.exists():
            return

        specs = self.epic.get("specs") or []
        for spec in specs:
            spec_id = spec.get("id", "")
            explicit_path = spec.get("path")
            if explicit_path:
                spec_path = explicit_path
            else:
                yaml_path = f"specs/{spec_id}.yaml"
                md_path = f"specs/{spec_id}.md"
                if (self.epic_dir / yaml_path).exists():
                    spec_path = yaml_path
                elif (self.epic_dir / md_path).exists():
                    spec_path = md_path
                else:
                    spec_path = yaml_path
            # Path is relative to epic dir
            full_path = self.epic_dir / spec_path
            if not full_path.exists():
                report.findings.append(Finding(
                    severity=Severity.warning,
                    category=Category.missing_path,
                    path=spec_path,
                    message=f"Spec '{spec_id}' file not found: {spec_path}",
                ))

    def _check_depends_on(self, report: ValidationReport) -> None:
        """Check all depends_on references resolve to declared spec IDs."""
        specs = self.epic.get("specs") or []
        declared_ids = {s.get("id") for s in specs}

        for spec in specs:
            spec_id = spec.get("id", "?")
            for dep in spec.get("depends_on") or []:
                if dep not in declared_ids:
                    report.findings.append(Finding(
                        severity=Severity.error,
                        category=Category.unresolved_depends,
                        path=spec_id,
                        message=f"Spec '{spec_id}' depends on '{dep}' which is not declared in this epic",
                    ))

    def _check_target_build_yamls(self, report: ValidationReport) -> None:
        """Check that targets with governor_project have build.yamls loaded."""
        targets = self.epic.get("targets") or []
        for target in targets:
            tid = target.get("id", "")
            gov_project = target.get("governor_project", tid)
            if gov_project and gov_project not in self.builds:
                report.findings.append(Finding(
                    severity=Severity.warning,
                    category=Category.missing_build_yaml,
                    path=gov_project,
                    message=f"Target '{tid}' has no build.yaml in governor (project: {gov_project})",
                ))

    def _check_spec_target_refs(self, report: ValidationReport) -> None:
        """Check that all specs reference valid targets."""
        targets = self.epic.get("targets") or []
        target_ids = {t.get("id") for t in targets}

        specs = self.epic.get("specs") or []
        for spec in specs:
            spec_id = spec.get("id", "?")
            repo = spec.get("repo", "")
            if repo and repo not in target_ids:
                report.findings.append(Finding(
                    severity=Severity.error,
                    category=Category.missing_repo,
                    path=spec_id,
                    message=f"Spec '{spec_id}' references target '{repo}' not declared in targets",
                ))

    # ------------------------------------------------------------------
    # Gap checks: expectations, build_delta, op-catalog
    # ------------------------------------------------------------------

    def _resolve_build_for_spec(self, spec: dict) -> dict | None:
        """Find the build.yaml dict for a spec's target repo."""
        repo = spec.get("repo", "")
        # Try governor_project mapping from targets first
        targets = self.epic.get("targets") or []
        for target in targets:
            if target.get("id") == repo:
                gov_project = target.get("governor_project", repo)
                if gov_project in self.builds:
                    return self.builds[gov_project]
        # Direct lookup
        return self.builds.get(repo)

    def _get_build_module_names(self, build: dict) -> set[str]:
        """Extract declared module names from a build.yaml."""
        names: set[str] = set()
        for mod in build.get("modules") or []:
            name = mod.get("name")
            if name:
                names.add(name)
        return names

    def _get_build_layout_paths(self, build: dict) -> set[str]:
        """Extract declared layout paths from a build.yaml."""
        paths: set[str] = set()
        for entry in build.get("layout") or []:
            p = entry.get("path")
            if p:
                paths.add(p)
        return paths

    def _check_expectations_vs_build(self, report: ValidationReport) -> None:
        """Check spec expectations that reference modules exist in build.yaml.

        Scans expectation strings for patterns like module references
        (words matching declared module names in build.yaml). Warns when
        an expectation mentions a path-like reference (e.g., ``src/foo/bar.py``)
        that doesn't appear in the target build.yaml layout.
        """
        specs = self.epic.get("specs") or []
        for spec in specs:
            spec_id = spec.get("id", "?")
            expectations = spec.get("expectations") or []
            if not expectations:
                continue

            build = self._resolve_build_for_spec(spec)
            if build is None:
                continue

            layout_paths = self._get_build_layout_paths(build)

            for exp_text in expectations:
                # Find path-like references (e.g., src/foo/bar.py, foo/bar/)
                path_refs = re.findall(r'\b(\w+/[\w./]+(?:\.py)?)\b', exp_text)
                for ref in path_refs:
                    # Only check references that look like they belong in layout
                    # (contain at least one slash and look like a file/dir path)
                    if ref in layout_paths:
                        continue
                    # Check if covered by a directory entry
                    if any(ref.startswith(lp) for lp in layout_paths if lp.endswith("/")):
                        continue
                    # Only flag references that look like source paths
                    if ref.startswith("src/") or "/" in ref:
                        report.findings.append(Finding(
                            severity=Severity.warning,
                            category=Category.expectation_module_missing,
                            path=spec_id,
                            message=(
                                f"Spec '{spec_id}' expectation references "
                                f"'{ref}' not found in build.yaml layout"
                            ),
                        ))

    def _check_build_deltas(self, report: ValidationReport) -> None:
        """Check build_delta fields don't conflict with current build.yaml.

        Validates:
        - 'adds' entries don't already exist in build.yaml
        - 'modifies' entries reference things that exist in build.yaml
        - 'removes' entries reference things that exist in build.yaml
        """
        specs = self.epic.get("specs") or []
        for spec in specs:
            spec_id = spec.get("id", "?")
            delta = spec.get("build_delta")
            if not delta:
                continue

            # Resolve which build.yaml this delta targets
            target_path = delta.get("target", "")
            # target is like "projects/workman/workman.build.yaml"
            # Extract project name
            parts = target_path.split("/")
            project_name = parts[1] if len(parts) >= 2 else ""
            build = self.builds.get(project_name)
            if build is None:
                # Can't validate delta without the build.yaml
                continue

            existing_modules = self._get_build_module_names(build)
            existing_layout = self._get_build_layout_paths(build)

            adds = delta.get("adds") or {}
            modifies = delta.get("modifies") or {}
            removes = delta.get("removes") or {}

            # Check adds: new modules/layout shouldn't already exist
            for mod in adds.get("modules") or []:
                name = mod.get("name", "")
                if name and name in existing_modules:
                    report.findings.append(Finding(
                        severity=Severity.warning,
                        category=Category.build_delta_conflict,
                        path=spec_id,
                        message=(
                            f"Spec '{spec_id}' build_delta adds module '{name}' "
                            f"but it already exists in {project_name}.build.yaml"
                        ),
                    ))
            for entry in adds.get("layout") or []:
                path = entry.get("path", "")
                if path and path in existing_layout:
                    report.findings.append(Finding(
                        severity=Severity.warning,
                        category=Category.build_delta_conflict,
                        path=spec_id,
                        message=(
                            f"Spec '{spec_id}' build_delta adds layout '{path}' "
                            f"but it already exists in {project_name}.build.yaml"
                        ),
                    ))

            # Check modifies: referenced modules/layout should exist
            for mod in modifies.get("modules") or []:
                name = mod.get("name", "")
                if name and name not in existing_modules:
                    report.findings.append(Finding(
                        severity=Severity.error,
                        category=Category.build_delta_conflict,
                        path=spec_id,
                        message=(
                            f"Spec '{spec_id}' build_delta modifies module '{name}' "
                            f"but it does not exist in {project_name}.build.yaml"
                        ),
                    ))

            # Check removes: referenced things should exist
            for mod in removes.get("modules") or []:
                name = mod.get("name", "")
                if name and name not in existing_modules:
                    report.findings.append(Finding(
                        severity=Severity.warning,
                        category=Category.build_delta_conflict,
                        path=spec_id,
                        message=(
                            f"Spec '{spec_id}' build_delta removes module '{name}' "
                            f"but it does not exist in {project_name}.build.yaml"
                        ),
                    ))

    def _check_op_catalog_refs(self, report: ValidationReport) -> None:
        """Check op-catalog references in spec expectations.

        If an op-catalog was provided, scans spec expectations for operation
        name patterns (domain.entity.verb) and verifies they exist in the catalog.
        """
        if self.op_catalog is None:
            return

        # Build set of declared op IDs from catalog
        declared_ops: set[str] = set()
        for op in self.op_catalog.get("operations") or []:
            op_id = op.get("id")
            if op_id:
                declared_ops.add(op_id)

        if not declared_ops:
            return

        specs = self.epic.get("specs") or []
        for spec in specs:
            spec_id = spec.get("id", "?")
            expectations = spec.get("expectations") or []

            for exp_text in expectations:
                # Match op-name patterns: word.word.word (domain.entity.verb)
                op_refs = re.findall(r'\b([a-z]\w*\.[a-z]\w*\.[a-z]\w*)\b', exp_text)
                for ref in op_refs:
                    if ref not in declared_ops:
                        report.findings.append(Finding(
                            severity=Severity.warning,
                            category=Category.op_catalog_missing,
                            path=spec_id,
                            message=(
                                f"Spec '{spec_id}' expectation references op "
                                f"'{ref}' not found in op-catalog"
                            ),
                        ))
