"""Top-level ``lorewiki`` CLI built with Typer.

Phase 1 wires up ``init``, ``index``, ``status``, ``search`` and the
``config`` sub-app. Commands that belong to later phases still surface the
"phase pending" panel so users get an honest error code (2) rather than a
crash.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from lorewiki import __version__
from lorewiki.config import (
    LoreWikiConfig,
    load_config,
    save_config,
)
from lorewiki.db import get_meta, open_db
from lorewiki.indexer import build_index, iter_markdown_files
from lorewiki.indexer import cleaning
from lorewiki.llm import AnswerGenerator
from lorewiki.retriever import (
    BaseRetriever,
    BM25Retriever,
    HierarchyRetriever,
    RRFFusion,
)
from lorewiki.topic import (
    CURRENT_FILE,
    USER_TOPICS_ROOT,
    TopicInfo,
    TopicManager,
    TopicNameError,
    suggest_names,
)
from lorewiki.utils.logger import get_logger


def _force_utf8_streams() -> None:
    """Force UTF-8 on stdout/stderr at import time.

    Without this, ``--raw`` JSON containing CJK characters becomes
    mojibake on Windows shells whose default code page is GBK
    (cp936). Python 3.7+ exposes ``TextIOWrapper.reconfigure``; we
    guard with ``hasattr`` so that non-standard stdouts captured by
    tests don't crash the CLI.
    """
    for stream in (sys.stdout, sys.stderr):
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


def _print_banner() -> None:
    """Print the LOREWIKI block-character banner in cyan + bold.

    Assumes a UTF-8 host terminal (Windows Terminal, PowerShell 7+,
    VS Code, any modern Linux/macOS console). Legacy conhost hosts
    with a non-UTF-8 code page (e.g. PowerShell 5.1 + ``chcp 936``)
    will see best-fit mojibake — we accept that limitation rather
    than ship a degraded ASCII banner, mirroring how ``cargo``,
    ``deno``, ``pnpm`` and ``mmx`` (the project the design was
    inspired by) all behave. Users on legacy hosts can run
    ``chcp 65001`` once per session for the full banner.
    """
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

console = Console()
log = get_logger(__name__)


def _version_callback(value: bool) -> None:
    if value:
        _print_banner()
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
    _print_banner()
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
                "Active knowledge topic for this invocation. Overrides "
                "LOREWIKI_TOPIC env and ~/lorewiki/current. Use `lorewiki "
                "topic list` to see available topics."
            ),
        ),
    ] = None,
) -> None:
    """LoreWiki CLI entrypoint."""
    # Plumb the topic into the process environment so :func:`load_config`
    # picks it up uniformly across CLI subcommands. We only set it
    # when non-empty, so a bare ``--topic ""`` is a no-op rather than
    # an explicit reset.
    if topic:
        os.environ["LOREWIKI_TOPIC"] = topic


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Wiki root path to initialise."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing wiki_path / config."),
    ] = False,
) -> None:
    """Create a config file and a sample wiki directory.

    Layout produced::

        <wiki_path>/
            index.md              # generated starter doc (only if dir is empty)
            .lorewiki/
                config.toml
    """
    target = Path(path).expanduser().resolve() if path else (Path.cwd() / "wiki").resolve()
    config_dir = target / ".lorewiki"
    config_path = config_dir / "config.toml"

    if target.exists() and any(target.iterdir()) and not force and config_path.exists():
        console.print(
            Panel(
                f"[yellow]Wiki already initialised at[/yellow] [bold]{target}[/bold]\n"
                f"Use --force to overwrite the config.",
                title="lorewiki init",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=1)
    target.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    # Seed config file using current defaults but pin wiki_path/db_path.
    cfg = LoreWikiConfig(wiki_path=target, db_path=config_dir / "index.db")
    save_config(cfg, config_path)

    # Seed a starter index.md if the directory is empty (besides .lorewiki/).
    visible = [p for p in target.iterdir() if p.name != ".lorewiki"]
    if not visible:
        starter = target / "index.md"
        starter.write_text(
            "---\n"
            'title: "My Wiki"\n'
            "module: root\n"
            "tags: [overview]\n"
            "---\n\n"
            "# My Wiki\n\n"
            "Welcome to your new LoreWiki!\n\n"
            "## Getting started\n\n"
            "1. Create Markdown files under modules (e.g. `api/users/auth.md`).\n"
            "2. Run `lorewiki index` to (re)build the index.\n"
            "3. Run `lorewiki search \"your query\"`.\n",
            encoding="utf-8",
        )

    console.print(
        Panel(
            f"[green]Initialised LoreWiki at[/green] [bold]{target}[/bold]\n"
            f"Config:  {config_path}\n"
            f"DB:      {cfg.db_path}\n\n"
            f"Next step:  [cyan]lorewiki index --path {target}[/cyan]",
            title="lorewiki init",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------


@app.command()
def index(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Directory to index (default: configured wiki_path)."),
    ] = None,
    rebuild: Annotated[
        bool,
        typer.Option("--rebuild", help="Drop and rebuild the index from scratch."),
    ] = False,
) -> None:
    """Index a directory of Markdown files into SQLite + FTS5."""
    cfg = _resolve_config(path)
    if not cfg.wiki_path.exists():
        console.print(
            f"[red]wiki_path does not exist:[/red] {cfg.wiki_path}\n"
            f"Run [cyan]lorewiki init --path {cfg.wiki_path}[/cyan] first."
        )
        raise typer.Exit(code=1)

    stats = build_index(cfg, rebuild=rebuild)
    table = Table(title="Index complete", show_header=False, box=None)
    table.add_row("Wiki path", str(cfg.wiki_path))
    table.add_row("Database", str(cfg.db_path))
    table.add_row("Files scanned", str(stats.files_scanned))
    table.add_row("Files indexed", str(stats.files_indexed))
    table.add_row("Files skipped (unchanged)", str(stats.files_skipped))
    table.add_row("Chunks written", str(stats.chunks_written))
    table.add_row("Hierarchy nodes", str(stats.nodes_written))
    table.add_row("Duration", f"{stats.duration_seconds:.3f}s")
    console.print(table)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path containing .lorewiki/config.toml."),
    ] = None,
) -> None:
    """Show index statistics (document count, last index time, db size)."""
    cfg = _resolve_config(path)
    db_path = cfg.db_path
    assert db_path is not None
    if not db_path.exists():
        console.print(
            f"[yellow]No index found at[/yellow] {db_path}\n"
            f"Run [cyan]lorewiki index[/cyan] first."
        )
        raise typer.Exit(code=1)

    db_size = db_path.stat().st_size
    with open_db(db_path, auto_init=False) as conn:
        doc_count = conn.execute("SELECT COUNT(DISTINCT doc_path) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        node_count = conn.execute("SELECT COUNT(*) FROM hierarchy").fetchone()[0]
        last_indexed = get_meta(conn, "last_indexed_at", "(never)")
        wiki_path_meta = get_meta(conn, "wiki_path", str(cfg.wiki_path))

        modules = conn.execute(
            "SELECT module, COUNT(*) AS c FROM documents "
            "WHERE module IS NOT NULL GROUP BY module ORDER BY module"
        ).fetchall()

    table = Table(title="LoreWiki status", show_header=False, box=None)
    table.add_row("Wiki path", wiki_path_meta)
    table.add_row("Database", f"{db_path}  ({_human_bytes(db_size)})")
    table.add_row("Documents", str(doc_count))
    table.add_row("Chunks", str(chunk_count))
    table.add_row("Hierarchy nodes", str(node_count))
    table.add_row("Last indexed", last_indexed)
    table.add_row("Retrieval mode", cfg.retrieval_mode)
    table.add_row("LLM backend", cfg.llm.backend if cfg.llm.enabled else "[dim](disabled)[/dim]")
    console.print(table)

    if modules:
        mtable = Table(title="Documents per module", show_lines=False)
        mtable.add_column("Module", style="cyan")
        mtable.add_column("Chunks", justify="right")
        for m in modules:
            mtable.add_row(m["module"], str(m["c"]))
        console.print(mtable)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    top_k: Annotated[int, typer.Option("--top-k", "-k", help="Number of results.")] = 5,
    mode: Annotated[
        str | None,
        typer.Option("--mode", "-m", help="Retrieval mode: mix | bm25 | hierarchy | vector."),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
    human: Annotated[
        bool,
        typer.Option(
            "--human",
            help="Render a Rich Table for human eyes. Default is JSON for agents.",
        ),
    ] = False,
) -> None:
    """Search the wiki and return top-k matching chunks.

    The default output is structured JSON, designed for downstream agents
    (opencode, claude code, custom scripts). Humans usually want
    ``lorewiki ask`` instead — it wraps the same retrieval with an LLM
    synthesis and Markdown rendering. Use ``--human`` here only when you
    want to eyeball raw retrieval hits in the terminal.
    """
    cfg = _resolve_config(path)
    db_path = cfg.db_path
    assert db_path is not None
    if not db_path.exists():
        console.print(
            f"[red]No index found at[/red] {db_path}\n"
            f"Run [cyan]lorewiki index[/cyan] first."
        )
        raise typer.Exit(code=1)

    # CLI --mode wins; otherwise honor the project config's
    # retrieval_mode; otherwise fall back to bm25.
    effective_mode = (mode or cfg.retrieval_mode or "bm25").lower()
    hits = _run_search(cfg, query, mode=effective_mode, top_k=top_k)

    if not human:
        payload = [
            {
                "chunk_id": h.chunk_id,
                "doc_path": h.doc_path,
                "title": h.title,
                "heading_path": h.heading_path,
                "module": h.module,
                "snippet": h.snippet,
                "score": h.score,
                "retriever": h.retriever,
            }
            for h in hits
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if not hits:
        console.print(f"[yellow]No results for[/yellow] [bold]{query}[/bold]")
        return

    console.print(
        Panel(f"[bold]{query}[/bold]", title=f"top {len(hits)} results", border_style="cyan")
    )
    for i, h in enumerate(hits, start=1):
        head = (
            f"[bold]{i}.[/bold] [cyan]{h.heading_path or h.title}[/cyan]  "
            f"[dim]({h.doc_path})[/dim]  "
            f"[green]score={h.score:.3f}[/green]  "
            f"[magenta]{h.retriever}[/magenta]"
        )
        console.print(head)
        console.print(Markdown((h.snippet or "").replace("<<", "**").replace(">>", "**")))
        console.print()


# ---------------------------------------------------------------------------
# update (placeholder, phase 6)
# ---------------------------------------------------------------------------


@app.command()
def update(
    watch: Annotated[
        bool,
        typer.Option("--watch", help="Watch for file changes and re-index incrementally."),
    ] = False,
) -> None:
    """Incrementally update the index."""
    _phase_pending("update", "phase 6 (incremental enhancements)")


# ---------------------------------------------------------------------------
# ask / ui / mcp / rest (still pending)
# ---------------------------------------------------------------------------


@app.command()
def ask(
    query: Annotated[str, typer.Argument(help="Question to answer.")],
    top_k: Annotated[
        int, typer.Option("--top-k", "-k", help="Number of context chunks to retrieve.")
    ] = 5,
    model: Annotated[
        str | None,
        typer.Option("--model", help="LLM backend override (ollama | openai)."),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Print the answer + hits as JSON."),
    ] = False,
) -> None:
    """Retrieve relevant chunks and ask the LLM to compose an answer.

    Gracefully degrades to "show the top chunks" if the LLM is disabled or
    unreachable, so the command always returns useful output.
    """
    cfg = _resolve_config(path)
    if cfg.db_path is None or not cfg.db_path.exists():
        console.print(
            f"[red]No index found at[/red] {cfg.db_path}\n"
            f"Run [cyan]lorewiki index[/cyan] first."
        )
        raise typer.Exit(code=1)

    # CLI `--model` lets the user flip the backend without editing the config
    # file (handy for `ollama` vs `openai` ad-hoc tests).
    if model:
        override_cfg = cfg.model_copy(deep=True)
        override_cfg.llm.enabled = True
        override_cfg.llm.backend = model  # type: ignore[assignment]
        cfg = override_cfg

    generator = AnswerGenerator(cfg)
    answer = generator.ask(query, top_k=top_k)

    if raw:
        payload = {
            "question": answer.question,
            "answer": answer.text,
            "used_llm": answer.used_llm,
            "backend": answer.backend,
            "model": answer.model,
            "prompt_tokens": answer.prompt_tokens,
            "completion_tokens": answer.completion_tokens,
            "degraded_reason": answer.degraded_reason,
            "hits": [
                {
                    "chunk_id": h.chunk_id,
                    "doc_path": h.doc_path,
                    "heading_path": h.heading_path,
                    "score": h.score,
                    "retriever": h.retriever,
                }
                for h in answer.hits
            ],
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    title = (
        f"Answer  [dim](backend={answer.backend}, model={answer.model})[/dim]"
        if answer.used_llm
        else f"Answer  [yellow](degraded: {answer.degraded_reason})[/yellow]"
    )
    console.print(Panel(Markdown(answer.text), title=title, border_style="cyan"))

    if answer.hits:
        ref_table = Table(title="Sources", show_lines=False)
        ref_table.add_column("#", style="dim", width=3)
        ref_table.add_column("Doc", style="cyan")
        ref_table.add_column("Section", style="green")
        ref_table.add_column("Score", justify="right", style="magenta")
        for i, h in enumerate(answer.hits, start=1):
            ref_table.add_row(
                str(i),
                h.doc_path,
                h.heading_path or "",
                f"{h.score:.3f}",
            )
        console.print(ref_table)


@app.command()
def mcp(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
) -> None:
    """Start the MCP stdio server.

    Designed to be launched by an MCP-aware client (Claude Desktop, Cursor,
    custom tool-calling agents) — the client speaks JSON-RPC over our stdin
    and listens on our stdout, so this command never prints panels or logs
    to stdout.
    """
    try:
        from lorewiki.server.mcp_server import run as run_mcp  # noqa: PLC0415
    except ImportError as exc:
        # Send the error to stderr so it doesn't corrupt the JSON-RPC stream.
        import sys  # noqa: PLC0415

        sys.stderr.write(
            "MCP server requires the 'mcp' extra: pip install lorewiki[mcp]\n"
            f"(missing: {exc.name})\n"
        )
        raise typer.Exit(code=1) from exc

    cfg = _resolve_config(path)
    run_mcp(cfg)


@app.command()
def rest(
    port: Annotated[int, typer.Option("--port", "-P", help="Port for the FastAPI server.")] = 8000,
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
) -> None:
    """Start the FastAPI REST server."""
    try:
        from lorewiki.server.rest_api import serve  # noqa: PLC0415
    except ImportError as exc:
        console.print(
            "[red]REST server requires the 'rest' extra:[/red] "
            "[cyan]pip install lorewiki[rest][/cyan]\n"
            f"(missing: {exc.name})"
        )
        raise typer.Exit(code=1) from exc

    cfg = _resolve_config(path)
    console.print(
        Panel(
            f"[green]LoreWiki REST API[/green] starting on "
            f"[bold]http://{host}:{port}[/bold]\n"
            f"OpenAPI docs: [cyan]http://{host}:{port}/docs[/cyan]\n"
            f"Wiki: [dim]{cfg.wiki_path}[/dim]",
            title="lorewiki rest",
            border_style="green",
        )
    )
    serve(host=host, port=port, cfg=cfg)


# ---------------------------------------------------------------------------
# clean / show / tree
# ---------------------------------------------------------------------------


@app.command()
def clean(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Report what would change, but do not write to disk.",
        ),
    ] = False,
    no_backup: Annotated[
        bool,
        typer.Option(
            "--no-backup",
            help="Skip the safety backup. (You will not be able to roll back.)",
        ),
    ] = False,
) -> None:
    """Rewrite on-disk .md files to drop scraper boilerplate.

    The indexer already cleans at index time, so ``search`` and ``tree``
    return clean output regardless. This command is for users who want
    the **on-disk vault** to look clean too — i.e. when they open the
    topic folder in Obsidian / Logseq, the files have no translation
    footer, no ``[\\#​](#anchor)`` heading markup, no ``> 基础库 X.X.X
    开始支持`` blockquote, and no ``.html`` suffix on internal links.

    A timestamped backup of every changed file is written to
    ``<wiki>/.lorewiki/clean-backup/<UTC-timestamp>/<relative-path>``
    unless ``--no-backup`` is given.

    Reindex after running this so the SQLite index reflects the new
    file contents (``lorewiki index`` is incremental).
    """
    from lorewiki.indexer.cleaning import clean_markdown_file

    cfg = _resolve_config(path)
    if not cfg.wiki_path.exists() or not cfg.wiki_path.is_dir():
        console.print(f"[red]wiki path not found:[/red] {cfg.wiki_path}")
        raise typer.Exit(code=2)
    files = iter_markdown_files(cfg.wiki_path)
    if not files:
        console.print("[yellow]no markdown files found under[/yellow] " + str(cfg.wiki_path))
        raise typer.Exit(code=0)

    backup_root: Path | None = None
    if not dry_run and not no_backup:
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_root = cfg.wiki_path / ".lorewiki" / "clean-backup" / stamp
        backup_root.mkdir(parents=True, exist_ok=True)

    changed = 0
    unchanged = 0
    errored = 0
    for md_path in files:
        try:
            original = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("read failed {}: {}", md_path, exc)
            errored += 1
            continue
        cleaned = clean_markdown_file(original)
        if cleaned == original:
            unchanged += 1
            continue
        changed += 1
        if dry_run:
            continue
        if backup_root is not None:
            rel = md_path.relative_to(cfg.wiki_path)
            backup_path = backup_root / rel
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                backup_path.write_text(original, encoding="utf-8")
            except OSError as exc:
                log.warning("backup failed {}: {}", backup_path, exc)
                errored += 1
                continue
        try:
            md_path.write_text(cleaned, encoding="utf-8")
        except OSError as exc:
            log.warning("write failed {}: {}", md_path, exc)
            errored += 1

    summary = Table(title="lorewiki clean", show_header=False)
    summary.add_row("Files scanned", str(len(files)))
    summary.add_row("Changed", f"[green]{changed}[/green]" if changed else "0")
    summary.add_row("Unchanged", str(unchanged))
    if errored:
        summary.add_row("Errors", f"[red]{errored}[/red]")
    summary.add_row("Mode", "dry-run (no files written)" if dry_run else "wrote in place")
    if backup_root is not None:
        summary.add_row("Backup", str(backup_root))
    console.print(summary)
    if changed and not dry_run:
        console.print(
            "\n[dim]Hint: run[/dim] [cyan]lorewiki index[/cyan] [dim]to refresh "
            "the SQLite index from the rewritten files.[/dim]"
        )


@app.command()
def show(
    doc_path: Annotated[
        str,
        typer.Argument(..., help="Relative path inside the wiki, e.g. api/share/wx.showShareMenu.md"),
    ],
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Print the on-disk .md verbatim (no cleaning)."),
    ] = False,
) -> None:
    """Print a single document's body (cleaned by default)."""
    cfg = _resolve_config(path)
    if cfg.db_path is None or not cfg.db_path.exists():
        console.print("[red]No index found. Run `lorewiki index` first.[/red]")
        raise typer.Exit(code=2)
    with open_db(cfg.db_path, auto_init=False) as conn:
        row = conn.execute(
            "SELECT doc_path, title, heading_path, module, content "
            "FROM documents WHERE doc_path = ? ORDER BY chunk_index LIMIT 1",
            (doc_path,),
        ).fetchone()
        if row is None:
            console.print(f"[red]doc not found:[/red] {doc_path}")
            raise typer.Exit(code=3)
        # Re-read the body. If the user wants the on-disk .md (with scraper
        # boilerplate), we go through the parser. Otherwise we render the
        # cleaned body that was indexed.
        if raw:
            from lorewiki.indexer.parser import parse_markdown

            abs_path = cfg.wiki_path / doc_path
            if not abs_path.exists():
                console.print(f"[red]file not found:[/red] {abs_path}")
                raise typer.Exit(code=4)
            try:
                parsed = parse_markdown(abs_path, rel_to=cfg.wiki_path)
            except (OSError, UnicodeDecodeError) as exc:
                console.print(f"[red]read failed:[/red] {exc}")
                raise typer.Exit(code=4) from exc
            console.print(f"--- [dim]{doc_path}[/dim] ---")
            console.print(parsed.body.rstrip())
        else:
            console.print(
                f"# {cleaning.clean_title(row['title'])}\n"
                f"\n"
                f"[dim]doc:[/dim] {row['doc_path']}\n"
                f"[dim]module:[/dim] {row['module']}\n"
                f"[dim]heading:[/dim] {cleaning.clean_heading_path(row['heading_path'])}\n"
            )
            # The stored content has the [heading_path] breadcrumb prefix
            # baked in for FTS recall. We strip it for display so users see
            # the body as it would render in Obsidian.
            body = cleaning.strip_breadcrumb_prefix(row["content"])
            body = cleaning.strip_translation_footer(body)
            console.print(body.rstrip())


@app.command()
def tree(
    prefix: Annotated[
        str | None,
        typer.Argument(help="Limit the tree to a sub-path, e.g. 'api/share'."),
    ] = None,
    depth: Annotated[
        int | None,
        typer.Option("--depth", "-d", help="Limit depth (None = unlimited)."),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
) -> None:
    """Print the wiki hierarchy as a tree."""
    cfg = _resolve_config(path)
    if cfg.db_path is None or not cfg.db_path.exists():
        console.print("[red]No index found. Run `lorewiki index` first.[/red]")
        raise typer.Exit(code=2)
    with open_db(cfg.db_path, auto_init=False) as conn:
        if prefix:
            root = conn.execute(
                "SELECT id, parent_id, title, level FROM hierarchy WHERE path = ?",
                (prefix,),
            ).fetchone()
            if root is None:
                console.print(f"[red]prefix not found:[/red] {prefix}")
                raise typer.Exit(code=3)
        else:
            root = conn.execute(
                "SELECT id, parent_id, title, level FROM hierarchy WHERE id = '__root__'"
            ).fetchone()
        # BFS to build tree.
        all_nodes = conn.execute(
            "SELECT id, parent_id, title, level, node_type, path FROM hierarchy"
        ).fetchall()
        children: dict[str | None, list[Any]] = {}
        for n in all_nodes:
            children.setdefault(n["parent_id"], []).append(n)
        # The root may not actually be in the all_nodes result if the
        # synthetic __root__ is the parent_id we use.
        children.setdefault("__root__", [])

        def _walk(node_id: str, current_depth: int, prefix_str: str, is_last: bool) -> None:
            node = next((n for n in all_nodes if n["id"] == node_id), None) if node_id != "__root__" else None
            if node is None and node_id == "__root__":
                label = "[bold]LoreWiki[/bold]"
            elif node is None:
                return
            else:
                marker = "📄" if node["node_type"] == "doc" else "📁"
                label = f"{marker} {cleaning.clean_title(node['title'])}"
            if node_id != "__root__":
                connector = "└── " if is_last else "├── "
                console.print(f"{prefix_str}{connector}{label}")
                new_prefix = prefix_str + ("    " if is_last else "│   ")
            else:
                console.print(label)
                new_prefix = ""
            if depth is not None and current_depth >= depth:
                return
            kids = sorted(
                children.get(node_id, []),
                key=lambda k: (k["node_type"] != "module", k["path"]),
            )
            for i, kid in enumerate(kids):
                _walk(kid["id"], current_depth + 1, new_prefix, i == len(kids) - 1)

        _walk("__root__", 0, "", True)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@config_app.command("list")
def config_list(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
) -> None:
    """List all configuration values."""
    cfg = _resolve_config(path)
    table = Table(title="LoreWiki configuration", show_lines=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    for key, val in _flatten_config(cfg).items():
        table.add_row(key, _format_value(val))
    console.print(table)


@config_app.command("get")
def config_get(
    key: Annotated[str, typer.Argument(help="Config key to read (dotted, e.g. llm.backend).")],
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
) -> None:
    """Print a single configuration value."""
    cfg = _resolve_config(path)
    flat = _flatten_config(cfg)
    if key not in flat:
        console.print(f"[red]unknown key:[/red] {key}")
        raise typer.Exit(code=1)
    typer.echo(_format_value(flat[key]))


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Config key to write (dotted).")],
    value: Annotated[str, typer.Argument(help="New value (parsed as TOML literal).")],
    path: Annotated[
        str | None,
        typer.Option(
            "--path", "-p",
            help="Project / wiki path. Defaults to the discovered project config.",
        ),
    ] = None,
) -> None:
    """Update a configuration value and persist it to the project config file."""
    cfg = _resolve_config(path)
    flat = _flatten_config(cfg)
    if key not in flat:
        console.print(f"[red]unknown key:[/red] {key}")
        raise typer.Exit(code=1)
    parsed_value = _parse_toml_literal(value)
    nested = _unflatten({key: parsed_value})

    project_dir = (Path(path).expanduser().resolve() if path else _discover_project_dir(cfg))
    target = project_dir / ".lorewiki" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)

    # Merge with whatever already lives in the project config file.
    existing = _safe_load_toml(target) if target.exists() else {}
    merged = _deep_merge(existing, nested)
    new_cfg = LoreWikiConfig(**merged)
    save_config(new_cfg, target)
    console.print(f"[green]set[/green] {key} = {parsed_value!r}  ->  {target}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _resolve_config(path_arg: str | None) -> LoreWikiConfig:
    """Build a :class:`LoreWikiConfig` honouring the optional --path argument."""
    if path_arg:
        project = Path(path_arg).expanduser().resolve()
        overrides: dict[str, Any] = {"wiki_path": str(project)}
        return load_config(project_dir=project, overrides=overrides)
    return load_config()


SUPPORTED_MODES = {"bm25", "hierarchy", "mix", "vector"}


def _run_search(
    cfg: LoreWikiConfig,
    query: str,
    *,
    mode: str,
    top_k: int,
) -> list[Any]:
    """Dispatch ``mode`` to one or more retrievers and return ordered hits."""
    if mode not in SUPPORTED_MODES:
        console.print(f"[red]Unknown retrieval mode:[/red] {mode}")
        raise typer.Exit(code=2)

    retrievers: dict[str, BaseRetriever] = {
        "bm25": BM25Retriever.from_config(cfg),
        "hierarchy": HierarchyRetriever.from_config(cfg),
    }
    if mode == "vector":
        # Vector retrieval is scheduled for phase 6; silently fall back
        # to mix so JSON consumers don't have to parse warning text.
        mode = "mix"

    if mode in {"bm25", "hierarchy"}:
        return list(retrievers[mode].search(query, top_k=top_k))

    # mix mode → run all available retrievers, fuse via RRF.
    per_retriever = {
        name: list(r.search(query, top_k=top_k * 2)) for name, r in retrievers.items()
    }
    fuser = RRFFusion(
        k=cfg.rrf_k,
        weights={
            "bm25": cfg.mix_weights.bm25,
            "hierarchy": cfg.mix_weights.hierarchy,
            "vector": cfg.mix_weights.vector,
        },
    )
    return list(fuser.fuse(per_retriever, top_k=top_k))


def _discover_project_dir(cfg: LoreWikiConfig) -> Path:
    """Return the directory that should host ``.lorewiki/config.toml``."""
    # Prefer cwd if a project config already exists there; otherwise default
    # to the configured wiki_path so init/index/status share one config file.
    cwd_candidate = Path.cwd() / ".lorewiki" / "config.toml"
    if cwd_candidate.exists():
        return Path.cwd()
    return cfg.wiki_path


def _flatten_config(cfg: LoreWikiConfig) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    raw = cfg.model_dump(mode="json", exclude_none=False)

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        else:
            flat[prefix] = value

    walk("", raw)
    return flat


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "(none)"
    return json.dumps(value, ensure_ascii=False)


def _parse_toml_literal(raw: str) -> Any:
    """Parse a CLI-provided value as a TOML right-hand-side."""
    if sys.version_info >= (3, 11):
        import tomllib as _toml  # noqa: PLC0415
    else:  # pragma: no cover
        import tomli as _toml  # noqa: PLC0415
    try:
        return _toml.loads(f"v = {raw}")["v"]
    except _toml.TOMLDecodeError:
        # Fall back to bare string.
        return raw


def _unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dotted, value in flat.items():
        parts = dotted.split(".")
        cursor = out
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return out


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _safe_load_toml(path: Path) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib as _toml  # noqa: PLC0415
    else:  # pragma: no cover
        import tomli as _toml  # noqa: PLC0415
    try:
        return _toml.loads(path.read_text(encoding="utf-8"))
    except _toml.TOMLDecodeError:
        return {}


def _human_bytes(num: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(num)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num} B"


def _phase_pending(command: str, phase: str) -> None:
    """Print a clear "not yet implemented" message and exit with code 2."""
    panel = Panel(
        f"[yellow]Command [bold]'{command}'[/bold] is not yet implemented.[/yellow]\n"
        f"Scheduled for [bold cyan]{phase}[/bold cyan].",
        title="LoreWiki - phase pending",
        border_style="yellow",
    )
    console.print(panel)
    raise typer.Exit(code=2)


def print_phase_status() -> None:
    """Helper for tests and `python -m lorewiki info` (added in later phases)."""
    table = Table(title="LoreWiki phase status", show_lines=False)
    table.add_column("Phase", style="cyan")
    table.add_column("Status", style="green")
    table.add_row("0  bootstrap / CLI skeleton", "done")
    table.add_row("1  index + BM25 search", "done")
    table.add_row("2  hierarchy + RRF fusion", "pending")
    table.add_row("3  LLM integration", "pending")
    table.add_row("4  REST + packaging", "pending")
    table.add_row("5  MCP server + packaging", "pending")
    console.print(table)


# ---------------------------------------------------------------------------
# topic (Phase 6: second-brain / vault management)
# ---------------------------------------------------------------------------


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
    panel_body = (
        f"[bold]name[/bold]    : {info.name}\n"
        f"[bold]name[/bold]    : {info.name}\n"
        f"[bold]root[/bold]   : {info.root}\n"
        f"[bold]wiki[/bold]   : {info.wiki_path}"
        f"{' (linked)' if info.source_link else ''}\n"
        f"[bold]db[/bold]     : {info.db_path}"
        f"  ({'indexed' if db_present else 'empty'}, {_human_bytes(db_size)})\n"
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


# ---------------------------------------------------------------------------
# Prepend the ASCII banner to every `--help` output (root + subcommands).
#
# typer wraps each :class:`Typer` in a click.Group at first dispatch, so
# the `get_help` method only materialises on the instance. We don't need
# to read it back from the instance — we just rebind it to a wrapper that
# delegates to click.Group's reference implementation.
# ---------------------------------------------------------------------------
import click as _click  # noqa: E402


def _get_help_with_banner(self: typer.Typer, ctx: typer.Context) -> str:  # type: ignore[override]
    return _BANNER_HELP + _click.Group.get_help(self, ctx)


app.get_help = _get_help_with_banner  # type: ignore[method-assign]


__all__ = ["app", "print_phase_status"]
