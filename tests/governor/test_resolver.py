"""Tests for epic/spec prefix resolver."""

from pathlib import Path

import pytest

from spec.governor.resolver import (
    ResolveError,
    list_epics,
    list_specs_in_epic,
    resolve_epic,
    resolve_spec,
)


@pytest.fixture
def gov(tmp_path: Path) -> Path:
    """Create a mini governor tree for testing."""
    epics = tmp_path / "epics"

    # t004-specwright-governance with two specs
    e1 = epics / "t004-specwright-governance"
    s1 = e1 / "specs"
    s1.mkdir(parents=True)
    (e1 / "epic.yaml").write_text("id: t004-specwright-governance\n")
    (s1 / "t004-01-validation-commands.md").write_text("# spec 01\n")
    (s1 / "t004-03-interactive-execution.md").write_text("# spec 03\n")

    # e005b-command-plane-and-performance with sub-specs
    e2 = epics / "e005b-command-plane-and-performance"
    s2 = e2 / "specs"
    s2.mkdir(parents=True)
    (e2 / "epic.yaml").write_text("id: e005b\n")
    (s2 / "e005b-01-executor-dispatch.md").write_text("# e005b-01\n")
    (s2 / "e005b-02a-injest-callable.md").write_text("# e005b-02a\n")
    (s2 / "e005b-02b-canonizer-callable.md").write_text("# e005b-02b\n")

    # t003-specwright-v2
    e3 = epics / "t003-specwright-v2"
    s3 = e3 / "specs"
    s3.mkdir(parents=True)
    (e3 / "epic.yaml").write_text("id: t003\n")
    (s3 / "e008-01-core-schemas.md").write_text("# e008-01\n")
    (s3 / "e008-02-git-sandbox.md").write_text("# e008-02\n")

    return tmp_path


class TestResolveEpic:
    def test_full_name(self, gov: Path) -> None:
        r = resolve_epic("t004-specwright-governance", gov)
        assert r.epic_id == "t004-specwright-governance"
        assert r.epic_yaml.exists()

    def test_short_prefix(self, gov: Path) -> None:
        r = resolve_epic("t004", gov)
        assert r.epic_id == "t004-specwright-governance"

    def test_ambiguous_prefix(self, gov: Path) -> None:
        # "t00" matches both t003 and t004
        with pytest.raises(ResolveError) as exc_info:
            resolve_epic("t00", gov)
        assert "t003-specwright-v2" in str(exc_info.value)
        assert "t004-specwright-governance" in str(exc_info.value)

    def test_no_match(self, gov: Path) -> None:
        with pytest.raises(ResolveError):
            resolve_epic("z999", gov)

    def test_e005b_prefix(self, gov: Path) -> None:
        r = resolve_epic("e005b", gov)
        assert r.epic_id == "e005b-command-plane-and-performance"


class TestResolveSpec:
    def test_short_spec_prefix(self, gov: Path) -> None:
        r = resolve_spec("t004-01", gov)
        assert r.spec_id == "t004-01-validation-commands"
        assert r.epic.epic_id == "t004-specwright-governance"
        assert r.spec_path.exists()

    def test_full_spec_name(self, gov: Path) -> None:
        r = resolve_spec("t004-01-validation-commands", gov)
        assert r.spec_id == "t004-01-validation-commands"

    def test_e005b_sub_spec(self, gov: Path) -> None:
        r = resolve_spec("e005b-02a", gov)
        assert r.spec_id == "e005b-02a-injest-callable"
        assert r.epic.epic_id == "e005b-command-plane-and-performance"

    def test_ambiguous_spec(self, gov: Path) -> None:
        # "e005b-02" matches 02a and 02b
        with pytest.raises(ResolveError) as exc_info:
            resolve_spec("e005b-02", gov)
        assert "e005b-02a" in str(exc_info.value)
        assert "e005b-02b" in str(exc_info.value)

    def test_spec_no_match(self, gov: Path) -> None:
        with pytest.raises(ResolveError):
            resolve_spec("t004-99", gov)

    def test_cross_named_spec_fails(self, gov: Path) -> None:
        """Specs named e008-* in t003 epic are not resolvable by e008 prefix."""
        with pytest.raises(ResolveError):
            resolve_spec("e008-01", gov)


class TestListFunctions:
    def test_list_epics(self, gov: Path) -> None:
        epics = list_epics(gov)
        assert "t003-specwright-v2" in epics
        assert "t004-specwright-governance" in epics
        assert "e005b-command-plane-and-performance" in epics

    def test_list_specs_in_epic(self, gov: Path) -> None:
        specs = list_specs_in_epic("t004", gov)
        assert "t004-01-validation-commands" in specs
        assert "t004-03-interactive-execution" in specs


@pytest.fixture
def gov_grouped(tmp_path: Path) -> Path:
    """Create a governor tree with letter-grouped epic layout."""
    epics = tmp_path / "epics"

    # t/t004-specwright-governance
    e1 = epics / "t" / "t004-specwright-governance"
    s1 = e1 / "specs"
    s1.mkdir(parents=True)
    (e1 / "epic.yaml").write_text("id: t004-specwright-governance\n")
    (s1 / "t004-01-validation-commands.md").write_text("# spec 01\n")

    # e/e005b-command-plane-and-performance
    e2 = epics / "e" / "e005b-command-plane-and-performance"
    s2 = e2 / "specs"
    s2.mkdir(parents=True)
    (e2 / "epic.yaml").write_text("id: e005b\n")
    (s2 / "e005b-01-executor-dispatch.md").write_text("# e005b-01\n")

    return tmp_path


class TestLetterGroupedLayout:
    def test_resolve_epic(self, gov_grouped: Path) -> None:
        r = resolve_epic("t004", gov_grouped)
        assert r.epic_id == "t004-specwright-governance"
        assert r.epic_yaml.exists()

    def test_resolve_spec(self, gov_grouped: Path) -> None:
        r = resolve_spec("t004-01", gov_grouped)
        assert r.spec_id == "t004-01-validation-commands"
        assert r.epic.epic_id == "t004-specwright-governance"

    def test_list_epics(self, gov_grouped: Path) -> None:
        epics = list_epics(gov_grouped)
        assert "t004-specwright-governance" in epics
        assert "e005b-command-plane-and-performance" in epics

    def test_cross_group_spec(self, gov_grouped: Path) -> None:
        r = resolve_spec("e005b-01", gov_grouped)
        assert r.spec_id == "e005b-01-executor-dispatch"
        assert r.epic.epic_id == "e005b-command-plane-and-performance"


class TestAgainstRealGovernor:
    """Integration tests against the actual local-governor.

    These tests run against the real filesystem. They're skipped if
    local-governor doesn't exist.
    """

    @pytest.fixture
    def real_gov_root(self) -> Path:
        return Path("~/.local/local-governor").expanduser()

    @pytest.fixture(autouse=True)
    def _require_governor(self, real_gov_root: Path) -> None:
        gov_epics = real_gov_root / "epics"
        if not gov_epics.exists():
            pytest.skip("local-governor not present")

    def test_resolve_t004(self, real_gov_root: Path) -> None:
        r = resolve_epic("t004", real_gov_root)
        assert r.epic_id == "t004-specwright-governance"

    def test_resolve_t004_01(self, real_gov_root: Path) -> None:
        r = resolve_spec("t004-01", real_gov_root)
        assert r.spec_id == "t004-01-validation-commands"
        assert r.spec_path.exists()

    def test_resolve_e005b_02a(self, real_gov_root: Path) -> None:
        r = resolve_spec("e005b-02a", real_gov_root)
        assert "injest" in r.spec_id

    def test_resolve_e008_01_fails(self, real_gov_root: Path) -> None:
        """e008 specs in t003 are not resolvable by e008 prefix (no fallback)."""
        with pytest.raises(ResolveError):
            resolve_spec("e008-01", real_gov_root)
