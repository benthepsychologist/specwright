import pytest

from spec.executor.contract import StepContract
from spec.executor.sep_builder import SEPBuilder


def make_contract(
    *,
    aip_id: str = "AIP-test-2024-12-13-001",
    step_id: str = "step-001",
    step_index: int = 1,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    verification_commands: list[str] | None = None,
) -> StepContract:
    return StepContract(
        aip_id=aip_id,
        step_id=step_id,
        step_index=step_index,
        allowed_paths=allowed_paths if allowed_paths is not None else ["src/**", "tests/**"],
        forbidden_paths=forbidden_paths if forbidden_paths is not None else [".git/**", ".env*", "secrets/**"],
        verification_commands=verification_commands if verification_commands is not None else ["pytest -q"],
    )


def test_build_sets_1_based_step_index_and_summarizes_objective() -> None:
    builder = SEPBuilder()
    aip = {
        "aip_id": "AIP-test-2024-12-13-001",
        "plan": [
            {
                "step_id": "step-001",
                "prompt": "Implement the SEP builder.\n\nCreate `src/spec/executor/sep_builder.py`.",
            }
        ],
    }

    sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

    assert sep.step_index == 1
    assert sep.step_id == "step-001"
    assert sep.objective == "Implement the SEP builder."
    assert len(sep.verification_steps) == 1
    assert sep.verification_steps[0].command == "pytest -q"


def test_extract_files_keeps_prompt_order_and_upgrades_action() -> None:
    builder = SEPBuilder()
    aip = {
        "aip_id": "AIP-test-2024-12-13-001",
        "plan": [
            {
                "step_id": "step-001",
                "prompt": "Create `a.py`. Update `b.py`. Delete `a.py`.",
            }
        ],
    }

    sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

    assert [fc.path for fc in sep.files_to_touch] == ["a.py", "b.py"]
    assert sep.files_to_touch[0].action == "delete"  # upgraded from create
    assert sep.files_to_touch[1].action == "modify"


def test_sensitive_path_prefix_pattern_triggers_review() -> None:
    builder = SEPBuilder()
    aip = {
        "aip_id": "AIP-test-2024-12-13-001",
        "plan": [
            {
                "step_id": "step-001",
                "prompt": "Update `.env.example`",
            }
        ],
    }

    sep = builder.build(
        aip=aip,
        step_idx=0,
        contract=make_contract(forbidden_paths=[".git/**", ".env*"]),
    )

    assert sep.requires_human_review is True


def test_sensitive_path_does_not_false_positive_on_dotgitignore() -> None:
    builder = SEPBuilder()
    aip = {
        "aip_id": "AIP-test-2024-12-13-001",
        "plan": [
            {
                "step_id": "step-001",
                "prompt": "Update `.gitignore`",
            }
        ],
    }

    sep = builder.build(
        aip=aip,
        step_idx=0,
        contract=make_contract(forbidden_paths=[".git/**"]),
    )

    assert sep.requires_human_review is False


def test_build_validates_step_idx_range() -> None:
    builder = SEPBuilder()
    aip = {"aip_id": "AIP-test-2024-12-13-001", "plan": [{"step_id": "step-001"}]}

    with pytest.raises(ValueError, match="out of range"):
        builder.build(aip=aip, step_idx=1, contract=make_contract())


def test_build_validates_plan_type() -> None:
    builder = SEPBuilder()
    aip = {"aip_id": "AIP-test-2024-12-13-001", "plan": "not-a-list"}

    with pytest.raises(ValueError, match="plan"):
        builder.build(aip=aip, step_idx=0, contract=make_contract())


# ==== Additional SEP Builder Tests ====


class TestFileExtractionPatterns:
    """Tests for file extraction from various prompt patterns."""

    def test_extract_create_pattern(self) -> None:
        """Extract file from 'Create `path`' pattern."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Create `src/new_module.py` with the initial implementation.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "src/new_module.py"
        assert sep.files_to_touch[0].action == "create"

    def test_extract_update_pattern(self) -> None:
        """Extract file from 'Update `path`' pattern."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Update `src/existing.py` to add new functionality.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "src/existing.py"
        assert sep.files_to_touch[0].action == "modify"

    def test_extract_modify_pattern(self) -> None:
        """Extract file from 'Modify `path`' pattern."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Modify `config/settings.yaml` to include new options.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "config/settings.yaml"
        assert sep.files_to_touch[0].action == "modify"

    def test_extract_delete_pattern(self) -> None:
        """Extract file from 'Delete `path`' pattern."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Delete `src/deprecated.py` as it's no longer needed.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "src/deprecated.py"
        assert sep.files_to_touch[0].action == "delete"

    def test_extract_add_to_pattern(self) -> None:
        """Extract file from 'Add to `path`' pattern."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Add to `src/__init__.py` the new exports.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "src/__init__.py"
        assert sep.files_to_touch[0].action == "modify"

    def test_extract_case_insensitive(self) -> None:
        """File extraction patterns are case-insensitive."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "CREATE `a.py`. UPDATE `b.py`. MODIFY `c.py`. DELETE `d.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 4
        assert sep.files_to_touch[0].action == "create"
        assert sep.files_to_touch[1].action == "modify"
        assert sep.files_to_touch[2].action == "modify"
        assert sep.files_to_touch[3].action == "delete"

    def test_extract_multiple_files_preserves_order(self) -> None:
        """Multiple file references preserve first-seen order."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Create `z.py`. Create `a.py`. Create `m.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert [fc.path for fc in sep.files_to_touch] == ["z.py", "a.py", "m.py"]

    def test_extract_whitespace_around_path_is_trimmed(self) -> None:
        """Whitespace around file paths is trimmed."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Create `  src/file.py  ` with content.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.files_to_touch[0].path == "src/file.py"

    def test_extract_empty_path_is_skipped(self) -> None:
        """Empty path strings are skipped."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Create `` and Create `real.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        # Only real.py should be extracted
        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "real.py"


class TestActionPriorityUpgrades:
    """Tests for action priority upgrade behavior."""

    def test_create_then_delete_upgrades_to_delete(self) -> None:
        """Create followed by Delete upgrades to delete (highest priority)."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Create `foo.py`. Delete `foo.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "foo.py"
        assert sep.files_to_touch[0].action == "delete"

    def test_create_then_modify_upgrades_to_modify(self) -> None:
        """Create followed by Update upgrades to modify."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Create `foo.py`. Update `foo.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].action == "modify"

    def test_modify_then_delete_upgrades_to_delete(self) -> None:
        """Modify followed by Delete upgrades to delete."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Update `foo.py`. Delete `foo.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.files_to_touch[0].action == "delete"

    def test_delete_then_create_stays_delete(self) -> None:
        """Delete then Create stays as delete (delete has highest priority)."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Delete `foo.py`. Create `foo.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.files_to_touch[0].action == "delete"

    def test_same_action_multiple_times_no_duplicates(self) -> None:
        """Same file mentioned multiple times with same action - no duplicates."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Update `foo.py`. Update `foo.py`. Update `foo.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "foo.py"


class TestComplexityEstimation:
    """Tests for complexity estimation logic."""

    def test_low_complexity_single_file_modify(self) -> None:
        """Single file modification is low complexity."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `foo.py`."}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.estimated_complexity == "low"

    def test_low_complexity_single_create(self) -> None:
        """Single file create is low complexity."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Create `foo.py`."}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.estimated_complexity == "low"

    def test_low_complexity_two_files(self) -> None:
        """Two file modifications is still low complexity."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `a.py`. Update `b.py`."}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.estimated_complexity == "low"

    def test_medium_complexity_three_files(self) -> None:
        """Three files is medium complexity."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {"step_id": "step-001", "prompt": "Update `a.py`. Update `b.py`. Update `c.py`."}
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.estimated_complexity == "medium"

    def test_medium_complexity_multiple_creates(self) -> None:
        """Multiple creates (> 1) is medium complexity."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Create `a.py`. Create `b.py`."}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.estimated_complexity == "medium"

    def test_high_complexity_many_files(self) -> None:
        """More than 5 files is high complexity."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Update `a.py`. Update `b.py`. Update `c.py`. Update `d.py`. Update `e.py`. Update `f.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.estimated_complexity == "high"

    def test_high_complexity_any_delete(self) -> None:
        """Any delete operation is high complexity."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Delete `old.py`."}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.estimated_complexity == "high"

    def test_low_complexity_no_files(self) -> None:
        """No files mentioned is low complexity."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Do something without files."}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.estimated_complexity == "low"


class TestSensitivePathDetection:
    """Tests for sensitive path detection logic."""

    def test_glob_pattern_match_triggers_review(self) -> None:
        """Direct glob pattern match triggers human review."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `secrets/keys.yaml`."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(forbidden_paths=["secrets/**"]),
        )

        assert sep.requires_human_review is True

    def test_env_prefix_pattern_triggers_review(self) -> None:
        """Files starting with .env* pattern trigger review."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `.env.local`."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(forbidden_paths=[".env*"]),
        )

        assert sep.requires_human_review is True

    def test_env_prefix_pattern_matches_dot_env_exactly(self) -> None:
        """The .env* pattern matches .env exactly."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `.env`."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(forbidden_paths=[".env*"]),
        )

        assert sep.requires_human_review is True

    def test_gitignore_does_not_match_git_pattern(self) -> None:
        """.gitignore does not match .git/** pattern."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `.gitignore`."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(forbidden_paths=[".git/**"]),
        )

        assert sep.requires_human_review is False

    def test_git_subpath_matches_git_pattern(self) -> None:
        """.git/config matches .git/** pattern."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `.git/config`."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(forbidden_paths=[".git/**"]),
        )

        assert sep.requires_human_review is True

    def test_safe_path_does_not_trigger_review(self) -> None:
        """Safe paths don't trigger human review."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `src/main.py`."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(forbidden_paths=[".git/**", ".env*", "secrets/**"]),
        )

        assert sep.requires_human_review is False

    def test_lock_file_triggers_review(self) -> None:
        """Lock files matching *.lock trigger review."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `package-lock.json`."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(forbidden_paths=["*.lock"]),
        )

        # Note: *.lock only matches files ending in .lock
        # package-lock.json doesn't match *.lock
        assert sep.requires_human_review is False

    def test_lock_pattern_matches_actual_lock_file(self) -> None:
        """Lock pattern matches actual .lock files."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Update `poetry.lock`."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(forbidden_paths=["*.lock"]),
        )

        assert sep.requires_human_review is True

    def test_any_one_sensitive_file_triggers_review(self) -> None:
        """If any file is sensitive, review is triggered."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Update `src/safe.py`. Update `.env.test`.",
                }
            ],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(forbidden_paths=[".env*"]),
        )

        assert sep.requires_human_review is True


class TestObjectiveSummarization:
    """Tests for objective summarization logic."""

    def test_summarize_takes_first_sentence(self) -> None:
        """Summarization prefers first sentence."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Implement the feature. This is additional context. More details here.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.objective == "Implement the feature."

    def test_summarize_truncates_long_objective(self) -> None:
        """Long objectives are truncated with ellipsis."""
        builder = SEPBuilder()
        long_prompt = "A" * 250  # Longer than 200 chars
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": long_prompt}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.objective) <= 200
        assert sep.objective.endswith("…")

    def test_summarize_empty_prompt_returns_empty(self) -> None:
        """Empty prompt returns empty objective."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": ""}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.objective == ""

    def test_summarize_collapses_whitespace(self) -> None:
        """Multiple whitespace is collapsed."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Do   the   thing.\n\nMore   stuff.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.objective == "Do the thing."

    def test_summarize_handles_exclamation_mark(self) -> None:
        """Exclamation mark is recognized as sentence end."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Fix the bug! More context here.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.objective == "Fix the bug!"

    def test_summarize_handles_question_mark(self) -> None:
        """Question mark is recognized as sentence end."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "What is the solution? Let me explain.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.objective == "What is the solution?"


class TestEdgeCases:
    """Tests for edge cases in SEP building."""

    def test_no_files_mentioned_in_prompt(self) -> None:
        """Prompt without file references produces empty files_to_touch."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Run the tests and verify everything works.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.files_to_touch == []

    def test_step_uses_objective_field_if_no_prompt(self) -> None:
        """Step can use 'objective' field instead of 'prompt'."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "objective": "Create `new_file.py` with implementation.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "new_file.py"

    def test_step_with_neither_prompt_nor_objective(self) -> None:
        """Step with neither prompt nor objective is handled gracefully."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001"}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.objective == ""
        assert sep.files_to_touch == []

    def test_step_with_null_prompt(self) -> None:
        """Step with null prompt is handled gracefully."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": None}],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert sep.objective == ""

    def test_contract_step_index_mismatch_raises_error(self) -> None:
        """Mismatched contract step_index raises ValueError."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Do something."}],
        }

        # step_idx=0 means step_index should be 1, but contract has 2
        with pytest.raises(ValueError, match="Contract step_index mismatch"):
            builder.build(
                aip=aip,
                step_idx=0,
                contract=make_contract(step_index=2),
            )

    def test_step_entry_not_a_dict_raises_error(self) -> None:
        """Non-dict plan entry raises ValueError."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": ["just a string"],
        }

        with pytest.raises(ValueError, match="plan entries must be mappings"):
            builder.build(aip=aip, step_idx=0, contract=make_contract())

    def test_negative_step_idx_raises_error(self) -> None:
        """Negative step_idx raises ValueError."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001"}],
        }

        with pytest.raises(ValueError, match="step_idx out of range"):
            builder.build(aip=aip, step_idx=-1, contract=make_contract())

    def test_verification_commands_from_contract(self) -> None:
        """Verification steps are built from contract verification_commands."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Do something."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(verification_commands=["pytest -v", "mypy src/"]),
        )

        assert len(sep.verification_steps) == 2
        assert sep.verification_steps[0].command == "pytest -v"
        assert sep.verification_steps[1].command == "mypy src/"
        assert sep.verification_steps[0].required is True
        assert "exits successfully" in sep.verification_steps[0].expected_outcome

    def test_empty_verification_commands(self) -> None:
        """Empty verification_commands produces empty verification_steps."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Do something."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(verification_commands=[]),
        )

        assert sep.verification_steps == []

    def test_builds_sep_for_middle_step(self) -> None:
        """SEPBuilder works for steps in the middle of a plan."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {"step_id": "step-001", "prompt": "First step."},
                {"step_id": "step-002", "prompt": "Create `middle.py`. Second step."},
                {"step_id": "step-003", "prompt": "Third step."},
            ],
        }

        sep = builder.build(
            aip=aip,
            step_idx=1,  # Zero-based index for step-002
            contract=make_contract(step_id="step-002", step_index=2),
        )

        assert sep.step_id == "step-002"
        assert sep.step_index == 2
        assert len(sep.files_to_touch) == 1
        assert sep.files_to_touch[0].path == "middle.py"

    def test_sep_inherits_paths_from_contract(self) -> None:
        """SEP inherits allowed_paths and forbidden_paths from contract."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [{"step_id": "step-001", "prompt": "Do something."}],
        }

        sep = builder.build(
            aip=aip,
            step_idx=0,
            contract=make_contract(
                allowed_paths=["lib/**", "bin/**"],
                forbidden_paths=["private/**"],
            ),
        )

        assert sep.allowed_paths == ["lib/**", "bin/**"]
        assert sep.forbidden_paths == ["private/**"]

    def test_file_change_descriptions_are_generated(self) -> None:
        """FileChange descriptions are auto-generated based on action."""
        builder = SEPBuilder()
        aip = {
            "aip_id": "AIP-test-001",
            "plan": [
                {
                    "step_id": "step-001",
                    "prompt": "Create `new.py`. Update `existing.py`. Delete `old.py`.",
                }
            ],
        }

        sep = builder.build(aip=aip, step_idx=0, contract=make_contract())

        assert "Create new file" in sep.files_to_touch[0].description
        assert "Modify existing file" in sep.files_to_touch[1].description
        assert "Delete file" in sep.files_to_touch[2].description
