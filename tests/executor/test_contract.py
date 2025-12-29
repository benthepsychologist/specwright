"""Tests for Step Contract Builder."""

import tempfile
from pathlib import Path

import pytest

from spec.executor.contract import (
    FORBIDDEN_DEFAULTS,
    SAFE_ALLOWED_DEFAULTS,
    StepContract,
    build_contract,
    load_contract,
    save_contract,
)


class TestStepContract:
    """Tests for StepContract dataclass."""

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        contract = StepContract(
            aip_id="AIP-test-2024-12-13-001",
            step_id="step-001",
            step_index=0,
            allowed_paths=["src/**"],
            forbidden_paths=[".git/**"],
        )

        assert contract.verification_commands == []
        assert contract.verification_timeout == 300
        assert contract.max_iterations == 3
        assert contract.adapter == {"name": "claude", "mode": "oneshot"}
        assert contract.created_at  # Should be auto-set

    def test_adapter_defaults(self) -> None:
        """Test adapter default values."""
        contract = StepContract(
            aip_id="AIP-test-2024-12-13-001",
            step_id="step-001",
            step_index=0,
            allowed_paths=["src/**"],
            forbidden_paths=[".git/**"],
        )

        assert contract.adapter["name"] == "claude"
        assert contract.adapter["mode"] == "oneshot"


class TestBuildContractExplicitPaths:
    """Tests for Priority 1: Explicit step declaration."""

    def test_explicit_allowed_paths(self) -> None:
        """Test that explicit allowed_paths in step takes priority."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "allowed_paths": ["config/**", "*.yaml"],
                    "outputs": ["src/spec/executor/contract.py"],
                }
            ],
        }

        contract = build_contract(aip, 0)

        assert contract.allowed_paths == ["config/**", "*.yaml"]
        assert "src/**" not in contract.allowed_paths  # Explicit overrides defaults

    def test_explicit_empty_list_falls_through(self) -> None:
        """Test that empty explicit allowed_paths falls through to next priority."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "allowed_paths": [],
                    "outputs": ["src/spec/executor/contract.py"],
                }
            ],
        }

        contract = build_contract(aip, 0)

        # Should fall through to Priority 2 (outputs + safe defaults)
        assert "src/**" in contract.allowed_paths


class TestBuildContractFromOutputs:
    """Tests for Priority 2: Step outputs + safe defaults."""

    def test_derive_from_outputs(self) -> None:
        """Test that allowed_paths is derived from step outputs."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "outputs": [
                        "src/spec/executor/contract.py",
                        "tests/executor/test_contract.py",
                        "docs/README.md",
                    ],
                }
            ],
        }

        contract = build_contract(aip, 0)

        # Should derive top-level dirs from outputs
        assert "docs/**" in contract.allowed_paths
        assert "src/**" in contract.allowed_paths
        assert "tests/**" in contract.allowed_paths

    def test_outputs_include_safe_defaults(self) -> None:
        """Test that safe defaults are included with outputs."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "outputs": ["docs/EXECUTOR.md"],
                }
            ],
        }

        contract = build_contract(aip, 0)

        # Should include safe defaults even though outputs only has docs/
        assert "docs/**" in contract.allowed_paths
        assert "src/**" in contract.allowed_paths
        assert "tests/**" in contract.allowed_paths

    def test_root_level_output(self) -> None:
        """Test handling of root-level output files."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "outputs": ["README.md", "pyproject.toml"],
                }
            ],
        }

        contract = build_contract(aip, 0)

        # Root-level files should be allowed as-is
        assert "README.md" in contract.allowed_paths
        assert "pyproject.toml" in contract.allowed_paths


class TestBuildContractFallback:
    """Tests for Priority 3 and 4: Repo paths and fallback."""

    def test_fallback_to_repo_paths(self) -> None:
        """Test that repo.paths is used when no step outputs."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "repo": {"paths": ["lib/**", "app/**"]},
            "plan": [
                {
                    "step_id": "step-001",
                }
            ],
        }

        contract = build_contract(aip, 0)

        assert "lib/**" in contract.allowed_paths
        assert "app/**" in contract.allowed_paths
        # Safe defaults should still be included
        assert "src/**" in contract.allowed_paths
        assert "tests/**" in contract.allowed_paths

    def test_fallback_to_safe_defaults(self) -> None:
        """Test fallback to safe defaults when nothing else defined."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [
                {
                    "step_id": "step-001",
                }
            ],
        }

        contract = build_contract(aip, 0)

        assert contract.allowed_paths == SAFE_ALLOWED_DEFAULTS


class TestBuildContractForbiddenPaths:
    """Tests for forbidden_paths derivation."""

    def test_forbidden_defaults_always_included(self) -> None:
        """Test that forbidden defaults are always included."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [{"step_id": "step-001"}],
        }

        contract = build_contract(aip, 0)

        for default in FORBIDDEN_DEFAULTS:
            assert default in contract.forbidden_paths

    def test_context_constraints_parsed(self) -> None:
        """Test that context.constraints 'No changes to' rules are parsed."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "context": {
                "constraints": [
                    "No changes to src/spec/compiler/",
                    "No changes to migrations",
                ]
            },
            "plan": [{"step_id": "step-001"}],
        }

        contract = build_contract(aip, 0)

        assert "src/spec/compiler/**" in contract.forbidden_paths
        assert "migrations/**" in contract.forbidden_paths


class TestBuildContractAutogovIntegration:
    """Tests for autogov policy integration."""

    def test_autogov_protected_paths_merged(self) -> None:
        """Test that autogov protected_paths are merged into forbidden."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [{"step_id": "step-001"}],
        }
        autogov = {
            "protected_paths": ["src/spec/compiler/**", "infrastructure/**"]
        }

        contract = build_contract(aip, 0, autogov_policy=autogov)

        assert "src/spec/compiler/**" in contract.forbidden_paths
        assert "infrastructure/**" in contract.forbidden_paths

    def test_autogov_no_duplicates(self) -> None:
        """Test that duplicate paths are not added."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [{"step_id": "step-001"}],
        }
        autogov = {
            "protected_paths": [".git/**"]  # Already in defaults
        }

        contract = build_contract(aip, 0, autogov_policy=autogov)

        # Should only appear once
        assert contract.forbidden_paths.count(".git/**") == 1


class TestBuildContractEscalation:
    """Tests for escalation on empty allowed_paths."""

    def test_escalation_not_raised_with_defaults(self) -> None:
        """Test that escalation is not raised with safe defaults."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [{"step_id": "step-001"}],
        }

        # Should not raise - falls back to safe defaults
        contract = build_contract(aip, 0)
        assert len(contract.allowed_paths) > 0


class TestBuildContractEdgeCases:
    """Tests for edge cases."""

    def test_step_index_out_of_range(self) -> None:
        """Test that out-of-range step index raises IndexError."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [{"step_id": "step-001"}],
        }

        with pytest.raises(IndexError):
            build_contract(aip, 5)

    def test_negative_step_index(self) -> None:
        """Test that negative step index raises IndexError."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [{"step_id": "step-001"}],
        }

        with pytest.raises(IndexError):
            build_contract(aip, -1)

    def test_missing_step_id_generates_default(self) -> None:
        """Test that missing step_id generates a default."""
        aip = {
            "aip_id": "AIP-test-2024-12-13-001",
            "plan": [{}],
        }

        contract = build_contract(aip, 0)

        assert contract.step_id == "step-001"


class TestSaveLoadContract:
    """Tests for contract serialization."""

    def test_save_and_load_roundtrip(self) -> None:
        """Test that save and load produce equivalent contract."""
        contract = StepContract(
            aip_id="AIP-test-2024-12-13-001",
            step_id="step-001",
            step_index=0,
            allowed_paths=["src/**", "tests/**"],
            forbidden_paths=[".git/**", "secrets/**"],
            verification_commands=["pytest", "ruff check ."],
            max_iterations=5,
            baseline_commit="abc123",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "contract.yaml"
            save_contract(contract, path)
            loaded = load_contract(path)

        assert loaded.aip_id == contract.aip_id
        assert loaded.step_id == contract.step_id
        assert loaded.step_index == contract.step_index
        assert sorted(loaded.allowed_paths) == sorted(contract.allowed_paths)
        assert sorted(loaded.forbidden_paths) == sorted(contract.forbidden_paths)
        assert loaded.verification_commands == contract.verification_commands
        assert loaded.max_iterations == contract.max_iterations
        assert loaded.baseline_commit == contract.baseline_commit

    def test_save_creates_parent_dirs(self) -> None:
        """Test that save creates parent directories."""
        contract = StepContract(
            aip_id="AIP-test-2024-12-13-001",
            step_id="step-001",
            step_index=0,
            allowed_paths=["src/**"],
            forbidden_paths=[".git/**"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "deep" / "contract.yaml"
            save_contract(contract, path)

            assert path.exists()

    def test_save_is_deterministic(self) -> None:
        """Test that save produces deterministic output."""
        contract = StepContract(
            aip_id="AIP-test-2024-12-13-001",
            step_id="step-001",
            step_index=0,
            allowed_paths=["tests/**", "src/**"],  # Unsorted
            forbidden_paths=["secrets/**", ".git/**"],  # Unsorted
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = Path(tmpdir) / "contract1.yaml"
            path2 = Path(tmpdir) / "contract2.yaml"

            save_contract(contract, path1)
            save_contract(contract, path2)

            content1 = path1.read_text()
            content2 = path2.read_text()

            assert content1 == content2

    def test_adapter_roundtrip(self) -> None:
        """Test that adapter config survives roundtrip."""
        adapter = {"name": "claude", "mode": "oneshot"}
        contract = StepContract(
            aip_id="AIP-test-2024-12-13-001",
            step_id="step-001",
            step_index=0,
            allowed_paths=["src/**"],
            forbidden_paths=[".git/**"],
            adapter=adapter,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "contract.yaml"
            save_contract(contract, path)
            loaded = load_contract(path)

        assert loaded.adapter["name"] == "claude"
        assert loaded.adapter["mode"] == "oneshot"
