"""Phase-1 recall acceptance check against example_wiki.

Each query is annotated with the expected document(s). We compute Recall@5
across the 10-query benchmark from the dev plan; the run prints a per-query
table plus an aggregate.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from lorewiki.config import LoreWikiConfig
from lorewiki.indexer import build_index
from lorewiki.retriever import BM25Retriever


# Each entry: (query, set of expected ``doc_path`` values that should be hit
# in the top-K results). A query is considered "recalled" if any of its
# expected docs appears in the top-K.
BENCHMARK: list[tuple[str, set[str]]] = [
    ("用户登录接口", {"api/user/auth.md"}),
    ("JWT 刷新策略", {"api/user/auth.md"}),
    ("如何实现幂等重试", {"patterns/retry.md", "api/order/checkout.md"}),
    ("下单库存超卖", {"api/order/checkout.md"}),
    ("令牌桶算法 Redis 实现", {"patterns/rate-limit.md"}),
    ("指数退避抖动", {"patterns/retry.md"}),
    ("网关层和应用层限流区别", {"patterns/rate-limit.md"}),
    ("Refresh Token 旋转", {"api/user/auth.md"}),
    ("Idempotency-Key", {"api/order/checkout.md", "patterns/retry.md"}),
    ("限流方案选型", {"patterns/rate-limit.md", "index.md"}),
]

TOP_K = 5


def main() -> None:
    project = Path(__file__).resolve().parent.parent
    wiki = project / "example_wiki"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "index.db"
        cfg = LoreWikiConfig(wiki_path=wiki, db_path=db_path)
        stats = build_index(cfg, rebuild=True)
        r = BM25Retriever.from_config(cfg)

        print(f"Indexed {stats.files_indexed} files, {stats.chunks_written} chunks "
              f"in {stats.duration_seconds:.3f}s")
        print(f"\n{'query':<35} {'top doc':<32} {'score':>10}  hit?")
        print("-" * 90)

        hits_count = 0
        total_latency = 0.0
        for query, expected in BENCHMARK:
            t0 = time.perf_counter()
            results = list(r.search(query, top_k=TOP_K))
            latency = time.perf_counter() - t0
            total_latency += latency
            top_doc = results[0].doc_path if results else "(none)"
            top_score = results[0].score if results else 0.0
            actual_docs = {h.doc_path for h in results}
            recalled = bool(expected & actual_docs)
            hits_count += int(recalled)
            mark = "OK" if recalled else "MISS"
            print(f"{query:<35} {top_doc:<32} {top_score:>10.3f}  {mark}")

        recall = hits_count / len(BENCHMARK)
        avg_lat_ms = (total_latency / len(BENCHMARK)) * 1000
        print("-" * 90)
        print(f"Recall@{TOP_K}: {hits_count}/{len(BENCHMARK)} = {recall:.2%}")
        print(f"Avg latency: {avg_lat_ms:.1f} ms per query")
        print(f"Threshold (phase-1 BM25 only): Recall@5 >= 0.80")
        if recall >= 0.80:
            print("ACCEPTANCE: PASS")
        else:
            print("ACCEPTANCE: FAIL - need hierarchy/RRF in phase 2")


if __name__ == "__main__":
    main()
