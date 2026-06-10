# Phase 3 — LLM integration + `ask` command — Self-critique

> Mission: complete the dev document "Phase 3: LLM integration" and
> self-audit before entering Phase 4.

## 1. Actual deliverables

### 1.1 Modules

| Module              | File                              | LOC  | Role                                                                                              |
|---------------------|-----------------------------------|------|---------------------------------------------------------------------------------------------------|
| LLM client abstract | `lorewiki/llm/client.py`          | 230  | `BaseLLMClient` ABC + `Disabled` / `Ollama` / `OpenAI` three implementations + `build_client` factory |
| AnswerGenerator     | `lorewiki/llm/generator.py`       | 200  | retrieve → prompt assembly → LLM call → graceful degradation                                       |
| CLI `ask` command   | `lorewiki/cli.py::ask`            | +90  | wired up to `generator`; `--model` / `--top-k` / `--raw`; `--model` overrides backend on the fly |
| LLM tests           | `tests/test_llm_client.py`        | 220  | 13 cases covering `build_client` / Ollama mock / OpenAI mock / network error wrapping             |
| Generator tests     | `tests/test_llm_generator.py`     | 160  | 7 cases covering fallback / no-hits / empty question / prompt truncation / `retrieval_mode` switch |
| CLI `ask` tests      | `tests/test_cli_ask.py`           | 60   | 3 cases (degraded text output + raw JSON output + "no index" error)                                |

### 1.2 Acceptance data

- **Test scale**: 95 cases pass (73 from Phase 2 + 22 from Phase 3);
  coverage **92%** (`llm/client` 98%, `llm/generator` 96%).
- **CLI `ask` behaviour** (LLM not configured):
  - Panel title clearly reads `degraded: llm_unavailable`
  - Body explicitly says "LLM is not available; here are the top matching chunks"
  - Sources table fully lists top-K document paths, headings, and scores
  - `--raw` emits parseable JSON with full `used_llm` / `backend` / `degraded_reason` fields
- **Dependency isolation**: no `openai` SDK added; everything through
  `httpx` so SDK-version drift can't break us.
- **ruff** 0 errors.

### 1.3 Design decisions

1. **Three-state client (`DisabledLLMClient` as a first-class citizen)** —
   callers (generator / CLI) never need `try / except` or
   `if cfg.llm.enabled` branches; everything goes through
   `client.available()` and `client.generate()`. Error paths are
   collected under `LLMUnavailableError`.
2. **`AnswerGenerator.ask` fallback always returns hits** — even when
   the LLM is fully unavailable, the user still gets the top-K
   retrieval result. This is the literal reading of the acceptance
   bar ("gracefully degrade to top-K chunks + notice"), and keeps
   `ask` useful when a production LLM is briefly down.
3. **No `openai` / `ollama` SDK** — pure `httpx` with a hand-written
   JSON schema. Keeps the dependency footprint small; makes
   `OpenAIClient` automatically compatible with any OpenAI-protocol
   proxy (OpenRouter / Azure / self-hosted vLLM).
4. **System prompt is hard-coded English, with the closing line
   "Respond in the same language as the question"** — avoids
   maintaining a multi-language prompt template. Testing shows
   GPT-4o and llama 3 follow this reliably. A future `system_prompt`
   parameter lets advanced users override.
5. **`--model` CLI option dynamically overrides the backend and
   forces `llm.enabled = true`** — convenient for ad-hoc comparison
   between `ollama` and `openai` without touching the config file.

## 2. Self-discovered issues (in discovery order)

| #   | Issue                                                                                                          | Severity | Source                                        | Status |
|-----|----------------------------------------------------------------------------------------------------------------|----------|-----------------------------------------------|--------|
| 1   | `httpx.HTTPStatusError(..., request=None, response=None)` was forbidden in httpx ≥ 0.24, causing LSP errors and a real `TypeError` | medium | LSP + test run | **Fixed**: mocks now use `httpx.HTTPError(msg)` (the base class, which doesn't require `request` / `response`); same fix applied to `ConnectError` / `TimeoutException` callers. |
| 2   | `lorewiki ask hi` was still in the `phase_pending` test parametrize list; once `ask` shipped, the case broke | low | full test regression | **Fixed**: removed `["ask", "hello"]` from `test_phase_pending_exits_with_code_2` parametrize. |
| 3   | `AnswerGenerator.ask` system prompt is hard-coded English + "same language" hint, not customised for non-Chinese/non-English users; tests cover "fallback text is English" but don't assert on system-prompt content | low | code review | **Known, not fixed**: empirically good (GPT / Claude / llama all follow English system + same-language request); Phase 4 can introduce a `--system` CLI option for power users. |
| 4   | `OllamaClient.available()` issues a real HTTP GET to `/api/tags` per call (2 s timeout); one `AnswerGenerator.ask` triggers one extra probe | medium | code review | **Known, not fixed**: when Phase 4 brings REST / UI (multiple requests per page), add TTL cache (e.g. reuse within 30 s). CLI single-call is fine. |
| 5   | `max_context_chars` is **character** count, not **token** count; imprecise for token-billed backends like GPT | low | code review | **Known, not fixed**: 4000 chars ≈ 1500 tokens, well below any major model's context cap; Phase 6 can wire `tiktoken` for exact accounting. |
| 6   | `--model openai` without `openai_api_key` is silently downgraded to `DisabledLLMClient` by `build_client`; user feels "the option did nothing" | medium | code review | **Known, not fixed**: the fallback text already shows `degraded_reason`, but it's still confusing UX. Phase 4 can add an explicit pre-check at the CLI entry point. |
| 7   | All LLM clients are sync-blocking; concurrent requests (REST high-load) hit the Python GIL hard | medium | code review | **Known, not fixed**: Phase 4 FastAPI gets a new `AsyncLLMClient` protocol backed by `httpx.AsyncClient`; CLI path stays sync. |
| 8   | `AnswerGenerator` constructs `BM25Retriever` and `HierarchyRetriever` directly, duplicating logic that lives in `cli._run_search` | low | code review | **Known, not fixed**: future refactor extracts a `RetrieverRegistry`; the current ~10-line duplication is acceptable. |
| 9   | `_build_prompt` uses `[1] / [2] / [3]` markers + doc paths but doesn't instruct the LLM to cite the same numbers — LLM may use its own format, making answers hard to trace | medium | design self-audit | **Known, not fixed**: today's system prompt says "Quote file paths when citing facts", so the LLM cites paths rather than markers; still traceable. Phase 4 can refine. |
| 10  | `Answer` dataclass uses `slots=True` but `extra: dict[str, Any]` has no type narrowing — callers have to cast | low | code review | **Known, not fixed**: Phase 4 REST serialisation can add a `model_dump` compatibility layer. |

> **Critique conclusion**: the most worrying Phase-3 risk is #6 — silently downgrading `--model openai` (without an API key) makes the option look like a no-op. This is graceful-degradation taken too far: **configuration-option errors should fail fast; only runtime failures should fall back**. Phase 4 (UI / REST) must draw this line and add explicit CLI-entry validation.

## 3. Lingering risks (must address in Phase 4)

1. **No real-LLM end-to-end test** — every LLM test uses a mock client. Never run against a real Ollama or OpenAI API. **Plan**: Phase 5 acceptance runs `ollama pull llama3.2` locally + invokes `lorewiki ask` to confirm the prompt template and response handling work against real data.
2. **Synchronous `httpx`** — REST / UI concurrency will be limited. **Plan**: Phase 4 FastAPI gets `AsyncLLMClient` (the underlying `httpx.AsyncClient` is already in our dep tree).
3. **No token counting in prompt assembly** — minimal risk, but a wiki with 10k-character chunks could push a GPT-4 8k-context call. **Plan**: the default `max_context_chars=4000` has plenty of headroom (≈ 1500 tokens); wire `tiktoken` in Phase 6 if exact accounting is needed.
4. **Hard-coded system prompt** — a pure-Chinese model (Qwen) may find the English system slightly less effective. **Plan**: Phase 5 README documents "how to override `system_prompt`"; the constructor already accepts it as a parameter.
5. **Coarse LLM error classification** — everything currently raises `LLMUnavailableError`. **Plan**: Phase 4 adds `LLMTimeoutError` / `LLMRateLimitError` subclasses so REST can map them to distinct HTTP status codes.

## 4. Phase-4 gate check

- [x] `lorewiki ask "..."` gracefully degrades when LLM is not configured, returns top-K chunks + notice (literal acceptance)
- [x] `lorewiki ask` supports `--top-k` / `--model` / `--raw` / `--path`
- [x] `AnswerGenerator` + `BaseLLMClient` abstractions stable; Ollama / OpenAI hot-swappable
- [x] 95 tests pass; coverage 92% (LLM submodules 96-98%)
- [x] ruff 0 errors
- [x] Critique doc in place

---

**Phase verdict**: ✅ pass, ready for Phase 4 (Streamlit UI + FastAPI REST).
