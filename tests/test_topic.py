"""Unit tests for :mod:`lorewiki.topic` — the second-brain / vault manager."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lorewiki import topic as _topic
from lorewiki.topic import (
    USER_TOPICS_ROOT,
    TopicManager,
    TopicNameError,
    suggest_names,
    validate_name,
)


@pytest.fixture()
def fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect USER_CONFIG_DIR and USER_TOPICS_ROOT to ``tmp_path/home``."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr("lorewiki.topic.USER_CONFIG_DIR", fake)
    monkeypatch.setattr("lorewiki.topic.USER_TOPICS_ROOT", fake / "topics")
    monkeypatch.setattr("lorewiki.topic.CURRENT_FILE", fake / "current")
    # Also redirect the duplicate in lorewiki.config (it reads the same
    # path on its own) so that ``load_config`` sees the same fake home.
    monkeypatch.setattr("lorewiki.config.USER_CONFIG_DIR", fake)
    monkeypatch.setattr("lorewiki.config.USER_CONFIG_PATH", fake / "config.toml")
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    return fake


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "react", "wechat-mp", "cocos-2d", "a", "ab", "a1b2c3",
        "1-topic",  # digit-leading is allowed
    ],
)
def test_validate_name_accepts_valid(name: str) -> None:
    validate_name(name)  # no exception


@pytest.mark.parametrize(
    "name,reason_fragment",
    [
        ("", "empty"),
        ("-leading", "must match"),
        ("trailing-", "must match"),
        ("Has-Spaces", "must match"),
        ("UPPER", "must match"),
        ("dot.bad", "must match"),
        ("path/topic", "must match"),
        ("..", "must match"),
        ("init", "reserved"),     # CLI subcommand
        ("current", "reserved"),  # CLI subcommand
        ("con", "reserved"),      # Windows reserved
    ],
)
def test_validate_name_rejects_invalid(
    name: str, reason_fragment: str,
) -> None:
    with pytest.raises(TopicNameError, match=reason_fragment):
        validate_name(name)


def test_validate_name_too_long() -> None:
    long_name = "a" * 65
    with pytest.raises(TopicNameError, match="must match"):
        validate_name(long_name)


# ---------------------------------------------------------------------------
# Manager: list / get / exists
# ---------------------------------------------------------------------------


def test_list_empty_when_no_topics_root(fake_home: Path) -> None:
    assert TopicManager().list() == []


def test_list_returns_sorted_with_active_first(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    mgr.create("wechat-mp")
    mgr.create("cocos")
    mgr.use("wechat-mp")
    infos = mgr.list()
    assert [i.name for i in infos] == ["wechat-mp", "cocos", "react"]


def test_get_missing_raises(fake_home: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        TopicManager().get("react")


def test_exists_true_and_false(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    assert mgr.exists("react") is True
    assert mgr.exists("cocos") is False


def test_list_skips_non_lorewiki_files(fake_home: Path) -> None:
    """If the user puts random stuff in ~/lorewiki/topics/, we ignore it."""
    mgr = TopicManager()
    mgr.create("react")
    USER_TOPICS_ROOT.mkdir(parents=True, exist_ok=True)  # already
    (USER_TOPICS_ROOT / "scratch.txt").write_text("not a topic")
    (USER_TOPICS_ROOT / ".hidden").mkdir(exist_ok=True)  # starts with . -> skip
    infos = mgr.list()
    assert [i.name for i in infos] == ["react"]


# ---------------------------------------------------------------------------
# Manager: create
# ---------------------------------------------------------------------------


def test_create_empty_topic(fake_home: Path) -> None:
    info = TopicManager().create("react")
    assert info.name == "react"
    assert info.root.is_dir()
    assert info.wiki_path == info.root  # vault root IS the wiki
    assert info.db_path == info.root / ".lorewiki" / "index.db"
    # config_path is the global config (~/lorewiki/config.toml), NOT
    # a per-topic file. We don't assert it exists because that would
    # require writing a sample global file in the test fixture.
    assert str(info.config_path).endswith("config.toml")
    assert info.source_link is False


def test_create_does_not_drop_config_into_vault_root(fake_home: Path) -> None:
    """The vault root must NOT contain a ``config.toml`` — config
    lives in **one** place (``~/.lorewiki/config.toml``). Dropping
    a per-topic config polluted the Obsidian / Logseq vault view.
    """
    info = TopicManager().create("react")
    assert not (info.root / "config.toml").exists()


def test_create_with_source_copies_files(fake_home: Path, tmp_path: Path) -> None:
    src = tmp_path / "external_wiki"
    (src / "api").mkdir(parents=True)
    (src / "api" / "auth.md").write_text("# auth", encoding="utf-8")
    (src / "architecture.md").write_text("# arch", encoding="utf-8")
    info = TopicManager().create("react", source=src)
    # Source was COPIED — both files present, vault owns the data.
    assert (info.wiki_path / "architecture.md").exists()
    assert (info.wiki_path / "api" / "auth.md").exists()
    assert (info.wiki_path / "api" / "auth.md").read_text(encoding="utf-8") == "# auth"
    assert info.source_link is False
    # Source untouched.
    assert (src / "api" / "auth.md").exists()


def test_create_with_source_and_link_makes_symlink(
    fake_home: Path, tmp_path: Path,
) -> None:
    src = tmp_path / "external_wiki"
    src.mkdir()
    (src / "index.md").write_text("# index", encoding="utf-8")
    info = TopicManager().create("react", source=src, link=True)
    # In admin / Developer Mode Windows + POSIX the wiki root is a
    # symlink. In sandboxed Windows where symlink_to fails, the
    # installer falls back to a copy (see
    # test_create_with_link_falls_back_to_copy_on_symlink_failure for
    # the explicit failure-injection test). Either way the content
    # must be reachable through the topic root.
    assert (info.wiki_path / "index.md").read_text(encoding="utf-8") == "# index"
    # When the OS cooperated, source_link is True and the wiki_path
    # is actually a symlink. Otherwise it's a copy — we don't assert
    # source_link here because the result is OS-dependent.


def test_create_with_link_falls_back_to_copy_on_symlink_failure(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In Windows sandboxes / non-admin tokens, symlink fails; the
    installer shouldn't block the user — copy mode is the fallback.
    """
    src = tmp_path / "external_wiki"
    src.mkdir()
    (src / "index.md").write_text("# index", encoding="utf-8")

    def boom(*_a, **_kw):
        raise OSError("WinError 1314 simulated")

    monkeypatch.setattr("pathlib.Path.symlink_to", boom)
    info = TopicManager().create("react", source=src, link=True)
    assert info.source_link is False  # fell back
    assert (info.wiki_path / "index.md").exists()


def test_create_rejects_existing_topic(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    with pytest.raises(FileExistsError, match="already exists"):
        mgr.create("react")


def test_create_rejects_invalid_name(fake_home: Path) -> None:
    with pytest.raises(TopicNameError):
        TopicManager().create("../escape")


def test_create_rejects_missing_source(fake_home: Path, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        TopicManager().create("react", source=tmp_path / "nope")


def test_seed_config_is_a_deprecated_noop(fake_home: Path) -> None:
    """The legacy ``_seed_config`` helper is now a no-op kept for
    backward compatibility with anyone who called it directly. We
    don't write per-topic ``config.toml`` files any more.
    """
    target = fake_home / "topics" / "react"
    TopicManager._seed_config(target)
    assert not (target / "config.toml").exists()


def test_create_skips_hidden_files_from_source(fake_home: Path, tmp_path: Path) -> None:
    """Don't drag .git, .DS_Store, etc. into the user's vault."""
    src = tmp_path / "external_wiki"
    src.mkdir()
    (src / "real.md").write_text("# real", encoding="utf-8")
    (src / ".hidden").mkdir()
    (src / ".hidden" / "secret.md").write_text("secret", encoding="utf-8")
    (src / ".DS_Store").write_text("binary junk", encoding="utf-8")
    info = TopicManager().create("react", source=src)
    assert (info.wiki_path / "real.md").exists()
    assert not (info.wiki_path / ".hidden").exists()
    assert not (info.wiki_path / ".DS_Store").exists()
    # The summary must report the skipped count so the user knows
    # something was dropped (issue #1 from the phase-6 critique).
    assert info.ingest_summary is not None
    copied, skipped = info.ingest_summary
    assert copied == 1
    assert skipped == 2  # .hidden/ + .DS_Store


def test_create_no_source_has_no_ingest_summary(fake_home: Path) -> None:
    """Empty topic creation: nothing was copied, summary is None."""
    info = TopicManager().create("react")
    assert info.ingest_summary is None


def test_create_source_no_hidden_reports_clean_summary(
    fake_home: Path, tmp_path: Path,
) -> None:
    """Source with only visible entries: copied > 0, skipped == 0."""
    src = tmp_path / "external_wiki"
    src.mkdir()
    (src / "a.md").write_text("# a", encoding="utf-8")
    (src / "b.md").write_text("# b", encoding="utf-8")
    info = TopicManager().create("react", source=src)
    assert info.ingest_summary == (2, 0)


# ---------------------------------------------------------------------------
# TopicManager(root=...) — path-injection defense (phase-6 high#2)
# ---------------------------------------------------------------------------


def test_topic_manager_rejects_external_root_by_default(
    fake_home: Path, tmp_path: Path,
) -> None:
    """A caller cannot direct the manager at an arbitrary path.

    This guards against a future caller (e.g. an MCP tool that
    forwards a config-supplied path) from accidentally installing
    into ``C:\\Windows\\`` or a tmp dir outside the user's home.
    """
    outside = tmp_path / "outside-home"
    outside.mkdir()
    with pytest.raises(ValueError, match="escapes the default"):
        TopicManager(root=outside)


def test_topic_manager_accepts_external_root_with_flag(
    fake_home: Path, tmp_path: Path,
) -> None:
    """The escape hatch is explicit and named; no silent surprises."""
    outside = tmp_path / "outside-home"
    outside.mkdir()
    mgr = TopicManager(root=outside, allow_external_root=True)
    assert mgr.root == outside.resolve()


def test_topic_manager_default_root_still_works(fake_home: Path) -> None:
    """The default (no-arg) and a sub-directory of USER_TOPICS_ROOT
    are both fine.
    """
    import lorewiki.topic as _live_topic_mod  # noqa: PLC0415
    live_root = _live_topic_mod.USER_TOPICS_ROOT.resolve()
    # The fixture sets the path on the module but doesn't mkdir it;
    # create the topics root so we can then test a sub-directory
    # of it.
    live_root.mkdir(parents=True, exist_ok=True)
    mgr_default = TopicManager()
    # Read USER_TOPICS_ROOT via the module attribute so the
    # fixture's monkeypatched path is honoured.
    assert mgr_default.root == live_root
    # Subdir: future-proofing for namespaces like ``topics/team-x/``.
    sub = live_root / "team-x"
    sub.mkdir(exist_ok=True)
    mgr_sub = TopicManager(root=sub)
    assert mgr_sub.root == sub.resolve()


# ---------------------------------------------------------------------------
# Manager: use / current / resolve_active
# ---------------------------------------------------------------------------


def test_use_writes_current_file(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    mgr.use("react")
    # Read via the manager's method so the fixture's monkeypatched
    # CURRENT_FILE path is honoured (the module-level ``CURRENT_FILE``
    # binding in this test file was imported before the fixture ran).
    assert mgr.current() == "react"


def test_current_returns_none_when_no_pointer(fake_home: Path) -> None:
    assert TopicManager().current() is None


def test_resolve_active_returns_none_when_unset(fake_home: Path) -> None:
    assert TopicManager().resolve_active() is None


def test_resolve_active_clears_stale_pointer(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    mgr.use("react")
    # Simulate the user deleting the topic dir by hand. Use the
    # manager-resolved path so the monkeypatched root is honoured.
    target = mgr.get("react").root
    shutil.rmtree(target)
    assert mgr.resolve_active() is None
    assert mgr.current() is None  # stale pointer cleared


# ---------------------------------------------------------------------------
# Manager: delete
# ---------------------------------------------------------------------------


def test_delete_removes_directory(fake_home: Path) -> None:
    mgr = TopicManager()
    info = mgr.create("react")
    assert info.root.exists()
    mgr.delete("react")
    assert not info.root.exists()
    assert not (USER_TOPICS_ROOT / "react").exists()


def test_delete_clears_current_pointer_if_active(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    mgr.use("react")
    mgr.delete("react")
    assert mgr.current() is None
    # Use the resolved path so the fixture's monkeypatched CURRENT_FILE is honoured.
    # Fetch through the module so the fixture's monkeypatch (rather than the
    # top-of-file import binding, which already captured the real home) is used.
    fake_current = _topic.USER_TOPICS_ROOT.parent / "current"
    assert not fake_current.exists()


def test_delete_keeps_current_pointer_if_other_topic_active(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    mgr.create("cocos")
    mgr.use("react")
    mgr.delete("cocos")
    assert mgr.current() == "react"


def test_delete_missing_raises(fake_home: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        TopicManager().delete("react")


# ---------------------------------------------------------------------------
# suggest_names
# ---------------------------------------------------------------------------


def test_suggest_basic_english() -> None:
    out = suggest_names("react hooks learning notes")
    # ``learning`` and ``notes`` are stopwords in the slugifier, so the
    # only meaningful candidates come from the head tokens.
    assert "react" in out
    assert "react-hooks" in out


def test_suggest_drops_stopwords() -> None:
    out = suggest_names("a tutorial on the vue framework")
    # 'a', 'the', 'on', 'tutorial' dropped; 'vue' kept (KEEP list);
    # 'framework' survives (length 9, not a stopword).
    assert "vue" in out
    assert "vue-framework" in out
    assert "a-tutorial" not in out
    assert "the-vue" not in out


def test_suggest_keeps_short_tech_terms() -> None:
    # "ai" / "ml" are in the KEEP set; should survive even though
    # they're ≤2 chars.
    out = suggest_names("intro to ai ml workflows")
    assert "ai" in out
    # "ai-ml" is also expected (adjacent pair with both terms in KEEP).
    assert "ai-ml" in out
    # "intro", "to" are stopwords; "workflows" survives.
    assert "intro" not in out
    assert "ml-workflows" in out


def test_suggest_strips_punctuation_and_case() -> None:
    out = suggest_names("React, Hooks: A 2024 Guide!")
    assert "react" in out or "react-hooks" in out
    # No raw punctuation in the result.
    for n in out:
        assert all(c.isalnum() or c == "-" for c in n)


def test_suggest_avoids_existing_topic_collisions() -> None:
    out = suggest_names("react hooks", existing=["react", "react-hooks"])
    # The first two are taken; the next ones should be suffixed.
    assert "react" not in out
    assert "react-hooks" not in out
    assert "react-2" in out or "react-hooks-2" in out


def test_suggest_cjk_returns_empty() -> None:
    # CJK can't be transliterated without a heavy dep; we return [].
    assert suggest_names("微信小程序开发") == []
    # Mixed: ASCII tokens survive, CJK gets dropped by the regex.
    mixed = suggest_names("react 微信 hooks")
    assert "react" in mixed
    assert "react-hooks" in mixed


def test_suggest_handles_all_stopwords() -> None:
    # Pure stopword description yields nothing.
    assert suggest_names("the of and") == []


def test_suggest_respects_limit() -> None:
    out = suggest_names("react hooks notes guide tutorial", limit=2)
    assert len(out) == 2


def test_suggest_omits_invalid_candidates() -> None:
    # A description that slugifies to invalid names (e.g. all
    # trailing hyphens) should yield an empty list, not crash.
    # We synthesise an artificial case: the slugifier never produces
    # leading/trailing hyphens by design, so this is a regression
    # guard against future regressions in the validator.
    out = suggest_names("react")
    for n in out:
        validate_name(n)  # must always pass


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


def test_rename_moves_directory(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    src = mgr.get("react").root
    info = mgr.rename("react", "frontend-react")
    assert info.name == "frontend-react"
    assert info.root.exists()
    assert not src.exists()


def test_rename_updates_current_if_active(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    mgr.use("react")
    mgr.rename("react", "frontend-react")
    assert mgr.current() == "frontend-react"


def test_rename_keeps_current_when_other_active(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    mgr.create("cocos")
    mgr.use("react")
    mgr.rename("cocos", "cocos2d-x")
    assert mgr.current() == "react"  # unchanged


def test_rename_to_existing_raises(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    mgr.create("cocos")
    with pytest.raises(FileExistsError, match="already exists"):
        mgr.rename("react", "cocos")


def test_rename_missing_raises(fake_home: Path) -> None:
    mgr = TopicManager()
    with pytest.raises(FileNotFoundError, match="not found"):
        mgr.rename("react", "frontend-react")


def test_rename_invalid_new_name_raises(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    with pytest.raises(TopicNameError):
        mgr.rename("react", "../escape")


def test_rename_to_same_name_is_noop(fake_home: Path) -> None:
    mgr = TopicManager()
    mgr.create("react")
    info = mgr.rename("react", "react")
    assert info.name == "react"
    assert info.root.exists()
