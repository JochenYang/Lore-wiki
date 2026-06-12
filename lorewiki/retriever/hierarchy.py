"""Hierarchy retriever: keyword search over the ``hierarchy`` tree.

Strategy (no-LLM variant, default for phase 2):

1. Tokenise the query into terms (CJK trigrams + ascii words ≥ 3 chars).
2. Score every hierarchy node by counting how many query terms appear in its
   ``title`` (weighted x3) and ``summary`` (weight x1). Shallower nodes get a
   small bonus because navigation-style hits should out-rank leaf hits.
3. For every matched node, collect every chunk under that subtree (via
   recursive descent on ``parent_id``) and emit them as :class:`SearchHit`.

The retriever returns chunks de-duplicated by ``chunk_id`` and sorted by the
node's score (highest first). Designed to *complement* BM25 — BM25 is great
at precise wording, hierarchy is great at "I want everything about X
module" style queries.

Phase 3 will add an optional LLM-driven navigator that replaces step (2)
with a model call.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from lorewiki.config import LoreWikiConfig
from lorewiki.db import open_db
from lorewiki.db.models import SearchHit
from lorewiki.indexer import cleaning
from lorewiki.retriever.base import BaseRetriever
from lorewiki.utils.logger import get_logger

log = get_logger(__name__)

CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
ASCII_RUN_RE = re.compile(r"[A-Za-z0-9_]+")


class HierarchyRetriever(BaseRetriever):
    name = "hierarchy"

    def __init__(self, db_path: Path, *, snippet_chars: int = 240):
        self.db_path = db_path
        self.snippet_chars = snippet_chars

    @classmethod
    def from_config(cls, cfg: LoreWikiConfig) -> HierarchyRetriever:
        if cfg.db_path is None:
            msg = "LoreWikiConfig.db_path must be resolved before building a retriever"
            raise ValueError(msg)
        return cls(cfg.db_path, snippet_chars=cfg.snippet_chars)

    def search(self, query: str, *, top_k: int = 5) -> Sequence[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []
        terms = _tokenize(query)
        if not terms:
            return []

        with open_db(self.db_path, auto_init=False) as conn:
            nodes = self._score_nodes(conn, terms)
            if not nodes:
                return []
            # Top-N nodes feed into chunk expansion; we then trim chunks
            # to ``top_k`` in the final sort.
            chunks = self._chunks_for_nodes(conn, nodes, top_k=top_k * 3)

        return self._merge_and_rank(chunks, nodes, top_k=top_k)

    # ---- internal ----

    def _score_nodes(
        self, conn: sqlite3.Connection, terms: list[str]
    ) -> list[tuple[float, sqlite3.Row]]:
        """Return ``[(score, row)]`` for every hierarchy row hit by any term.

        Score formula::

            title_hits * 3.0 + summary_hits * 1.0 + (1.0 / (level + 1))

        which gives heavier weight to title matches and a small "shallow nodes
        first" prior. We skip the synthetic root node (level 0) because it
        owns every document and would dominate every search.
        """
        rows = conn.execute(
            "SELECT id, parent_id, node_type, title, summary, path, level, doc_id "
            "FROM hierarchy WHERE level > 0"
        ).fetchall()

        scored: list[tuple[float, sqlite3.Row]] = []
        lowered_terms = [t.lower() for t in terms]
        min_matches = min(2, len(lowered_terms))
        for row in rows:
            title_low = (row["title"] or "").lower()
            summary_low = (row["summary"] or "").lower()
            matched_terms: set[str] = set()
            title_hits = 0
            summary_hits = 0
            for t in lowered_terms:
                in_title = t in title_low
                in_summary = t in summary_low
                if in_title:
                    title_hits += 1
                if in_summary:
                    summary_hits += 1
                if in_title or in_summary:
                    matched_terms.add(t)
            if len(matched_terms) < min_matches:
                continue
            score = title_hits * 3.0 + summary_hits * 1.0 + 1.0 / (row["level"] + 1)
            scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored

    def _chunks_for_nodes(
        self,
        conn: sqlite3.Connection,
        scored_nodes: list[tuple[float, sqlite3.Row]],
        *,
        top_k: int,
    ) -> list[tuple[float, sqlite3.Row, str]]:
        """For each scored node, collect the chunks living under its subtree.

        Returns ``[(node_score, chunk_row, source_node_id)]`` lists.
        """
        # Build a parent → children map so we can DFS without recursive SQL.
        all_nodes = conn.execute(
            "SELECT id, parent_id, doc_id FROM hierarchy"
        ).fetchall()
        children: dict[str | None, list[sqlite3.Row]] = {}
        for n in all_nodes:
            children.setdefault(n["parent_id"], []).append(n)

        out: list[tuple[float, sqlite3.Row, str]] = []
        seen_chunks: set[str] = set()
        for score, node in scored_nodes:
            doc_paths = _collect_doc_paths(node, children)
            if not doc_paths:
                continue
            placeholders = ",".join("?" * len(doc_paths))
            rows = conn.execute(
                f"SELECT id AS chunk_id, doc_path, title, heading_path, module, "
                f"       content AS snippet "
                f"FROM documents WHERE doc_path IN ({placeholders})",
                (*doc_paths,),
            ).fetchall()
            for r in rows:
                if r["chunk_id"] in seen_chunks:
                    continue
                seen_chunks.add(r["chunk_id"])
                out.append((score, r, node["id"]))
            if len(out) >= top_k:
                break
        return out[:top_k]

    @staticmethod
    def _merge_and_rank(
        chunks: list[tuple[float, sqlite3.Row, str]],
        _nodes: list[tuple[float, sqlite3.Row]],
        *,
        top_k: int,
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for score, row, source_node in chunks:
            hits.append(
                SearchHit(
                    chunk_id=row["chunk_id"],
                    doc_path=row["doc_path"],
                    title=cleaning.clean_title(row["title"]),
                    heading_path=cleaning.clean_heading_path(row["heading_path"]),
                    module=row["module"],
                    snippet=cleaning.clean_snippet(row["snippet"]),
                    score=score,
                    retriever="hierarchy",
                    extra={"node": source_node},
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]


def _collect_doc_paths(
    node: sqlite3.Row, children: dict[str | None, list[sqlite3.Row]]
) -> list[str]:
    """DFS collect every ``doc_id`` reachable from ``node``.

    Returns *doc_path* values (not chunk IDs) so the caller can fetch every
    chunk for those docs in a single SQL query.
    """
    out: list[str] = []
    if node["doc_id"]:
        # doc_id is ``<doc_path>#<chunk_idx>``; we just want the doc_path part.
        out.append(_doc_path_of(node["doc_id"]))
    stack = list(children.get(node["id"], []))
    while stack:
        current = stack.pop()
        if current["doc_id"]:
            out.append(_doc_path_of(current["doc_id"]))
        stack.extend(children.get(current["id"], []))
    # Deduplicate preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def _doc_path_of(doc_id: str) -> str:
    return doc_id.split("#", 1)[0]


def _tokenize(query: str) -> list[str]:
    """Build a list of search terms from a free-form query.

    For CJK runs we generate **both** bigrams (so 2-character terms like
    ``"幂等"`` / ``"重试"`` can match document titles directly) and trigrams
    (mirroring the FTS5 index for longer phrases). For ASCII runs we keep
    words ≥ 3 characters. The original full CJK run is also retained as a
    high-precision term.
    """
    terms: list[str] = []
    for run in CJK_RUN_RE.findall(query):
        if len(run) >= 2:
            terms.append(run)
            for i in range(len(run) - 1):
                terms.append(run[i : i + 2])
        if len(run) >= 3:
            for i in range(len(run) - 2):
                terms.append(run[i : i + 3])
    for run in ASCII_RUN_RE.findall(query):
        if len(run) >= 3:
            terms.append(run)
    # Deduplicate preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


__all__ = ["HierarchyRetriever"]
