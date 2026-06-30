"""``lorewiki mcp`` — run the LoreWiki MCP server (stdio transport).

This is the entry point an MCP-compatible LLM client (Claude Desktop,
Cursor, opencode, …) points at so it can auto-discover and call
``search`` / ``show`` / ``tree`` without the user writing a skill
document.
"""

from __future__ import annotations

from typing import Annotated

import typer

from lorewiki.cli.apps import app, console


@app.command()
def mcp(
    action: Annotated[
        str,
        typer.Argument(help="MCP action: 'serve'."),
    ] = "serve",
) -> None:
    """Run the LoreWiki MCP server (stdio transport).

    Only ``serve`` is supported today. The server speaks the standard
    MCP stdio protocol, so an MCP client config just points at::

        lorewiki mcp serve
    """
    if action != "serve":
        console.print(f"[red]Unknown action:[/red] {action}. Use 'serve'.")
        raise typer.Exit(code=1)

    # Imported lazily so a bare ``lorewiki --help`` (or any unrelated
    # subcommand) doesn't pay the mcp SDK import cost, and so users
    # without the ``mcp`` extra installed only see the error when they
    # actually try to run the server.
    import asyncio  # noqa: PLC0415

    try:
        from lorewiki.mcp.server import run_server  # noqa: PLC0415
    except ImportError as exc:
        console.print(
            f"[red]MCP SDK not installed:[/red] {exc.name}\n"
            f"Install with:  [cyan]pip install 'lorewiki[mcp]'[/cyan]"
        )
        raise typer.Exit(code=1) from exc

    asyncio.run(run_server())


__all__ = ["mcp"]
