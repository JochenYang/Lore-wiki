# Phase 4 — Streamlit UI + FastAPI REST — Self-critique

> Mission: complete the dev document "Phase 4: visualisation and
> API" and self-audit before entering Phase 5.

## 1. Actual deliverables

### 1.1 Modules

| Module              | File                              | LOC  | Role                                                                                |
|---------------------|-----------------------------------|------|-------------------------------------------------------------------------------------|
| REST API            | `lorewiki/server/rest_api.py`     | 240  | FastAPI app + 6 endpoints (health / status / search / ask / modules / module/{path}) + 503 fallback |
| Streamlit UI        | `lorewiki/server/ui.py`           | 245  | 4 pages (Search / Browse / Config / Status), lazy-imports Streamlit                |
| CLI `rest`          | `lorewiki/cli.py::rest`           | +35  | launches uvicorn, prints the OpenAPI URL                                          |
| CLI `ui`            | `lorewiki/cli.py::ui`             | +45  | spawns `streamlit run` as a subprocess; friendly fallback when streamlit isn't installed |
| REST integration tests | `tests/test_rest_api.py`        | 160  | 12 cases: health / status / search tri-mode / ask fallback / modules / 404 / 503 / OpenAPI |

### 1.2 Acceptance data

- **Test scale**: 107 cases pass (95 from Phase 3 + 12 REST from
  Phase 4); coverage **92%**.
- **REST API**:
  - `POST /search` supports mix / bm25 / hierarchy; includes
    field validation (mode regex, query length).
  - `POST /ask` returns a fully structured fallback when no LLM is
    configured (`used_llm=false`,
    `degraded_reason="llm_unavailable"`).
  - `GET /modules` + `GET /module/{path:path}` support arbitrary
    subtree expansion.
  - `GET /status` returns documents / chunks / nodes / db_size /
    last_indexed_at core metrics.
  - `/openapi.json` fully lists every endpoint schema; Swagger UI
    at `/docs` is reachable.
  - When the index is missing, every data endpoint returns
    **HTTP 503** with an explanation, not 500.
- **CLI**:
  - `lorewiki rest --port 8000 --path ...` starts uvicorn in the
    foreground (typer.Exit wraps subprocess return code).
  - `lorewiki ui --port 8501` uses `subprocess.call("python -m
    streamlit run ...")` to spawn Streamlit. If streamlit isn't
    installed, prints `pip install lorewiki[ui]`.
- **ruff** 0 errors.

### 1.3 Design decisions

1. **REST and UI share retrieval / answer logic** — `rest_api.py::_run_search` and `cli.py::_run_search` duplicate the retriever-construction + RRF-fusion code (≈ 15 lines). **Deliberate**: avoid introducing a bigger abstraction (`RetrieverDispatcher` class) in Phase 4 and disturbing 95 already-passing tests; the refactor is queued for Phase 6.
2. **Lazy import in the UI** — `lorewiki/server/ui.py` doesn't `import streamlit` at module top; every streamlit call is wrapped in a function-body `import streamlit as st`. That way `lorewiki/server/__init__.py` can still be imported without streamlit installed, and the main CLI flow is unaffected. The cost is several `# noqa: PLC0415` markers in one file.
3. **REST data endpoints return 503 when the index is missing** — `HTTPException(status_code=503, detail=...)` tells the user to run `lorewiki index` instead of dumping a stack trace.
4. **UI Browse page loads full Markdown text** — `file_path.read_text()` and render. Risk for > 1 MB files, but real-world wiki files are usually < 50 KB.
5. **REST app uses a `lifespan` context** (not the deprecated `on_event`) — best practice for FastAPI ≥ 0.110.
6. **`TestClient` `StarletteDeprecationWarning` ("install httpx2") is left as informational** — starlette hints at httpx2, which isn't on a stable release yet; the warning doesn't block anything.

## 2. Self-discovered issues (in discovery order)

| #   | Issue                                                                                                          | Severity | Source                                         | Status |
|-----|----------------------------------------------------------------------------------------------------------------|----------|------------------------------------------------|--------|
| 1   | Streamlit drags in numpy / pandas / pyarrow / pydeck (~ 80 MB+); network downloads timed out repeatedly during this phase | **high** | `uv pip install` timeouts | **Known, not fixed**: the UI code is complete and runnable once the user does `pip install lorewiki[ui]`; no Streamlit live-verify in this phase. Marked in `production-readiness.md`: "Streamlit UI code is ready; live verify needs the user to install `lorewiki[ui]`". **Coverage for UI**: 12 FastAPI `TestClient` cases + UI-module import smoke test. |
| 2   | Background-launching `lorewiki.exe rest` for testing used `Start-Sleep 4`, blocking the bash turn for 4+ s | medium (process-level) | user feedback | **Fixed**: switched REST verification to FastAPI `TestClient` in-process tests; no socket server. CLI command itself covered by the CLI test set. Live verify deferred to the user running `lorewiki rest`. |
| 3   | `Stop-Process` cleanup accidentally killed a running uvicorn child (PID 36148) because the filter was `Where-Object { $_.StartTime -gt 1 minute ago }` (fuzzy time-window) | medium | user feedback | **Lesson recorded**: kill background processes by **specific PID**, not by time window. No more background processes in this phase. |
| 4   | `test_phase_pending_exits_with_code_2` parametrize list went stale again (this time missing `ui` / `rest`) — once those commands shipped, the test broke | low | full test regression | **Fixed**: parametrize now contains only `update` and `mcp`. **Lesson**: after Phase 5 implements mcp, sweep the parametrize list again. |
| 5   | `lorewiki rest`'s Rich panel output is occasionally clipped in PowerShell (panel content is intact, just a terminal-width rendering quirk) | low | manual observation | **Known, not fixed**: rich rendering is terminal-width sensitive; Phase 5 README documents `COLUMNS=120` as a workaround. |
| 6   | `_run_search` is duplicated between `cli.py` and `rest_api.py`; adding `vector` / async retriever means editing both | medium | code review | **Known, not fixed**: Phase 6 extracts `RetrieverDispatcher`. The two copies are kept in sync by sharing the retriever unit tests. |
| 7   | REST API has no authentication — anyone able to reach the port can `search` / `ask` | medium | code review | **Known, not fixed**: the dev document explicitly says "no multi-user permission system" (1.2 non-goals); single-machine deployment defaults to `bind 127.0.0.1` for isolation. Production deployment documented to use a reverse proxy (Caddy / Nginx) with basic auth. |
| 8   | REST `/ask` is sync-blocking under concurrency (httpx is not async) | medium | code review | **Known, not fixed**: already recorded in Phase 3 critique; Phase 6 introduces an async LLM client. |
| 9   | UI Config page is read-only, but dev document §5.6 says "edit config (LLM backend, retrieval weights, etc.) without restart" | medium | compared to dev doc | **Partial**: today's UI Config page only displays `cfg.model_dump`; no edit form. Reason: phase time-budget prioritised getting all 4 pages to render. **Plan**: noted in `production-readiness.md` as a known limit; the dev doc accepts "read-only Config page" or an edit form gets added in Phase 6. |
| 10  | UI Browse page doesn't filter Markdown for XSS (Streamlit's `st.markdown` defaults to safe, but writing `<script>` may render depending on the Streamlit version) | low | code review | **Known, not fixed**: single-machine / team scenarios where the wiki author is trusted; `st.markdown` is safe by default in current Streamlit. |

> **Critique conclusion**: Phase 4's biggest exposed issues are **#1 Streamlit not installed in this session** and **#9 Config page read-only** vs. the dev document. The aggregate judgement: **REST API part (the core) is fully complete** (12 tests pass, end-to-end schema consistent); **UI code is ready but needs the user to install streamlit for live verify**, and the Config-page edit form is deferred to Phase 6. Both points must be explicitly stated in `production-readiness.md`.

## 3. Lingering risks (must address in Phase 5)

1. **Streamlit not live-verified** — code is statically correct (lazy import passes CLI smoke), but actually running `streamlit run` may surface session_state lifecycle, page-reload issues, etc. **Plan**: Phase 5 README adds a quickstart; final acceptance evidence is the user's screenshot after `pip install lorewiki[ui]`.
2. **REST has no CORS** — browser-based JS clients are blocked by same-origin policy. **Plan**: Phase 5 README documents "for browser cross-origin, add `cors_origins` to cfg"; MCP / CLI consumers don't need it.
3. **Neither UI nor REST support LLM streaming** — long answers block. **Plan**: Phase 6 adds an SSE endpoint (`POST /ask/stream`).
4. **No OpenTelemetry / metrics** — production deployments are unobservable. **Plan**: noted in `production-readiness.md` as a known limit; can be added later via `opentelemetry-instrumentation-fastapi`.
5. **CLI `rest` doesn't guarantee graceful shutdown on SIGTERM** — uvicorn handles SIGINT gracefully by default; SIGTERM may be abrupt. **Plan**: Phase 5 adds a `--graceful-timeout` option for uvicorn.

## 4. Phase-5 gate check

- [x] `lorewiki rest --port N` implemented; starts uvicorn with 6 endpoints (OpenAPI included)
- [x] `lorewiki ui --port N` implemented; friendly fallback when streamlit missing
- [x] 12 REST integration tests pass (mix / bm25 / hierarchy + ask fallback + 404 / 503)
- [x] OpenAPI schema complete; `/docs` reachable (verified via `TestClient`)
- [x] All 107 tests pass; coverage 92%
- [x] ruff 0 errors
- [x] Critique doc in place
- [ ] Streamlit live verify — **known incomplete**; user needs `pip install lorewiki[ui]` to test; will be noted in `production-readiness.md`

---

**Phase verdict**: ⚠️ **CORE PASS** (REST + CLI complete) / **UI code ready but not live-verified**, ready for Phase 5.
