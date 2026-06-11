"""Tests for LLM clients (Ollama / OpenAI / disabled) using mocked httpx."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from lorewiki.config import LLMConfig
from lorewiki.llm.client import (
    DisabledLLMClient,
    LLMUnavailableError,
    OllamaClient,
    OpenAIClient,
    build_client,
)

# ---- build_client dispatch ----


def test_build_client_disabled_when_llm_off() -> None:
    cfg = LLMConfig(enabled=False)
    c = build_client(cfg)
    assert isinstance(c, DisabledLLMClient)
    assert c.available() is False


def test_build_client_ollama_when_enabled() -> None:
    cfg = LLMConfig(enabled=True, backend="ollama", ollama_model="llama3.2")
    c = build_client(cfg)
    assert isinstance(c, OllamaClient)
    assert c.model == "llama3.2"


def test_build_client_openai_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wipe any env the shell may have leaked in, so the test isolates
    # the cfg-only path.
    for name in ("OPENAI_API_KEY", "MINIMAX_API_KEY", "LOREWIKI_TEST_KEY"):
        monkeypatch.delenv(name, raising=False)

    cfg_no_key = LLMConfig(enabled=True, backend="openai", openai_api_key="")
    c = build_client(cfg_no_key)
    assert isinstance(c, DisabledLLMClient), "missing key must downgrade to disabled"

    cfg_with_key = LLMConfig(
        enabled=True,
        backend="openai",
        openai_api_key="sk-test",
        openai_model="gpt-4o-mini",
    )
    c2 = build_client(cfg_with_key)
    assert isinstance(c2, OpenAIClient)
    assert c2.model == "gpt-4o-mini"
    assert c2.api_key == "sk-test"


def test_build_client_openai_env_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """`openai_api_key = "env:NAME"` reads the key from os.environ["NAME"]."""
    cfg = LLMConfig(
        enabled=True,
        backend="openai",
        openai_api_key="env:LOREWIKI_TEST_KEY",
    )

    # Env unset → disabled with a clear warning.
    monkeypatch.delenv("LOREWIKI_TEST_KEY", raising=False)
    c = build_client(cfg)
    assert isinstance(c, DisabledLLMClient)

    # Env set → OpenAIClient gets the env value.
    monkeypatch.setenv("LOREWIKI_TEST_KEY", "sk-from-env")
    c2 = build_client(cfg)
    assert isinstance(c2, OpenAIClient)
    assert c2.api_key == "sk-from-env"


def test_build_client_openai_env_reference_uses_full_env_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The env var name is whatever the config says — no hard-coded names."""
    cfg = LLMConfig(
        enabled=True,
        backend="openai",
        openai_api_key="env:SOME_PROVIDER_SPECIFIC_KEY",
    )
    # A different env var name should NOT be picked up just because it
    # happens to be a common name like OPENAI_API_KEY.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-be-used")
    monkeypatch.setenv("SOME_PROVIDER_SPECIFIC_KEY", "sk-correct")
    c = build_client(cfg)
    assert isinstance(c, OpenAIClient)
    assert c.api_key == "sk-correct"


def test_build_client_openai_plain_key_does_not_consult_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain (non-`env:`) key is used verbatim — env vars are ignored."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-from-minimax")
    cfg = LLMConfig(enabled=True, backend="openai", openai_api_key="sk-plain")
    c = build_client(cfg)
    assert isinstance(c, OpenAIClient)
    assert c.api_key == "sk-plain"


def test_build_client_unknown_backend_disabled() -> None:
    # Pydantic blocks invalid literal values, but a raw object skips that:
    fake = LLMConfig(enabled=True, backend="ollama")
    fake.backend = "totally-not-a-backend"  # type: ignore[assignment]
    c = build_client(fake)
    assert isinstance(c, DisabledLLMClient)


# ---- DisabledLLMClient ----


def test_disabled_client_generate_raises() -> None:
    c = DisabledLLMClient()
    with pytest.raises(LLMUnavailableError, match="disabled"):
        c.generate("hello")


# ---- OllamaClient (mocked) ----


class _MockResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            # Use a generic httpx.HTTPError; HTTPStatusError requires a real
            # Request object which is awkward to fake in unit tests.
            raise httpx.HTTPError(f"status {self.status_code}")


def test_ollama_generate_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, json: dict[str, Any], timeout: float) -> _MockResponse:
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _MockResponse(
            {
                "response": "the answer is 42",
                "prompt_eval_count": 12,
                "eval_count": 8,
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    c = OllamaClient(url="http://localhost:11434", model="llama3.2", timeout=5.0)
    resp = c.generate("what's the meaning of life?", system="be brief", max_tokens=64)

    assert resp.text == "the answer is 42"
    assert resp.backend == "ollama"
    assert resp.model == "llama3.2"
    assert resp.prompt_tokens == 12
    assert resp.completion_tokens == 8
    assert captured["url"].endswith("/api/generate")
    assert captured["json"]["model"] == "llama3.2"
    assert captured["json"]["system"] == "be brief"
    assert captured["json"]["options"]["num_predict"] == 64
    assert captured["json"]["stream"] is False


def test_ollama_generate_network_error_wraps(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, **_kw: Any) -> _MockResponse:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "post", fake_post)
    c = OllamaClient(url="http://localhost:11434", model="x")
    with pytest.raises(LLMUnavailableError, match="ollama request failed"):
        c.generate("hello")


def test_ollama_available_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_ok(url: str, *, timeout: float) -> _MockResponse:
        assert url.endswith("/api/tags")
        return _MockResponse({"models": []})

    monkeypatch.setattr(httpx, "get", fake_get_ok)
    assert OllamaClient(url="http://localhost:11434", model="x").available() is True

    def fake_get_fail(url: str, **_kw: Any) -> _MockResponse:
        raise httpx.ConnectError("no")

    monkeypatch.setattr(httpx, "get", fake_get_fail)
    assert OllamaClient(url="http://localhost:11434", model="x").available() is False


# ---- OpenAIClient (mocked) ----


def test_openai_requires_api_key() -> None:
    with pytest.raises(ValueError, match="openai_api_key"):
        OpenAIClient(api_key="", model="gpt-4o-mini")


def test_openai_generate_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(
        url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> _MockResponse:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _MockResponse(
            {
                "choices": [{"message": {"role": "assistant", "content": "hi there"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    c = OpenAIClient(api_key="sk-test", model="gpt-4o-mini")
    resp = c.generate("hi", system="be concise")
    assert resp.text == "hi there"
    assert resp.backend == "openai"
    assert resp.prompt_tokens == 5
    assert resp.completion_tokens == 2
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "gpt-4o-mini"
    assert captured["json"]["messages"][0]["role"] == "system"
    assert captured["json"]["messages"][1]["role"] == "user"


def test_openai_empty_choices_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "post", lambda *_a, **_kw: _MockResponse({"choices": [], "usage": {}})
    )
    c = OpenAIClient(api_key="sk-x", model="x")
    with pytest.raises(LLMUnavailableError, match="no choices"):
        c.generate("hi")


def test_openai_network_error_wraps(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*_a: Any, **_kw: Any) -> _MockResponse:
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx, "post", fake_post)
    c = OpenAIClient(api_key="sk-x", model="x")
    with pytest.raises(LLMUnavailableError, match="openai request failed"):
        c.generate("hi")
