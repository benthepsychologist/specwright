"""Tests for check executor."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from spec.checks.executor import CheckExecutor
from spec.checks.inputs import InputGatherError
from spec.epic.schema import (
    Check,
    CheckInput,
    CheckScope,
    Defaults,
    Epic,
    EpicState,
    Intent,
    RunContext,
    SpecStatus,
    Target,
)


def _make_epic(
    targets: list[Target] | None = None,
    checks: list[Check] | None = None,
    run_context: RunContext | None = None,
    defaults: Defaults | None = None,
    state: EpicState | None = None,
) -> Epic:
    """Create a minimal Epic for testing."""
    return Epic(
        version="0.1",
        kind="epic",
        id="e001-test",
        title="Test Epic",
        owner="tester",
        created=datetime(2025, 1, 1, tzinfo=UTC),
        updated=datetime(2025, 1, 1, tzinfo=UTC),
        intent=Intent(goal="Test"),
        targets=targets or [],
        specs=[],
        checks=checks or [],
        run_context=run_context,
        defaults=defaults,
        state=state,
    )


def _make_check(
    check_id: str = "CHECK-001",
    inputs: list[CheckInput] | None = None,
    model: str | None = None,
) -> Check:
    """Create a minimal Check for testing."""
    return Check(
        id=check_id,
        name="Test Check",
        scope=CheckScope.EPIC,
        prompt_ref="checks/test.md",
        inputs=inputs or [],
        model=model,
    )


class MockLLMClient:
    """Mock LLM client for testing."""

    def __init__(self, response: str = "VERDICT: PASS\n\nAnalysis complete."):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt: str, model: str) -> str:
        self.calls.append((prompt, model))
        return self.response


class TestCheckExecutorStub:
    """Tests for CheckExecutor stub mode (no LLM client)."""

    def test_stub_executor_produces_not_run_verdict(self) -> None:
        """Test that stub executor produces NOT_RUN verdict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml for epic input
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(checks=[check])

            executor = CheckExecutor(llm_client=None)  # Stub mode
            report = executor.execute(epic, "CHECK-001", epic_path)

            assert report.verdict == "NOT_RUN"
            assert report.model == "stub"
            assert "LLM integration not configured" in report.content

    def test_stub_response_includes_input_count(self) -> None:
        """Test that stub response mentions gathered inputs count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(checks=[check])

            executor = CheckExecutor(llm_client=None)
            report = executor.execute(epic, "CHECK-001", epic_path)

            assert "1 inputs were gathered" in report.content


class TestCheckExecutorWithLLM:
    """Tests for CheckExecutor with LLM client."""

    def test_executor_with_llm_parses_verdict(self) -> None:
        """Test that executor parses verdict from LLM response."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(checks=[check])

            mock_client = MockLLMClient(response="VERDICT: PASS\n\nAll good.")
            executor = CheckExecutor(llm_client=mock_client)
            report = executor.execute(epic, "CHECK-001", epic_path)

            assert report.verdict == "PASS"

    def test_executor_uses_check_model(self) -> None:
        """Test that executor uses model from check definition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(
                inputs=[CheckInput(type="epic")],
                model="gpt-4o",
            )
            epic = _make_epic(checks=[check])

            mock_client = MockLLMClient()
            executor = CheckExecutor(llm_client=mock_client)
            report = executor.execute(epic, "CHECK-001", epic_path)

            assert report.model == "gpt-4o"
            assert mock_client.calls[0][1] == "gpt-4o"

    def test_executor_uses_epic_defaults_model(self) -> None:
        """Test that executor falls back to epic defaults model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(inputs=[CheckInput(type="epic")])  # No model
            epic = _make_epic(
                checks=[check],
                defaults=Defaults(model="claude-3"),
            )

            mock_client = MockLLMClient()
            executor = CheckExecutor(llm_client=mock_client)
            report = executor.execute(epic, "CHECK-001", epic_path)

            assert report.model == "claude-3"

    def test_executor_default_model_when_none_specified(self) -> None:
        """Test that executor uses 'default' when no model specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(checks=[check])  # No defaults

            mock_client = MockLLMClient()
            executor = CheckExecutor(llm_client=mock_client)
            report = executor.execute(epic, "CHECK-001", epic_path)

            assert report.model == "default"


class TestCheckExecutorVerdictParsing:
    """Tests for verdict parsing in executor."""

    @pytest.mark.parametrize("verdict", ["PASS", "WARN", "FAIL"])
    def test_parse_valid_verdicts(self, verdict: str) -> None:
        """Test parsing valid verdict values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(checks=[check])

            mock_client = MockLLMClient(response=f"VERDICT: {verdict}\n\nDetails.")
            executor = CheckExecutor(llm_client=mock_client)
            report = executor.execute(epic, "CHECK-001", epic_path)

            assert report.verdict == verdict

    def test_default_to_error_when_verdict_not_found(self) -> None:
        """Test that missing verdict defaults to ERROR for real LLM."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(checks=[check])

            # Response without VERDICT line
            mock_client = MockLLMClient(response="Analysis complete.")
            executor = CheckExecutor(llm_client=mock_client)
            report = executor.execute(epic, "CHECK-001", epic_path)

            assert report.verdict == "ERROR"


class TestCheckExecutorRunAndSave:
    """Tests for run_and_save method."""

    def test_run_and_save_writes_report(self) -> None:
        """Test that run_and_save writes report to epic path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'\nkind: epic\nid: e001-test\ntitle: Test\nowner: test\ncreated: 2025-01-01T00:00:00+00:00\nupdated: 2025-01-01T00:00:00+00:00\nintent:\n  goal: Test\ntargets: []\nspecs: []\nchecks: []\nstate:\n  status: planned\n  history: []")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(
                checks=[check],
                state=EpicState(
                    status=SpecStatus.PLANNED,
                    history=[],
                ),
            )

            executor = CheckExecutor(llm_client=None)

            # Patch get_epic_path to return our temp directory
            with patch("spec.epic.writer.get_epic_path", return_value=epic_path):
                report, report_path = executor.run_and_save(epic, "CHECK-001", epic_path)

            assert report_path.exists()
            assert report_path.parent.name == "reports"
            assert "CHECK-001" in report_path.name

    def test_run_and_save_appends_history_event(self) -> None:
        """Test that run_and_save appends history event."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml with proper structure
            (epic_path / "epic.yaml").write_text("version: '0.1'\nkind: epic\nid: e001-test\ntitle: Test\nowner: test\ncreated: 2025-01-01T00:00:00+00:00\nupdated: 2025-01-01T00:00:00+00:00\nintent:\n  goal: Test\ntargets: []\nspecs: []\nchecks: []\nstate:\n  status: planned\n  history: []")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(
                checks=[check],
                state=EpicState(
                    status=SpecStatus.PLANNED,
                    history=[],
                ),
            )

            executor = CheckExecutor(llm_client=None)

            # Patch get_epic_path to return our temp directory
            with patch("spec.epic.writer.get_epic_path", return_value=epic_path):
                executor.run_and_save(epic, "CHECK-001", epic_path)

            # Check that history was updated
            assert len(epic.state.history) == 1
            event = epic.state.history[0]
            assert event.check_id == "CHECK-001"
            assert event.verdict == "NOT_RUN"

    def test_run_and_save_with_spec_id(self) -> None:
        """Test run_and_save with spec_id parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'\nkind: epic\nid: e001-test\ntitle: Test\nowner: test\ncreated: 2025-01-01T00:00:00+00:00\nupdated: 2025-01-01T00:00:00+00:00\nintent:\n  goal: Test\ntargets: []\nspecs: []\nchecks: []\nstate:\n  status: planned\n  history: []")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(
                checks=[check],
                state=EpicState(
                    status=SpecStatus.PLANNED,
                    history=[],
                ),
            )

            executor = CheckExecutor(llm_client=None)

            # Patch get_epic_path to return our temp directory
            with patch("spec.epic.writer.get_epic_path", return_value=epic_path):
                report, _ = executor.run_and_save(
                    epic, "CHECK-001", epic_path, spec_id="e001-01-core"
                )

            assert report.spec_id == "e001-01-core"


class TestCheckExecutorErrors:
    """Tests for executor error handling."""

    def test_check_not_found_raises_value_error(self) -> None:
        """Test that missing check raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            epic = _make_epic(checks=[])  # No checks

            executor = CheckExecutor(llm_client=None)

            with pytest.raises(ValueError) as exc_info:
                executor.execute(epic, "NONEXISTENT", epic_path)

            assert "Check not found" in str(exc_info.value)

    def test_run_and_save_handles_input_gather_error(self) -> None:
        """Test that run_and_save handles InputGatherError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml - but DON'T create the file that the check needs
            (epic_path / "epic.yaml").write_text("version: '0.1'\nkind: epic\nid: e001-test\ntitle: Test\nowner: test\ncreated: 2025-01-01T00:00:00+00:00\nupdated: 2025-01-01T00:00:00+00:00\nintent:\n  goal: Test\ntargets: []\nspecs: []\nchecks: []\nstate:\n  status: planned\n  history: []")

            # Check that requires a file that doesn't exist
            check = _make_check(inputs=[
                CheckInput(type="file", path="nonexistent.txt")
            ])
            epic = _make_epic(
                checks=[check],
                targets=[Target(id="main", repo_path=str(epic_path), default_branch="main")],
                state=EpicState(
                    status=SpecStatus.PLANNED,
                    history=[],
                ),
            )

            executor = CheckExecutor(llm_client=None)

            # Patch get_epic_path to return our temp directory
            with patch("spec.epic.writer.get_epic_path", return_value=epic_path):
                with pytest.raises(InputGatherError):
                    executor.run_and_save(epic, "CHECK-001", epic_path)

            # Check that error report was written and history updated
            assert len(epic.state.history) == 1
            event = epic.state.history[0]
            assert event.verdict == "ERROR"


class TestPromptAssembly:
    """Tests for prompt assembly."""

    def test_prompt_includes_inputs_section(self) -> None:
        """Test that assembled prompt includes inputs section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt\n\nInstructions here.")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(checks=[check])

            mock_client = MockLLMClient()
            executor = CheckExecutor(llm_client=mock_client)
            executor.execute(epic, "CHECK-001", epic_path)

            # Check the prompt that was sent to LLM
            sent_prompt = mock_client.calls[0][0]
            assert "# Test Prompt" in sent_prompt
            assert "# Inputs" in sent_prompt
            assert "epic:" in sent_prompt

    def test_prompt_without_inputs(self) -> None:
        """Test that prompt without inputs has no inputs section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            check = _make_check(inputs=[])  # No inputs
            epic = _make_epic(checks=[check])

            mock_client = MockLLMClient()
            executor = CheckExecutor(llm_client=mock_client)
            executor.execute(epic, "CHECK-001", epic_path)

            sent_prompt = mock_client.calls[0][0]
            assert "# Inputs" not in sent_prompt


class TestCheckReport:
    """Tests for CheckReport creation."""

    def test_report_has_correct_fields(self) -> None:
        """Test that report has all required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)

            # Create prompt file
            checks_dir = epic_path / "checks"
            checks_dir.mkdir()
            (checks_dir / "test.md").write_text("# Test Prompt")

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            check = _make_check(inputs=[CheckInput(type="epic")])
            epic = _make_epic(checks=[check])

            executor = CheckExecutor(llm_client=None)
            report = executor.execute(epic, "CHECK-001", epic_path)

            assert report.check_id == "CHECK-001"
            assert report.epic_id == "e001-test"
            assert report.model == "stub"
            assert report.verdict == "NOT_RUN"
            assert isinstance(report.timestamp, datetime)
            assert isinstance(report.inputs, list)
            assert isinstance(report.content, str)
