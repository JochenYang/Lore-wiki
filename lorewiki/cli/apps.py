"""Typer app instances, Rich console, and the ASCII banner.

The :class:`Typer` instances live here (not in :mod:`lorewiki.cli.__init__`)
so that the command modules can import them without dragging in
the subcommand decorators, which would defeat Typer's lazy
registration. ``__init__.py`` then imports the ``app`` symbol so the
existing ``lorewiki.cli:app`` console-script entry point keeps working.
"""

from __future__ import annotations

import contextlib
import sys
from typing import Annotated

import click as _click
import typer
from rich.console import Console

from lorewiki import __version__
from lorewiki.utils.logger import get_logger

console = Console()
log = get_logger(__name__)


def _force_utf8_streams() -> None:
    """Force UTF-8 on stdin/stdout/stderr at import time.

    Windows Python 3.6+ sets the default encoding for a redirected
    (piped) stdin to the console code page — historically cp936
    (GBK) in zh_CN locales, cp1252 in en_US. If we left it alone,
    a command like::

        PS> echo "幂等设计" | lorewiki add --title "X" --module m

    would feed GBK-encoded bytes into the child Python's stdin,
    which would then re-encode them as UTF-8 and write mojibake
    into the resulting Markdown file (the ``骞傜瓑璁捐…``
    rot observed in early 0.2.7 smoke tests). We reconfigure all
    three streams to UTF-8 with errors='replace' so the bytes the
    child sees are the bytes the parent intended.

    stdout/stderr are also reconfigured — without this, ``--raw``
    JSON dumps containing CJK would mojibake on a cp936 terminal.
    The change is a no-op on POSIX (utf-8 is already the default).

    Python 3.7+ exposes ``TextIOWrapper.reconfigure``; we guard
    with ``hasattr`` so non-standard streams captured by tests
    don't crash the import.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(OSError, ValueError):
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


_force_utf8_streams()


# ---------------------------------------------------------------------------
# ASCII banner
# ---------------------------------------------------------------------------
#
# Hand-laid block-character logo, designed to render cleanly on Windows
# Terminal / PowerShell 7+ / macOS Terminal. Six lines high, ~56 cols wide.
_BANNER_LINES = (
    " ██╗      ██████╗ ██████╗ ███████╗██╗    ██╗██╗██╗  ██╗██╗",
    " ██║     ██╔═══██╗██╔══██╗██╔════╝██║    ██║██║██║ ██╔╝██║",
    " ██║     ██║   ██║██████╔╝█████╗  ██║ █╗ ██║██║█████╔╝ ██║",
    " ██║     ██║   ██║██╔══██╗██╔══╝  ██║███╗██║██║██╔═██╗ ██║",
    " ███████╗╚██████╔╝██║  ██║███████╗╚███╔███╔╝██║██║  ██╗██║",
    " ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝ ╚══╝╚══╝ ╚═╝╚═╝  ╚═╝╚═╝",
)
_BANNER_HELP = "\n".join(_BANNER_LINES) + "\n"


def print_banner() -> None:
    """Print the LOREWIKI block-character banner in cyan + bold."""
    console.print(_BANNER_HELP.rstrip(), style="bold cyan", highlight=False)
    console.print(
        f"  [dim]local-first knowledge base \u00b7 v{__version__}[/dim]",
        highlight=False,
    )
    console.print()


app = typer.Typer(
    name="lorewiki",
    help="Local-first knowledge base for LLM-assisted coding.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)

config_app = typer.Typer(
    name="config",
    help="View and edit LoreWiki configuration.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")

topic_app = typer.Typer(
    name="topic",
    help=(
        "Manage knowledge topics (your 'second-brain' vaults). "
        "Each topic is an isolated index under ~/lorewiki/topics/<name>/."
    ),
    no_args_is_help=True,
)
app.add_typer(topic_app, name="topic")


def _version_callback(value: bool) -> None:
    if value:
        print_banner()
        raise typer.Exit()


def _help_callback(ctx: typer.Context, value: bool) -> None:
    """Top-level ``--help`` / ``-h`` shortcut that prepends the banner.

    typer 0.9+ auto-generates ``--help`` *before* user code runs, so the
    banner injection via :func:`_get_help_with_banner` never fires. We
    therefore define an explicit ``--help`` option with ``is_eager=True``;
    typer defers to the user-defined callback whenever an option with
    that name exists. The standard typer-rendered help text is then
    fetched via :meth:`typer.Context.get_help` so all subcommand /
    option metadata still flows through the normal path.
    """
    if not value:
        return
    print_banner()
    # typer's Context exposes ``get_help`` which delegates to click's
    # ``Context.get_help`` on the bound click.Command, so the output
    # matches what the auto-generated help would have shown.
    console.print(ctx.get_help(), highlight=False)
    raise typer.Exit(0)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show LoreWiki version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    help_: Annotated[
        bool,
        typer.Option(
            "--help",
            "-h",
            help="Show this message and exit.",
            callback=_help_callback,
            is_eager=True,
        ),
    ] = False,
    topic: Annotated[
        str | None,
        typer.Option(
            "--topic",
            "-t",
            help=(
                "Active knowledge topic NAME for this invocation. Overrides "
                "the LOREWIKI_TOPIC env var and ~/lorewiki/current. "
                "Note: this is the OPTION form — to manage topics "
                "(list / create / use / delete), use the `topic` subcommand. "
                "Example: --topic react search 'useState closure'."
            ),
        ),
    ] = None,
) -> None:
    """LoreWiki CLI entrypoint."""
    import os  # noqa: PLC0415

    # Plumb the topic into the process environment so :func:`load_config`
    # picks it up uniformly across CLI subcommands. We only set it
    # when non-empty, so a bare ``--topic ""`` is a no-op rather than
    # an explicit reset.
    if topic:
        os.environ["LOREWIKI_TOPIC"] = topic


def _get_help_with_banner(self: typer.Typer, ctx: typer.Context) -> str:  # type: ignore[override]
    return _BANNER_HELP + _click.Group.get_help(self, ctx)


# Prepend the ASCII banner to every `--help` output. typer wraps each
# :class:`Typer` in a click.Group at first dispatch, so the `get_help`
# method only materialises on the instance — we rebind it here.
app.get_help = _get_help_with_banner  # type: ignore[method-assign]


__all__ = ["app", "config_app", "console", "log", "print_banner", "topic_app"]
