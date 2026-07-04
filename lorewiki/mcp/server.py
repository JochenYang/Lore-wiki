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
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

import frontmatter
from loguru import logger as log
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from lorewiki.cli.add import (
    _build_frontmatter,
    _is_safe_target,
    _resolve_wiki_root,
    _strip_surrogates,
    slugify,
)
from lorewiki.config import load_config
from lorewiki.db.connection import open_db
from lorewiki.indexer import build_index, cleaning
from lorewiki.indexer.parser import parse_markdown
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
        Tool(
            name="add",
            description=(
                "Create a new knowledge note in the wiki. "
                "Writes a Markdown file with frontmatter (title, module, tags) and "
                "auto-reindexes so the new doc is immediately retrievable via search(). "
                "Use this to persist a learning, decision, postmortem, or any "
                "small chunk of knowledge. The body is required; title and module "
                "are auto-derived if omitted.\n\n"
                "IMPORTANT: always pass ``topic`` when the note belongs to a "
                "specific second-brain topic. For project-specific content use "
                "the project's topic name (e.g. ``warm-kitchen-time``); for "
                "cross-project patterns use ``shared``. If omitted, the note "
                "lands in the active topic, which may not be the right one."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Document title (auto-derived from first H1 if omitted).",
                    },
                    "body": {
                        "type": "string",
                        "description": "Markdown body content.",
                    },
                    "module": {
                        "type": "string",
                        "description": "Module / category directory (default 'root').",
                        "default": "root",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of free-form tags (helps discovery).",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Overwrite an existing file at the target path.",
                        "default": False,
                    },
                    "topic": {
                        "type": "string",
                        "description": "Topic name to write to. Use the project's topic for "
                        "project-specific notes (e.g. 'warm-kitchen-time'), or 'shared' "
                        "for cross-project patterns. If omitted, uses the active topic.",
                    },
                },
                "required": ["body"],
            },
        ),
        Tool(
            name="update",
            description=(
                "Modify an existing knowledge note in place. "
                "Pass a doc_path plus any subset of body / title / module / tags. "
                "Omitted options preserve the existing value, so you can update just "
                "the body, just the title, or any combination. Auto-reindexes after.\n\n"
                "IMPORTANT: always pass ``topic`` when the note belongs to a "
                "specific second-brain topic (same logic as the add tool)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_path": {
                        "type": "string",
                        "description": "Relative path of the doc to update.",
                    },
                    "body": {
                        "type": "string",
                        "description": "New Markdown body (omit to preserve existing).",
                    },
                    "title": {
                        "type": "string",
                        "description": "New title (omit to preserve existing).",
                    },
                    "module": {
                        "type": "string",
                        "description": "New module (omit to preserve existing).",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New tags list (omit to preserve existing).",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Topic name to write to. Same semantics as the add tool.",
                    },
                },
                "required": ["doc_path"],
            },
        ),
        Tool(
            name="delete",
            description=(
                "Delete a knowledge note from the wiki. "
                "Removes the file and purges stale index rows so search() no longer "
                "returns it. Use this to clean up outdated or wrong docs.\n\n"
                "IMPORTANT: pass ``topic`` to target a specific second-brain topic "
                "(same logic as add/update)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_path": {
                        "type": "string",
                        "description": "Relative path of the doc to delete.",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Skip confirmation (always pass true for MCP calls).",
                        "default": True,
                    },
                    "topic": {
                        "type": "string",
                        "description": "Topic name to target. Same semantics as the add tool.",
                    },
                },
                "required": ["doc_path"],
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

                # Enrich with related_docs from the edges table. Each
                # top-K doc gets up to 5 outgoing links. We fetch in
                # one SQL to avoid N+1 round-trips; the ``seen`` set
                # keeps the payload from referencing a doc we already
                # returned as a primary hit.
                if seen:
                    edge_rows = conn.execute(
                        f"SELECT source_doc, target_doc, link_text FROM edges "
                        f"WHERE source_doc IN ({placeholders})",
                        tuple(seen.keys()),
                    ).fetchall()
                    # Group by source_doc, cap at 5 each
                    rel_count: dict[str, int] = {}
                    for er in edge_rows:
                        src = er["source_doc"]
                        tgt = er["target_doc"]
                        # Skip if the target is already in the top-K
                        # set (would just duplicate the link the LLM
                        # already has).
                        if tgt in seen:
                            continue
                        entry = seen.get(src)
                        if entry is None:
                            continue
                        if rel_count.get(src, 0) >= 5:
                            continue
                        entry.setdefault("related_docs", []).append({
                            "doc_path": tgt,
                            "context": er["link_text"] or "",
                        })
                        rel_count[src] = rel_count.get(src, 0) + 1

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
            # Fetch ALL chunks and concatenate so long docs are returned
            # in full. A single doc may span multiple chunks (split on H2
            # boundaries at index time); chunk 0 carries the H1 banner and
            # breadcrumb prefix, subsequent chunks the body sections.
            rows = conn.execute(
                "SELECT chunk_index, title, heading_path, module, content "
                "FROM documents WHERE doc_path = ? ORDER BY chunk_index",
                (doc_path,),
            ).fetchall()
            if not rows:
                return [TextContent(type="text", text=f"Document not found: {doc_path}")]

            # Join chunks with double newlines so section boundaries remain
            # visible. Strip the breadcrumb prefix only from the first chunk
            # (it's redundant once chunks are joined); strip the
            # translation footer from each chunk in case it leaked in.
            joined_parts: list[str] = []
            for i, row in enumerate(rows):
                chunk_text = row["content"]
                if i == 0:
                    chunk_text = cleaning.strip_breadcrumb_prefix(chunk_text)
                chunk_text = cleaning.strip_translation_footer(chunk_text)
                if chunk_text.strip():
                    joined_parts.append(chunk_text)
            body = "\n\n".join(joined_parts)
            # First chunk carries the doc-level metadata (title, heading_path).
            first = rows[0]

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
                "doc_path": doc_path,
                "title": cleaning.clean_title(first["title"]),
                "module": first["module"] or "",
                "chunk_count": len(rows),
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

    elif name == "add":
        body = arguments.get("body", "")
        title = arguments.get("title", "")
        module = arguments.get("module", "root")
        tags = arguments.get("tags", []) or []
        force = bool(arguments.get("force", False))
        topic_arg = arguments.get("topic")
        # If topic is provided, route the write to that topic's vault.
        if topic_arg:
            from lorewiki.config import load_config as _mcp_load_config  # noqa: PLC0415
            _topic_cfg = _mcp_load_config(overrides={"topic": topic_arg})
            wiki_root = _topic_cfg.wiki_path
            # Also update cfg so build_index targets the right database.
            cfg = _topic_cfg
        else:
            wiki_root = _resolve_wiki_root(None)

        raw_body = _strip_surrogates(body)
        # Title resolution: explicit > first H1 > slug of first 64 chars.
        h1_match = re.search(r"^#\s+(.+?)\s*$", raw_body, re.MULTILINE)
        h1 = cleaning.clean_title(h1_match.group(1)) if h1_match else ""
        final_title = (title or "").strip() or h1 or slugify(raw_body[:64])
        if not wiki_root.is_dir():
            return [TextContent(
                type="text",
                text=f"wiki path not found: {wiki_root}",
            )]

        module_slug = slugify(module) if module != "root" else "root"
        title_slug = slugify(final_title)
        target_dir = wiki_root / module_slug
        target_path = target_dir / f"{title_slug}.md"

        if not _is_safe_target(wiki_root, target_path):
            return [TextContent(
                type="text",
                text=f"refusing to write outside wiki root: {target_path}",
            )]
        if target_path.exists() and not force:
            return [TextContent(
                type="text",
                text=f"file already exists: {target_path} (pass force=true to overwrite)",
            )]

        metadata = _build_frontmatter(
            title=final_title, module=module_slug, tags=tags,
        )
        post = frontmatter.Post(raw_body, **metadata)
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            target_path.write_text(
                frontmatter.dumps(post) + "\n", encoding="utf-8",
            )
        except (OSError, UnicodeEncodeError) as exc:
            target_path.unlink(missing_ok=True)
            return [TextContent(type="text", text=f"write failed: {exc}")]

        # Re-index so the new doc is immediately searchable.
        try:
            build_index(cfg, rebuild=False)
        except Exception as exc:
            # Indexing failure is non-fatal — file was written, index will
            # catch up on the next ``lorewiki index`` run.
            return [TextContent(
                type="text",
                text=f"wrote {target_path} but reindex failed: {exc}",
            )]

        return [TextContent(
            type="text",
            text=json.dumps(
                {
                    "status": "ok",
                    # ``as_posix()`` so Windows backslashes don't leak into
                    # the returned payload — matches the POSIX-style keys
                    # stored in ``documents.doc_path`` and the ``delete``
                    # tool's input contract.
                    "doc_path": target_path.relative_to(wiki_root).as_posix(),
                    "title": final_title,
                    "module": module_slug,
                    "tags": tags,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )]

    elif name == "update":
        from lorewiki.cli.helpers import resolve_doc_target  # noqa: PLC0415

        doc_path_arg = arguments.get("doc_path", "")
        topic_arg = arguments.get("topic")
        if topic_arg:
            _topic_cfg = load_config(overrides={"topic": topic_arg})
            wiki_root = _topic_cfg.wiki_path
            cfg = _topic_cfg
        else:
            wiki_root = _resolve_wiki_root(None)
        if not wiki_root.is_dir():
            return [TextContent(type="text", text=f"wiki path not found: {wiki_root}")]

        try:
            target_path = resolve_doc_target(doc_path_arg, wiki_root)
        except ValueError as exc:
            return [TextContent(type="text", text=f"path-traversal blocked: {exc}")]

        if not target_path.exists():
            return [TextContent(
                type="text",
                text=f"doc not found: {doc_path_arg}",
            )]

        # Read the existing doc and its frontmatter.
        try:
            parsed = parse_markdown(target_path, rel_to=wiki_root)
        except (OSError, UnicodeDecodeError) as exc:
            return [TextContent(type="text", text=f"read failed: {exc}")]

        old_meta = dict(parsed.metadata or {})
        new_body = arguments.get("body")
        new_title = arguments.get("title")
        new_module = arguments.get("module")
        new_tags = arguments.get("tags")

        # Build the merged payload — only override fields the caller passed.
        final_body = _strip_surrogates(new_body) if new_body is not None else parsed.body
        final_title = (new_title or "").strip() or old_meta.get("title", parsed.title)
        final_module = (
            new_module.strip()
            if (new_module and new_module.strip())
            else old_meta.get("module", parsed.module or "root")
        )
        final_tags = list(new_tags) if new_tags is not None else parsed.tags

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        merged_meta: dict[str, Any] = {**old_meta}
        merged_meta["title"] = final_title
        merged_meta["module"] = final_module
        merged_meta["tags"] = final_tags
        # Preserve created_at (seed to today if legacy doc lacks it).
        merged_meta.setdefault("created_at", today)
        merged_meta["last_review"] = today

        post = frontmatter.Post(final_body, **merged_meta)
        try:
            target_path.write_text(
                frontmatter.dumps(post) + "\n", encoding="utf-8",
            )
        except (OSError, UnicodeEncodeError) as exc:
            return [TextContent(type="text", text=f"write failed: {exc}")]

        try:
            build_index(cfg, rebuild=False)
        except Exception as exc:
            return [TextContent(
                type="text",
                text=f"updated {target_path} but reindex failed: {exc}",
            )]

        return [TextContent(
            type="text",
            text=json.dumps(
                {
                    "status": "ok",
                    "doc_path": doc_path_arg,
                    "title": final_title,
                    "module": final_module,
                    "tags": final_tags,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )]

    elif name == "delete":
        from lorewiki.cli.helpers import resolve_doc_target  # noqa: PLC0415

        doc_path_arg = arguments.get("doc_path", "")
        # ``force`` defaults to True in the schema — MCP calls are programmatic
        # and shouldn't require a y/N confirmation.
        force = bool(arguments.get("force", True))
        topic_arg = arguments.get("topic")
        if topic_arg:
            _topic_cfg = load_config(overrides={"topic": topic_arg})
            wiki_root = _topic_cfg.wiki_path
            cfg = _topic_cfg
        else:
            wiki_root = _resolve_wiki_root(None)
        if not wiki_root.is_dir():
            return [TextContent(type="text", text=f"wiki path not found: {wiki_root}")]

        try:
            target_path = resolve_doc_target(doc_path_arg, wiki_root)
        except ValueError as exc:
            return [TextContent(type="text", text=f"path-traversal blocked: {exc}")]

        if not target_path.exists():
            return [TextContent(type="text", text=f"doc not found: {doc_path_arg}")]

        if not force:
            # Defensive: never let MCP delete without explicit force.
            return [TextContent(
                type="text",
                text="refusing to delete without force=true",
            )]

        target_path.unlink()
        # Purge stale index rows + refresh hierarchy.
        # Use cfg.wiki_path (the same root build_index uses) to compute
        # the doc_path key — calling _resolve_wiki_root() again here
        # can return a different resolved root and skew the relative path.
        # IMPORTANT: use as_posix() so Windows backslashes don't sneak into
        # the POSIX-style ``del/del.md`` keys stored in the documents table.
        wiki_root_for_path = cfg.wiki_path
        if cfg.db_path is not None:
            doc_path_db = target_path.relative_to(wiki_root_for_path).as_posix()
            purge_db = pathlib.Path(cfg.db_path)
            try:
                with open_db(purge_db, auto_init=False) as purge_conn:
                    purge_conn.execute(
                        "DELETE FROM documents WHERE doc_path = ?",
                        (doc_path_db,),
                    )
                    purge_conn.commit()
            except Exception as exc:
                log.warning("delete purge failed for {}: {}", doc_path_db, exc)
        try:
            build_index(cfg, rebuild=False)
        except Exception as exc:
            return [TextContent(
                type="text",
                text=f"deleted {target_path} but reindex failed: {exc}",
            )]

        return [TextContent(
            type="text",
            text=json.dumps(
                {
                    "status": "ok",
                    "doc_path": doc_path_arg,
                    "deleted": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run_server() -> None:
    """Run the MCP server on stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


__all__ = ["run_server", "server"]
