"""Tests for core.loader module."""

import pytest
from pathlib import Path
from spec.core.loader import deep_merge, load_defaults, merge_aip_with_defaults


def test_deep_merge_flat_dicts():
    """Test deep merge with flat dictionaries."""
    base = {"a": 1, "b": 2}
    override = {"b": 99, "c": 3}
    result = deep_merge(base, override)

    assert result == {"a": 1, "b": 99, "c": 3}


def test_deep_merge_nested_dicts():
    """Test deep merge with nested dictionaries."""
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    override = {"b": {"c": 99}, "e": 5}
    result = deep_merge(base, override)

    assert result == {"a": 1, "b": {"c": 99, "d": 3}, "e": 5}


def test_deep_merge_deeply_nested():
    """Test deep merge with multiple nesting levels."""
    base = {
        "level1": {
            "level2": {
                "level3": {"a": 1, "b": 2}
            }
        }
    }
    override = {
        "level1": {
            "level2": {
                "level3": {"b": 99, "c": 3}
            }
        }
    }
    result = deep_merge(base, override)

    assert result == {
        "level1": {
            "level2": {
                "level3": {"a": 1, "b": 99, "c": 3}
            }
        }
    }


def test_deep_merge_override_with_non_dict():
    """Test that non-dict values completely override."""
    base = {"a": {"b": 1, "c": 2}}
    override = {"a": "string_value"}
    result = deep_merge(base, override)

    assert result == {"a": "string_value"}


def test_deep_merge_empty_base():
    """Test deep merge with empty base."""
    base = {}
    override = {"a": 1, "b": 2}
    result = deep_merge(base, override)

    assert result == {"a": 1, "b": 2}


def test_deep_merge_empty_override():
    """Test deep merge with empty override."""
    base = {"a": 1, "b": 2}
    override = {}
    result = deep_merge(base, override)

    assert result == {"a": 1, "b": 2}


def test_deep_merge_both_empty():
    """Test deep merge with both empty."""
    result = deep_merge({}, {})
    assert result == {}


def test_deep_merge_lists_override():
    """Test that lists are replaced, not merged."""
    base = {"items": [1, 2, 3]}
    override = {"items": [4, 5]}
    result = deep_merge(base, override)

    assert result == {"items": [4, 5]}


def test_load_defaults_tier_only(tmp_path):
    """Test loading defaults with only tier file."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("""
gates:
  - gate_id: G0
    name: Plan Approval
coverage_target: 85
""")

    result = load_defaults("B", project_root=tmp_path)

    assert result["gates"][0]["gate_id"] == "G0"
    assert result["coverage_target"] == 85


def test_load_defaults_with_project_defaults(tmp_path):
    """Test loading defaults with project-level defaults."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    # Project defaults (lower precedence)
    project_file = defaults_dir / "project.yaml"
    project_file.write_text("""
company: Acme Corp
coverage_target: 70
budget:
  max_usd: 1000
""")

    # Tier defaults (higher precedence)
    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("""
coverage_target: 85
gates:
  - gate_id: G0
""")

    result = load_defaults("B", project_root=tmp_path)

    # Tier should override coverage_target
    assert result["coverage_target"] == 85
    # Project values should be preserved
    assert result["company"] == "Acme Corp"
    assert result["budget"]["max_usd"] == 1000
    # Tier values should be present
    assert result["gates"][0]["gate_id"] == "G0"


def test_load_defaults_with_policy_packs(tmp_path):
    """Test loading defaults with policy packs."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()

    # Policy pack (lowest precedence)
    policy_file = policies_dir / "security.yaml"
    policy_file.write_text("""
security_scan: true
coverage_target: 90
""")

    # Project defaults (medium precedence)
    project_file = defaults_dir / "project.yaml"
    project_file.write_text("""
coverage_target: 70
company: Acme Corp
""")

    # Tier defaults (highest precedence)
    tier_file = defaults_dir / "tier-A.yaml"
    tier_file.write_text("""
coverage_target: 95
gates:
  - gate_id: G0
""")

    result = load_defaults("A", policy_packs=["security"], project_root=tmp_path)

    # Tier should win
    assert result["coverage_target"] == 95
    # Policy pack values should be present
    assert result["security_scan"] is True
    # Project values should be present
    assert result["company"] == "Acme Corp"
    # Tier values should be present
    assert result["gates"][0]["gate_id"] == "G0"


def test_load_defaults_multiple_policy_packs(tmp_path):
    """Test loading defaults with multiple policy packs."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()

    # First policy pack
    policy1 = policies_dir / "security.yaml"
    policy1.write_text("""
security_scan: true
coverage_target: 90
""")

    # Second policy pack (should override first)
    policy2 = policies_dir / "compliance.yaml"
    policy2.write_text("""
compliance_check: true
coverage_target: 95
""")

    # Tier defaults
    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("""
gates:
  - gate_id: G0
""")

    result = load_defaults(
        "B",
        policy_packs=["security", "compliance"],
        project_root=tmp_path
    )

    # Later policy pack should override earlier one
    assert result["coverage_target"] == 95
    # Both policy pack values should be present
    assert result["security_scan"] is True
    assert result["compliance_check"] is True


def test_load_defaults_missing_files(tmp_path):
    """Test loading defaults when files don't exist."""
    result = load_defaults("B", project_root=tmp_path)

    # Should return empty dict when no files exist
    assert result == {}


def test_load_defaults_missing_policy_pack(tmp_path):
    """Test loading defaults with missing policy pack."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("""
gates:
  - gate_id: G0
""")

    # Request non-existent policy pack
    result = load_defaults(
        "B",
        policy_packs=["nonexistent"],
        project_root=tmp_path
    )

    # Should still load tier defaults
    assert result["gates"][0]["gate_id"] == "G0"


def test_load_defaults_empty_yaml_files(tmp_path):
    """Test loading defaults with empty YAML files."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("")  # Empty file

    result = load_defaults("B", project_root=tmp_path)

    # Should return empty dict
    assert result == {}


def test_merge_aip_with_defaults_tier_a(tmp_path):
    """Test merging AIP with Tier A defaults."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    tier_file = defaults_dir / "tier-A.yaml"
    tier_file.write_text("""
coverage_target: 95
gates:
  - gate_id: G0
    name: Plan Approval
""")

    aip = {
        "metadata": {
            "risk": "high",
            "title": "My Feature"
        },
        "budget": {
            "max_usd": 150.00
        }
    }

    result = merge_aip_with_defaults(aip, project_root=tmp_path)

    # AIP values should be preserved
    assert result["metadata"]["risk"] == "high"
    assert result["metadata"]["title"] == "My Feature"
    assert result["budget"]["max_usd"] == 150.00
    # Defaults should be merged in
    assert result["coverage_target"] == 95
    assert result["gates"][0]["gate_id"] == "G0"


def test_merge_aip_with_defaults_tier_b(tmp_path):
    """Test merging AIP with Tier B defaults."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("""
coverage_target: 85
sla_hours: 48
""")

    aip = {
        "metadata": {
            "risk": "moderate",
            "title": "My Feature"
        }
    }

    result = merge_aip_with_defaults(aip, project_root=tmp_path)

    assert result["coverage_target"] == 85
    assert result["sla_hours"] == 48


def test_merge_aip_with_defaults_tier_c(tmp_path):
    """Test merging AIP with Tier C defaults."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    tier_file = defaults_dir / "tier-C.yaml"
    tier_file.write_text("""
coverage_target: 70
sla_hours: 24
""")

    aip = {
        "metadata": {
            "risk": "low",
            "title": "My Feature"
        }
    }

    result = merge_aip_with_defaults(aip, project_root=tmp_path)

    assert result["coverage_target"] == 70
    assert result["sla_hours"] == 24


def test_merge_aip_with_defaults_aip_overrides(tmp_path):
    """Test that AIP values override defaults."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("""
coverage_target: 85
budget:
  max_usd: 1000
""")

    aip = {
        "metadata": {
            "risk": "moderate",
            "title": "My Feature"
        },
        "coverage_target": 90,  # Override default
        "budget": {
            "max_usd": 500  # Override default
        }
    }

    result = merge_aip_with_defaults(aip, project_root=tmp_path)

    # AIP values should take precedence
    assert result["coverage_target"] == 90
    assert result["budget"]["max_usd"] == 500


def test_merge_aip_with_defaults_no_risk_defaults_to_moderate(tmp_path):
    """Test that missing risk defaults to moderate (Tier B)."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("""
coverage_target: 85
""")

    aip = {
        "metadata": {
            "title": "My Feature"
            # No risk specified
        }
    }

    result = merge_aip_with_defaults(aip, project_root=tmp_path)

    # Should use Tier B defaults
    assert result["coverage_target"] == 85


def test_merge_aip_with_policy_packs(tmp_path):
    """Test merging AIP with policy packs."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()

    policy_file = policies_dir / "security.yaml"
    policy_file.write_text("""
security_scan: true
""")

    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("""
coverage_target: 85
""")

    aip = {
        "metadata": {
            "risk": "moderate",
            "title": "My Feature"
        },
        "policy_packs": ["security"]
    }

    result = merge_aip_with_defaults(aip, project_root=tmp_path)

    # Should have values from all layers
    assert result["security_scan"] is True
    assert result["coverage_target"] == 85
    assert result["policy_packs"] == ["security"]


def test_merge_aip_nested_override(tmp_path):
    """Test that nested AIP values properly override nested defaults."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()

    tier_file = defaults_dir / "tier-B.yaml"
    tier_file.write_text("""
metadata:
  sla_hours: 48
  auto_approve: false
""")

    aip = {
        "metadata": {
            "risk": "moderate",
            "title": "My Feature",
            "auto_approve": True  # Override this specific field
        }
    }

    result = merge_aip_with_defaults(aip, project_root=tmp_path)

    # AIP should override auto_approve but keep sla_hours from defaults
    assert result["metadata"]["auto_approve"] is True
    assert result["metadata"]["sla_hours"] == 48
    assert result["metadata"]["title"] == "My Feature"
