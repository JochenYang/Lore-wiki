"""Unified search dispatch used by the CLI and any other entry point.

The CLI used to open-code BM25 + Hierarchy + RRF logic in three
places (``search``, ``ask`` and a helper). Centralising it here means
a single change to the dispatch logic propagates everywhere.
"""

from __future__ import annotations

import contextlib

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

    if mode == "bm25":
        return list(retrievers["bm25"].search(query, top_k=top_k))
    if mode == "hierarchy":
        return list(retrievers["hierarchy"].search(query, top_k=top_k))
    if mode == "vector":
        # Phase 6 deliverable. Surface a constructor so callers that
        # want to inspect the placeholder still get something; the
        # ``.search`` call will raise NotImplementedError on its own.
        # For now, fall back to mix so the CLI never throws on a
        # ``--mode vector`` request.
        with contextlib.suppress(NotImplementedError):
            VectorRetriever.from_config(cfg)  # construction is cheap; the
                                              # .search() call is what raises.
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
