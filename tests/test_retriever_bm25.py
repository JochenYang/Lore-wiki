"""Tests for the BM25Retriever (phrase / OR / LIKE fallback) + score scaling."""

from __future__ import annotations

from pathlib import Path

import pytest

from lorewiki.config import LoreWikiConfig
from lorewiki.indexer import build_index
from lorewiki.retriever import BM25Retriever


@pytest.fixture()
def indexed_wiki(tmp_path: Path) -> LoreWikiConfig:
    """Build a tiny wiki on disk and return a config pointing at its index."""
    wiki = tmp_path / "wiki"
    (wiki / "api" / "user").mkdir(parents=True)
    (wiki / "patterns").mkdir(parents=True)

    (wiki / "api" / "user" / "auth.md").write_text(
        "---\ntitle: 用户认证 API\nmodule: api/user\n---\n\n"
        "## 概述\n\n本接口实现 JWT 双 Token 方案。\n\n"
        "## POST /login\n\n用户提交账号密码后调用登录接口。\n\n"
        "## POST /refresh\n\nrefresh token rotation 用于安全续期。\n",
        encoding="utf-8",
    )
    (wiki / "patterns" / "retry.md").write_text(
        "---\ntitle: 重试与幂等\nmodule: patterns\n---\n\n"
        "## 退避\n\n指数退避 + 抖动 (Full Jitter) 是工程最稳的选择。\n\n"
        "## 幂等\n\nIdempotency-Key 模式, 重复请求返回首次结果。\n",
        encoding="utf-8",
    )
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    build_index(cfg, rebuild=True)
    return cfg


def test_phrase_pass_returns_results(indexed_wiki: LoreWikiConfig) -> None:
    r = BM25Retriever.from_config(indexed_wiki)
    hits = list(r.search("JWT 双 Token", top_k=3))
    assert hits
    assert hits[0].score > 0
    assert hits[0].retriever.startswith("bm25.")
    assert "api/user/auth.md" in {h.doc_path for h in hits}


def test_or_fallback_for_long_cjk_query(indexed_wiki: LoreWikiConfig) -> None:
    r = BM25Retriever.from_config(indexed_wiki)
    hits = list(r.search("指数退避抖动", top_k=3))
    assert hits
    assert any("retry.md" in h.doc_path for h in hits)


def test_like_fallback_for_short_query(indexed_wiki: LoreWikiConfig) -> None:
    r = BM25Retriever.from_config(indexed_wiki)
    hits = list(r.search("幂等", top_k=3))
    assert hits
    for h in hits:
        # LIKE fallback labels and scores are bounded to [0, 0.5].
        if h.retriever == "bm25.like":
            assert 0 < h.score <= 0.5


def test_empty_query_returns_empty(indexed_wiki: LoreWikiConfig) -> None:
    r = BM25Retriever.from_config(indexed_wiki)
    assert list(r.search("", top_k=3)) == []
    assert list(r.search("   ", top_k=3)) == []


def test_score_is_strictly_positive_for_phrase_hit(indexed_wiki: LoreWikiConfig) -> None:
    """Regression: score used to be ``0.0`` because of an ``in sqlite3.Row`` bug.

    The absolute magnitude depends on the corpus size; we only require that
    it is strictly positive and *much* larger than 0 so any future regression
    to the silent-zero state is caught.
    """
    r = BM25Retriever.from_config(indexed_wiki)
    hits = list(r.search("用户认证", top_k=1))
    assert hits, "expected at least one phrase hit"
    top = hits[0]
    assert top.retriever == "bm25.phrase"
    assert top.score > 0, f"phrase score must be positive, got {top.score!r}"


def test_phrase_or_pass_used_for_long_query(indexed_wiki: LoreWikiConfig) -> None:
    """Long enough queries (>= 3 chars) hit via phrase or OR pass, not LIKE."""
    r = BM25Retriever.from_config(indexed_wiki)
    hits = list(r.search("用户认证", top_k=1))
    assert hits
    assert hits[0].retriever in {"bm25.phrase", "bm25.or"}


def test_like_pass_score_capped_at_half(indexed_wiki: LoreWikiConfig) -> None:
    """The LIKE pseudo-score must never exceed 0.5 so it never outranks FTS."""
    r = BM25Retriever.from_config(indexed_wiki)
    hits = list(r.search("幂等", top_k=5))
    assert hits
    for h in hits:
        if h.retriever == "bm25.like":
            assert h.score <= 0.5


def test_special_characters_do_not_crash(indexed_wiki: LoreWikiConfig) -> None:
    r = BM25Retriever.from_config(indexed_wiki)
    # Quotes / parens are FTS5 special characters; retriever must sanitise.
    hits = list(r.search('"用户认证" AND (login)', top_k=3))
    # No crash; may or may not return hits depending on tokenizer.
    assert isinstance(hits, list)


def test_dedup_across_passes(indexed_wiki: LoreWikiConfig) -> None:
    r = BM25Retriever.from_config(indexed_wiki)
    hits = list(r.search("JWT 双 Token", top_k=5))
    ids = [h.chunk_id for h in hits]
    assert len(ids) == len(set(ids)), "chunks should not appear twice across passes"
