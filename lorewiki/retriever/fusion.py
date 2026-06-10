"""Reciprocal Rank Fusion for merging multiple retriever outputs.

RRF (Cormack et al. 2009) is a no-tuning algorithm that consistently
beats per-retriever weighting in IR literature:

    fused_score(d) = Σᵢ wᵢ / (k + rankᵢ(d))

where ``rankᵢ(d)`` is the 1-based rank of document ``d`` in retriever ``i``'s
ordered output, ``k`` is a smoothing constant (typically 60), and ``wᵢ`` is
an optional per-retriever weight.

Properties exploited here:

* No score normalisation needed — only ranks matter. This sidesteps the
  cross-retriever score-scale problem (BM25 scores ~0-10, LIKE 0-0.5,
  hierarchy 0-N word-hit counts).
* Documents reached by more retrievers naturally accumulate higher fused
  scores, which is exactly the "consensus boost" we want.

The fuser returns ``SearchHit`` objects whose ``retriever`` field is set to
``"mix"`` and whose ``score`` is the fused RRF score.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from lorewiki.db.models import SearchHit


class RRFFusion:
    """Fuse hits from multiple retrievers via Reciprocal Rank Fusion."""

    def __init__(
        self,
        *,
        k: int = 60,
        weights: Mapping[str, float] | None = None,
    ):
        if k <= 0:
            msg = f"k must be positive, got {k}"
            raise ValueError(msg)
        self.k = k
        self.weights = dict(weights or {})

    def fuse(
        self,
        per_retriever: Mapping[str, Iterable[SearchHit]],
        *,
        top_k: int = 5,
    ) -> Sequence[SearchHit]:
        """Fuse ``per_retriever`` mapping ``name -> ordered_hits`` into one list."""
        scores: dict[str, float] = {}
        best_hit: dict[str, SearchHit] = {}
        contributors: dict[str, set[str]] = {}

        for retr_name, hits in per_retriever.items():
            weight = self.weights.get(retr_name, 1.0)
            for rank, hit in enumerate(hits, start=1):
                key = hit.chunk_id
                scores[key] = scores.get(key, 0.0) + weight / (self.k + rank)
                contributors.setdefault(key, set()).add(retr_name)
                if key not in best_hit or hit.score > best_hit[key].score:
                    best_hit[key] = hit

        if not scores:
            return []

        ordered_keys = sorted(scores.keys(), key=lambda k_: scores[k_], reverse=True)
        out: list[SearchHit] = []
        for key in ordered_keys[:top_k]:
            base = best_hit[key]
            extra = dict(base.extra)
            extra["contributors"] = sorted(contributors[key])
            extra["original_score"] = base.score
            out.append(
                replace(
                    base,
                    score=scores[key],
                    retriever="mix",
                    extra=extra,
                )
            )
        return out


__all__ = ["RRFFusion"]
