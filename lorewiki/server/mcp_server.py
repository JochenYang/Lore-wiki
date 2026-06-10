"""MCP stdio server for LoreWiki.

Exposes two tools usable by Claude Desktop, Cursor, and any other MCP client:

* ``search_lorewiki`` — keyword + hierarchy search returning ranked chunks.
* ``get_module_summary`` — list the immediate children of a hierarchy node.

The transport is stdio (line-delimited JSON-RPC), wired up via the MCP
Python SDK. The server runs an async loop but our retrievers / generator
are synchronous; that's fine because each request is a single short SQLite
read, well below the latency where blocking the event loop would matter.

CLI entrypoint: ``lorewiki mcp``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from lorewiki.config import LoreWikiConfig, load_config
from lorewiki.db import open_db
from lorewiki.retriever import BM25Retriever, HierarchyRetriever, RRFFusion
from lorewiki.utils.logger import get_logger

log = get_logger(__name__)

SEARCH_TOOL_DESC = (
    "Search the LoreWiki knowledge base and return relevant document chunks "
    "with their file paths, headings, and short snippets. Use this to ground "
    "answers in team-curated documentation before answering API or pattern "
    "questions."
)

MODULE_TOOL_DESC = (
    "Inspect a module node in the wiki hierarchy. Returns the node's title, "
    "summary, level, and its immediate child nodes (sub-modules + leaf "
    "documents). Useful for navigation when search alone is too broad."
)


def build_server(cfg: LoreWikiConfig | None = None) -> Server:
    """Construct an :class:`mcp.Server` wired to the given configuration.

    Tool handlers are registered as decorators on the returned server; the
    actual event loop is started by :func:`run` (or :func:`run_async`).
    """
    config = cfg or load_config()
    server: Server = Server(
        name="lorewiki",
        version="0.1.0",
        instructions=(
            "LoreWiki is a local, FTS5-backed documentation index. "
            "Prefer `search_lorewiki` for any question that might be answered "
            "by team docs (API contracts, design patterns, troubleshooting). "
            "Quote file paths in your answers."
        ),
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search_lorewiki",
                description=SEARCH_TOOL_DESC,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural-language or keyword query.",
                            "minLength": 1,
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Maximum number of chunks to return (1-20).",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 5,
                        },
                        "mode": {
                            "type": "string",
                            "description": "Retrieval strategy.",
                            "enum": ["mix", "bm25", "hierarchy"],
                            "default": "mix",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_module_summary",
                description=MODULE_TOOL_DESC,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "module_path": {
                            "type": "string",
                            "description": (
                                "Hierarchy path, e.g. 'api/user'. "
                                "Empty string means root."
                            ),
                            "default": "",
                        },
                    },
                    "required": ["module_path"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "search_lorewiki":
                payload = _handle_search(config, arguments)
            elif name == "get_module_summary":
                payload = _handle_get_module(config, arguments)
            else:
                payload = {"error": f"unknown tool: {name}"}
        except Exception as exc:
            log.exception("mcp tool {} failed", name)
            payload = {"error": str(exc), "tool": name}
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server


# ---- tool handlers (sync, called from async wrappers above) ----


def _handle_search(cfg: LoreWikiConfig, args: dict[str, Any]) -> dict[str, Any]:
    if cfg.db_path is None or not cfg.db_path.exists():
        return {
            "error": "index not built",
            "hint": f"run `lorewiki index --path {cfg.wiki_path}` first",
        }
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "empty query"}
    top_k = int(args.get("top_k", 5))
    mode = str(args.get("mode", "mix"))

    retrievers = {
        "bm25": BM25Retriever.from_config(cfg),
        "hierarchy": HierarchyRetriever.from_config(cfg),
    }
    if mode in {"bm25", "hierarchy"}:
        hits = list(retrievers[mode].search(query, top_k=top_k))
    else:
        per_retriever = {
            name: list(r.search(query, top_k=top_k * 2)) for name, r in retrievers.items()
        }
        fuser = RRFFusion(
            k=cfg.rrf_k,
            weights={
                "bm25": cfg.mix_weights.bm25,
                "hierarchy": cfg.mix_weights.hierarchy,
            },
        )
        hits = list(fuser.fuse(per_retriever, top_k=top_k))

    return {
        "query": query,
        "mode": mode,
        "hits": [
            {
                "chunk_id": h.chunk_id,
                "doc_path": h.doc_path,
                "title": h.title,
                "heading_path": h.heading_path,
                "module": h.module,
                "snippet": (h.snippet or "").replace("<<", "").replace(">>", ""),
                "score": h.score,
                "retriever": h.retriever,
            }
            for h in hits
        ],
    }


def _handle_get_module(cfg: LoreWikiConfig, args: dict[str, Any]) -> dict[str, Any]:
    if cfg.db_path is None or not cfg.db_path.exists():
        return {
            "error": "index not built",
            "hint": f"run `lorewiki index --path {cfg.wiki_path}` first",
        }
    module_path = str(args.get("module_path") or "").strip()
    with open_db(cfg.db_path, auto_init=False) as conn:
        if module_path:
            node = conn.execute(
                "SELECT id, parent_id, node_type, title, summary, path, level, doc_id "
                "FROM hierarchy WHERE path = ?",
                (module_path,),
            ).fetchone()
        else:
            node = conn.execute(
                "SELECT id, parent_id, node_type, title, summary, path, level, doc_id "
                "FROM hierarchy WHERE id = '__root__'"
            ).fetchone()
        if node is None:
            return {"error": f"module not found: {module_path or '(root)'}"}

        children = conn.execute(
            "SELECT path, title, node_type, summary, level "
            "FROM hierarchy WHERE parent_id = ? ORDER BY node_type, path",
            (node["id"],),
        ).fetchall()
        # For doc-type leaves, count chunks for context.
        chunk_counts = {}
        for ch in children:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM documents "
                "WHERE doc_path = ? OR doc_path LIKE ?",
                (ch["path"], f"{ch['path']}/%"),
            ).fetchone()
            chunk_counts[ch["path"]] = int(row["c"]) if row else 0

    return {
        "node": {
            "path": node["path"],
            "title": node["title"],
            "node_type": node["node_type"],
            "summary": node["summary"],
            "level": node["level"],
            "doc_id": node["doc_id"],
        },
        "children": [
            {
                "path": ch["path"],
                "title": ch["title"],
                "node_type": ch["node_type"],
                "summary": ch["summary"],
                "level": ch["level"],
                "chunk_count": chunk_counts.get(ch["path"], 0),
            }
            for ch in children
        ],
    }


# ---- runtime ----


async def run_async(cfg: LoreWikiConfig | None = None) -> None:
    """Async entrypoint — runs forever, communicating over stdio."""
    server = build_server(cfg)
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


def run(cfg: LoreWikiConfig | None = None) -> None:
    """Sync entrypoint used by the CLI."""
    asyncio.run(run_async(cfg))


__all__ = ["build_server", "run", "run_async"]
