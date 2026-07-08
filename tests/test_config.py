"""Tests for the configuration loader (TOML + env + overrides merging)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lorewiki.config import (
    LoreWikiConfig,
    default_config_toml,
    load_config,
    save_config,
)
from lorewiki.topic import TopicManager


def _patch_lorewiki_home(monkeypatch: pytest.MonkeyPatch, fake_home: Path) -> None:
    monkeypatch.setattr("lorewiki.config.USER_CONFIG_DIR", fake_home)
    monkeypatch.setattr("lorewiki.config.USER_CONFIG_PATH", fake_home / "config.toml")
    monkeypatch.setattr("lorewiki.topic.USER_CONFIG_DIR", fake_home)
    monkeypatch.setattr("lorewiki.topic.USER_TOPICS_ROOT", fake_home / "topics")
    monkeypatch.setattr("lorewiki.topic.CURRENT_FILE", fake_home / "current")
    monkeypatch.setattr("lorewiki.utils.topic_shared.USER_CONFIG_DIR", fake_home)
    monkeypatch.setattr("lorewiki.utils.topic_shared.USER_TOPICS_ROOT", fake_home / "topics")
    monkeypatch.setattr("lorewiki.utils.topic_shared.CURRENT_FILE", fake_home / "current")


def test_defaults_resolve_paths(tmp_path: Path) -> None:
    cfg = LoreWikiConfig(wiki_path=tmp_path / "wiki")
    assert cfg.wiki_path.is_absolute()
    assert cfg.db_path is not None
    assert cfg.db_path == cfg.wiki_path / ".lorewiki" / "index.db"


def test_default_config_toml_round_trip(tmp_path: Path) -> None:
    toml_text = default_config_toml()
    assert "retrieval_mode" in toml_text
    assert "[llm]" in toml_text
    target = tmp_path / "config.toml"
    target.write_text(toml_text, encoding="utf-8")
    cfg = load_config(project_dir=tmp_path)
    # Default db_path is derived from wiki_path; loading round-trip must keep
    # the same retrieval_mode and chunking knobs.
    assert cfg.retrieval_mode == "mix"
    assert cfg.chunk_max_tokens == 800


def test_project_overrides_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setattr("lorewiki.config.USER_CONFIG_PATH", fake_home / "config.toml")
    fake_home.mkdir()
    (fake_home / "config.toml").write_text(
        'retrieval_mode = "bm25"\nrrf_k = 10\n', encoding="utf-8"
    )

    project = tmp_path / "project"
    (project / ".lorewiki").mkdir(parents=True)
    (project / ".lorewiki" / "config.toml").write_text(
        'retrieval_mode = "hierarchy"\n', encoding="utf-8"
    )

    cfg = load_config(project_dir=project)
    # Project value wins for retrieval_mode; user value still wins where the
    # project file is silent (rrf_k).
    assert cfg.retrieval_mode == "hierarchy"
    assert cfg.rrf_k == 10


def test_env_vars_override_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lorewiki.config.USER_CONFIG_PATH", tmp_path / "u.toml")
    monkeypatch.setenv("LOREWIKI_RETRIEVAL_MODE", "bm25")
    monkeypatch.setenv("LOREWIKI_LLM__BACKEND", "openai")
    cfg = load_config(project_dir=tmp_path)
    assert cfg.retrieval_mode == "bm25"
    assert cfg.llm.backend == "openai"


def test_unknown_keys_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lorewiki.config.USER_CONFIG_PATH", tmp_path / "u.toml")
    (tmp_path / ".lorewiki").mkdir()
    (tmp_path / ".lorewiki" / "config.toml").write_text(
        'definitely_not_a_real_key = 42\n', encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="invalid configuration"):
        load_config(project_dir=tmp_path)


def test_save_config_serialises_paths(tmp_path: Path) -> None:
    cfg = LoreWikiConfig(wiki_path=tmp_path / "wiki")
    target = tmp_path / "out.toml"
    save_config(cfg, target)
    body = target.read_text(encoding="utf-8")
    # Paths must be stringified for TOML output.
    assert "wiki_path" in body
    assert "[llm]" in body


def test_stale_project_wiki_path_is_ignored(tmp_path: Path) -> None:
    """Added in 0.3.0: a project-level wiki_path that doesn't exist
    on disk must be dropped (with a WARNING) so the topic / user
    fallback wins, rather than silently shadowing it.

    Smoke-verified manually that the WARNING is emitted via
    ``lorewiki status``; the caplog fixture doesn't intercept loguru
    output (loguru uses its own sinks), so this test asserts the
    observable behaviour: ``cfg.wiki_path`` no longer points at the
    stale value.
    """
    # Project dir with a config that points at a non-existent wiki path.
    project = tmp_path / "project"
    (project / ".lorewiki").mkdir(parents=True)
    stale_path = tmp_path / "wiki-that-was-moved-or-deleted"
    (project / ".lorewiki" / "config.toml").write_text(
        f'wiki_path = "{stale_path.as_posix()}"\n', encoding="utf-8"
    )

    cfg = load_config(project_dir=project)

    # The stale value must be dropped. ``cfg.wiki_path`` falls back to
    # the default ``Path("./wiki")`` resolved against the test's cwd
    # (``tmp_path``), which is *not* ``stale_path``.
    assert cfg.wiki_path != stale_path
    assert stale_path not in cfg.wiki_path.parents, (
        f"cfg.wiki_path={cfg.wiki_path} unexpectedly descends from stale_path={stale_path}"
    )


def test_project_default_topic_beats_current_topic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    _patch_lorewiki_home(monkeypatch, fake_home)
    mgr = TopicManager()
    project_info = mgr.create("project-topic")
    mgr.create("current-topic")
    mgr.use("current-topic")

    project = tmp_path / "project"
    (project / ".lorewiki").mkdir(parents=True)
    (project / ".lorewiki" / "config.toml").write_text(
        'default_topic = "project-topic"\n', encoding="utf-8"
    )

    cfg = load_config(project_dir=project)

    assert cfg.topic == "project-topic"
    assert cfg.default_topic == "project-topic"
    assert cfg.wiki_path == project_info.wiki_path
    assert cfg.db_path == project_info.db_path


def test_explicit_topic_beats_project_default_topic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    _patch_lorewiki_home(monkeypatch, fake_home)
    mgr = TopicManager()
    mgr.create("project-topic")
    explicit_info = mgr.create("explicit-topic")

    project = tmp_path / "project"
    (project / ".lorewiki").mkdir(parents=True)
    (project / ".lorewiki" / "config.toml").write_text(
        'default_topic = "project-topic"\n', encoding="utf-8"
    )

    cfg = load_config(project_dir=project, overrides={"topic": "explicit-topic"})

    assert cfg.topic == "explicit-topic"
    assert cfg.default_topic == "project-topic"
    assert cfg.wiki_path == explicit_info.wiki_path
    assert cfg.db_path == explicit_info.db_path


def test_discovers_project_default_topic_from_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    _patch_lorewiki_home(monkeypatch, fake_home)
    info = TopicManager().create("project-topic")

    project = tmp_path / "project"
    child = project / "src" / "pkg"
    child.mkdir(parents=True)
    (project / ".lorewiki").mkdir()
    (project / ".lorewiki" / "config.toml").write_text(
        'default_topic = "project-topic"\n', encoding="utf-8"
    )
    monkeypatch.chdir(child)

    cfg = load_config()

    assert cfg.topic == "project-topic"
    assert cfg.wiki_path == info.wiki_path
    assert cfg.db_path == info.db_path


def test_explicit_wiki_path_keeps_legacy_per_wiki_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    _patch_lorewiki_home(monkeypatch, fake_home)
    TopicManager().create("project-topic")

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    project = tmp_path / "project"
    (project / ".lorewiki").mkdir(parents=True)
    (project / ".lorewiki" / "config.toml").write_text(
        'default_topic = "project-topic"\n', encoding="utf-8"
    )

    cfg = load_config(project_dir=project, overrides={"wiki_path": str(wiki)})

    assert cfg.topic is None
    assert cfg.wiki_path == wiki.resolve()
    assert cfg.db_path == wiki.resolve() / ".lorewiki" / "index.db"
