"""Typed dataclasses representing rows in the LoreWiki SQLite database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DocumentChunk:
    """One indexed Markdown chunk (a single row in the ``documents`` table)."""

    id: str
    doc_path: str
    chunk_index: int
    title: str
    content: str
    heading_path: str | None = None
    module: str | None = None
    tags: list[str] = field(default_factory=list)
    token_count: int = 0
    content_hash: str | None = None

    def tags_csv(self) -> str:
        return ",".join(self.tags) if self.tags else ""


@dataclass(slots=True)
class HierarchyNode:
    """One node in the hierarchy index tree."""

    id: str
    parent_id: str | None
    node_type: str
    title: str
    path: str
    level: int
    summary: str | None = None
    doc_id: str | None = None


@dataclass(slots=True)
class SearchHit:
    """A single retrieval result returned by any retriever."""

    chunk_id: str
    doc_path: str
    title: str
    heading_path: str | None
    module: str | None
    snippet: str
    score: float
    retriever: str = "unknown"
    extra: dict[str, Any] = field(default_factory=dict)


__all__ = ["DocumentChunk", "HierarchyNode", "SearchHit"]
