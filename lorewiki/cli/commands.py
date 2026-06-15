"""Top-level lorewiki sub-commands (init, index, status, search, ask, show, tree, clean).

Importing this module is what triggers Typer to register the
``@app.command()`` decorators on the shared :data:`app` instance from
:mod:`lorewiki.cli.apps`. The :mod:`lorewiki.cli.__init__` re-exports
the subcommand modules so any single import of the package is enough
to make the CLI fully functional.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from lorewiki.cli.apps import app, console, log
from lorewiki.cli.helpers import (
    human_bytes,
    phase_pending,
    resolve_config,
)
from lorewiki.config import LoreWikiConfig, save_config
from lorewiki.db import get_meta, open_db
from lorewiki.indexer import build_index, cleaning, iter_markdown_files
from lorewiki.indexer.cleaning import clean_markdown_file
from lorewiki.indexer.parser import parse_markdown
from lorewiki.llm import AnswerGenerator
from lorewiki.retriever import run_search

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
    cfg = resolve_config(path)
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
    cfg = resolve_config(path)
    db_path = cfg.db_path
    if db_path is None:
        msg = "LoreWikiConfig.db_path must be resolved before status()"
        raise ValueError(msg)
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
    table.add_row("Database", f"{db_path}  ({human_bytes(db_size)})")
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
    cfg = resolve_config(path)
    db_path = cfg.db_path
    if db_path is None:
        msg = "LoreWikiConfig.db_path must be resolved before search()"
        raise ValueError(msg)
    if not db_path.exists():
        console.print(
            f"[red]No index found at[/red] {db_path}\n"
            f"Run [cyan]lorewiki index[/cyan] first."
        )
        raise typer.Exit(code=1)

    # CLI --mode wins; otherwise honor the project config's
    # retrieval_mode; otherwise fall back to bm25.
    effective_mode = (mode or cfg.retrieval_mode or "bm25").lower()
    hits = run_search(cfg, query, mode=effective_mode, top_k=top_k)

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
    phase_pending("update", "phase 6 (incremental enhancements)")


# ---------------------------------------------------------------------------
# ask
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
    cfg = resolve_config(path)
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
    footer, no ``[\\#\u200b](#anchor)`` heading markup, no ``> 基础库 X.X.X
    开始支持`` blockquote, and no ``.html`` suffix on internal links.

    A timestamped backup of every changed file is written to
    ``<wiki>/.lorewiki/clean-backup/<UTC-timestamp>/<relative-path>``
    unless ``--no-backup`` is given.

    Reindex after running this so the SQLite index reflects the new
    file contents (``lorewiki index`` is incremental).
    """
    cfg = resolve_config(path)
    if not cfg.wiki_path.exists() or not cfg.wiki_path.is_dir():
        console.print(f"[red]wiki path not found:[/red] {cfg.wiki_path}")
        raise typer.Exit(code=2)
    files = iter_markdown_files(cfg.wiki_path)
    if not files:
        console.print("[yellow]no markdown files found under[/yellow] " + str(cfg.wiki_path))
        raise typer.Exit(code=0)

    backup_root: Path | None = None
    if not dry_run and not no_backup:
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
        typer.Argument(..., help="Relative path inside the wiki, e.g. 'api/share/foo.md'."),
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
    cfg = resolve_config(path)
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
    cfg = resolve_config(path)
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
            if node_id == "__root__":
                node = None
            else:
                node = next((n for n in all_nodes if n["id"] == node_id), None)
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


__all__ = [
    "ask",
    "clean",
    "index",
    "init",
    "search",
    "show",
    "status",
    "tree",
    "update",
]
