"""``lorewiki delete`` — remove a knowledge note and clean up its index rows.

The command takes a ``doc_path`` (relative to the wiki root),
optionally prompts for confirmation (skip with ``--force``), unlinks
the file, purges the doc's stale chunks from the SQLite index, then
runs an incremental ``build_index`` to refresh the hierarchy.

Why the explicit DB purge? ``build_index(rebuild=False)`` only walks
files that **still exist on disk** — it has no way to learn about a
file that was just deleted, so without this cleanup the deleted doc's
chunks would linger in the ``documents`` table and ``search`` would
keep returning them. The ``hierarchy`` table is rebuilt from scratch
on every ``build_index`` run, so it needs no manual purge here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel

from lorewiki.cli.add import _is_safe_target, _resolve_wiki_root
from lorewiki.cli.apps import app, console, log
from lorewiki.cli.helpers import resolve_config, resolve_doc_target
from lorewiki.db import open_db
from lorewiki.indexer import build_index

# ---------------------------------------------------------------------------
# Stale-row purge
# ---------------------------------------------------------------------------


def _purge_doc_rows(db_path: Path, doc_path_db: str) -> None:
    """Delete the stale ``documents`` rows for a removed file.

    Best-effort: if the DB / table is missing or the call fails, we
    log and let the subsequent ``build_index`` reconcile state. The
    ``hierarchy`` table is rebuilt from scratch by ``build_index`` so
    it does not need a manual purge here.
    """
    try:
        with open_db(db_path, auto_init=False) as conn:
            conn.execute("DELETE FROM documents WHERE doc_path = ?", (doc_path_db,))
            conn.commit()
    except Exception as exc:
        log.warning("pre-reindex purge failed for {}: {}", doc_path_db, exc)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _emit_delete_result(
    target: Path, doc_path_db: str, *, raw: bool
) -> None:
    """Print the success Panel (or ``--raw`` JSON) for a completed delete."""
    if raw:
        typer.echo(
            json.dumps(
                {"ok": True, "path": str(target), "doc_path": doc_path_db},
                ensure_ascii=False,
            )
        )
        return
    console.print(
        Panel(
            f"[green]deleted[/green] [bold]{target}[/bold]\n"
            f"  doc_path: {doc_path_db}\n\n"
            f"Search will no longer return this document.",
            title="lorewiki delete",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@app.command()
def delete(
    doc_path: Annotated[
        str,
        typer.Argument(
            help="Relative path of the doc to delete (e.g. 'patterns/python-design.md').",
        ),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", help="Skip the confirmation prompt."),
    ] = False,
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
    topic: Annotated[
        str | None,
        typer.Option(
            "--topic",
            "-T",
            help="Topic name. Delete from this topic's vault instead of the active topic. "
            "Use this when the note belongs to a specific second-brain topic "
            "(e.g. '--topic warm-kitchen-time' for project-specific notes, "
            "'--topic shared' for cross-project patterns).",
        ),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Emit a machine-readable JSON object on success."),
    ] = False,
) -> None:
    """Delete a knowledge note and re-index the wiki.

    Prompts for confirmation unless ``--force`` is given. After the
    file is removed, the doc's stale index rows are purged and an
    incremental ``build_index`` refreshes the hierarchy.
    """
    # ---- 1. resolve paths ---------------------------------------------------
    wiki_root = _resolve_wiki_root(path, topic_arg=topic)
    if not wiki_root.is_dir():
        console.print(f"[red]wiki path not found:[/red] {wiki_root}")
        raise typer.Exit(code=2)

    target = resolve_doc_target(doc_path, wiki_root)

    # ---- 2. path-traversal safety net -------------------------------------
    if not _is_safe_target(wiki_root, target):
        console.print(
            Panel(
                f"[red]Refusing to delete outside the wiki root:[/red]\n"
                f"  target:  {target}\n"
                f"  wiki:    {wiki_root}\n"
                f"Pass a doc_path inside the wiki.",
                title="path-traversal blocked",
                border_style="red",
            )
        )
        raise typer.Exit(code=3)

    # ---- 3. existence check ------------------------------------------------
    if not target.exists() or not target.is_file():
        console.print(
            Panel(
                f"[red]Document not found:[/red] {target}\n"
                f"Nothing to delete.",
                title="lorewiki delete",
                border_style="red",
            )
        )
        raise typer.Exit(code=4)

    # ---- 4. confirm --------------------------------------------------------
    if not force:
        confirmed = typer.confirm(f"Delete {target}?", default=False)
        if not confirmed:
            console.print("[yellow]aborted[/yellow]")
            raise typer.Exit(code=0)

    # ---- 5. compute DB doc_path + delete file ------------------------------
    # If --topic was given, override the cfg.db_path so build_index and
    # the DB purge target the right topic vault.
    if topic is not None and topic.strip():
        from lorewiki.config import load_config as _delete_load_config  # noqa: PLC0415
        cfg = _delete_load_config(overrides={"topic": topic.strip()})
    else:
        cfg = resolve_config(path)
    # Resolve with strict=True (file confirmed to exist above) so the
    # relative path matches the exact on-disk casing the indexer stored
    # (Windows is case-insensitive on the FS layer but the DB stores the
    # indexer's spelling verbatim).
    try:
        rel = target.resolve(strict=True).relative_to(wiki_root.resolve(strict=True))
        doc_path_db = rel.as_posix()
    except ValueError:
        # Safety net: should be unreachable after the _is_safe_target
        # check, but guard so a weird path never crashes the command.
        doc_path_db = target.name

    try:
        target.unlink()
    except OSError as exc:
        log.error("delete failed {}: {}", target, exc)
        console.print(f"[red]delete failed:[/red] {exc}")
        raise typer.Exit(code=5) from exc

    # ---- 6. purge stale index rows + re-index ------------------------------
    if cfg.db_path is not None and cfg.db_path.exists():
        _purge_doc_rows(cfg.db_path, doc_path_db)

    try:
        build_index(cfg, rebuild=False)
    except Exception as exc:
        log.warning("post-delete reindex failed: {}", exc)
        console.print(
            f"[yellow]warning: reindex failed[/yellow] (the file is gone, "
            f"but you may want to run `lorewiki index`): {exc}"
        )

    # ---- 7. output ---------------------------------------------------------
    _emit_delete_result(target, doc_path_db, raw=raw)


__all__ = ["delete"]
