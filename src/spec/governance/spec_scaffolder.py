"""Spec scaffolder for generating spec-v2 YAML from intents."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from spec.governance.intent_parser import ParsedIntent


class SpecScaffolder:
    """Generate scaffolded YAML specs from intents."""

    def __init__(
        self,
        intent: ParsedIntent,
        repo_path: Path,
        governor_root: Path | None = None,
        context: str | None = None,
    ):
        """Initialize scaffolder.

        Args:
            intent: Parsed intent to scaffold from.
            repo_path: Path to the target repository.
            governor_root: Override governor root (for testing).
            context: Additional context content to include.
        """
        self.intent = intent
        self.repo_path = repo_path
        self.governor_root = governor_root or Path.home() / ".local" / "local-governor"
        self.context = context
        self.build_yaml = self._load_build_yaml()

    def _load_build_yaml(self) -> dict[str, Any] | None:
        """Find and load build.yaml for repo.

        Checks these locations in order:
        1. governor/projects/{repo_name}/{repo_name}.build.yaml
        2. {repo_path}/.specwright/build.yaml (legacy)
        3. {repo_path}/build.yaml (simple)

        Returns:
            Parsed build.yaml dict, or None if not found.
        """
        repo_name = self.repo_path.name

        governor_build = (
            self.governor_root / "projects" / repo_name / f"{repo_name}.build.yaml"
        )
        if governor_build.exists():
            return yaml.safe_load(governor_build.read_text())

        legacy_build = self.repo_path / ".specwright" / "build.yaml"
        if legacy_build.exists():
            return yaml.safe_load(legacy_build.read_text())

        simple_build = self.repo_path / "build.yaml"
        if simple_build.exists():
            return yaml.safe_load(simple_build.read_text())

        return None

    def scaffold(self, num_phases: int = 2) -> str:
        """Generate scaffolded spec as YAML (spec-v2.1 format)."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        branch = self.intent.branch or f"feat/{self.intent.id}"
        tier = (self.intent.tier or "B").upper()

        spec = {
            "artifact_id": "",
            "name": self.intent.id,
            "version": "0.1.0",
            "kind": "spec",
            "title": self.intent.title,
            "epic_artifact_id": "",
            "tier": tier,
            "owner": self.intent.owner or "TODO",
            "goal": self.intent.goal,
            "objective": "TODO: describe the objective",
            "key_decisions": [],
            "phases": [
                {
                    "phase_number": i,
                    "title": "TODO",
                    "objective": "TODO",
                    "files_to_touch": [],
                    "notes": "",
                    "verification": [],
                }
                for i in range(1, num_phases + 1)
            ],
            "acceptance_criteria": [
                {"text": c, "status": "pending"}
                for c in (self.intent.expectations or ["TODO"])
            ],
            "constraints": self.intent.constraints or ["TODO"],
            "dependencies": [],
            "labels": [],
            "repo": {
                "name": self.repo_path.name,
                "url": str(self.repo_path),
                "working_branch": branch,
            },
            "created": now,
            "updated": now,
            "metadata": {},
        }
        return yaml.dump(
            spec,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
