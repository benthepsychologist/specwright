"""Tests for epic loader - load and validate from YAML."""

import os
from pathlib import Path

import pytest

from spec.epic.loader import (
    CATEGORY_MAP,
    EpicNotFoundError,
    EpicValidationError,
    get_category_dir,
    get_category_from_id,
    get_epic_path,
    get_governor_root,
    list_epics,
    load_epic,
    load_epic_from_path,
)


@pytest.fixture
def temp_governor(tmp_path: Path):
    """Create a temporary governor directory."""
    epics_dir = tmp_path / "epics"
    epics_dir.mkdir()

    old_env = os.environ.get("SPECWRIGHT_GOVERNOR_ROOT")
    os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = str(tmp_path)

    yield tmp_path

    if old_env:
        os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = old_env
    else:
        del os.environ["SPECWRIGHT_GOVERNOR_ROOT"]


@pytest.fixture
def valid_epic_yaml() -> str:
    """Valid epic YAML content."""
    return '''version: "0.1"
kind: epic
id: test-epic
title: "Test Epic"
owner: testuser
created: 2025-12-26T00:00:00Z
updated: 2025-12-26T00:00:00Z

intent:
  goal: "Test the epic system"
  narrative: "A test narrative."

targets:
  - id: myrepo
    repo_path: /workspace/myrepo
    default_branch: main

specs:
  - id: spec-001
    repo: myrepo
    branch: feat/test
    path: specs/test.md
    status: active

state:
  status: active
  current_spec: spec-001
  history:
    - id: EVT-0001
      at: 2025-12-26T00:00:00Z
      event: epic.created
      actor: human
'''


class TestGetGovernorRoot:
    """Tests for get_governor_root function."""

    def test_uses_env_var(self, tmp_path: Path):
        """Uses SPECWRIGHT_GOVERNOR_ROOT env var when set."""
        os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = str(tmp_path)
        try:
            root = get_governor_root()
            assert root == tmp_path
        finally:
            del os.environ["SPECWRIGHT_GOVERNOR_ROOT"]

    def test_expands_user(self, tmp_path: Path):
        """Expands ~ in paths."""
        os.environ["SPECWRIGHT_GOVERNOR_ROOT"] = "~/test-governor"
        try:
            root = get_governor_root()
            assert "~" not in str(root)
            assert root.is_absolute()
        finally:
            del os.environ["SPECWRIGHT_GOVERNOR_ROOT"]

    def test_default_path(self, monkeypatch):
        """Uses default path when env var not set."""
        monkeypatch.delenv("SPECWRIGHT_GOVERNOR_ROOT", raising=False)
        root = get_governor_root()
        assert ".local/local-governor" in str(root)


class TestCategoryFunctions:
    """Tests for category helper functions."""

    def test_get_category_from_id_tooling(self):
        """Extracts 't' from tooling epic IDs."""
        assert get_category_from_id("t004-specwright") == "t"
        assert get_category_from_id("t012-canon-registries") == "t"

    def test_get_category_from_id_epics(self):
        """Extracts 'e' from domain epic IDs."""
        assert get_category_from_id("e001-auth") == "e"
        assert get_category_from_id("e012-pm-system") == "e"

    def test_get_category_from_id_all_categories(self):
        """Extracts all category prefixes correctly."""
        assert get_category_from_id("a001-architecture") == "a"
        assert get_category_from_id("e001-domain") == "e"
        assert get_category_from_id("h001-hotfix") == "h"
        assert get_category_from_id("s001-security") == "s"
        assert get_category_from_id("t001-tooling") == "t"

    def test_get_category_from_id_invalid(self):
        """Returns None for IDs without category prefix."""
        assert get_category_from_id("my-epic") is None
        assert get_category_from_id("test-001") is None
        assert get_category_from_id("x001-unknown") is None  # 'x' not a valid category

    def test_get_category_dir(self):
        """Returns correct directory names for categories."""
        assert get_category_dir("a") == "a-architecture"
        assert get_category_dir("e") == "e-epics"
        assert get_category_dir("h") == "h-hotfix"
        assert get_category_dir("s") == "s-security"
        assert get_category_dir("t") == "t-tooling"

    def test_get_category_dir_invalid(self):
        """Returns None for unknown categories."""
        assert get_category_dir("x") is None
        assert get_category_dir("z") is None

    def test_category_map_completeness(self):
        """CATEGORY_MAP contains all expected categories."""
        expected = {"a", "e", "h", "s", "t"}
        assert set(CATEGORY_MAP.keys()) == expected


class TestGetEpicPath:
    """Tests for get_epic_path function."""

    def test_returns_epics_subdir_legacy(self, temp_governor: Path):
        """Returns flat path for IDs without category prefix."""
        path = get_epic_path("my-epic")
        assert path == temp_governor / "epics" / "my-epic"

    def test_returns_category_subdir_tooling(self, temp_governor: Path):
        """Returns category path for tooling epics."""
        path = get_epic_path("t004-specwright")
        assert path == temp_governor / "epics" / "t-tooling" / "t004-specwright"

    def test_returns_category_subdir_epics(self, temp_governor: Path):
        """Returns category path for domain epics."""
        path = get_epic_path("e012-pm-system")
        assert path == temp_governor / "epics" / "e-epics" / "e012-pm-system"

    def test_returns_category_subdir_all(self, temp_governor: Path):
        """Returns correct category paths for all categories."""
        assert get_epic_path("a001-arch") == temp_governor / "epics" / "a-architecture" / "a001-arch"
        assert get_epic_path("e001-domain") == temp_governor / "epics" / "e-epics" / "e001-domain"
        assert get_epic_path("h001-hotfix") == temp_governor / "epics" / "h-hotfix" / "h001-hotfix"
        assert get_epic_path("s001-security") == temp_governor / "epics" / "s-security" / "s001-security"
        assert get_epic_path("t001-tool") == temp_governor / "epics" / "t-tooling" / "t001-tool"

    def test_finds_existing_epic_in_category(self, temp_governor: Path, valid_epic_yaml: str):
        """Finds existing epic in category subdir when loading."""
        # Create epic in category subdir
        epic_dir = temp_governor / "epics" / "t-tooling" / "t004-specwright"
        epic_dir.mkdir(parents=True)
        (epic_dir / "epic.yaml").write_text(valid_epic_yaml.replace("test-epic", "t004-specwright"))

        # get_epic_path should find it
        path = get_epic_path("t004-specwright")
        assert path == epic_dir


class TestLoadEpic:
    """Tests for load_epic function."""

    def test_load_existing_epic(self, temp_governor: Path, valid_epic_yaml: str):
        """Loads existing epic successfully."""
        epic_dir = temp_governor / "epics" / "test-epic"
        epic_dir.mkdir(parents=True)
        (epic_dir / "epic.yaml").write_text(valid_epic_yaml)

        epic = load_epic("test-epic")
        assert epic.id == "test-epic"
        assert epic.title == "Test Epic"

    def test_load_nonexistent_epic(self, temp_governor: Path):
        """Raises EpicNotFoundError for nonexistent epic."""
        with pytest.raises(EpicNotFoundError) as exc_info:
            load_epic("nonexistent")
        assert exc_info.value.exit_code == 2


class TestLoadEpicFromPath:
    """Tests for load_epic_from_path function."""

    def test_load_valid_epic(self, tmp_path: Path, valid_epic_yaml: str):
        """Loads and validates epic from path."""
        epic_file = tmp_path / "epic.yaml"
        epic_file.write_text(valid_epic_yaml)

        epic = load_epic_from_path(epic_file)
        assert epic.id == "test-epic"
        assert epic.owner == "testuser"
        assert len(epic.targets) == 1
        assert len(epic.specs) == 1

    def test_load_nonexistent_file(self, tmp_path: Path):
        """Raises EpicNotFoundError for nonexistent file."""
        with pytest.raises(EpicNotFoundError) as exc_info:
            load_epic_from_path(tmp_path / "missing.yaml")
        assert exc_info.value.exit_code == 2

    def test_load_invalid_yaml(self, tmp_path: Path):
        """Raises EpicValidationError for invalid YAML."""
        epic_file = tmp_path / "epic.yaml"
        epic_file.write_text("invalid: yaml: content:")

        with pytest.raises(EpicValidationError) as exc_info:
            load_epic_from_path(epic_file)
        assert exc_info.value.exit_code == 3

    def test_load_empty_file(self, tmp_path: Path):
        """Raises EpicValidationError for empty file."""
        epic_file = tmp_path / "epic.yaml"
        epic_file.write_text("")

        with pytest.raises(EpicValidationError) as exc_info:
            load_epic_from_path(epic_file)
        assert exc_info.value.exit_code == 3

    def test_load_missing_required_field(self, tmp_path: Path):
        """Raises EpicValidationError for missing required field."""
        epic_file = tmp_path / "epic.yaml"
        epic_file.write_text('version: "0.1"\nkind: epic\n')

        with pytest.raises(EpicValidationError) as exc_info:
            load_epic_from_path(epic_file)
        assert exc_info.value.exit_code == 3

    def test_load_invalid_target_ref(self, tmp_path: Path):
        """Raises EpicValidationError for invalid target reference."""
        yaml_content = '''version: "0.1"
kind: epic
id: test-epic
title: "Test Epic"
owner: testuser
created: 2025-12-26T00:00:00Z
updated: 2025-12-26T00:00:00Z
intent:
  goal: "Test"
targets: []
specs:
  - id: spec-001
    repo: unknown-repo
    branch: main
    path: test.md
    status: planned
'''
        epic_file = tmp_path / "epic.yaml"
        epic_file.write_text(yaml_content)

        with pytest.raises(EpicValidationError) as exc_info:
            load_epic_from_path(epic_file)
        assert exc_info.value.exit_code == 3
        assert "unknown target" in str(exc_info.value)

    def test_load_z_suffix_datetime(self, tmp_path: Path, valid_epic_yaml: str):
        """Handles Z suffix in datetime correctly."""
        # The fixture already uses Z suffix
        epic_file = tmp_path / "epic.yaml"
        epic_file.write_text(valid_epic_yaml)

        epic = load_epic_from_path(epic_file)
        assert epic.created is not None
        assert epic.created.year == 2025

    def test_load_iso_offset_datetime(self, tmp_path: Path):
        """Handles ISO offset datetime correctly."""
        yaml_content = '''version: "0.1"
kind: epic
id: test-epic
title: "Test Epic"
owner: testuser
created: 2025-12-26T00:00:00+00:00
updated: 2025-12-26T12:30:00-05:00
intent:
  goal: "Test"
targets: []
specs: []
'''
        epic_file = tmp_path / "epic.yaml"
        epic_file.write_text(yaml_content)

        epic = load_epic_from_path(epic_file)
        assert epic.created is not None
        assert epic.updated is not None


class TestListEpics:
    """Tests for list_epics function."""

    def test_empty_governor(self, temp_governor: Path):
        """Returns empty list for empty governor."""
        result = list_epics()
        assert result == []

    def test_list_existing_epics(self, temp_governor: Path, valid_epic_yaml: str):
        """Lists existing epics."""
        # Create two epics
        for name in ["epic-a", "epic-b"]:
            epic_dir = temp_governor / "epics" / name
            epic_dir.mkdir(parents=True)
            (epic_dir / "epic.yaml").write_text(valid_epic_yaml.replace("test-epic", name))

        result = list_epics()
        assert len(result) == 2
        assert "epic-a" in result
        assert "epic-b" in result

    def test_ignores_non_epic_dirs(self, temp_governor: Path, valid_epic_yaml: str):
        """Ignores directories without epic.yaml."""
        # Create valid epic
        epic_dir = temp_governor / "epics" / "valid-epic"
        epic_dir.mkdir(parents=True)
        (epic_dir / "epic.yaml").write_text(valid_epic_yaml.replace("test-epic", "valid-epic"))

        # Create directory without epic.yaml
        (temp_governor / "epics" / "not-an-epic").mkdir()

        result = list_epics()
        assert len(result) == 1
        assert result[0] == "valid-epic"

    def test_list_sorted(self, temp_governor: Path, valid_epic_yaml: str):
        """Returns epics in sorted order."""
        for name in ["z-epic", "a-epic", "m-epic"]:
            epic_dir = temp_governor / "epics" / name
            epic_dir.mkdir(parents=True)
            (epic_dir / "epic.yaml").write_text(valid_epic_yaml.replace("test-epic", name))

        result = list_epics()
        assert result == ["a-epic", "m-epic", "z-epic"]

    def test_list_epics_in_category_subdirs(self, temp_governor: Path, valid_epic_yaml: str):
        """Lists epics from category subdirectories."""
        # Create epics in different category subdirs
        for category_dir, epic_id in [
            ("t-tooling", "t001-tool"),
            ("t-tooling", "t002-other"),
            ("e-epics", "e001-domain"),
            ("a-architecture", "a001-arch"),
        ]:
            epic_dir = temp_governor / "epics" / category_dir / epic_id
            epic_dir.mkdir(parents=True)
            (epic_dir / "epic.yaml").write_text(valid_epic_yaml.replace("test-epic", epic_id))

        result = list_epics()
        assert len(result) == 4
        assert "t001-tool" in result
        assert "t002-other" in result
        assert "e001-domain" in result
        assert "a001-arch" in result

    def test_list_mixed_flat_and_category(self, temp_governor: Path, valid_epic_yaml: str):
        """Lists epics from both flat and category structures."""
        # Flat epic
        flat_epic = temp_governor / "epics" / "legacy-epic"
        flat_epic.mkdir(parents=True)
        (flat_epic / "epic.yaml").write_text(valid_epic_yaml.replace("test-epic", "legacy-epic"))

        # Category epic
        cat_epic = temp_governor / "epics" / "t-tooling" / "t001-new"
        cat_epic.mkdir(parents=True)
        (cat_epic / "epic.yaml").write_text(valid_epic_yaml.replace("test-epic", "t001-new"))

        result = list_epics()
        assert len(result) == 2
        assert "legacy-epic" in result
        assert "t001-new" in result
