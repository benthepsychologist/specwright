"""Tests for the artifact writer."""

from __future__ import annotations

import json
from pathlib import Path

from spec.executor.artifacts import (
    ArtifactWriter,
    create_artifact_writer,
    parse_diff_stats,
    write_step_summary,
    write_failure_context,
    write_input_bundle,
)
from spec.executor.runner import StepResult, TerminationReason


class TestArtifactWriter:
    """Tests for ArtifactWriter class."""

    def test_init(self, tmp_path: Path) -> None:
        """Test ArtifactWriter initialization."""
        writer = ArtifactWriter(tmp_path / "runs")
        assert writer.runs_dir == (tmp_path / "runs").resolve()

    def test_create_run_dir(self, tmp_path: Path) -> None:
        """Test create_run_dir creates correct structure."""
        writer = ArtifactWriter(tmp_path / "runs")

        run_dir = writer.create_run_dir("AIP-test-001", "step-003")

        assert run_dir.exists()
        assert "AIP-test-001" in str(run_dir)
        assert "step-003" in str(run_dir)
        # Check timestamp format (YYYY-MM-DDTHH-MM-SS)
        parts = run_dir.parts
        timestamp_part = parts[-2]  # Should be between aip_id and step_id
        assert len(timestamp_part) == 19  # YYYY-MM-DDTHH-MM-SS

    def test_write_result(self, tmp_path: Path) -> None:
        """Test write_result writes correct JSON."""
        writer = ArtifactWriter(tmp_path)
        run_dir = tmp_path / "step-001"
        run_dir.mkdir()

        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test-001",
            termination_reason=TerminationReason.PASS,
            iterations=[],
            touched_files=["src/foo.py", "tests/test_foo.py"],
        )

        result_path = writer.write_result(run_dir, result)

        assert result_path.exists()
        assert result_path.name == "result.json"

        content = json.loads(result_path.read_text())
        assert content["step_id"] == "step-001"
        assert content["aip_id"] == "AIP-test-001"
        assert content["termination_reason"] == "PASS"
        assert content["touched_files"] == ["src/foo.py", "tests/test_foo.py"]
        assert "timestamp" in content

    def test_write_result_with_error(self, tmp_path: Path) -> None:
        """Test write_result includes error info."""
        writer = ArtifactWriter(tmp_path)
        run_dir = tmp_path / "step-001"
        run_dir.mkdir()

        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test-001",
            termination_reason=TerminationReason.FAIL_SCOPE,
            iterations=[],
            error="Scope violation detected",
        )

        result_path = writer.write_result(run_dir, result)
        content = json.loads(result_path.read_text())

        assert content["termination_reason"] == "FAIL_SCOPE"
        assert content["details"]["error_message"] == "Scope violation detected"

    def test_write_gate_package(self, tmp_path: Path) -> None:
        """Test write_gate_package writes markdown."""
        writer = ArtifactWriter(tmp_path)
        run_dir = tmp_path / "step-001"
        run_dir.mkdir()

        gate_content = "# Gate Review\n\n**Result:** PASS"

        gate_path = writer.write_gate_package(run_dir, gate_content)

        assert gate_path.exists()
        assert gate_path.name == "gate.md"
        assert gate_path.read_text() == gate_content

    def test_write_final_reports(self, tmp_path: Path) -> None:
        """Test write_final_reports writes both reports."""
        writer = ArtifactWriter(tmp_path)
        run_dir = tmp_path / "step-001"
        run_dir.mkdir()

        policy_report = {"passed": True, "violations": []}
        verification_report = {"passed": True, "commands": []}

        writer.write_final_reports(run_dir, policy_report, verification_report)

        assert (run_dir / "policy_report.json").exists()
        assert (run_dir / "verification_report.json").exists()

        assert json.loads((run_dir / "policy_report.json").read_text()) == policy_report
        assert json.loads((run_dir / "verification_report.json").read_text()) == verification_report

    def test_write_final_reports_with_none(self, tmp_path: Path) -> None:
        """Test write_final_reports handles None values."""
        writer = ArtifactWriter(tmp_path)
        run_dir = tmp_path / "step-001"
        run_dir.mkdir()

        writer.write_final_reports(run_dir, None, None)

        assert not (run_dir / "policy_report.json").exists()
        assert not (run_dir / "verification_report.json").exists()

    def test_write_final_reports_partial(self, tmp_path: Path) -> None:
        """Test write_final_reports with only one report."""
        writer = ArtifactWriter(tmp_path)
        run_dir = tmp_path / "step-001"
        run_dir.mkdir()

        policy_report = {"passed": False, "violations": [{"file": "foo.py"}]}

        writer.write_final_reports(run_dir, policy_report, None)

        assert (run_dir / "policy_report.json").exists()
        assert not (run_dir / "verification_report.json").exists()


class TestCreateArtifactWriter:
    """Tests for factory function."""

    def test_creates_writer(self, tmp_path: Path) -> None:
        """Test factory function creates ArtifactWriter."""
        writer = create_artifact_writer(tmp_path / "runs")

        assert isinstance(writer, ArtifactWriter)
        assert writer.runs_dir == (tmp_path / "runs").resolve()


class TestWriteInputBundle:
    """Tests for write_input_bundle function."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        """Test write_input_bundle creates input directory."""
        input_dir = tmp_path / "input"

        write_input_bundle(
            input_dir,
            "step_id: step-001",
            "# Step Prompt",
            {"commit": "abc123", "branch": "main", "dirty": False, "baseline": "abc123"},
        )

        assert input_dir.exists()

    def test_writes_all_files(self, tmp_path: Path) -> None:
        """Test write_input_bundle writes all required files."""
        input_dir = tmp_path / "input"

        write_input_bundle(
            input_dir,
            "step_id: step-001",
            "# Step Prompt\n\nDo the thing.",
            {"commit": "abc123", "branch": "main", "dirty": False, "baseline": "abc123"},
        )

        assert (input_dir / "contract.yaml").exists()
        assert (input_dir / "prompt.md").exists()
        assert (input_dir / "repo_state.json").exists()

        assert (input_dir / "contract.yaml").read_text() == "step_id: step-001"
        assert (input_dir / "prompt.md").read_text() == "# Step Prompt\n\nDo the thing."

        repo_state = json.loads((input_dir / "repo_state.json").read_text())
        assert repo_state["commit"] == "abc123"
        assert repo_state["branch"] == "main"


class TestWriteFailureContext:
    """Tests for write_failure_context function."""

    def test_writes_basic_context(self, tmp_path: Path) -> None:
        """Test write_failure_context writes basic context."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        write_failure_context(
            input_dir,
            iteration=1,
            failure_category="verify_fail",
            failed_commands=[
                {"command": "pytest", "exit_code": 1, "stderr_tail": "FAILED"}
            ],
        )

        assert (input_dir / "failure_context.json").exists()

        context = json.loads((input_dir / "failure_context.json").read_text())
        assert context["iteration"] == 1
        assert context["failure_category"] == "verify_fail"
        assert len(context["failed_commands"]) == 1
        assert context["failed_commands"][0]["command"] == "pytest"

    def test_writes_with_paths(self, tmp_path: Path) -> None:
        """Test write_failure_context includes previous paths."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        write_failure_context(
            input_dir,
            iteration=2,
            failure_category="test_failure",
            failed_commands=[],
            previous_patch_path="iter-1/patch.diff",
            previous_verification_report_path="iter-1/verification_report.json",
        )

        context = json.loads((input_dir / "failure_context.json").read_text())
        assert context["previous_patch_path"] == "iter-1/patch.diff"
        assert context["previous_verification_report_path"] == "iter-1/verification_report.json"

    def test_omits_none_paths(self, tmp_path: Path) -> None:
        """Test write_failure_context omits None paths."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        write_failure_context(
            input_dir,
            iteration=1,
            failure_category="verify_fail",
            failed_commands=[],
        )

        context = json.loads((input_dir / "failure_context.json").read_text())
        assert "previous_patch_path" not in context
        assert "previous_verification_report_path" not in context


class TestDirectoryLayout:
    """Tests for the complete directory layout."""

    def test_full_layout_structure(self, tmp_path: Path) -> None:
        """Test that full layout can be created."""
        writer = ArtifactWriter(tmp_path / "runs")

        # Create run directory
        run_dir = writer.create_run_dir("AIP-test-001", "step-003")

        # Create input/output directories
        input_dir = run_dir / "input"
        output_dir = run_dir / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        # Write input bundle
        write_input_bundle(
            input_dir,
            "step_id: step-003",
            "# Do something",
            {"commit": "abc", "branch": "main", "dirty": False, "baseline": "abc"},
        )

        # Create iteration directory
        iter_dir = run_dir / "iter-0"
        iter_dir.mkdir()
        (iter_dir / "input").mkdir()
        (iter_dir / "output").mkdir()

        # Write iteration artifacts
        (iter_dir / "output" / "patch.diff").write_text("--- a/foo.py\n+++ b/foo.py")
        (iter_dir / "output" / "agent.json").write_text('{"status": "success"}')
        (iter_dir / "policy_report.json").write_text('{"passed": true}')
        (iter_dir / "verification_report.json").write_text('{"passed": true}')

        # Write final artifacts
        result = StepResult(
            step_id="step-003",
            aip_id="AIP-test-001",
            termination_reason=TerminationReason.PASS,
            touched_files=["foo.py"],
        )
        writer.write_result(run_dir, result)
        writer.write_gate_package(run_dir, "# Gate\n\nPASS")
        writer.write_final_reports(run_dir, {"passed": True}, {"passed": True})

        # Verify structure
        assert (run_dir / "input" / "contract.yaml").exists()
        assert (run_dir / "input" / "prompt.md").exists()
        assert (run_dir / "input" / "repo_state.json").exists()
        assert (run_dir / "iter-0" / "output" / "patch.diff").exists()
        assert (run_dir / "iter-0" / "output" / "agent.json").exists()
        assert (run_dir / "result.json").exists()
        assert (run_dir / "gate.md").exists()
        assert (run_dir / "policy_report.json").exists()
        assert (run_dir / "verification_report.json").exists()


class TestResultJsonSchema:
    """Tests verifying result.json contains all required fields."""

    def test_result_json_required_fields(self, tmp_path: Path) -> None:
        """Test result.json includes all required fields."""
        writer = ArtifactWriter(tmp_path)
        run_dir = tmp_path / "step-001"
        run_dir.mkdir()

        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test-001",
            step_idx=0,
            baseline_sha="abc123def456",
            adapter_name="claude",
            artifacts_dir="AIP-test-001/2024-01-01T00-00-00/step-001",
            termination_reason=TerminationReason.PASS,
            iterations=[],
            touched_files=["src/foo.py"],
        )

        result_path = writer.write_result(run_dir, result)
        content = json.loads(result_path.read_text())

        # Required identifiers
        assert content["aip_id"] == "AIP-test-001"
        assert content["step_idx"] == 0
        assert content["step_id"] == "step-001"

        # Execution context
        assert content["baseline_sha"] == "abc123def456"
        assert content["adapter_name"] == "claude"

        # Result
        assert content["termination_reason"] == "PASS"
        assert content["iterations_attempted"] == 0

        # Artifact paths
        assert content["artifacts_dir"] == "AIP-test-001/2024-01-01T00-00-00/step-001"

        # Meta
        assert "timestamp" in content

    def test_result_json_with_failure_details(self, tmp_path: Path) -> None:
        """Test result.json includes failure details when applicable."""
        writer = ArtifactWriter(tmp_path)
        run_dir = tmp_path / "step-001"
        run_dir.mkdir()

        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test-001",
            step_idx=1,
            baseline_sha="abc123",
            adapter_name="claude",
            artifacts_dir="test/path",
            termination_reason=TerminationReason.FAIL_VERIFY_RETRYABLE,
            iterations=[],
            error="Tests failed",
            verification_report={"passed": False, "failure_category": "test_failure"},
        )

        result_path = writer.write_result(run_dir, result)
        content = json.loads(result_path.read_text())

        assert content["termination_reason"] == "FAIL_VERIFY_RETRYABLE"
        assert content["details"]["error_message"] == "Tests failed"
        assert content["details"]["failure_category"] == "test_failure"

    def test_result_json_scope_violation_category(self, tmp_path: Path) -> None:
        """Test result.json marks scope violations correctly."""
        writer = ArtifactWriter(tmp_path)
        run_dir = tmp_path / "step-001"
        run_dir.mkdir()

        result = StepResult(
            step_id="step-001",
            aip_id="AIP-test-001",
            termination_reason=TerminationReason.FAIL_SCOPE,
            error="Out of scope",
            policy_report={"passed": False, "violations": [{"file": "bad.py"}]},
        )

        result_path = writer.write_result(run_dir, result)
        content = json.loads(result_path.read_text())

        assert content["details"]["failure_category"] == "scope_violation"


class TestParseDiffStats:
        def test_empty_diff(self) -> None:
                stats = parse_diff_stats("")
                assert stats["files_changed"] == 0
                assert stats["insertions"] == 0
                assert stats["deletions"] == 0
                assert stats["files"] == []

        def test_counts_files_and_hunks(self) -> None:
                diff = """diff --git a/src/a.py b/src/a.py
index 0000000..1111111 100644
--- a/src/a.py
+++ b/src/a.py
@@ -0,0 +1,2 @@
+print('hello')
+print('world')
diff --git a/tests/test_a.py b/tests/test_a.py
index 0000000..2222222 100644
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -0,0 +1,1 @@
+assert True
"""
                stats = parse_diff_stats(diff)
                assert stats["files_changed"] == 2
                assert stats["insertions"] == 3
                assert stats["deletions"] == 0
                assert stats["files"] == ["src/a.py", "tests/test_a.py"]


class TestWriteStepSummary:
        def test_writes_summary_with_outlines_and_no_patch_body(self, tmp_path: Path) -> None:
                run_dir = tmp_path / "step-001"
                (run_dir / "input").mkdir(parents=True)

                (run_dir / "input" / "contract.yaml").write_text(
                        """step_id: step-001
allowed_paths:
    - src/**
forbidden_paths:
    - secrets/**
verification_commands:
    - pytest -q
"""
                )
                (run_dir / "input" / "prompt.md").write_text(
                        "# Prompt\n\nDo the thing.\n\nThis is a longer body."
                )
                (run_dir / "sep.yaml").write_text(
                        """aip_id: AIP-test-001
step_id: step-001
objective: |
    Do the thing.
files_to_touch:
    - path: src/a.py
        action: modify
verification_steps:
    - command: pytest -q
allowed_paths:
    - src/**
forbidden_paths:
    - secrets/**
"""
                )

                unique_line = "+SOME_UNIQUE_INSERTION_LINE_SHOULD_NOT_APPEAR"
                (run_dir / "patch.diff").write_text(
                        """diff --git a/src/a.py b/src/a.py
index 0000000..1111111 100644
--- a/src/a.py
+++ b/src/a.py
@@ -0,0 +1,1 @@
"""
                        + unique_line
                        + "\n"
                )

                result = StepResult(
                        step_id="step-001",
                        aip_id="AIP-test-001",
                        termination_reason=TerminationReason.PASS,
                        iterations=[],
                        touched_files=["src/a.py"],
                        verification_report={
                                "passed": True,
                                "commands": [
                                        {"command": "pytest -q", "exit_code": 0, "passed": True},
                                ],
                        },
                        policy_report={"passed": True, "violations": []},
                )

                summary_path = write_step_summary(run_dir=run_dir, result=result)
                assert summary_path.exists()

                text = summary_path.read_text()
                assert unique_line not in text
                assert "patch_evaluation" in text
                assert "inputs" in text
                assert "preview" in text
                assert "outline" in text
