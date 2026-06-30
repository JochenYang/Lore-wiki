"""LoreWiki MCP Server — exposes lorewiki as MCP tools.

This lets MCP-compatible LLM clients (Claude Desktop, Cursor, etc.)
automatically discover and use lorewiki without the user writing
any rules or skill documents.

Usage:
    lorewiki mcp serve

The server runs on stdio (standard MCP transport).
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from lorewiki.config import load_config
from lorewiki.db.connection import open_db
from lorewiki.indexer import cleaning
from lorewiki.retriever import run_search

server: Server = Server("lorewiki")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available lorewiki tools."""
    return [
        Tool(
            name="search",
            description=(
                "Search the local knowledge base for relevant documentation. "
                "Returns document summaries (doc_path, title, summary, score). "
                "Use this when you need to look up API docs, design patterns, "
                "team decisions, or error solutions. After finding a relevant "
                "doc, use 'show' to read its full content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords, API name, concept, or error message.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Max results to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="show",
            description=(
                "Read a full document from the knowledge base. "
                "Returns the complete content and related docs (citation links). "
                "Use after 'search' to read the full content of a relevant doc."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_path": {
                        "type": "string",
                        "description": "Relative path of the doc, e.g. 'api/user/auth.md'.",
                    },
                },
                "required": ["doc_path"],
            },
        ),
        Tool(
            name="tree",
            description=(
                "Browse the knowledge base hierarchy. "
                "Returns a list of all nodes (modules, docs) with their paths and levels. "
                "Use this to understand what's in the wiki before searching."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "depth": {
                        "type": "integer",
                        "description": "Max depth to return (None = unlimited).",
                        "default": None,
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls dispatched by the MCP client.

    The dispatch mirrors the three CLI commands (``search`` / ``show`` /
    ``tree``) but returns JSON-serialised payloads wrapped in
    :class:`TextContent` so any MCP client can consume them uniformly.
    """
    cfg = load_config()
    if cfg.db_path is None or not cfg.db_path.exists():
        # No index → surface a actionable hint instead of raising, so the
        # LLM client can guide the user to run ``lorewiki index`` first.
        return [TextContent(
            type="text",
            text="No index found. Run 'lorewiki index' first to build the knowledge base."
        )]

    if name == "search":
        query = arguments.get("query", "")
        top_k = arguments.get("top_k", 5)
        hits = run_search(cfg, query, mode="mix", top_k=top_k)

        # Deduplicate by doc_path: a single doc may produce multiple chunk
        # hits; the MCP tool returns one summary per doc (mirrors the CLI
        # default ``lorewiki search`` behaviour). We keep the highest score
        # seen for that doc so ranking stays meaningful.
        seen: dict[str, dict[str, Any]] = {}
        for h in hits:
            if h.doc_path not in seen:
                seen[h.doc_path] = {
                    "doc_path": h.doc_path,
                    "title": h.title,
                    "module": h.module,
                    "score": h.score,
                }
            elif h.score > seen[h.doc_path]["score"]:
                seen[h.doc_path]["score"] = h.score

        # Enrich with human-authored summaries from the doc_summaries table
        # (one row per doc, generated at index time). Skip the query when
        # there are no hits to avoid an empty ``IN ()`` clause.
        with open_db(cfg.db_path, auto_init=False) as conn:
            if seen:
                placeholders = ",".join("?" * len(seen))
                rows = conn.execute(
                    f"SELECT doc_path, summary, doc_type FROM doc_summaries "
                    f"WHERE doc_path IN ({placeholders})",
                    tuple(seen.keys()),
                ).fetchall()
                for row in rows:
                    entry = seen.get(row["doc_path"])
                    if entry:
                        entry["summary"] = row["summary"]
                        entry["doc_type"] = row["doc_type"]

        # Fallback: for docs not present in doc_summaries (e.g. older
        # indexes built before the table existed), synthesise a short
        # summary from the first hit's snippet so the payload stays
        # uniform for the LLM consumer.
        for h in hits:
            entry = seen.get(h.doc_path)
            if entry and "summary" not in entry:
                entry["summary"] = (h.snippet or "")[:200]

        result = list(seen.values())
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "show":
        doc_path = arguments.get("doc_path", "")
        with open_db(cfg.db_path, auto_init=False) as conn:
            # Pick the first chunk (chunk_index ASC) as the entry point;
            # the full body is reconstructed by concatenating chunks at
            # index time, so chunk 0 carries the canonical cleaned content.
            row = conn.execute(
                "SELECT doc_path, title, heading_path, module, content "
                "FROM documents WHERE doc_path = ? ORDER BY chunk_index LIMIT 1",
                (doc_path,),
            ).fetchone()
            if row is None:
                return [TextContent(type="text", text=f"Document not found: {doc_path}")]

            body = cleaning.strip_breadcrumb_prefix(row["content"])
            body = cleaning.strip_translation_footer(body)

            # Related docs come from the ``edges`` knowledge-graph table
            # (Markdown [text](target.md) links captured at index time).
            # The broad ``except Exception`` guards older indexes that
            # predate the edges table — mirrors the CLI ``show`` fallback.
            related = []
            try:
                edge_rows = conn.execute(
                    "SELECT target_doc, link_text FROM edges WHERE source_doc = ?",
                    (doc_path,),
                ).fetchall()
                related = [
                    {"doc_path": e["target_doc"], "context": e["link_text"] or ""}
                    for e in edge_rows
                ]
            except Exception:
                pass

            payload = {
                "doc_path": row["doc_path"],
                "title": cleaning.clean_title(row["title"]),
                "module": row["module"],
                "content": body.rstrip(),
                "related_docs": related,
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            return [TextContent(type="text", text=text)]

    elif name == "tree":
        # ``depth`` is declared in the tool schema for forward compatibility
        # (and to mirror the CLI ``--depth`` flag). The current implementation
        # returns every node so the LLM can browse the full hierarchy; the
        # CLI ``tree --raw`` path does the same. Filtering by depth, if
        # needed later, is a non-breaking addition.
        with open_db(cfg.db_path, auto_init=False) as conn:
            all_nodes = conn.execute(
                "SELECT id, parent_id, title, level, node_type, path FROM hierarchy"
            ).fetchall()
            nodes_json = [
                {
                    "id": n["id"],
                    "parent_id": n["parent_id"],
                    "node_type": n["node_type"],
                    "title": cleaning.clean_title(n["title"]),
                    "path": n["path"],
                    "level": n["level"],
                }
                for n in all_nodes
            ]
            text = json.dumps({"nodes": nodes_json}, ensure_ascii=False, indent=2)
            return [TextContent(type="text", text=text)]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run_server() -> None:
    """Run the MCP server on stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


__all__ = ["run_server", "server"]
