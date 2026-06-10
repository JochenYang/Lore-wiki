"""Tests for ``AnswerGenerator`` including the fallback path."""

from __future__ import annotations

from pathlib import Path

import pytest

from lorewiki.config import LoreWikiConfig
from lorewiki.db.models import SearchHit
from lorewiki.indexer import build_index
from lorewiki.llm.client import BaseLLMClient, LLMResponse, LLMUnavailableError
from lorewiki.llm.generator import AnswerGenerator


@pytest.fixture()
def indexed_cfg(tmp_path: Path) -> LoreWikiConfig:
    wiki = tmp_path / "wiki"
    (wiki / "api").mkdir(parents=True)
    (wiki / "api" / "auth.md").write_text(
        "---\ntitle: Auth\nmodule: api\n---\n\n# Auth\n\n"
        "## Login\n\nThe login endpoint signs a JWT pair and returns access "
        "+ refresh tokens. Refresh rotation is required for safety.\n",
        encoding="utf-8",
    )
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    build_index(cfg, rebuild=True)
    return cfg


class _StubClient(BaseLLMClient):
    backend = "stub"

    def __init__(self, *, available: bool, raise_exc: Exception | None = None):
        self._available = available
        self._raise = raise_exc
        self.last_prompt: str | None = None
        self.last_system: str | None = None
        self.model = "stub-7b"

    def available(self) -> bool:
        return self._available

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: float | None = None,
    ) -> LLMResponse:
        self.last_prompt = prompt
        self.last_system = system
        if self._raise is not None:
            raise self._raise
        return LLMResponse(
            text="stub answer based on context",
            backend=self.backend,
            model=self.model,
            prompt_tokens=42,
            completion_tokens=7,
        )


def test_ask_with_real_llm_returns_answer(indexed_cfg: LoreWikiConfig) -> None:
    client = _StubClient(available=True)
    gen = AnswerGenerator(indexed_cfg, llm_client=client)
    ans = gen.ask("how does login work?", top_k=2)
    assert ans.used_llm is True
    assert ans.backend == "stub"
    assert ans.text == "stub answer based on context"
    assert ans.prompt_tokens == 42
    assert ans.completion_tokens == 7
    # Prompt must include retrieved chunks.
    assert client.last_prompt is not None
    assert "auth.md" in client.last_prompt
    assert client.last_system is not None


def test_ask_with_disabled_llm_falls_back(indexed_cfg: LoreWikiConfig) -> None:
    client = _StubClient(available=False)
    gen = AnswerGenerator(indexed_cfg, llm_client=client)
    ans = gen.ask("how does login work?", top_k=3)
    assert ans.used_llm is False
    assert ans.backend == "fallback"
    assert ans.degraded_reason == "llm_unavailable"
    assert ans.hits, "fallback must still surface the matched chunks"
    assert "LLM is not available" in ans.text
    # Top docs appear in the textual fallback.
    assert "auth.md" in ans.text


def test_ask_with_llm_error_falls_back(indexed_cfg: LoreWikiConfig) -> None:
    client = _StubClient(available=True, raise_exc=LLMUnavailableError("boom"))
    gen = AnswerGenerator(indexed_cfg, llm_client=client)
    ans = gen.ask("how does login work?", top_k=2)
    assert ans.used_llm is False
    assert ans.backend == "fallback"
    assert ans.degraded_reason is not None
    assert "llm_error" in ans.degraded_reason


def test_ask_with_empty_question_returns_explanatory_answer(
    indexed_cfg: LoreWikiConfig,
) -> None:
    gen = AnswerGenerator(indexed_cfg, llm_client=_StubClient(available=True))
    ans = gen.ask("   ", top_k=3)
    assert ans.used_llm is False
    assert ans.degraded_reason == "empty_question"
    assert ans.hits == []


def test_ask_with_no_hits_returns_explanatory_answer(
    indexed_cfg: LoreWikiConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    gen = AnswerGenerator(indexed_cfg, llm_client=_StubClient(available=True))
    # Force retrieval to return empty without breaking the index.
    monkeypatch.setattr(gen, "_retrieve", lambda *_a, **_kw: [])
    ans = gen.ask("totally unrelated query xyz", top_k=3)
    assert ans.used_llm is False
    assert ans.degraded_reason == "no_hits"
    assert "No matching documents" in ans.text


def test_prompt_truncates_to_max_context(indexed_cfg: LoreWikiConfig) -> None:
    """Even if many hits arrive, the prompt is bounded by ``max_context_chars``."""
    client = _StubClient(available=True)
    gen = AnswerGenerator(indexed_cfg, llm_client=client)
    # 200-char ceiling is enough for ~1 context block; we still get an answer.
    ans = gen.ask("login", top_k=5, max_context_chars=200)
    assert ans.used_llm is True
    assert client.last_prompt is not None
    # Body length must respect the ceiling (roughly — header/footer add some).
    assert len(client.last_prompt) < 800


def test_retrieve_uses_configured_mode(indexed_cfg: LoreWikiConfig) -> None:
    """``retrieval_mode = "bm25"`` must skip RRF entirely."""
    indexed_cfg_bm25 = indexed_cfg.model_copy(deep=True)
    indexed_cfg_bm25.retrieval_mode = "bm25"
    gen = AnswerGenerator(indexed_cfg_bm25, llm_client=_StubClient(available=True))
    ans = gen.ask("login", top_k=2)
    # Hits should carry a bm25-flavoured retriever label, not "mix".
    assert ans.hits
    assert all(h.retriever.startswith("bm25") for h in ans.hits)


def test_answer_hits_are_sorted_search_hits(indexed_cfg: LoreWikiConfig) -> None:
    gen = AnswerGenerator(indexed_cfg, llm_client=_StubClient(available=True))
    ans = gen.ask("login", top_k=3)
    assert all(isinstance(h, SearchHit) for h in ans.hits)
    # Top-1 score must be >= subsequent ones.
    scores = [h.score for h in ans.hits]
    assert scores == sorted(scores, reverse=True)
