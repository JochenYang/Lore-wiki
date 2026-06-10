"""Abstract retriever interface shared by BM25 / hierarchy / vector backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from lorewiki.db.models import SearchHit


class BaseRetriever(ABC):
    """Every retriever returns a sorted (best-first) sequence of ``SearchHit``."""

    name: str = "base"

    @abstractmethod
    def search(self, query: str, *, top_k: int = 5) -> Sequence[SearchHit]:
        """Return up to ``top_k`` hits ranked best-first."""


__all__ = ["BaseRetriever"]
