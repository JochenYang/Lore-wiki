"""LLM client abstraction with Ollama / OpenAI backends and graceful fallback.

The public surface is intentionally minimal::

    client = build_client(cfg.llm)         # picks the right backend
    if not client.available():             # offline / mis-configured?
        ...                                # caller decides whether to skip
    answer = client.generate(prompt, ...)  # blocking text completion

Both real backends speak HTTP only (no SDK dependency); :class:`DisabledLLMClient`
returns a sentinel so the caller can degrade gracefully without try/except
around every LLM call.

Error policy
------------
Network errors / non-200 responses are wrapped in :class:`LLMUnavailableError`.
Callers in the application layer treat that as "LLM degraded, return raw
chunks instead of a synthesised answer" — see ``lorewiki/llm/generator.py``.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from lorewiki.config import LLMConfig
from lorewiki.utils.logger import get_logger

log = get_logger(__name__)


class LLMUnavailableError(RuntimeError):
    """Raised when the configured LLM backend cannot satisfy a request."""


@dataclass(slots=True)
class LLMResponse:
    text: str
    backend: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class BaseLLMClient(ABC):
    """Common interface every LLM backend must implement."""

    backend: str = "base"
    model: str = ""

    def available(self) -> bool:
        """Quick liveness probe (defaults to True for offline backends)."""
        return True

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Synchronous one-shot completion. Raises ``LLMUnavailableError`` on
        transport / HTTP failures."""


class DisabledLLMClient(BaseLLMClient):
    """Sentinel client used when ``llm.enabled = false`` or backend missing."""

    backend = "disabled"
    model = ""

    def available(self) -> bool:
        return False

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: float | None = None,
    ) -> LLMResponse:
        msg = (
            "LLM is disabled in configuration. "
            "Run `lorewiki config set llm.enabled true` and configure a backend."
        )
        raise LLMUnavailableError(msg)


class OllamaClient(BaseLLMClient):
    """Talk to a local Ollama server via its native HTTP API.

    We use the non-streaming ``/api/generate`` endpoint. Streaming is left to
    a later phase since the CLI ``ask`` command is line-buffered anyway.
    """

    backend = "ollama"

    def __init__(self, url: str, model: str, *, timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        try:
            r = httpx.get(f"{self.url}/api/tags", timeout=2.0)
            r.raise_for_status()
            return True
        except (httpx.HTTPError, OSError):
            return False

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: float | None = None,
    ) -> LLMResponse:
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system
        try:
            r = httpx.post(
                f"{self.url}/api/generate",
                json=payload,
                timeout=timeout or self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, OSError, json.JSONDecodeError) as exc:
            msg = f"ollama request failed: {exc}"
            raise LLMUnavailableError(msg) from exc
        text = data.get("response", "")
        return LLMResponse(
            text=text,
            backend=self.backend,
            model=self.model,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )


class OpenAIClient(BaseLLMClient):
    """OpenAI-compatible Chat Completions client (works with OpenAI, Azure
    OpenAI-compatible proxies, OpenRouter, etc. — anything that speaks the
    standard ``/v1/chat/completions`` schema)."""

    backend = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
    ):
        if not api_key:
            msg = "openai backend requires llm.openai_api_key"
            raise ValueError(msg)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        # No cheap ping for OpenAI; assume available if we have a key.
        return bool(self.api_key)

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: float | None = None,
    ) -> LLMResponse:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=timeout or self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, OSError, json.JSONDecodeError) as exc:
            msg = f"openai request failed: {exc}"
            raise LLMUnavailableError(msg) from exc

        choices = data.get("choices") or []
        if not choices:
            msg = f"openai returned no choices: {data}"
            raise LLMUnavailableError(msg)
        text = choices[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        return LLMResponse(
            text=text,
            backend=self.backend,
            model=self.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


def build_client(llm_cfg: LLMConfig) -> BaseLLMClient:
    """Return the right :class:`BaseLLMClient` for the current configuration.

    If LLM is disabled, mis-configured (e.g. openai without api_key), or the
    backend value is unknown, we fall back to :class:`DisabledLLMClient` so
    the caller can still decide whether to degrade silently or warn.
    """
    if not llm_cfg.enabled:
        return DisabledLLMClient()
    if llm_cfg.backend == "ollama":
        return OllamaClient(
            url=llm_cfg.ollama_url,
            model=llm_cfg.ollama_model,
            timeout=llm_cfg.timeout_seconds,
        )
    if llm_cfg.backend == "openai":
        if not llm_cfg.openai_api_key:
            log.warning("openai backend selected but openai_api_key is empty; disabling")
            return DisabledLLMClient()
        return OpenAIClient(
            api_key=llm_cfg.openai_api_key,
            model=llm_cfg.openai_model,
            base_url=llm_cfg.openai_base_url or "https://api.openai.com/v1",
            timeout=llm_cfg.timeout_seconds,
        )
    log.warning("unknown llm backend {}; disabling", llm_cfg.backend)
    return DisabledLLMClient()


__all__ = [
    "BaseLLMClient",
    "DisabledLLMClient",
    "LLMResponse",
    "LLMUnavailableError",
    "OllamaClient",
    "OpenAIClient",
    "build_client",
]
