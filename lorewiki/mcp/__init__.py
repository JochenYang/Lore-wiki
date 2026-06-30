"""MCP (Model Context Protocol) server package.

Exposes LoreWiki as a set of MCP tools so that MCP-compatible LLM
clients (Claude Desktop, Cursor, opencode, etc.) can automatically
discover and call ``search`` / ``show`` / ``tree`` without the user
hand-writing a skill document.

Public surface:

* :data:`server` — the singleton :class:`mcp.server.Server` instance.
* :func:`run_server` — entry point used by ``lorewiki mcp serve``.
"""

from lorewiki.mcp.server import run_server, server

__all__ = ["run_server", "server"]
