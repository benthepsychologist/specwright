"""
Tests for Step Contract Builder.
"""

import json
from pathlib import Path

import pytest
import yaml

from spec.executor.contract import (
    ContractBuildError,
    EscalationRequired,
    build_contract,
    load_contract,
    load_contract_json,
    save_contract,
    save_contract_json,
)
from spec.executor.schemas import StepContract


# =============================================================================
# Basic Contract Building
# =============================================================================


class TestBuildContract:
    """Tests for build_contract function."""

    def test_minimal_aip(self, tmp_path):
        """Build contract from minimal AIP."""
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {"step_id": "step-001", "prompt": "Do something"},
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.step_id == "step-001"
        assert contract.aip_id == "AIP-test-001"
        assert contract.repo_root == tmp_path
        # Should get extended defaults
        assert "src/**" in contract.allowed_paths
        assert "tests/**" in contract.allowed_paths
        assert "docs/**" in contract.allowed_paths

    def test_repo_root_required(self):
        """build_contract requires repo_root."""
        aip = {"plan": [{"step_id": "step-001"}]}

        with pytest.raises(ContractBuildError) as exc:
            build_contract(aip, step_idx=0, repo_root=None)
        assert "repo_root is required" in str(exc.value)

    def test_invalid_step_idx(self, tmp_path):
        """Invalid step_idx raises error."""
        aip = {"plan": [{"step_id": "step-001"}]}

        with pytest.raises(ContractBuildError) as exc:
            build_contract(aip, step_idx=5, repo_root=tmp_path)
        assert "out of range" in str(exc.value)

    def test_negative_step_idx(self, tmp_path):
        """Negative step_idx raises error."""
        aip = {"plan": [{"step_id": "step-001"}]}

        with pytest.raises(ContractBuildError) as exc:
            build_contract(aip, step_idx=-1, repo_root=tmp_path)
        assert "out of range" in str(exc.value)

    def test_step_id_fallback(self, tmp_path):
        """Step ID defaults to step-NNN if not provided."""
        aip = {"plan": [{"prompt": "Do something"}]}

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.step_id == "step-001"

    def test_aip_id_fallback(self, tmp_path):
        """AIP ID defaults to 'unknown' if not provided."""
        aip = {"plan": [{"step_id": "step-001"}]}

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.aip_id == "unknown"

    def test_alternate_aip_structure(self, tmp_path):
        """Support alternate AIP structures (steps vs plan, id vs aip_id)."""
        aip = {
            "id": "AIP-alt-001",
            "steps": [
                {"id": "step-alt", "prompt": "Do something"},
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.aip_id == "AIP-alt-001"
        assert contract.step_id == "step-alt"


# =============================================================================
# Allowed Paths Derivation
# =============================================================================


class TestAllowedPathsDerivation:
    """Tests for allowed_paths derivation rules."""

    def test_rule1_explicit_step_paths(self, tmp_path):
        """Rule 1: Step explicitly declares allowed_paths."""
        aip = {
            "plan": [
                {
                    "step_id": "step-001",
                    "allowed_paths": ["lib/**", "bin/**"],
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.allowed_paths == ["lib/**", "bin/**"]
        # Should NOT have safe defaults when explicit
        assert "src/**" not in contract.allowed_paths

    def test_rule2_derive_from_outputs(self, tmp_path):
        """Rule 2: Derive from step outputs + safe defaults."""
        aip = {
            "plan": [
                {
                    "step_id": "step-001",
                    "outputs": [
                        "artifacts/report.md",
                        "docs/api.md",
                    ],
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        # Should have safe defaults + derived from outputs
        assert "src/**" in contract.allowed_paths
        assert "tests/**" in contract.allowed_paths
        assert "artifacts/**" in contract.allowed_paths
        assert "docs/**" in contract.allowed_paths

    def test_rule2_outputs_dict_format(self, tmp_path):
        """Rule 2: Outputs can be dicts with path key."""
        aip = {
            "plan": [
                {
                    "step_id": "step-001",
                    "outputs": [
                        {"path": "generated/code.py", "type": "file"},
                    ],
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert "generated/**" in contract.allowed_paths

    def test_rule3_repo_paths(self, tmp_path):
        """Rule 3: Use spec repo.paths + safe defaults."""
        aip = {
            "repo": {
                "paths": ["lib/**", "configs/**"],
            },
            "plan": [
                {"step_id": "step-001"},
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        # Should have safe defaults + repo paths
        assert "src/**" in contract.allowed_paths
        assert "tests/**" in contract.allowed_paths
        assert "lib/**" in contract.allowed_paths
        assert "configs/**" in contract.allowed_paths

    def test_rule4_extended_defaults(self, tmp_path):
        """Rule 4: Fallback to extended safe defaults."""
        aip = {
            "plan": [
                {"step_id": "step-001"},
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert set(contract.allowed_paths) == {"docs/**", "src/**", "tests/**"}

    def test_priority_step_over_repo(self, tmp_path):
        """Step-level paths override repo-level paths."""
        aip = {
            "repo": {
                "paths": ["old/**"],
            },
            "plan": [
                {
                    "step_id": "step-001",
                    "allowed_paths": ["new/**"],
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.allowed_paths == ["new/**"]
        assert "old/**" not in contract.allowed_paths


# =============================================================================
# Forbidden Paths Derivation
# =============================================================================


class TestForbiddenPathsDerivation:
    """Tests for forbidden_paths derivation."""

    def test_step_level_forbidden(self, tmp_path):
        """Step-level forbidden_paths."""
        aip = {
            "plan": [
                {
                    "step_id": "step-001",
                    "forbidden_paths": ["**/*.lock"],
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert "**/*.lock" in contract.forbidden_paths

    def test_spec_level_forbidden(self, tmp_path):
        """Spec-level forbidden_paths."""
        aip = {
            "forbidden_paths": [".env*"],
            "plan": [
                {"step_id": "step-001"},
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert ".env*" in contract.forbidden_paths

    def test_repo_level_forbidden(self, tmp_path):
        """Repo-level forbidden_paths."""
        aip = {
            "repo": {
                "forbidden_paths": ["pyproject.toml"],
            },
            "plan": [
                {"step_id": "step-001"},
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert "pyproject.toml" in contract.forbidden_paths

    def test_autogov_policy_forbidden(self, tmp_path):
        """Autogov policy forbidden_paths merged."""
        aip = {
            "plan": [
                {"step_id": "step-001"},
            ],
        }
        autogov = {
            "forbidden_paths": ["secrets/**"],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path, autogov_policy=autogov)

        assert "secrets/**" in contract.forbidden_paths

    def test_autogov_path_constraints(self, tmp_path):
        """Autogov path_constraints.forbidden merged."""
        aip = {
            "plan": [
                {"step_id": "step-001"},
            ],
        }
        autogov = {
            "path_constraints": {
                "forbidden": [
                    "credentials.json",
                    {"pattern": ".env*", "reason": "secrets"},
                ],
            },
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path, autogov_policy=autogov)

        assert "credentials.json" in contract.forbidden_paths
        assert ".env*" in contract.forbidden_paths

    def test_merge_all_forbidden_sources(self, tmp_path):
        """All forbidden sources are merged."""
        aip = {
            "forbidden_paths": ["spec-level"],
            "repo": {
                "forbidden_paths": ["repo-level"],
            },
            "plan": [
                {
                    "step_id": "step-001",
                    "forbidden_paths": ["step-level"],
                },
            ],
        }
        autogov = {
            "forbidden_paths": ["autogov-level"],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path, autogov_policy=autogov)

        assert "spec-level" in contract.forbidden_paths
        assert "repo-level" in contract.forbidden_paths
        assert "step-level" in contract.forbidden_paths
        assert "autogov-level" in contract.forbidden_paths


# =============================================================================
# Other Fields
# =============================================================================


class TestOtherFields:
    """Tests for other contract fields."""

    def test_allowed_ops_step_level(self, tmp_path):
        """allowed_ops from step level."""
        aip = {
            "plan": [
                {
                    "step_id": "step-001",
                    "allowed_ops": ["read", "lint"],
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.allowed_ops == ["read", "lint"]

    def test_allowed_ops_spec_level(self, tmp_path):
        """allowed_ops from spec level."""
        aip = {
            "allowed_ops": ["read", "write", "test", "lint"],
            "plan": [
                {"step_id": "step-001"},
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert "lint" in contract.allowed_ops

    def test_allowed_ops_default(self, tmp_path):
        """Default allowed_ops."""
        aip = {"plan": [{"step_id": "step-001"}]}

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.allowed_ops == ["read", "write", "test"]

    def test_max_iterations_step_level(self, tmp_path):
        """max_iterations from step level."""
        aip = {
            "plan": [
                {
                    "step_id": "step-001",
                    "max_iterations": 5,
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.max_iterations == 5

    def test_max_iterations_spec_level(self, tmp_path):
        """max_iterations from spec level."""
        aip = {
            "max_iterations": 7,
            "plan": [
                {"step_id": "step-001"},
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.max_iterations == 7

    def test_max_iterations_clamped(self, tmp_path):
        """max_iterations clamped to valid range."""
        aip = {
            "plan": [
                {"step_id": "step-001", "max_iterations": 100},
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.max_iterations == 10  # Clamped to max

    def test_codex_config_step_level(self, tmp_path):
        """Codex config from step level."""
        aip = {
            "plan": [
                {
                    "step_id": "step-001",
                    "codex": {
                        "sandbox": "workspace-write",
                        "emit_json_events": False,
                    },
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        assert contract.codex.sandbox == "workspace-write"
        assert contract.codex.emit_json_events is False

    def test_codex_config_merged(self, tmp_path):
        """Codex config merged from spec and step (step wins)."""
        aip = {
            "codex": {
                "sandbox": "read-only",
                "output_schema": "/path/schema.json",
            },
            "plan": [
                {
                    "step_id": "step-001",
                    "codex": {
                        "sandbox": "workspace-write",
                    },
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        # Step overrides spec
        assert contract.codex.sandbox == "workspace-write"
        # Spec value preserved when not overridden
        assert contract.codex.output_schema == "/path/schema.json"


# =============================================================================
# Serialization
# =============================================================================


class TestContractSerialization:
    """Tests for contract save/load functions."""

    def test_save_and_load_yaml(self, tmp_path):
        """Contract can be saved and loaded as YAML."""
        contract = StepContract(
            step_id="step-001",
            aip_id="AIP-test",
            repo_root=tmp_path,
            allowed_paths=["src/**"],
            forbidden_paths=["*.lock"],
        )

        yaml_path = tmp_path / "contract.yaml"
        save_contract(contract, yaml_path)

        assert yaml_path.exists()

        loaded = load_contract(yaml_path)

        assert loaded.step_id == contract.step_id
        assert loaded.aip_id == contract.aip_id
        assert loaded.allowed_paths == contract.allowed_paths
        assert loaded.forbidden_paths == contract.forbidden_paths

    def test_save_and_load_json(self, tmp_path):
        """Contract can be saved and loaded as JSON."""
        contract = StepContract(
            step_id="step-001",
            aip_id="AIP-test",
            repo_root=tmp_path,
        )

        json_path = tmp_path / "contract.json"
        save_contract_json(contract, json_path)

        assert json_path.exists()

        loaded = load_contract_json(json_path)

        assert loaded.step_id == contract.step_id
        assert loaded.aip_id == contract.aip_id

    def test_save_creates_parent_dirs(self, tmp_path):
        """save_contract creates parent directories."""
        contract = StepContract(
            step_id="step-001",
            aip_id="AIP-test",
            repo_root=tmp_path,
        )

        deep_path = tmp_path / "deep" / "nested" / "contract.yaml"
        save_contract(contract, deep_path)

        assert deep_path.exists()

    def test_load_nonexistent_raises(self, tmp_path):
        """Loading nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_contract(tmp_path / "nonexistent.yaml")


# =============================================================================
# Edge Cases and Errors
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_allowed_paths_escalates(self, tmp_path):
        """Empty allowed_paths after derivation triggers escalation."""
        # This is a pathological case - in practice the defaults should
        # always provide something. But if step explicitly sets empty:
        aip = {
            "plan": [
                {
                    "step_id": "step-001",
                    "allowed_paths": [],  # Explicitly empty
                },
            ],
        }

        with pytest.raises(EscalationRequired) as exc:
            build_contract(aip, step_idx=0, repo_root=tmp_path)
        assert "Cannot derive allowed_paths" in str(exc.value)
        assert exc.value.step_id == "step-001"

    def test_invalid_plan_type(self, tmp_path):
        """Non-list plan raises error."""
        aip = {"plan": "not a list"}

        with pytest.raises(ContractBuildError) as exc:
            build_contract(aip, step_idx=0, repo_root=tmp_path)
        assert "must be a list" in str(exc.value)

    def test_invalid_step_type(self, tmp_path):
        """Non-dict step raises error."""
        aip = {"plan": ["not a dict"]}

        with pytest.raises(ContractBuildError) as exc:
            build_contract(aip, step_idx=0, repo_root=tmp_path)
        assert "must be a dict" in str(exc.value)

    def test_glob_patterns_preserved(self, tmp_path):
        """Glob patterns in outputs are preserved as-is."""
        aip = {
            "plan": [
                {
                    "step_id": "step-001",
                    "outputs": ["generated/**/*.py"],
                },
            ],
        }

        contract = build_contract(aip, step_idx=0, repo_root=tmp_path)

        # Glob pattern should be preserved
        assert "generated/**/*.py" in contract.allowed_paths

    def test_multiple_steps(self, tmp_path):
        """Build contract for different steps in same AIP."""
        aip = {
            "aip_id": "AIP-multi",
            "plan": [
                {"step_id": "step-001", "allowed_paths": ["step1/**"]},
                {"step_id": "step-002", "allowed_paths": ["step2/**"]},
                {"step_id": "step-003", "allowed_paths": ["step3/**"]},
            ],
        }

        c1 = build_contract(aip, step_idx=0, repo_root=tmp_path)
        c2 = build_contract(aip, step_idx=1, repo_root=tmp_path)
        c3 = build_contract(aip, step_idx=2, repo_root=tmp_path)

        assert c1.step_id == "step-001"
        assert c2.step_id == "step-002"
        assert c3.step_id == "step-003"

        assert c1.allowed_paths == ["step1/**"]
        assert c2.allowed_paths == ["step2/**"]
        assert c3.allowed_paths == ["step3/**"]
