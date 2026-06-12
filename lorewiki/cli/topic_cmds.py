"""``lorewiki topic ...`` sub-commands (list, suggest, create, use, show, delete, rename)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from lorewiki.cli.apps import console, topic_app
from lorewiki.cli.helpers import human_bytes
from lorewiki.topic import (
    CURRENT_FILE,
    USER_TOPICS_ROOT,
    TopicInfo,
    TopicManager,
    TopicNameError,
    suggest_names,
)


def _format_topic_row(info: TopicInfo, *, active: bool) -> tuple[str, str, str, str]:
    """Build a 4-tuple for the ``topic list`` table: marker, name, db, source.

    Hidden behind a helper so the table layout stays consistent
    whether called from the CLI or from tests.
    """
    marker = "[bold green]*[/bold green]" if active else " "
    db_marker = "[green]indexed[/green]" if info.db_path.is_file() else "[dim]empty[/dim]"
    src_marker = "[yellow](linked)[/yellow]" if info.source_link else "[dim](local)[/dim]"
    return marker, info.name, str(info.db_path), f"{db_marker} {src_marker}"


@topic_app.command("list")
def topic_list(
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="Emit newline-delimited JSON (one object per topic). "
            "For agent scripting; the default is a Rich table for humans.",
        ),
    ] = False,
) -> None:
    """List all topics. The active one is starred.

    Use ``--raw`` for machine-readable output (active topic marked
    with ``"active": true``). Default is a human-friendly Rich table.
    """
    mgr = TopicManager()
    infos = mgr.list()
    active_name = mgr.current()
    if raw:
        # Pure JSON, no Rich formatting — agents can parse without
        # ANSI-stripping. Empty list prints ``[]`` rather than nothing
        # so callers don't have to special-case.
        payload = [
            {
                "name": info.name,
                "active": info.name == active_name,
                "root": str(info.root),
                "wiki_path": str(info.wiki_path),
                "db_path": str(info.db_path),
                "indexed": info.db_path.is_file(),
                "linked": info.source_link,
            }
            for info in infos
        ]
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return
    if not infos:
        console.print(
            Panel(
                "[yellow]No topics yet.[/yellow]\n"
                "Create your first with:  [bold]lorewiki topic create <name>[/bold]\n"
                f"Topics live under: [dim]{USER_TOPICS_ROOT}[/dim]",
                title="lorewiki topic list",
                border_style="yellow",
            )
        )
        return
    table = Table(title=f"LoreWiki topics ({USER_TOPICS_ROOT})", show_lines=False)
    table.add_column("", width=2)
    table.add_column("name", style="cyan", no_wrap=True)
    table.add_column("db", overflow="fold")
    table.add_column("source", style="dim")
    for info in infos:
        m, n, d, s = _format_topic_row(info, active=info.name == active_name)
        table.add_row(m, n, d, s)
    console.print(table)
    if active_name is None:
        console.print(
            "\n[dim]No active topic. Use `lorewiki topic use <name>` to pick one.[/dim]"
        )


@topic_app.command("suggest")
def topic_suggest(
    description: Annotated[
        str,
        typer.Argument(help="Free-form description, e.g. \"react hooks learning\"."),
    ],
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-n",
            help="Maximum number of suggestions to return.",
        ),
    ] = 4,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Print one suggestion per line (no bullets)."),
    ] = False,
) -> None:
    """Suggest topic names for a free-form description.

    The slugifier is rule-based (no LLM, no network). CJK-only
    descriptions return no suggestions — name the topic by hand
    in that case.

    Existing topics are detected and the suggested names are
    suffixed (``react-2``, ``react-3``, ...) to avoid collisions.
    """
    existing = [i.name for i in TopicManager().list()]
    suggestions = suggest_names(description, existing=existing, limit=limit)
    if not suggestions:
        console.print(
            Panel(
                "[yellow]No suggestions.[/yellow]\n"
                "Possible reasons: description is empty, all words were "
                "stopwords, or it's non-ASCII (CJK).\n\n"
                "Name the topic by hand:  [bold]lorewiki topic create <name>[/bold]\n"
                "(rules: lowercase letters, digits, hyphens; 1-64 chars.)",
                title="lorewiki topic suggest",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=1)
    if raw:
        sys.stdout.write("\n".join(suggestions) + "\n")
        return
    console.print(
        f"[bold cyan]Suggestions for[/bold cyan] [dim]{description!r}[/dim]"
    )
    for i, name in enumerate(suggestions, 1):
        console.print(f"  [cyan]{i}.[/cyan] {name}")
    console.print(
        "\n[dim]Pick one and run:  lorewiki topic create <name> "
        "[--source <md-dir>][/dim]"
    )


@topic_app.command("rename")
def topic_rename(
    old: Annotated[str, typer.Argument(help="Current topic name.")],
    new: Annotated[str, typer.Argument(help="New topic name (must pass validate_name).")],
) -> None:
    """Rename a topic in place. The index and config move with it.

    If the renamed topic is the active one, ``~/lorewiki/current`` is
    updated so subsequent commands keep working without ``topic use``.
    """
    try:
        info = TopicManager().rename(old, new)
    except TopicNameError as exc:
        console.print(
            Panel(f"[red]{exc}[/red]", title="invalid topic name", border_style="red")
        )
        raise typer.Exit(code=2) from exc
    except (FileNotFoundError, FileExistsError) as exc:
        console.print(
            Panel(f"[red]{exc}[/red]", title="rename failed", border_style="red")
        )
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]renamed[/green] [bold]{old}[/bold] -> [bold cyan]{info.name}[/bold cyan]"
    )


@topic_app.command("create")
def topic_create(
    name: Annotated[str, typer.Argument(help="Topic name (lowercase, digits, hyphens).")],
    source: Annotated[
        Path | None,
        typer.Option(
            "--source", "-s",
            help="Optional path to an existing markdown directory to import.",
        ),
    ] = None,
    link: Annotated[
        bool,
        typer.Option(
            "--link", "-l",
            help="With --source: symlink the source instead of copying (default: copy).",
        ),
    ] = False,
) -> None:
    """Create a new topic (vault).

    Without ``--source`` the topic is created empty. With
    ``--source <PATH>`` the source directory is **copied** into the
    new topic by default, so the topic owns its data; pass
    ``--link`` to symlink instead (useful for throwaway indexing of
    a docs/ folder you don't want to move).
    """
    try:
        info = TopicManager().create(name, source=source, link=link)
    except TopicNameError as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="invalid topic name", border_style="red"))
        raise typer.Exit(code=2) from exc
    except FileExistsError as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="topic exists", border_style="red"))
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        console.print(
            Panel(f"[red]{exc}[/red]", title="source not found", border_style="red")
        )
        raise typer.Exit(code=1) from exc
    if info.source_link:
        mode = "[yellow]linked[/yellow]"
    elif source:
        mode = "[green]copied[/green]"
    else:
        mode = "empty"
    console.print(
        f"[green]created[/green] topic [bold cyan]{info.name}[/bold cyan] "
        f"({mode}) at [dim]{info.root}[/dim]"
    )
    # Show what was actually ingested. ``ingest_summary`` is set
    # when ``--source`` was used; ``None`` otherwise.
    extra = ""
    if info.ingest_summary is not None:
        copied, skipped = info.ingest_summary
        if skipped:
            extra = (
                f"  ingest: [green]{copied}[/green] entries copied, "
                f"[yellow]{skipped} hidden[/yellow] skipped "
                "(.git, .DS_Store, .lorewiki, etc.)\n"
            )
        else:
            extra = f"  ingest: [green]{copied}[/green] entries copied\n"
    console.print(
        f"  wiki:  [dim]{info.wiki_path}[/dim]\n"
        f"  db:    [dim]{info.db_path}[/dim]\n"
        f"  cfg:   [dim]{info.config_path}[/dim]"
        + (f"\n{extra}" if extra else "\n")
        + f"\nNext: [bold]lorewiki topic use {info.name}[/bold] then "
        f"[bold]lorewiki index[/bold]."
    )


@topic_app.command("use")
def topic_use(
    name: Annotated[str, typer.Argument(help="Topic name to activate.")],
) -> None:
    """Set the active topic (persisted to ``~/lorewiki/current``)."""
    try:
        info = TopicManager().use(name)
    except (FileNotFoundError, TopicNameError) as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="topic not found", border_style="red"))
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]active topic:[/green] [bold cyan]{info.name}[/bold cyan] "
        f"(written to [dim]{CURRENT_FILE}[/dim])"
    )


@topic_app.command("show")
def topic_show() -> None:
    """Print the active topic's full state."""
    mgr = TopicManager()
    info = mgr.resolve_active()
    if info is None:
        console.print(
            Panel(
                "[yellow]No active topic.[/yellow]\n"
                "List available topics with `lorewiki topic list`, then "
                "`lorewiki topic use <name>` to pick one.",
                title="lorewiki topic show",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=1)
    db_present = info.db_path.is_file()
    db_size = info.db_path.stat().st_size if db_present else 0
    md_count = sum(
        1 for _ in info.wiki_path.rglob("*.md") if _.is_file()
    ) if info.wiki_path.exists() else 0
    # Fix: the previous version printed ``[bold]name[/bold]`` twice (a
    # copy-paste bug). Each field appears exactly once now.
    panel_body = (
        f"[bold]name[/bold]    : {info.name}\n"
        f"[bold]root[/bold]   : {info.root}\n"
        f"[bold]wiki[/bold]   : {info.wiki_path}"
        f"{' (linked)' if info.source_link else ''}\n"
        f"[bold]db[/bold]     : {info.db_path}"
        f"  ({'indexed' if db_present else 'empty'}, {human_bytes(db_size)})\n"
        f"[bold]cfg[/bold]    : {info.config_path}\n"
        f"[bold]md files[/bold]: {md_count}\n"
    )
    console.print(Panel(panel_body, title="active topic", border_style="cyan"))


@topic_app.command("delete")
def topic_delete(
    name: Annotated[str, typer.Argument(help="Topic name to delete (hard delete).")],
    force: Annotated[
        bool,
        typer.Option(
            "--force", "-f",
            help="Skip the confirmation prompt.",
        ),
    ] = False,
) -> None:
    """Hard-delete a topic's directory and all its content.

    There is no recycle bin. If the topic is the active one, the
    active pointer is cleared.
    """
    mgr = TopicManager()
    try:
        info = mgr.get(name)
    except (FileNotFoundError, TopicNameError) as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="topic not found", border_style="red"))
        raise typer.Exit(code=1) from exc
    if not force:
        confirm = typer.confirm(
            f"Delete topic {info.name!r} at {info.root}? This cannot be undone.",
            default=False,
        )
        if not confirm:
            console.print("[yellow]aborted[/yellow]")
            raise typer.Exit(code=1)
    mgr.delete(name)
    console.print(f"[red]deleted[/red] topic [bold]{info.name}[/bold]")


__all__ = [
    "topic_create",
    "topic_delete",
    "topic_list",
    "topic_rename",
    "topic_show",
    "topic_suggest",
    "topic_use",
]
