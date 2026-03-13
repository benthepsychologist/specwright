"""Tests for spec draft CLI command."""

from unittest.mock import patch

from typer.testing import CliRunner

from spec.cli.spec import app

runner = CliRunner()


class TestSpecDraftHelp:
    """Tests for spec draft --help."""

    def test_draft_help_shows_usage(self):
        """spec draft --help shows usage information."""
        result = runner.invoke(app, ["draft", "--help"])
        assert result.exit_code == 0
        assert "Draft a spec from an epic entry" in result.output
        assert "--context" in result.output
        assert "--output" in result.output
        assert "--phases" in result.output
        assert "--llm" in result.output
        assert "--dry-run" in result.output


class TestSpecDraftFromEpic:
    """Tests for drafting from epic entries."""

    @patch("spec.cli.draft._load_epic_spec")
    def test_draft_from_epic_dry_run(self, mock_load, tmp_path):
        """Drafting with --dry-run prints to stdout."""
        from datetime import datetime

        from spec.epic.schema import Epic, Intent, SpecRef, Target

        epic = Epic(
            version="1.0",
            kind="epic",
            id="t004-test",
            title="Test Epic",
            owner="testuser",
            created=datetime.now(),
            updated=datetime.now(),
            intent=Intent(goal="Test goal"),
            targets=[
                Target(
                    id="myrepo",
                    repo_path=str(tmp_path / "myrepo"),
                    default_branch="main",
                )
            ],
            specs=[
                SpecRef(
                    id="t004-01-test",
                    repo="myrepo",
                    branch="feat/test",
                    title="Test Spec",
                    path="specs/t004-01-test.md",
                    expectations=["It should work"],
                )
            ],
        )

        # Create repo dir
        (tmp_path / "myrepo").mkdir()

        mock_load.return_value = (epic, epic.specs[0], tmp_path / "epic")

        result = runner.invoke(app, ["draft", "t004/t004-01", "--dry-run"])
        assert result.exit_code == 0
        assert "name: t004-01-test" in result.output
        assert "kind: spec" in result.output
        assert "acceptance_criteria:" in result.output

    @patch("spec.cli.draft._load_epic_spec")
    def test_draft_writes_to_epic_spec_path(self, mock_load, tmp_path):
        """Drafting writes to epic's spec.path by default."""
        from datetime import datetime

        from spec.epic.schema import Epic, Intent, SpecRef, Target

        epic_dir = tmp_path / "epic"
        epic_dir.mkdir()

        epic = Epic(
            version="1.0",
            kind="epic",
            id="t004-test",
            title="Test Epic",
            owner="testuser",
            created=datetime.now(),
            updated=datetime.now(),
            intent=Intent(goal="Test goal"),
            targets=[
                Target(
                    id="myrepo",
                    repo_path=str(tmp_path / "myrepo"),
                    default_branch="main",
                )
            ],
            specs=[
                SpecRef(
                    id="t004-01-test",
                    repo="myrepo",
                    branch="feat/test",
                    path="specs/t004-01-test.md",
                    expectations=["It should work"],
                )
            ],
        )

        # Create repo dir
        (tmp_path / "myrepo").mkdir()

        mock_load.return_value = (epic, epic.specs[0], epic_dir)

        result = runner.invoke(app, ["draft", "t004/t004-01"])
        assert result.exit_code == 0
        assert "Wrote spec to" in result.output

        # Check file was created
        output_file = epic_dir / "specs" / "t004-01-test.md"
        assert output_file.exists()
        content = output_file.read_text()
        assert "name: t004-01-test" in content

    @patch("spec.cli.draft._load_epic_spec")
    def test_draft_output_override(self, mock_load, tmp_path):
        """--output overrides default path."""
        from datetime import datetime

        from spec.epic.schema import Epic, Intent, SpecRef, Target

        epic = Epic(
            version="1.0",
            kind="epic",
            id="t004-test",
            title="Test Epic",
            owner="testuser",
            created=datetime.now(),
            updated=datetime.now(),
            intent=Intent(goal="Test goal"),
            targets=[
                Target(
                    id="myrepo",
                    repo_path=str(tmp_path / "myrepo"),
                    default_branch="main",
                )
            ],
            specs=[
                SpecRef(
                    id="t004-01-test",
                    repo="myrepo",
                    branch="feat/test",
                    expectations=["It should work"],
                )
            ],
        )

        # Create repo dir
        (tmp_path / "myrepo").mkdir()

        mock_load.return_value = (epic, epic.specs[0], tmp_path / "epic")

        custom_output = tmp_path / "custom" / "output.md"
        result = runner.invoke(
            app, ["draft", "t004/t004-01", "--output", str(custom_output)]
        )
        assert result.exit_code == 0
        assert custom_output.exists()

    @patch("spec.cli.draft._load_epic_spec")
    def test_draft_defaults_to_yaml_path_without_spec_entry_path(self, mock_load, tmp_path):
        """Without spec_entry.path, draft writes specs/<id>.yaml by default."""
        from datetime import datetime

        from spec.epic.schema import Epic, Intent, SpecRef, Target

        epic_dir = tmp_path / "epic"
        epic_dir.mkdir()

        epic = Epic(
            version="1.0",
            kind="epic",
            id="t004-test",
            title="Test Epic",
            owner="testuser",
            created=datetime.now(),
            updated=datetime.now(),
            intent=Intent(goal="Test goal"),
            targets=[
                Target(
                    id="myrepo",
                    repo_path=str(tmp_path / "myrepo"),
                    default_branch="main",
                )
            ],
            specs=[
                SpecRef(
                    id="t004-01-test",
                    repo="myrepo",
                    branch="feat/test",
                    expectations=["It should work"],
                )
            ],
        )

        (tmp_path / "myrepo").mkdir()
        mock_load.return_value = (epic, epic.specs[0], epic_dir)

        result = runner.invoke(app, ["draft", "t004/t004-01"])
        assert result.exit_code == 0
        assert (epic_dir / "specs" / "t004-01-test.yaml").exists()

    @patch("spec.cli.draft._load_epic_spec")
    def test_draft_phases_parameter(self, mock_load, tmp_path):
        """--phases controls number of phase sections."""
        from datetime import datetime

        from spec.epic.schema import Epic, Intent, SpecRef, Target

        epic = Epic(
            version="1.0",
            kind="epic",
            id="t004-test",
            title="Test Epic",
            owner="testuser",
            created=datetime.now(),
            updated=datetime.now(),
            intent=Intent(goal="Test goal"),
            targets=[
                Target(
                    id="myrepo",
                    repo_path=str(tmp_path / "myrepo"),
                    default_branch="main",
                )
            ],
            specs=[
                SpecRef(
                    id="t004-01-test",
                    repo="myrepo",
                    branch="feat/test",
                    expectations=["It should work"],
                )
            ],
        )

        # Create repo dir
        (tmp_path / "myrepo").mkdir()

        mock_load.return_value = (epic, epic.specs[0], tmp_path / "epic")

        result = runner.invoke(
            app, ["draft", "t004/t004-01", "--dry-run", "--phases", "4"]
        )
        assert result.exit_code == 0
        assert "phase_number: 1" in result.output
        assert "phase_number: 2" in result.output
        assert "phase_number: 3" in result.output
        assert "phase_number: 4" in result.output
        assert "phase_number: 5" not in result.output


class TestSpecDraftContext:
    """Tests for --context flag."""

    @patch("spec.cli.draft._load_epic_spec")
    def test_draft_with_context_file(self, mock_load, tmp_path):
        """--context includes additional material."""
        from datetime import datetime

        from spec.epic.schema import Epic, Intent, SpecRef, Target

        epic = Epic(
            version="1.0",
            kind="epic",
            id="t004-test",
            title="Test Epic",
            owner="testuser",
            created=datetime.now(),
            updated=datetime.now(),
            intent=Intent(goal="Test goal"),
            targets=[
                Target(
                    id="myrepo",
                    repo_path=str(tmp_path / "myrepo"),
                    default_branch="main",
                )
            ],
            specs=[
                SpecRef(
                    id="t004-01-test",
                    repo="myrepo",
                    branch="feat/test",
                    expectations=["It should work"],
                )
            ],
        )

        # Create repo and context file
        (tmp_path / "myrepo").mkdir()
        context_file = tmp_path / "notes.md"
        context_file.write_text("# Extra Notes\n\nSome additional context here.")

        mock_load.return_value = (epic, epic.specs[0], tmp_path / "epic")

        result = runner.invoke(
            app,
            ["draft", "t004/t004-01", "--dry-run", "--context", str(context_file)],
        )
        assert result.exit_code == 0

    def test_draft_context_file_not_found(self, tmp_path):
        """Missing context file fails with error."""
        result = runner.invoke(
            app,
            ["draft", "t004/t004-01", "--context", str(tmp_path / "nonexistent.md")],
        )
        assert result.exit_code == 1
        assert "Error" in result.output


class TestSpecDraftErrors:
    """Tests for error handling."""

    def test_invalid_spec_reference_fails(self):
        """Invalid spec reference fails with error."""
        result = runner.invoke(app, ["draft", "nonexistent-epic/nonexistent-spec"])
        assert result.exit_code == 1
        assert "Error" in result.output
