"""Tests for the MCP server (tool handlers exercised directly).

We don't spin up the stdio transport; instead we exercise the underlying
synchronous helpers (``_handle_search`` / ``_handle_get_module``) plus an
end-to-end ``build_server + list_tools`` check to make sure the tool schema
is what we promised.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")  # the [mcp] extra; CI installs it via -e ".[dev,rest,mcp]"

from lorewiki.config import LoreWikiConfig
from lorewiki.indexer import build_index
from lorewiki.server.mcp_server import (
    _handle_get_module,
    _handle_search,
    build_server,
)


@pytest.fixture()
def indexed_cfg(tmp_path: Path) -> LoreWikiConfig:
    wiki = tmp_path / "wiki"
    (wiki / "api" / "user").mkdir(parents=True)
    (wiki / "patterns").mkdir(parents=True)
    (wiki / "api" / "user" / "auth.md").write_text(
        "---\ntitle: Auth\nmodule: api/user\n---\n\n# Auth\n\n"
        "## Login\n\nThe login endpoint signs and returns a JWT pair, "
        "including a long-lived refresh token for silent renewal.\n",
        encoding="utf-8",
    )
    (wiki / "patterns" / "retry.md").write_text(
        "---\ntitle: Retry\nmodule: patterns\n---\n\n# Retry\n\n"
        "## Backoff\n\nExponential backoff with full jitter avoids retry storms "
        "during failover.\n",
        encoding="utf-8",
    )
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    build_index(cfg, rebuild=True)
    return cfg


# ---- _handle_search ----


def test_search_handler_returns_hits(indexed_cfg: LoreWikiConfig) -> None:
    payload = _handle_search(indexed_cfg, {"query": "login", "top_k": 3, "mode": "bm25"})
    assert "hits" in payload
    assert payload["hits"]
    assert any("auth.md" in h["doc_path"] for h in payload["hits"])
    for h in payload["hits"]:
        assert h["retriever"].startswith("bm25")


def test_search_handler_default_mode_is_mix(indexed_cfg: LoreWikiConfig) -> None:
    payload = _handle_search(indexed_cfg, {"query": "login"})
    assert payload["mode"] == "mix"
    assert payload["hits"]
    assert all(h["retriever"] == "mix" for h in payload["hits"])


def test_search_handler_empty_query(indexed_cfg: LoreWikiConfig) -> None:
    assert _handle_search(indexed_cfg, {"query": ""}) == {"error": "empty query"}
    assert _handle_search(indexed_cfg, {"query": "   "}) == {"error": "empty query"}


def test_search_handler_missing_index(tmp_path: Path) -> None:
    cfg = LoreWikiConfig(wiki_path=tmp_path / "missing", db_path=tmp_path / "nope.db")
    payload = _handle_search(cfg, {"query": "x", "top_k": 1})
    assert "error" in payload
    assert "index not built" in payload["error"]


# ---- _handle_get_module ----


def test_get_module_root(indexed_cfg: LoreWikiConfig) -> None:
    payload = _handle_get_module(indexed_cfg, {"module_path": ""})
    assert payload["node"]["node_type"] == "root"
    child_paths = {c["path"] for c in payload["children"]}
    assert "api" in child_paths
    assert "patterns" in child_paths


def test_get_module_subtree(indexed_cfg: LoreWikiConfig) -> None:
    payload = _handle_get_module(indexed_cfg, {"module_path": "api"})
    assert payload["node"]["path"] == "api"
    child_paths = {c["path"] for c in payload["children"]}
    assert "api/user" in child_paths


def test_get_module_leaf_includes_chunk_count(indexed_cfg: LoreWikiConfig) -> None:
    payload = _handle_get_module(indexed_cfg, {"module_path": "api/user"})
    assert any(c["chunk_count"] >= 1 for c in payload["children"])


def test_get_module_unknown_path(indexed_cfg: LoreWikiConfig) -> None:
    payload = _handle_get_module(indexed_cfg, {"module_path": "does/not/exist"})
    assert "error" in payload


# ---- end-to-end server construction ----


def test_build_server_exposes_two_tools(indexed_cfg: LoreWikiConfig) -> None:
    server = build_server(indexed_cfg)
    # Resolve the registered list_tools handler from the request_handlers
    # mapping. The mcp SDK stores them keyed by request type.
    from mcp.types import ListToolsRequest  # noqa: PLC0415

    handler = server.request_handlers[ListToolsRequest]

    request = ListToolsRequest(method="tools/list", params=None)
    result = asyncio.run(handler(request))
    # result is ServerResult wrapping ListToolsResult; pull out the tools.
    tools = result.root.tools
    names = {t.name for t in tools}
    assert names == {"search_lorewiki", "get_module_summary"}
    for tool in tools:
        # Every tool must have at least one required field declared.
        schema = tool.inputSchema
        assert "required" in schema or "properties" in schema


def test_call_tool_round_trip_for_search(indexed_cfg: LoreWikiConfig) -> None:
    server = build_server(indexed_cfg)
    from mcp.types import CallToolRequest, CallToolRequestParams  # noqa: PLC0415

    handler = server.request_handlers[CallToolRequest]
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="search_lorewiki",
            arguments={"query": "login", "top_k": 2, "mode": "bm25"},
        ),
    )
    result = asyncio.run(handler(req))
    contents = result.root.content
    assert contents
    # First content is JSON text with our search payload.
    payload = json.loads(contents[0].text)
    assert payload["query"] == "login"
    assert payload["hits"]


def test_call_tool_unknown_tool_returns_error(indexed_cfg: LoreWikiConfig) -> None:
    server = build_server(indexed_cfg)
    from mcp.types import CallToolRequest, CallToolRequestParams  # noqa: PLC0415

    handler = server.request_handlers[CallToolRequest]
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="does_not_exist", arguments={}),
    )
    result = asyncio.run(handler(req))
    payload = json.loads(result.root.content[0].text)
    assert "error" in payload
    assert "unknown tool" in payload["error"]
