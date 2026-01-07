"""End-to-end integration tests for the epic system.

These tests cover only the Step 6 required workflows:
1) Create epic -> add target -> add spec -> set-current -> status
2) mark-done -> status shows done with checkmark
3) validate detects cycles and missing refs
4) check with LLM disabled returns exit 4 with message (deterministic)
5) check with mock LLM returns deterministic output

Determinism notes:
- Epic storage is isolated via SPECWRIGHT_GOVERNOR_ROOT (temp dir).
- LLM config path does NOT follow SPECWRIGHT_GOVERNOR_ROOT, so tests patch
  spec.llm.config.get_governor_config_path to point at a temp config file.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from spec.cli.spec import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def governor_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "epics").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SPECWRIGHT_GOVERNOR_ROOT", str(tmp_path))
    return tmp_path


def _invoke_ok(runner: CliRunner, args: list[str]) -> str:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.output


def _write_epic_yaml(governor_root: Path, epic_id: str, yaml_text: str) -> None:
    epic_dir = governor_root / "epics" / epic_id
    epic_dir.mkdir(parents=True, exist_ok=True)
    (epic_dir / "epic.yaml").write_text(yaml_text)


def _write_epic_with_check(governor_root: Path, epic_id: str) -> None:
    epic_dir = governor_root / "epics" / epic_id
    checks_dir = epic_dir / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)
    (checks_dir / "CHECK-001.md").write_text("# Check\n\nReturn a short response.")

    _write_epic_yaml(
        governor_root,
        epic_id,
        f"""version: \"0.1\"
kind: epic
id: {epic_id}
title: \"Test Epic\"
owner: testuser
created: 2025-01-01T00:00:00Z
updated: 2025-01-01T00:00:00Z
intent:
  goal: \"Test goal\"

targets: []
specs: []
checks:
  - id: CHECK-001
    name: \"Test Check\"
    scope: epic
    prompt_ref: checks/CHECK-001.md
state:
  status: planned
""",
    )


class TestEpicE2ERequiredWorkflows:
    def test_01_create_add_target_add_spec_set_current_status(
        self, runner: CliRunner, governor_root: Path
    ) -> None:
        epic_id = "e001-test-epic"

        _invoke_ok(
            runner,
            [
                "epic",
                "create",
                "Test Epic",
                "--id",
                epic_id,
                "--goal",
                "Test the epic system",
                "--owner",
                "testuser",
            ],
        )

        _invoke_ok(
            runner,
            [
                "epic",
                "add-target",
                epic_id,
                "--id",
                "myrepo",
                "--repo-path",
                "/workspace/myrepo",
                "--branch",
                "main",
            ],
        )

        _invoke_ok(
            runner,
            [
                "epic",
                "add-spec",
                epic_id,
                "--id",
                "spec-01",
                "--repo",
                "myrepo",
                "--branch",
                "feat/test",
                "--path",
                "specs/test.md",
            ],
        )

        _invoke_ok(runner, ["epic", "set-current", epic_id, "--spec", "spec-01"])

        output = _invoke_ok(runner, ["epic", "status", epic_id])
        assert f"ID: {epic_id}" in output
        assert "Current: spec-01" in output
        assert "spec-01" in output

    def test_02_mark_done_then_status_shows_done_checkmark(
        self, runner: CliRunner, governor_root: Path
    ) -> None:
        epic_id = "e002-mark-done"

        _invoke_ok(
            runner,
            [
                "epic",
                "create",
                "Mark Done Epic",
                "--id",
                epic_id,
                "--goal",
                "Test mark-done",
                "--owner",
                "testuser",
            ],
        )

        _invoke_ok(
            runner,
            [
                "epic",
                "add-target",
                epic_id,
                "--id",
                "myrepo",
                "--repo-path",
                "/workspace/myrepo",
            ],
        )

        _invoke_ok(
            runner,
            [
                "epic",
                "add-spec",
                epic_id,
                "--id",
                "spec-01",
                "--repo",
                "myrepo",
                "--branch",
                "main",
                "--path",
                "specs/spec-01.md",
            ],
        )

        _invoke_ok(runner, ["epic", "set-current", epic_id, "--spec", "spec-01"])
        _invoke_ok(
            runner,
            ["epic", "mark-done", epic_id, "--spec", "spec-01", "--note", "done"],
        )

        output = _invoke_ok(runner, ["epic", "status", epic_id])
        assert "spec-01" in output
        assert "\u2713" in output
        assert "spec-01 [done]" in output

    def test_03_validate_detects_cycle_exit_3(self, runner: CliRunner, governor_root: Path) -> None:
        epic_id = "e003-cycle"

        _write_epic_yaml(
            governor_root,
            epic_id,
            f"""version: \"0.1\"
kind: epic
id: {epic_id}
title: \"Cycle Epic\"
owner: testuser
created: 2025-01-01T00:00:00Z
updated: 2025-01-01T00:00:00Z
intent:
  goal: \"Test cycle\"

targets:
  - id: myrepo
    repo_path: /workspace/myrepo
    default_branch: main
specs:
  - id: spec-01
    repo: myrepo
    branch: main
    path: specs/one.md
    status: planned
    depends_on: [spec-02]
  - id: spec-02
    repo: myrepo
    branch: main
    path: specs/two.md
    status: planned
    depends_on: [spec-01]
checks: []
""",
        )

        result = runner.invoke(app, ["epic", "validate", epic_id])
        assert result.exit_code == 3
        assert "cycle" in result.output.lower()

    def test_04_validate_detects_missing_target_ref_exit_3(
        self, runner: CliRunner, governor_root: Path
    ) -> None:
        epic_id = "e004-missing-target"

        _write_epic_yaml(
            governor_root,
            epic_id,
            f"""version: \"0.1\"
kind: epic
id: {epic_id}
title: \"Missing Target Epic\"
owner: testuser
created: 2025-01-01T00:00:00Z
updated: 2025-01-01T00:00:00Z
intent:
  goal: \"Test missing target\"

targets: []
specs:
  - id: spec-01
    repo: missingrepo
    branch: main
    path: specs/one.md
    status: planned
checks: []
""",
        )

        result = runner.invoke(app, ["epic", "validate", epic_id])
        assert result.exit_code == 3
        assert "unknown target" in result.output.lower()

    def test_05_check_llm_disabled_exit_4_is_deterministic(
        self, runner: CliRunner, governor_root: Path
    ) -> None:
        epic_id = "e005-llm-disabled"
        _write_epic_with_check(governor_root, epic_id)

        config_path = governor_root / "config.yaml"
        config_path.write_text("llm:\n  enabled: false\n")

        with patch("spec.llm.config.get_governor_config_path", return_value=config_path):
            result = runner.invoke(app, ["epic", "check", epic_id])

        assert result.exit_code == 4
        assert "LLM is not enabled" in result.output

    def test_06_check_with_mock_llm_exit_0_and_outputs_response(
        self, runner: CliRunner, governor_root: Path
    ) -> None:
        epic_id = "e006-llm-mock"
        _write_epic_with_check(governor_root, epic_id)

        from spec.llm.config import LLMConfig

        with patch(
            "spec.llm.config.require_llm_enabled",
            return_value=LLMConfig(enabled=True, timeout_s=120),
        ):
            with patch("spec.llm.client.LLMClient") as MockClient:
                instance = MockClient.return_value
                instance.prompt.return_value = "MOCK RESPONSE"

                result = runner.invoke(app, ["epic", "check", epic_id])

        assert result.exit_code == 0
        assert "MOCK RESPONSE" in result.output
        assert "All checks completed" in result.output
