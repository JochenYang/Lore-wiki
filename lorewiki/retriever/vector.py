"""Vector retrieval (placeholder).

Vector retrieval is scheduled for Phase 6. Until then, this module
provides a placeholder that fails loudly when callers ask for it —
the CLI's ``vector`` mode currently silently falls back to ``mix``,
but a direct ``VectorRetriever().search(...)`` call should not
hide that the backend isn't implemented yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from lorewiki.config import LoreWikiConfig
from lorewiki.db.models import SearchHit
from lorewiki.retriever.base import BaseRetriever


class VectorRetriever(BaseRetriever):
    """Stub for the Phase-6 vector backend.

    ``search`` raises :class:`NotImplementedError` so callers see a
    clear, actionable error rather than a silent empty result. The
    CLI's ``--mode vector`` flag is meant to fall back to ``mix`` in
    this release; the failing here is a safety net for any direct
    programmatic use.
    """

    name = "vector"

    def __init__(self, db_path: Path, *, snippet_chars: int = 240) -> None:
        self.db_path = db_path
        self.snippet_chars = snippet_chars

    @classmethod
    def from_config(cls, cfg: LoreWikiConfig) -> VectorRetriever:
        if cfg.db_path is None:
            msg = "LoreWikiConfig.db_path must be resolved before building a retriever"
            raise ValueError(msg)
        return cls(cfg.db_path, snippet_chars=cfg.snippet_chars)

    def search(self, query: str, *, top_k: int = 5) -> Sequence[SearchHit]:
        msg = (
            "Vector retrieval is scheduled for Phase 6 and is not yet "
            "implemented. Use --mode mix (or bm25 / hierarchy) in the meantime."
        )
        raise NotImplementedError(msg)


__all__ = ["VectorRetriever"]
