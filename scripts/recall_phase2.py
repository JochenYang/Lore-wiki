"""Phase-2 recall: compare bm25 / hierarchy / mix on the same benchmark."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from lorewiki.config import LoreWikiConfig
from lorewiki.indexer import build_index
from lorewiki.retriever import BM25Retriever, HierarchyRetriever, RRFFusion

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
    ("限流方案选型", {"patterns/rate-limit.md"}),  # 去掉 index.md 让数据集更纯
]
TOP_K = 5


def run_mode(name: str, search_fn, label: str) -> tuple[float, float]:
    print(f"\n=== {label} ===")
    hits = 0
    total_latency = 0.0
    for query, expected in BENCHMARK:
        t0 = time.perf_counter()
        results = list(search_fn(query, top_k=TOP_K))
        latency = time.perf_counter() - t0
        total_latency += latency
        actual = {h.doc_path for h in results}
        mark = "OK" if expected & actual else "MISS"
        top = results[0].doc_path if results else "(none)"
        score = results[0].score if results else 0
        print(f"  {query:<28} top={top:<28} score={score:>8.3f}  {mark}")
        if expected & actual:
            hits += 1
    recall = hits / len(BENCHMARK)
    avg_ms = total_latency / len(BENCHMARK) * 1000
    print(f"  Recall@{TOP_K} = {hits}/{len(BENCHMARK)} = {recall:.2%}   avg {avg_ms:.1f}ms")
    return recall, avg_ms


def main() -> None:
    project = Path(__file__).resolve().parent.parent
    wiki = project / "example_wiki"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg = LoreWikiConfig(wiki_path=wiki, db_path=Path(tmp) / "index.db")
        stats = build_index(cfg, rebuild=True)
        print(f"Indexed {stats.files_indexed} files / {stats.chunks_written} chunks")

        bm25 = BM25Retriever.from_config(cfg)
        hier = HierarchyRetriever.from_config(cfg)
        fuser = RRFFusion(
            k=cfg.rrf_k,
            weights={
                "bm25": cfg.mix_weights.bm25,
                "hierarchy": cfg.mix_weights.hierarchy,
            },
        )

        def mix_search(q: str, top_k: int) -> list:
            return list(
                fuser.fuse(
                    {
                        "bm25": list(bm25.search(q, top_k=top_k * 2)),
                        "hierarchy": list(hier.search(q, top_k=top_k * 2)),
                    },
                    top_k=top_k,
                )
            )

        bm25_r, _ = run_mode("bm25", lambda q, top_k: bm25.search(q, top_k=top_k), "BM25 only")
        hier_r, _ = run_mode("hier", lambda q, top_k: hier.search(q, top_k=top_k), "Hierarchy only")
        mix_r, _ = run_mode("mix", mix_search, "Mix (RRF fused)")

        print("\n--- Summary ---")
        print(f"  BM25       : {bm25_r:.2%}")
        print(f"  Hierarchy  : {hier_r:.2%}")
        print(f"  Mix (RRF)  : {mix_r:.2%}")
        print(f"\nThreshold (phase-2 mix): Recall@5 >= 0.85")
        print(f"ACCEPTANCE: {'PASS' if mix_r >= 0.85 else 'FAIL'}")


if __name__ == "__main__":
    main()
