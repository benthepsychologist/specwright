"""Tests for input gathering for check execution."""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spec.checks.inputs import (
    GatheredInput,
    InputGatherError,
    gather_inputs,
)
from spec.epic.schema import (
    Check,
    CheckInput,
    CheckScope,
    Epic,
    GovernanceConfig,
    Intent,
    RunContext,
    Target,
)


def _make_epic(
    targets: list[Target] | None = None,
    run_context: RunContext | None = None,
    governance: GovernanceConfig | None = None,
) -> Epic:
    """Create a minimal Epic for testing."""
    return Epic(
        version="0.1",
        kind="epic",
        id="e001-test",
        title="Test Epic",
        owner="tester",
        created=datetime(2025, 1, 1),
        updated=datetime(2025, 1, 1),
        intent=Intent(goal="Test"),
        targets=targets or [],
        specs=[],
        checks=[],
        run_context=run_context,
        governance=governance,
    )


def _make_check(
    inputs: list[CheckInput],
    check_id: str = "CHECK-001",
) -> Check:
    """Create a minimal Check for testing."""
    return Check(
        id=check_id,
        name="Test Check",
        scope=CheckScope.EPIC,
        prompt_ref="checks/test.md",
        inputs=inputs,
    )


class TestGatherInputsEpic:
    """Tests for gathering epic type inputs."""

    def test_gather_epic_input(self) -> None:
        """Test gathering epic.yaml content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            epic_yaml = epic_path / "epic.yaml"
            epic_yaml.write_text("version: '0.1'\nkind: epic\n")

            epic = _make_epic()
            check = _make_check([CheckInput(type="epic")])

            result = gather_inputs(check, epic, epic_path)

            assert len(result) == 1
            assert result[0].type == "epic"
            assert result[0].content == "version: '0.1'\nkind: epic\n"
            assert "epic.yaml" in result[0].source

    def test_missing_epic_yaml_raises_error(self) -> None:
        """Test that missing epic.yaml raises InputGatherError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            # Don't create epic.yaml

            epic = _make_epic()
            check = _make_check([CheckInput(type="epic")])

            with pytest.raises(InputGatherError) as exc_info:
                gather_inputs(check, epic, epic_path)

            assert "epic.yaml not found" in str(exc_info.value)


class TestGatherInputsSpec:
    """Tests for gathering spec type inputs."""

    def test_gather_spec_input(self) -> None:
        """Test gathering spec file content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            governor_root = Path(tmpdir)
            spec_dir = governor_root / "specs"
            spec_dir.mkdir()
            spec_file = spec_dir / "feature.md"
            spec_file.write_text("# Feature Spec\n\nDetails here.")

            epic = _make_epic(
                run_context=RunContext(
                    governor_root=str(governor_root),
                    cli_bin="spec",
                    cwd_policy="repo",
                )
            )
            check = _make_check([
                CheckInput(type="spec", path="specs/feature.md")
            ])

            result = gather_inputs(check, epic, Path("/tmp/epic"))

            assert len(result) == 1
            assert result[0].type == "spec"
            assert result[0].content == "# Feature Spec\n\nDetails here."

    def test_spec_input_requires_path(self) -> None:
        """Test that spec input requires path field."""
        epic = _make_epic(
            run_context=RunContext(
                governor_root="/tmp",
                cli_bin="spec",
                cwd_policy="repo",
            )
        )
        check = _make_check([CheckInput(type="spec")])  # No path

        with pytest.raises(InputGatherError) as exc_info:
            gather_inputs(check, epic, Path("/tmp/epic"))

        assert "path" in str(exc_info.value).lower()

    def test_spec_input_requires_run_context(self) -> None:
        """Test that spec input requires run_context."""
        epic = _make_epic()  # No run_context
        check = _make_check([CheckInput(type="spec", path="specs/test.md")])

        with pytest.raises(InputGatherError) as exc_info:
            gather_inputs(check, epic, Path("/tmp/epic"))

        assert "run_context" in str(exc_info.value)


class TestGatherInputsFile:
    """Tests for gathering file type inputs."""

    def test_gather_file_input(self) -> None:
        """Test gathering file content from target repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            src_dir = repo_path / "src"
            src_dir.mkdir()
            code_file = src_dir / "main.py"
            code_file.write_text("print('hello')")

            epic = _make_epic(
                targets=[Target(
                    id="main",
                    repo_path=str(repo_path),
                    default_branch="main",
                )]
            )
            check = _make_check([CheckInput(type="file", path="src/main.py")])

            result = gather_inputs(check, epic, Path("/tmp/epic"))

            assert len(result) == 1
            assert result[0].type == "file"
            assert result[0].content == "print('hello')"

    def test_file_input_uses_specified_target(self) -> None:
        """Test that file input uses specified target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo1 = Path(tmpdir) / "repo1"
            repo2 = Path(tmpdir) / "repo2"
            repo1.mkdir()
            repo2.mkdir()

            (repo1 / "file.txt").write_text("repo1 content")
            (repo2 / "file.txt").write_text("repo2 content")

            epic = _make_epic(
                targets=[
                    Target(id="first", repo_path=str(repo1), default_branch="main"),
                    Target(id="second", repo_path=str(repo2), default_branch="main"),
                ]
            )
            check = _make_check([
                CheckInput(type="file", path="file.txt", target="second")
            ])

            result = gather_inputs(check, epic, Path("/tmp/epic"))

            assert result[0].content == "repo2 content"

    def test_file_input_missing_target_raises_error(self) -> None:
        """Test that missing target raises InputGatherError."""
        epic = _make_epic(
            targets=[Target(id="main", repo_path="/tmp", default_branch="main")]
        )
        check = _make_check([
            CheckInput(type="file", path="file.txt", target="nonexistent")
        ])

        with pytest.raises(InputGatherError) as exc_info:
            gather_inputs(check, epic, Path("/tmp/epic"))

        assert "not found" in str(exc_info.value)


class TestGatherInputsGitDiff:
    """Tests for gathering git_diff type inputs."""

    def test_git_diff_runs_in_correct_directory(self) -> None:
        """Test that git diff runs in the correct target directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            epic = _make_epic(
                targets=[Target(
                    id="main",
                    repo_path=str(repo_path),
                    default_branch="main",
                )]
            )
            check = _make_check([CheckInput(type="git_diff")])

            with patch("spec.checks.inputs.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="diff --git a/file.txt b/file.txt\n",
                    stderr="",
                )

                gather_inputs(check, epic, Path("/tmp/epic"))

                # Verify git was called with correct cwd
                mock_run.assert_called_once()
                call_kwargs = mock_run.call_args.kwargs
                assert call_kwargs["cwd"] == repo_path

    def test_git_diff_uses_correct_range(self) -> None:
        """Test that git diff uses the specified range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            epic = _make_epic(
                targets=[Target(
                    id="main",
                    repo_path=str(repo_path),
                    default_branch="main",
                )]
            )
            check = _make_check([
                CheckInput(type="git_diff", range="main..feature")
            ])

            with patch("spec.checks.inputs.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="diff output",
                    stderr="",
                )

                gather_inputs(check, epic, Path("/tmp/epic"))

                # Verify correct range was used
                call_args = mock_run.call_args.args[0]
                assert "main..feature" in call_args

    def test_git_diff_default_range(self) -> None:
        """Test that git diff uses default range when not specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            epic = _make_epic(
                targets=[Target(
                    id="main",
                    repo_path=str(repo_path),
                    default_branch="main",
                )]
            )
            check = _make_check([CheckInput(type="git_diff")])  # No range

            with patch("spec.checks.inputs.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="diff output",
                    stderr="",
                )

                gather_inputs(check, epic, Path("/tmp/epic"))

                # Verify default range was used
                call_args = mock_run.call_args.args[0]
                assert "HEAD~1..HEAD" in call_args

    def test_git_diff_failure_raises_error(self) -> None:
        """Test that git diff failure raises InputGatherError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            epic = _make_epic(
                targets=[Target(
                    id="main",
                    repo_path=str(repo_path),
                    default_branch="main",
                )]
            )
            check = _make_check([CheckInput(type="git_diff")])

            with patch("spec.checks.inputs.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=128,
                    stdout="",
                    stderr="fatal: not a git repository",
                )

                with pytest.raises(InputGatherError) as exc_info:
                    gather_inputs(check, epic, Path("/tmp/epic"))

                assert "git diff failed" in str(exc_info.value)


class TestGatherInputsCliOutput:
    """Tests for gathering cli_output type inputs."""

    def test_cli_output_captures_stdout(self) -> None:
        """Test that cli_output captures stdout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            epic = _make_epic(
                targets=[Target(
                    id="main",
                    repo_path=str(repo_path),
                    default_branch="main",
                )],
                run_context=RunContext(
                    governor_root="/tmp/gov",
                    cli_bin="echo",
                    cwd_policy="repo",
                ),
            )
            check = _make_check([
                CheckInput(type="cli_output", args=["hello", "world"])
            ])

            with patch("spec.checks.inputs.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="hello world\n",
                    stderr="",
                )

                result = gather_inputs(check, epic, Path("/tmp/epic"))

                assert result[0].content == "hello world\n"

    def test_cli_output_captures_stderr(self) -> None:
        """Test that cli_output captures stderr."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            epic = _make_epic(
                targets=[Target(
                    id="main",
                    repo_path=str(repo_path),
                    default_branch="main",
                )],
                run_context=RunContext(
                    governor_root="/tmp/gov",
                    cli_bin="test_cmd",
                    cwd_policy="repo",
                ),
            )
            check = _make_check([CheckInput(type="cli_output", args=["arg1"])])

            with patch("spec.checks.inputs.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="stdout content",
                    stderr="stderr content",
                )

                result = gather_inputs(check, epic, Path("/tmp/epic"))

                assert "stdout content" in result[0].content
                assert "stderr" in result[0].content
                assert "stderr content" in result[0].content

    def test_cli_output_requires_args(self) -> None:
        """Test that cli_output requires args field."""
        epic = _make_epic(
            run_context=RunContext(
                governor_root="/tmp",
                cli_bin="spec",
                cwd_policy="repo",
            ),
            targets=[Target(id="main", repo_path="/tmp", default_branch="main")],
        )
        check = _make_check([CheckInput(type="cli_output")])  # No args

        with pytest.raises(InputGatherError) as exc_info:
            gather_inputs(check, epic, Path("/tmp/epic"))

        assert "args" in str(exc_info.value).lower()

    def test_cli_output_failure_raises_error(self) -> None:
        """Test that cli_output failure raises InputGatherError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            epic = _make_epic(
                targets=[Target(
                    id="main",
                    repo_path=str(repo_path),
                    default_branch="main",
                )],
                run_context=RunContext(
                    governor_root="/tmp/gov",
                    cli_bin="failing_cmd",
                    cwd_policy="repo",
                ),
            )
            check = _make_check([CheckInput(type="cli_output", args=["arg"])])

            with patch("spec.checks.inputs.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="command failed",
                )

                with pytest.raises(InputGatherError) as exc_info:
                    gather_inputs(check, epic, Path("/tmp/epic"))

                assert "Command failed" in str(exc_info.value)


class TestGatherInputsGovernancePack:
    """Tests for gathering governance_pack type inputs (dormant stub)."""

    def test_gather_governance_pack_returns_dormant(self) -> None:
        """Test gathering governance pack returns dormant stub."""
        epic = _make_epic(
            governance=GovernanceConfig(
                enabled=False,
                source="local",
                project="test-project",
            )
        )
        check = _make_check([CheckInput(type="governance_pack")])

        result = gather_inputs(check, epic, Path("/tmp/epic"))

        assert len(result) == 1
        assert result[0].type == "governance_pack"
        assert result[0].source == "governance (dormant)"
        assert "autogov is dormant" in result[0].content.lower()

    def test_gather_governance_pack_no_governance_config(self) -> None:
        """Test gathering governance pack with no governance config returns dormant."""
        epic = _make_epic()  # No governance
        check = _make_check([CheckInput(type="governance_pack")])

        result = gather_inputs(check, epic, Path("/tmp/epic"))

        assert len(result) == 1
        assert result[0].type == "governance_pack"
        assert result[0].source == "governance (dormant)"
        assert "autogov is dormant" in result[0].content.lower()

    def test_gather_governance_pack_enabled_still_dormant(self) -> None:
        """Test governance pack returns dormant even when enabled (autogov removed)."""
        epic = _make_epic(
            governance=GovernanceConfig(
                enabled=True,
                source="local",
                project="test-project",
            )
        )
        check = _make_check([CheckInput(type="governance_pack")])

        result = gather_inputs(check, epic, Path("/tmp/epic"))

        assert len(result) == 1
        assert result[0].type == "governance_pack"
        assert result[0].source == "governance (dormant)"
        assert "autogov is dormant" in result[0].content.lower()


class TestUnknownInputType:
    """Tests for unknown input types."""

    def test_unknown_input_type_raises_error(self) -> None:
        """Test that unknown input type raises InputGatherError."""
        epic = _make_epic()
        check = _make_check([CheckInput(type="unknown_type")])

        with pytest.raises(InputGatherError) as exc_info:
            gather_inputs(check, epic, Path("/tmp/epic"))

        assert "Unknown input type" in str(exc_info.value)
        assert "unknown_type" in str(exc_info.value)


class TestGatherMultipleInputs:
    """Tests for gathering multiple inputs."""

    def test_gather_multiple_inputs(self) -> None:
        """Test gathering multiple inputs of different types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            epic_path = Path(tmpdir)
            repo_path = Path(tmpdir) / "repo"
            repo_path.mkdir()

            # Create epic.yaml
            (epic_path / "epic.yaml").write_text("version: '0.1'")

            # Create file in repo
            (repo_path / "file.txt").write_text("file content")

            epic = _make_epic(
                targets=[Target(
                    id="main",
                    repo_path=str(repo_path),
                    default_branch="main",
                )],
                governance=GovernanceConfig(
                    enabled=True,
                    source="local",
                    project="test",
                ),
            )
            check = _make_check([
                CheckInput(type="epic"),
                CheckInput(type="file", path="file.txt"),
                CheckInput(type="governance_pack"),
            ])

            result = gather_inputs(check, epic, epic_path)

            assert len(result) == 3
            assert result[0].type == "epic"
            assert result[1].type == "file"
            assert result[2].type == "governance_pack"


class TestInputGatherErrorExitCode:
    """Tests for InputGatherError exit code."""

    def test_exit_code_is_1(self) -> None:
        """Test that InputGatherError has exit_code 1."""
        assert InputGatherError.exit_code == 1


class TestGatheredInput:
    """Tests for GatheredInput dataclass."""

    def test_create_gathered_input(self) -> None:
        """Test creating a GatheredInput."""
        inp = GatheredInput(
            type="file",
            source="/path/to/file.txt",
            content="file content",
        )

        assert inp.type == "file"
        assert inp.source == "/path/to/file.txt"
        assert inp.content == "file content"
