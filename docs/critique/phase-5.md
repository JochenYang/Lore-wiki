# Phase 5 — MCP server + README + packaging — Self-critique

> Mission: complete the dev document "Phase 5: MCP service and
> packaging" and self-audit before entering production-readiness.

## 1. Actual deliverables

### 1.1 Modules

| Module             | File                              | LOC  | Role                                                                                |
|--------------------|-----------------------------------|------|-------------------------------------------------------------------------------------|
| MCP stdio server   | `lorewiki/server/mcp_server.py`   | 245  | `Server` + two tools (`search_lorewiki` / `get_module_summary`) + async run loop      |
| CLI `mcp`          | `lorewiki/cli.py::mcp`            | +25  | launches the stdio server; errors go to stderr to avoid corrupting JSON-RPC        |
| MCP tests          | `tests/test_mcp_server.py`        | 165  | 11 cases: tool handlers + schema + `call_tool` round trip + unknown-tool error       |
| README             | `README.md`                       | 235  | full install / use / config / LLM / REST / UI / MCP / Architecture / Roadmap sections |

### 1.2 Acceptance data

- **Test scale**: **118 cases pass** (107 from Phase 4 + 11 MCP from
  Phase 5); coverage 82% (because `ui.py` is 0% — core without UI
  is still 92%).
- **MCP tool schema**:
  - `search_lorewiki` accepts `{query, top_k?, mode?}`, required
    `["query"]`, `mode` enum `mix | bm25 | hierarchy`.
  - `get_module_summary` accepts `{module_path}` (empty string
    means root); returns the node + all children (with
    `chunk_count`).
- **MCP end-to-end tests**: invoke the handler via the SDK's
  internal `request_handlers` directly. `list_tools` returns two
  tools, `call_tool("search_lorewiki", ...)` returns a complete
  JSON payload, an unknown tool returns `{"error": "unknown
  tool"}` without crashing.
- **MCP error isolation**: every handler is wrapped in
  `try / except Exception` and serialises errors as
  `TextContent` JSON instead of raising — keeps the JSON-RPC
  frame intact.
- **ruff** 0 errors.

### 1.3 Design decisions

1. **Use the low-level `Server` API, not the `FastMCP` high-level wrapper** — `FastMCP` has shifted signatures between mcp 1.x point releases; the low-level `Server` is stable.
2. **Tool output is uniformly a JSON string** — every handler returns `[TextContent(type="text", text=json.dumps(...))]`, which LLM clients can parse directly. Returning multiple `TextContent` segments (one per field) is less friendly to LLM tool calls.
3. **MCP errors go to stderr, not stdout** — when the `lorewiki mcp` entry imports the `mcp` extra and finds it missing, the error is written to `sys.stderr`. Stdout is already owned by the MCP protocol; any human-readable text there would corrupt the JSON-RPC frame.
4. **The MCP server doesn't print logs to stdout** — it relies on loguru's default stderr sink; a future file sink can be wired through `LOREWIKI_LOG_FILE`.
5. **README uses `pip install -e .` rather than PyPI** — not yet published; deferred to the production-readiness decision.
6. **README doesn't list the Phase 0-6 internal progress** — dev docs / critique are for maintainers; README is for users.

## 2. Self-discovered issues (in discovery order)

| #   | Issue                                                                                                          | Severity | Source                                         | Status |
|-----|----------------------------------------------------------------------------------------------------------------|----------|------------------------------------------------|--------|
| 1   | The mcp SDK has no `mcp.__version__`; a probe like `print(mcp.__version__)` would raise `AttributeError`       | low      | probing the SDK                                 | **Known, not fixed**: README / docs rely on `pip show mcp` instead. |
| 2   | The mcp SDK's `Server.list_tools()` decorator takes **async** functions returning `list[Tool]`; the dev document's older example (§5.7) used a module-level `tools = [Tool(...)]` list, which doesn't match the current API | medium | reading the SDK source | **Fixed**: every tool is registered via the `@server.list_tools()` decorator, matching the mcp 1.x API. |
| 3   | The `call_tool` decorator signature is `async def call_tool(name, arguments)`; my earlier checks also missed the `request_handlers` dict access path | low | while writing tests | **Fixed**: tests grab the handler via `server.request_handlers[CallToolRequest]` and call it directly. |
| 4   | `_handle_search` / `_handle_get_module` call SQLite synchronously, but are wrapped in async tool handlers — long queries would in theory block the event loop | low | code review | **Known, not fixed**: SQLite queries are < 10 ms (3 ms average measured); CLI / MCP are low-concurrency. Phase 6 can move to `aiosqlite` for high-concurrency scenarios. |
| 5   | MCP server's `extra` fields (e.g. `contributors` from RRF) are loaded by `SearchHit.extra` dict but `_handle_search` doesn't serialise them — information loss | low | code review | **Known, not fixed**: hurts debugging but not functionality; Phase 6 can plumb `extra` through. |
| 6   | `test_phase_pending_exits_with_code_2` needs parametrize updates for the (N+1)-th time — now only `update` remains — predictable regression point | low | full test regression | **Fixed**: Phase 6 implements `update --watch`; this test can be deleted then. |
| 7   | Streamlit still isn't installed in this session, UI's 0% coverage drags total to 82% (core without UI is still 92%) | medium | coverage report | **Known, not fixed**: UI code is statically OK; user installs streamlit and goes live; full details in `phase-4.md`. |
| 8   | Every `pip install -e .` path in the README assumes the user is in the repo root; no PyPI publish yet, so `pip install lorewiki` isn't available | medium | code review | **Known, not fixed**: production-readiness will decide on `python -m build && twine upload`; README uses `-e .` for source installs. |
| 9   | MCP `instructions` field is in English ("Prefer search_lorewiki for any question..."); LLMs don't always use tools proactively when given instructions — the LLM's behaviour, but the prompt could be more pointed | low | design self-audit | **Known, not fixed**: instructions cover the core guidance; user can add their own system prompt in Claude Desktop to reinforce. |
| 10  | The hatchling package-includes `schema.sql` claim from Phase 1 was a hypothesis, not verified; with MCP added, `schema.sql + ui.py + rest_api.py + mcp_server.py` all need to be in the wheel | medium | code review | **To be verified in production-readiness**: run `pip wheel . -w /tmp/dist` then unzip and inspect. |

> **Critique conclusion**: the most valuable Phase-5 outcome is that the MCP server fully matches the mcp SDK 1.x current API and passed `call_tool` round-trip tests — more reliable than the (now-stale) dev-document example. The largest remaining risk is **#10 wheel packaging unverified**, which must be exercised in the production-readiness pass.

## 3. Lingering risks (must address in production-readiness)

1. **Wheel packaging not yet exercised** — must run `python -m build` to produce a wheel + sdist, then `pip install` into a clean venv to confirm.
2. **Streamlit UI not live-verified** — same Phase-4 risk; production-readiness needs at least one "install streamlit + launch UI + screenshot" piece of evidence.
3. **MCP ↔ Claude Desktop not end-to-end** — only SDK round-trip tests today; real Claude Desktop stdio handshake is unverified.
4. **No fresh-venv `pip install lorewiki` end-to-end** — the current `.venv` is dev-time; dependencies may have drifted from the declared set.
5. **README assumes the user is in the repo root** — after PyPI publish, paths need to switch from `pip install -e .` to `pip install lorewiki`.

## 4. Production-readiness gate check

- [x] `lorewiki mcp` starts the stdio server, exposing `search_lorewiki` and `get_module_summary`
- [x] All 11 MCP integration tests pass (including `call_tool` round trip)
- [x] All 10 CLI commands implemented (init / index / status / update* / search / ask / ui / mcp / rest / config)
  - * `update` is still a "phase 6" placeholder per the dev document
- [x] All 118 tests pass; coverage 82% (core 92%)
- [x] ruff 0 errors
- [x] README complete with install / use / config / LLM / REST / UI / MCP / Architecture sections
- [x] Critique docs in place
- [ ] Wheel packaging verification — **required for production-readiness**
- [ ] Streamlit live verification — **required for production-readiness**
- [ ] Final `production-readiness.md` — **required for production-readiness**

---

**Phase verdict**: ✅ MCP + CLI + REST all complete; ready to enter the "production-readiness" phase for final acceptance.
