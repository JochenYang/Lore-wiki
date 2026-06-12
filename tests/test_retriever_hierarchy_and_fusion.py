"""Tests for HierarchyRetriever and RRFFusion."""

from __future__ import annotations

from pathlib import Path

import pytest

from lorewiki.config import LoreWikiConfig
from lorewiki.db.models import SearchHit
from lorewiki.indexer import build_index
from lorewiki.retriever import BM25Retriever, HierarchyRetriever, RRFFusion


@pytest.fixture()
def indexed_wiki(tmp_path: Path) -> LoreWikiConfig:
    wiki = tmp_path / "wiki"
    (wiki / "api" / "user").mkdir(parents=True)
    (wiki / "patterns").mkdir(parents=True)
    (wiki / "api" / "user" / "auth.md").write_text(
        "---\ntitle: 用户认证 API\nmodule: api/user\n---\n\n"
        "## 概述\n\n"
        "本接口实现 JWT 双 Token 方案与 refresh token rotation 安全机制, "
        "供身份服务集成使用, 文档涵盖登录、登出、刷新流程。\n\n"
        "## POST /login\n\n用户提交账号密码后调用登录接口, 服务端校验后签发"
        " token。\n",
        encoding="utf-8",
    )
    (wiki / "patterns" / "retry.md").write_text(
        "---\ntitle: 重试与幂等设计\nmodule: patterns\n---\n\n"
        "## 退避\n\n指数退避 + 抖动 (Full Jitter) 是工程最稳的选择, "
        "适合各种分布式场景。\n",
        encoding="utf-8",
    )
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    build_index(cfg, rebuild=True)
    return cfg


# ---- HierarchyRetriever ----


def test_hierarchy_finds_module_node(indexed_wiki: LoreWikiConfig) -> None:
    r = HierarchyRetriever.from_config(indexed_wiki)
    hits = list(r.search("用户认证", top_k=5))
    assert hits
    paths = {h.doc_path for h in hits}
    assert "api/user/auth.md" in paths
    assert all(h.retriever == "hierarchy" for h in hits)


def test_hierarchy_score_is_positive(indexed_wiki: LoreWikiConfig) -> None:
    r = HierarchyRetriever.from_config(indexed_wiki)
    hits = list(r.search("重试", top_k=3))
    assert hits
    assert all(h.score > 0 for h in hits)


def test_hierarchy_empty_query_returns_empty(indexed_wiki: LoreWikiConfig) -> None:
    r = HierarchyRetriever.from_config(indexed_wiki)
    assert list(r.search("", top_k=5)) == []
    assert list(r.search("    ", top_k=5)) == []


def test_hierarchy_unmatched_query_returns_empty(indexed_wiki: LoreWikiConfig) -> None:
    r = HierarchyRetriever.from_config(indexed_wiki)
    assert list(r.search("zzzzzz-not-in-corpus", top_k=5)) == []


def test_hierarchy_expands_module_to_all_children(indexed_wiki: LoreWikiConfig) -> None:
    """A query that matches a *module* node should return chunks from all docs
    under that module, not just the module's own (empty) content."""
    r = HierarchyRetriever.from_config(indexed_wiki)
    hits = list(r.search("patterns", top_k=10))
    # patterns/ has 1 doc; all chunks of that doc must surface.
    assert any(h.doc_path == "patterns/retry.md" for h in hits)


# ---- RRFFusion ----


def _make_hit(chunk_id: str, score: float, retriever: str = "x") -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        doc_path=chunk_id.split("#", 1)[0],
        title="t",
        heading_path="t",
        module="m",
        snippet="s",
        score=score,
        retriever=retriever,
    )


def test_rrf_basic_fusion() -> None:
    r1 = [_make_hit("a#0", 9.0, "r1"), _make_hit("b#0", 7.0, "r1")]
    r2 = [_make_hit("b#0", 8.0, "r2"), _make_hit("c#0", 6.0, "r2")]
    fuser = RRFFusion(k=60)
    fused = list(fuser.fuse({"r1": r1, "r2": r2}, top_k=3))
    ids = [h.chunk_id for h in fused]
    # b#0 appears in both → should rank first.
    assert ids[0] == "b#0"
    assert set(ids) == {"a#0", "b#0", "c#0"}
    for h in fused:
        assert h.retriever == "mix"
        assert h.score > 0


def test_rrf_respects_weights() -> None:
    a = [_make_hit("a#0", 1.0, "r1")]
    b = [_make_hit("b#0", 1.0, "r2")]
    fuser = RRFFusion(k=60, weights={"r1": 5.0, "r2": 1.0})
    fused = list(fuser.fuse({"r1": a, "r2": b}, top_k=2))
    assert fused[0].chunk_id == "a#0"


def test_rrf_empty_inputs_return_empty() -> None:
    fuser = RRFFusion()
    assert list(fuser.fuse({}, top_k=5)) == []
    assert list(fuser.fuse({"r1": []}, top_k=5)) == []


def test_rrf_records_contributors() -> None:
    r1 = [_make_hit("a#0", 9.0, "r1")]
    r2 = [_make_hit("a#0", 8.0, "r2")]
    fuser = RRFFusion()
    fused = list(fuser.fuse({"r1": r1, "r2": r2}, top_k=1))
    assert fused[0].extra["contributors"] == ["r1", "r2"]
    assert fused[0].extra["original_score"] in {9.0, 8.0}


def test_rrf_invalid_k_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        RRFFusion(k=0)
    with pytest.raises(ValueError, match="positive"):
        RRFFusion(k=-1)


# ---- CLI mix integration ----


def test_mix_mode_combines_both_retrievers(indexed_wiki: LoreWikiConfig) -> None:
    """The unified search dispatcher used by ``lorewiki search --mode mix``
    must return hits whose ``retriever`` is ``"mix"`` (set by RRF) —
    proving fusion ran."""
    from lorewiki.retriever import run_search  # noqa: PLC0415

    hits = run_search(indexed_wiki, "用户认证", mode="mix", top_k=3)
    assert hits
    assert all(h.retriever == "mix" for h in hits)


def test_bm25_and_hierarchy_can_overlap(indexed_wiki: LoreWikiConfig) -> None:
    """Sanity check that the same chunk can surface in both retrievers."""
    bm25 = BM25Retriever.from_config(indexed_wiki)
    hier = HierarchyRetriever.from_config(indexed_wiki)
    bm25_ids = {h.chunk_id for h in bm25.search("用户认证", top_k=10)}
    hier_ids = {h.chunk_id for h in hier.search("用户认证", top_k=10)}
    assert bm25_ids & hier_ids, "expected at least one overlapping chunk"
