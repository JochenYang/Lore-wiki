"""BM25 retriever over the FTS5 ``docs_fts`` virtual table.

Design notes
------------

The schema uses the SQLite ``trigram`` tokenizer which gives strong recall for
Chinese + English when the query length is >= 3 characters. However FTS5
matches on intersected trigrams using AND semantics, so a 5-character query
like ``"指数退避抖动"`` produces 4 trigrams (``指数退``, ``数退避``,
``退避抖``, ``避抖动``) and the document must contain **every** trigram.
Real documents often only contain a subset, e.g. "指数退避 + 抖动" → no
``退避抖`` trigram. This retriever therefore performs query rewriting:

1. **Phrase pass** — issue the original query as a FTS5 phrase. Best precision.
2. **OR pass** — split the query into terms (whitespace-separated, then
   re-trigramised for CJK runs) and ``OR`` them. Trades precision for recall.
3. **LIKE fallback** — for very short queries (< 3 characters) or when the
   above two passes return nothing, do a ``LIKE %query%`` scan with a length-
   normalised pseudo-score. Slow but never empty for matched substrings.

Results from the three passes are deduplicated by ``chunk_id``; the highest
score across passes is kept.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from lorewiki.config import LoreWikiConfig
from lorewiki.db import open_db
from lorewiki.db.models import SearchHit
from lorewiki.indexer import cleaning
from lorewiki.retriever.base import BaseRetriever
from lorewiki.utils.logger import get_logger

log = get_logger(__name__)

# Characters that have special meaning inside FTS5 MATCH expressions and must
# either be quoted or stripped before they reach the parser.
_FTS_SPECIAL = re.compile(r'["()*:^]')


class BM25Retriever(BaseRetriever):
    name = "bm25"

    def __init__(self, db_path: Path, *, snippet_chars: int = 240):
        self.db_path = db_path
        self.snippet_chars = snippet_chars

    @classmethod
    def from_config(cls, cfg: LoreWikiConfig) -> BM25Retriever:
        if cfg.db_path is None:
            msg = "LoreWikiConfig.db_path must be resolved before building a retriever"
            raise ValueError(msg)
        return cls(cfg.db_path, snippet_chars=cfg.snippet_chars)

    def search(self, query: str, *, top_k: int = 5) -> Sequence[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []

        with open_db(self.db_path, auto_init=False) as conn:
            hits: dict[str, SearchHit] = {}

            if len(query) >= 3:
                for hit in self._fts_phrase_pass(conn, query, top_k):
                    self._upsert(hits, hit)

                if len(hits) < top_k:
                    for hit in self._fts_or_pass(conn, query, top_k):
                        self._upsert(hits, hit)

            if len(hits) < top_k:
                for hit in self._like_pass(conn, query, top_k):
                    self._upsert(hits, hit)

        ordered = sorted(hits.values(), key=lambda h: h.score, reverse=True)
        return ordered[:top_k]

    # ---- internal passes ----

    def _fts_phrase_pass(
        self, conn: sqlite3.Connection, query: str, top_k: int
    ) -> Iterable[SearchHit]:
        match_expr = self._as_phrase(query)
        if not match_expr:
            return []
        rows = self._fts_select(conn, match_expr, top_k)
        # Phrase matches get a 1.5x boost because they signal higher precision.
        return [self._row_to_hit(r, source="bm25.phrase", boost=1.5) for r in rows]

    def _fts_or_pass(
        self, conn: sqlite3.Connection, query: str, top_k: int
    ) -> Iterable[SearchHit]:
        terms = self._or_terms(query)
        if not terms:
            return []
        match_expr = " OR ".join(f'"{t}"' for t in terms)
        rows = self._fts_select(conn, match_expr, top_k * 2)
        return [self._row_to_hit(r, source="bm25.or", boost=1.0) for r in rows]

    def _like_pass(
        self, conn: sqlite3.Connection, query: str, top_k: int
    ) -> Iterable[SearchHit]:
        like = f"%{query}%"
        # Only search title and heading_path to avoid full content scan
        rows = conn.execute(
            """
            SELECT id AS chunk_id, doc_path, title, heading_path, module,
                   content AS snippet, length(content) AS clen
            FROM documents
            WHERE title LIKE ? OR heading_path LIKE ?
            LIMIT ?
            """,
            (like, like, top_k * 2),
        ).fetchall()
        hits: list[SearchHit] = []
        for r in rows:
            # Pseudo-score: shorter documents that contain the query get a
            # higher score; cap at 0.5 so FTS hits always rank above LIKE.
            pseudo = min(0.5, 50.0 / max(1, r["clen"]))
            hits.append(
                SearchHit(
                    chunk_id=r["chunk_id"],
                    doc_path=r["doc_path"],
                    title=cleaning.clean_title(r["title"]),
                    heading_path=cleaning.clean_heading_path(r["heading_path"]),
                    module=r["module"],
                    snippet=cleaning.clean_snippet(r["snippet"]),
                    score=pseudo,
                    retriever="bm25.like",
                )
            )
        return hits

    # ---- helpers ----

    def _fts_select(
        self, conn: sqlite3.Connection, match_expr: str, limit: int
    ) -> list[sqlite3.Row]:
        try:
            return conn.execute(
                """
                SELECT
                    d.id AS chunk_id, d.doc_path, d.title, d.heading_path, d.module,
                    d.content AS snippet,
                    rank
                FROM docs_fts
                JOIN documents d ON d.rowid = docs_fts.rowid
                WHERE docs_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match_expr, limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("fts5 query failed ({}): {}", exc, match_expr)
            return []

    @staticmethod
    def _row_to_hit(row: sqlite3.Row, *, source: str, boost: float = 1.0) -> SearchHit:
        # ``sqlite3.Row.__contains__`` checks *values*, not column names, so
        # we explicitly look at ``row.keys()`` here. ruff SIM118 wants
        # ``"rank" in row``, but that would silently return False.
        rank = row["rank"] if "rank" in row.keys() else 0.0  # noqa: SIM118
        # FTS5 rank is a negative BM25-like score (more negative = better).
        # We invert sign and multiply by ``boost`` (phrase pass > or pass).
        # Scores are typically in the [0, ~10] range and NOT clamped to 1, so
        # fusion algorithms see real magnitude differences. LIKE pass scores
        # live in [0, 0.5] so they never outrank FTS hits.
        score = -float(rank) * boost
        return SearchHit(
            chunk_id=row["chunk_id"],
            doc_path=row["doc_path"],
            title=cleaning.clean_title(row["title"]),
            heading_path=cleaning.clean_heading_path(row["heading_path"]),
            module=row["module"],
            snippet=cleaning.clean_snippet(row["snippet"]),
            score=score,
            retriever=source,
        )

    @staticmethod
    def _as_phrase(query: str) -> str:
        cleaned = _FTS_SPECIAL.sub(" ", query).strip()
        if not cleaned:
            return ""
        return f'"{cleaned}"'

    @staticmethod
    def _or_terms(query: str) -> list[str]:
        cleaned = _FTS_SPECIAL.sub(" ", query)
        terms: list[str] = []
        for word in cleaned.split():
            if not word:
                continue
            if word.isascii():
                if len(word) >= 3:
                    terms.append(word)
                continue
            # CJK run: turn into overlapping trigrams; if the run is shorter
            # than 3 characters we keep it as-is so the LIKE fallback can find
            # it.
            if len(word) < 3:
                continue
            for i in range(len(word) - 2):
                terms.append(word[i : i + 3])
        # Deduplicate while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for t in terms:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    @staticmethod
    def _upsert(hits: dict[str, SearchHit], hit: SearchHit) -> None:
        existing = hits.get(hit.chunk_id)
        if existing is None or hit.score > existing.score:
            hits[hit.chunk_id] = hit


__all__ = ["BM25Retriever"]
