"""Smoke test BM25Retriever including the long-query OR fallback."""

from __future__ import annotations

import tempfile
from pathlib import Path

from lorewiki.config import LoreWikiConfig
from lorewiki.indexer import build_index
from lorewiki.retriever import BM25Retriever


QUERIES = [
    # Expected hits in parentheses (informal).
    "用户认证",         # auth.md
    "JWT 双 Token",     # auth.md
    "幂等设计",         # retry.md / checkout.md
    "令牌桶 Redis",     # rate-limit.md
    "指数退避抖动",     # retry.md  (long CJK query - tests OR fallback)
    "限流方案选型",     # rate-limit.md / index.md
    "幂等",             # short query - tests LIKE fallback
    "登录",             # short query - tests LIKE fallback
    "认证",             # short query
    "网关层与应用层限流区别",  # very long mixed
    "Token Bucket",     # mixed English
    "重试风暴",         # 4-char idiom
]


def main() -> None:
    project = Path(__file__).resolve().parent.parent
    wiki = project / "example_wiki"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "index.db"
        cfg = LoreWikiConfig(wiki_path=wiki, db_path=db_path)
        build_index(cfg, rebuild=True)
        bm25 = BM25Retriever.from_config(cfg)
        for q in QUERIES:
            hits = bm25.search(q, top_k=3)
            print(f"\nq={q!r:<32} ->  {len(hits)} hits")
            for h in hits:
                print(
                    f"  [{h.score:.4f}|{h.retriever:<10}] {h.doc_path} :: {h.heading_path}"
                )


if __name__ == "__main__":
    main()
