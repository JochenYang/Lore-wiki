"""Unified search dispatch used by the CLI and any other entry point.

The CLI used to open-code BM25 + Hierarchy + RRF logic in three
places (``search``, ``ask`` and a helper). Centralising it here means
a single change to the dispatch logic propagates everywhere.
"""

from __future__ import annotations

from loguru import logger as log

from lorewiki.config import LoreWikiConfig
from lorewiki.db.models import SearchHit
from lorewiki.retriever.bm25 import BM25Retriever
from lorewiki.retriever.fusion import RRFFusion
from lorewiki.retriever.hierarchy import HierarchyRetriever
from lorewiki.retriever.vector import VectorRetriever

SUPPORTED_MODES: frozenset[str] = frozenset({"bm25", "hierarchy", "mix", "vector"})


def run_search(
    cfg: LoreWikiConfig,
    query: str,
    *,
    mode: str,
    top_k: int,
) -> list[SearchHit]:
    """Run a single retriever, or fuse the two real ones via RRF.

    Parameters
    ----------
    cfg
        Resolved :class:`LoreWikiConfig` (must have ``db_path`` set).
    query
        The natural-language or keyword query.
    mode
        One of ``"bm25"``, ``"hierarchy"``, ``"mix"``, or ``"vector"``.
        ``"vector"`` silently falls back to ``"mix"`` for now (the
        vector backend is a Phase-6 deliverable).
    top_k
        Maximum number of hits to return.

    Returns
    -------
    list[SearchHit]
        Ordered best-first. Empty list when the query is empty.
    """
    if not query.strip():
        return []
    if mode not in SUPPORTED_MODES:
        msg = f"Unknown retrieval mode: {mode!r} (expected one of {sorted(SUPPORTED_MODES)})"
        raise ValueError(msg)

    retrievers = {
        "bm25": BM25Retriever.from_config(cfg),
        "hierarchy": HierarchyRetriever.from_config(cfg),
    }
    # ``vector`` is added lazily — only imported if the user explicitly
    # requested vector mode. This keeps the core CLI's import graph
    # free of fastembed / sqlite-vec for users who never use --mode
    # vector.
    vector_retr = None
    if mode == "vector":
        try:
            vector_retr = VectorRetriever.from_config(cfg)
            retrievers["vector"] = vector_retr
        except Exception as exc:
            # No fastembed / sqlite-vec installed, or the model failed
            # to load. Surface a clear log line and fall back to mix
            # so the CLI never errors.
            log.warning(
                "vector retriever unavailable ({}); falling back to mix",
                exc,
            )
            mode = "mix"

    if mode == "bm25":
        return list(retrievers["bm25"].search(query, top_k=top_k))
    if mode == "hierarchy":
        return list(retrievers["hierarchy"].search(query, top_k=top_k))
    if mode == "vector" and vector_retr is not None:
        # If the vector backend returned no hits (empty index, OOV
        # query, etc.), gracefully fall back to mix so the LLM still
        # has something to look at.
        vec_hits = list(vector_retr.search(query, top_k=top_k))
        if vec_hits:
            return vec_hits
        log.debug("vector mode returned 0 hits, falling back to mix")
        mode = "mix"

    per_retriever = {
        name: list(r.search(query, top_k=top_k * 2))
        for name, r in retrievers.items()
    }
    fuser = RRFFusion(
        k=cfg.rrf_k,
        weights={
            "bm25": cfg.mix_weights.bm25,
            "hierarchy": cfg.mix_weights.hierarchy,
        },
    )
    return list(fuser.fuse(per_retriever, top_k=top_k))


__all__ = ["SUPPORTED_MODES", "run_search"]
