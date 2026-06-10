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
