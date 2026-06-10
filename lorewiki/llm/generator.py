"""Answer generation: search the wiki, build a prompt, call the LLM.

Exposed:

* :class:`Answer` — dataclass returned to the CLI / REST / MCP layers.
* :class:`AnswerGenerator` — orchestrates retrieval → prompt → LLM → answer.

If the LLM is unavailable (offline, disabled, network error), the generator
degrades gracefully: it returns the same context bundle as a "fallback
answer" so users still see the most relevant chunks. The CLI surfaces this
clearly so the user knows whether the answer came from a model or from raw
retrieval.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from lorewiki.config import LoreWikiConfig
from lorewiki.db.models import SearchHit
from lorewiki.llm.client import BaseLLMClient, LLMUnavailableError, build_client
from lorewiki.retriever import BM25Retriever, HierarchyRetriever, RRFFusion
from lorewiki.retriever.base import BaseRetriever
from lorewiki.utils.logger import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class Answer:
    """Outcome of one ``ask`` call.

    Attributes:
        question: original user query.
        text: synthesised answer if the LLM ran; otherwise an explanatory
              fallback message.
        hits: ordered list of context chunks used (top-K).
        used_llm: True if the response came from a real LLM call.
        backend: which LLM backend ran (or ``"disabled"`` / ``"fallback"``).
        model: model name used (empty for fallback).
        prompt_tokens / completion_tokens: best-effort accounting.
        degraded_reason: present when ``used_llm`` is False; explains why.
    """

    question: str
    text: str
    hits: list[SearchHit] = field(default_factory=list)
    used_llm: bool = False
    backend: str = ""
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    degraded_reason: str | None = None


DEFAULT_SYSTEM_PROMPT = (
    "You are a precise documentation assistant. Answer the user's question "
    "using ONLY the provided context excerpts. If the answer is not in the "
    "context, say so explicitly. Quote file paths when citing facts. "
    "Respond in the same language as the question."
)


class AnswerGenerator:
    """End-to-end ``ask`` pipeline."""

    def __init__(
        self,
        cfg: LoreWikiConfig,
        *,
        llm_client: BaseLLMClient | None = None,
        retrievers: dict[str, BaseRetriever] | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ):
        self.cfg = cfg
        self.llm = llm_client or build_client(cfg.llm)
        self.retrievers = retrievers or {
            "bm25": BM25Retriever.from_config(cfg),
            "hierarchy": HierarchyRetriever.from_config(cfg),
        }
        self.system_prompt = system_prompt

    def ask(
        self,
        question: str,
        *,
        top_k: int = 5,
        max_context_chars: int = 4000,
    ) -> Answer:
        question = (question or "").strip()
        if not question:
            return Answer(
                question="",
                text="(empty question)",
                degraded_reason="empty_question",
            )

        hits = self._retrieve(question, top_k=top_k)
        if not hits:
            return Answer(
                question=question,
                text="No matching documents found in the wiki. Try another phrasing.",
                hits=[],
                degraded_reason="no_hits",
            )

        if not self.llm.available():
            return self._fallback(question, hits, reason="llm_unavailable")

        prompt = self._build_prompt(question, hits, max_context_chars=max_context_chars)
        try:
            resp = self.llm.generate(
                prompt,
                system=self.system_prompt,
                temperature=0.2,
                max_tokens=512,
                timeout=self.cfg.llm.timeout_seconds,
            )
        except LLMUnavailableError as exc:
            log.warning("LLM call failed, degrading to fallback: {}", exc)
            return self._fallback(question, hits, reason=f"llm_error: {exc}")

        return Answer(
            question=question,
            text=resp.text.strip() or "(empty model response)",
            hits=hits,
            used_llm=True,
            backend=resp.backend,
            model=resp.model,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
        )

    # ---- internal ----

    def _retrieve(self, question: str, *, top_k: int) -> list[SearchHit]:
        """Use the configured retrieval_mode."""
        mode = self.cfg.retrieval_mode
        if mode in {"bm25", "hierarchy"}:
            r = self.retrievers.get(mode)
            if r is None:
                return []
            return list(r.search(question, top_k=top_k))

        # mix (default) and vector (fallback) both use RRF over what we have.
        per_retriever = {
            name: list(r.search(question, top_k=top_k * 2))
            for name, r in self.retrievers.items()
        }
        fuser = RRFFusion(
            k=self.cfg.rrf_k,
            weights={
                "bm25": self.cfg.mix_weights.bm25,
                "hierarchy": self.cfg.mix_weights.hierarchy,
            },
        )
        return list(fuser.fuse(per_retriever, top_k=top_k))

    def _build_prompt(
        self, question: str, hits: Sequence[SearchHit], *, max_context_chars: int
    ) -> str:
        ctx_parts: list[str] = []
        used = 0
        for i, h in enumerate(hits, start=1):
            label = h.heading_path or h.title
            snippet = (h.snippet or "").replace("<<", "").replace(">>", "")
            piece = f"[{i}] {h.doc_path} :: {label}\n{snippet}\n"
            if used + len(piece) > max_context_chars:
                break
            ctx_parts.append(piece)
            used += len(piece)
        context = "\n".join(ctx_parts) or "(no context)"
        return (
            f"# Context excerpts (from the wiki):\n\n{context}\n\n"
            f"# Question\n\n{question}\n\n"
            f"# Answer"
        )

    def _fallback(self, question: str, hits: list[SearchHit], *, reason: str) -> Answer:
        # Compose a readable fallback message that includes the top contexts.
        bullets = []
        for i, h in enumerate(hits[:3], start=1):
            label = h.heading_path or h.title
            snippet = (h.snippet or "").strip().replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:240] + "..."
            bullets.append(f"  {i}. [{h.doc_path}] {label}\n     {snippet}")
        body = "\n".join(bullets) if bullets else "  (no hits)"
        text = (
            "LLM is not available; here are the top matching chunks instead. "
            "Configure `llm.enabled = true` and a backend to get a synthesised answer.\n\n"
            f"{body}"
        )
        return Answer(
            question=question,
            text=text,
            hits=hits,
            used_llm=False,
            backend="fallback",
            degraded_reason=reason,
        )


__all__ = ["DEFAULT_SYSTEM_PROMPT", "Answer", "AnswerGenerator"]
