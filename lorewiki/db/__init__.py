"""Database layer (SQLite + FTS5).

Exposes connection helpers and typed row models; concrete CRUD lives in the
indexer / retriever modules to keep this layer thin.
"""

from lorewiki.db.connection import (
    get_meta,
    init_db,
    open_db,
    schema_version,
    set_meta,
)
from lorewiki.db.models import DocumentChunk, HierarchyNode, SearchHit

__all__ = [
    "DocumentChunk",
    "HierarchyNode",
    "SearchHit",
    "get_meta",
    "init_db",
    "open_db",
    "schema_version",
    "set_meta",
]
