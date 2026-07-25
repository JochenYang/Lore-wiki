"""Vector retrieval via sqlite-vec + fastembed (optional).

When the ``[vector]`` extra is installed (``pip install lorewiki[vector]``),
chunks are embedded with fastembed (default ``BAAI/bge-small-en-v1.5``,
384 dims) and stored in a ``doc_vec`` virtual table. At search time the
query is embedded the same way and we ask sqlite-vec for the K nearest
neighbours.

When fastembed / sqlite-vec are not installed, ``VectorRetriever.search()``
returns an empty list and the run_search dispatcher falls back to ``mix``
so the CLI never errors.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger as log

from lorewiki.config import LoreWikiConfig
from lorewiki.db.models import SearchHit
from lorewiki.retriever.base import BaseRetriever

if TYPE_CHECKING:
    import sqlite3

VECTOR_DIM = 384  # BAAI/bge-small-en-v1.5 default in fastembed
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# SQL contract for sqlite-vec KNN: ``distance`` is a special column on the
# virtual table side, not on ``documents``. Tests pin this string so a
# regression cannot reintroduce ``d.embedding_distance``.
VECTOR_SEARCH_SQL = """
SELECT
    d.chunk_index,
    d.doc_path,
    d.title,
    d.heading_path,
    d.content,
    d.module,
    doc_vec.distance AS distance
FROM doc_vec
JOIN documents d ON d.rowid = doc_vec.rowid
WHERE doc_vec.embedding MATCH ?
  AND k = ?
ORDER BY distance
"""


class VectorRetriever(BaseRetriever):
    """Semantic search via sqlite-vec + fastembed.

    All heavy lifting (model load, extension load, query embedding) is
    lazy and cached at the instance level. Multiple queries on the
    same retriever reuse the loaded model — first query is slow
    (~1-2s for the model download + ~50ms for embedding the query);
    subsequent queries are <10ms.
    """

    name = "vector"

    def __init__(
        self,
        db_path: Path,
        *,
        snippet_chars: int = 240,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self.db_path = db_path
        self.snippet_chars = snippet_chars
        self.embedding_model = embedding_model
        self._model: Any | None = None  # lazy-loaded TextEmbedding
        self._available: bool | None = None  # cache capability check

    @classmethod
    def from_config(cls, cfg: LoreWikiConfig) -> VectorRetriever:
        if cfg.db_path is None:
            msg = "LoreWikiConfig.db_path must be resolved before building a retriever"
            raise ValueError(msg)
        # Env wins so operators can override without editing TOML; config
        # default matches the indexer (BAAI/bge-small-en-v1.5).
        model = os.environ.get(
            "LOREWIKI_VECTOR_MODEL",
            cfg.vector.embedding_model or DEFAULT_EMBEDDING_MODEL,
        )
        return cls(
            cfg.db_path,
            snippet_chars=cfg.snippet_chars,
            embedding_model=model,
        )

    def _ensure_available(self) -> bool:
        """Return True if the embedding model + sqlite-vec are usable, False otherwise.

        Caches the result so the first-call cost (model download, extension
        load) is paid exactly once. Returns False — and the caller's search
        returns empty — if fastembed isn't installed or the sqlite-vec
        extension can't be loaded.
        """
        if self._available is not None:
            return self._available
        try:
            import sqlite_vec  # noqa: PLC0415, F401 — lazy import for graceful degradation
        except ImportError:
            log.debug("sqlite-vec not installed; vector retriever is no-op")
            self._available = False
            return False
        if not self.db_path.exists():
            log.debug("db_path does not exist; vector retriever is no-op")
            self._available = False
            return False
        self._available = True
        return True

    def _load_model(self) -> Any:
        """Lazy-load fastembed TextEmbedding once per instance."""
        if self._model is not None:
            return self._model
        from fastembed import TextEmbedding  # noqa: PLC0415 — lazy load for speed

        log.info(
            "loading fastembed model {} (first call may download)",
            self.embedding_model,
        )
        self._model = TextEmbedding(model_name=self.embedding_model)
        return self._model

    def _open_with_vec(self) -> sqlite3.Connection | None:
        """Open a sqlite3 connection with the sqlite-vec extension loaded.

        Sets ``row_factory`` so search results support name-based access
        (``row["doc_path"]``). Returns None if the extension can't be
        loaded (caller should gracefully return empty hits).
        """
        import sqlite3  # noqa: PLC0415, I001 — func-scoped
        import sqlite_vec  # noqa: PLC0415 — lazy load for graceful degradation

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.enable_load_extension(True)
            conn.load_extension(sqlite_vec.loadable_path())
        except Exception as exc:
            log.warning("could not load sqlite-vec extension: {}", exc)
            conn.close()
            return None
        return conn

    def search(self, query: str, *, top_k: int = 5) -> Sequence[SearchHit]:
        """Return up to ``top_k`` hits ranked by vector distance.

        Returns an empty list if vector retrieval is unavailable (fastembed
        or sqlite-vec not installed, or the doc_vec table hasn't been
        populated yet). The dispatcher will fall back to ``mix`` mode in
        that case.
        """
        if not self._ensure_available():
            return []
        if not query.strip():
            return []

        try:
            model = self._load_model()
            # query_embedding is a generator yielding one ndarray; pull
            # the first (and only) result.
            qvec = next(model.embed(query.strip())).tolist()

            conn = self._open_with_vec()
            if conn is None:
                return []

            try:
                rows = conn.execute(VECTOR_SEARCH_SQL, (qvec, top_k)).fetchall()
            except Exception as exc:
                # Table missing, wrong schema, or empty index — surface once
                # at warning so operators notice, then degrade to empty.
                log.warning("vector search failed: {}", exc)
                rows = []
            finally:
                conn.close()

            hits: list[SearchHit] = []
            for row in rows:
                # sqlite-vec ``distance`` is L2 (or 1 - cosine for cosine
                # metrics). Map to a higher-is-better score for RRF/LLM.
                distance = float(row["distance"])
                snippet = row["content"] or ""
                if self.snippet_chars and len(snippet) > self.snippet_chars:
                    snippet = snippet[: self.snippet_chars]
                hits.append(
                    SearchHit(
                        chunk_id=f"{row['doc_path']}#{row['chunk_index']}",
                        doc_path=row["doc_path"],
                        title=row["title"],
                        heading_path=row["heading_path"],
                        module=row["module"],
                        snippet=snippet,
                        score=1.0 - distance,
                        retriever="vector",
                    )
                )
            return hits
        except Exception as exc:
            log.warning("vector retriever failed: {}", exc)
            return []


__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "VECTOR_DIM",
    "VECTOR_SEARCH_SQL",
    "VectorRetriever",
]
