"""Context builder for governance-enriched template rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .loader import GovernanceBundle


class SpecContextBuilder:
    """Builds template context from governance artifacts.

    Provides deterministic, sorted output for stable template rendering
    and reproducible agent prompts.
    """

    def build_governance_context(
        self, bundle: GovernanceBundle, project: str, source: str
    ) -> dict[str, Any]:
        """Build complete governance context for template rendering.

        Args:
            bundle: GovernanceBundle loaded from project.build.yaml
            project: Project name
            source: Registry source

        Returns:
            Dict with all governance template variables:
            - autogov: {"project", "source", "captured_at", "version", "description"}
            - autogov_decisions: sorted list of decision dicts
            - autogov_rules: sorted list of rule dicts
            - autogov_policies: sorted list of applied policy dicts
            - autogov_patterns: sorted list of applied pattern dicts
            - autogov_invariants: list of invariant strings
            - autogov_frozen_paths: list of frozen path strings
        """
        captured_at = datetime.now(UTC).isoformat()

        # Extract and sort decisions
        decisions = self._format_decisions(bundle)

        # Extract and sort rules
        rules = self._format_rules(bundle)

        # Extract applied policies and patterns
        policies = self._format_policies(bundle)
        patterns = self._format_patterns(bundle)

        return {
            "autogov": {
                "project": project,
                "source": source,
                "captured_at": captured_at,
                "version": bundle.version,
            },
            "autogov_description": bundle.description,
            "autogov_decisions": decisions,
            "autogov_rules": rules,
            "autogov_policies": policies,
            "autogov_patterns": patterns,
            "autogov_invariants": bundle.invariants,
            "autogov_frozen_paths": bundle.frozen_paths,
        }

    def _format_decisions(self, bundle: GovernanceBundle) -> list[dict[str, Any]]:
        """Format decisions for template rendering.

        Args:
            bundle: GovernanceBundle with decisions

        Returns:
            Sorted list of decision dicts (by id)
        """
        decisions = []
        for d in bundle.decisions:
            decision_dict: dict[str, Any] = {
                "id": d.id,
                "title": d.title,
                "status": d.status,
            }
            if d.rationale:
                decision_dict["rationale"] = d.rationale
            if d.decision:
                decision_dict["decision"] = d.decision
            decisions.append(decision_dict)

        return sorted(decisions, key=lambda d: d.get("id", ""))

    def _format_rules(self, bundle: GovernanceBundle) -> list[dict[str, Any]]:
        """Format rules for template rendering.

        Args:
            bundle: GovernanceBundle with rules

        Returns:
            Sorted list of rule dicts (by id)
        """
        rules = []
        for r in bundle.rules:
            rules.append({
                "id": r.id,
                "message": r.message,
                "severity": r.severity,
                "kind": r.kind,
            })

        return sorted(rules, key=lambda r: r.get("id", ""))

    def _format_policies(self, bundle: GovernanceBundle) -> list[dict[str, str]]:
        """Format applied policies for template rendering.

        Args:
            bundle: GovernanceBundle with policies

        Returns:
            Sorted list of policy dicts (by name)
        """
        policies = []
        for p in bundle.policies:
            policies.append({
                "ref": p.ref,
                "name": p.name,
                "version": p.version,
            })

        return sorted(policies, key=lambda p: p.get("name", ""))

    def _format_patterns(self, bundle: GovernanceBundle) -> list[dict[str, str]]:
        """Format applied patterns for template rendering.

        Args:
            bundle: GovernanceBundle with patterns

        Returns:
            Sorted list of pattern dicts (by name)
        """
        patterns = []
        for p in bundle.patterns:
            patterns.append({
                "ref": p.ref,
                "name": p.name,
                "version": p.version,
            })

        return sorted(patterns, key=lambda p: p.get("name", ""))

    def merge_with_template_context(
        self,
        bundle: GovernanceBundle,
        base_context: dict[str, Any],
        project: str,
        source: str,
    ) -> dict[str, Any]:
        """Merge governance context into base template context.

        Governance keys are overlaid onto a copy of base_context.
        Base context keys are preserved unless they conflict with
        governance-specific keys (autogov_* prefixed).

        Args:
            bundle: GovernanceBundle loaded from project.build.yaml
            base_context: Existing Jinja2 template context
            project: Project name
            source: Registry source

        Returns:
            New dict with base context plus governance context merged in
        """
        # Start with a copy of base context
        merged = base_context.copy()

        # Build and overlay governance context
        governance_context = self.build_governance_context(bundle, project, source)
        merged.update(governance_context)

        return merged
