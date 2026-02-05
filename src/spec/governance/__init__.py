"""Governance validation for build.yaml, epic, and contract consistency.

Also provides spec scaffolding from intents.
"""

from spec.governance.intent_parser import IntentParser, ParsedIntent
from spec.governance.spec_drafter import SpecDrafter, check_claude_available
from spec.governance.spec_scaffolder import SpecScaffolder

__all__ = [
    "IntentParser",
    "ParsedIntent",
    "SpecDrafter",
    "SpecScaffolder",
    "check_claude_available",
]
