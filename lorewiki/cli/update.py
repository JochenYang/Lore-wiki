"""``lorewiki update`` — modify an existing knowledge note in place.

Mirrors :mod:`lorewiki.cli.add` but targets an existing file: pass a
``doc_path`` (relative to the wiki root) plus any subset of
``--body`` / ``--file`` / stdin / ``--title`` / ``--module`` /
``--tag`` overrides. Omitted options preserve the existing value, so
you can update just the body, just the title, or any combination.

``created_at`` is always preserved (carried over from the existing
frontmatter, or seeded to today for legacy docs that lack it);
``last_review`` is refreshed to today. Extra frontmatter fields the
user may have added manually (``owner``, custom keys) are preserved
too — only the well-known fields are touched.

After a successful write, an incremental ``build_index`` runs so the
change is immediately retrievable via ``lorewiki search``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import frontmatter
import typer
from rich.panel import Panel

from lorewiki.cli.add import (
    _is_safe_target,
    _resolve_wiki_root,
    _strip_surrogates,
    slugify,
)
from lorewiki.cli.apps import app, console, log
from lorewiki.cli.helpers import resolve_config, resolve_doc_target
from lorewiki.indexer import build_index

# ---------------------------------------------------------------------------
# Body acquisition (optional variant of add._read_body)
# ---------------------------------------------------------------------------


def _read_body_optional(body: str | None, file: Path | None) -> str | None:
    """Read new body text if any source provides content; return None otherwise.

    Unlike :func:`lorewiki.cli.add._read_body`, returning ``None`` is a
    valid outcome meaning "keep the existing body" — the update command
    treats a missing body as a no-op on the body field.

    Priority / behaviour mirrors :func:`_read_body`: ``--body`` →
    ``--file`` → ``sys.stdin`` (when not a TTY). The caller is
    responsible for the lone-surrogate scrub via
    :func:`_strip_surrogates` — kept out of this helper so it stays a
    single-responsibility mirror of the add path.
    """
    if body is not None and body.strip():
        return body.rstrip() + "\n"
    if file is not None:
        return file.read_text(encoding="utf-8").rstrip() + "\n"
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return data.rstrip() + "\n"
    return None


# ---------------------------------------------------------------------------
# Frontmatter merge
# ---------------------------------------------------------------------------


def _merge_metadata(
    existing: dict[str, Any],
    *,
    title: str | None,
    module: str | None,
    tag: list[str] | None,
    target_stem: str,
) -> dict[str, Any]:
    """Return a frontmatter dict with only the overridden fields changed.

    Carries over every existing key (including user-added extras like
    ``owner``) so ``update`` never silently drops metadata.
    ``created_at`` is preserved (or initialised to today if the legacy
    doc had none); ``last_review`` is always refreshed to reflect the
    edit.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    merged: dict[str, Any] = dict(existing)

    # Title: override if a non-empty value was passed; else keep the
    # existing one; else fall back to the filename stem so the
    # frontmatter always carries a usable title.
    if title and title.strip():
        merged["title"] = title.strip()
    elif "title" not in merged or not merged["title"]:
        merged["title"] = target_stem

    # Module: slugify on override (same rules as `add`); else leave the
    # existing value (or its absence) untouched so the indexer's
    # directory fallback still applies.
    if module is not None and module.strip():
        merged["module"] = slugify(module)

    # Tags: --tag replaces the whole list when passed; else preserve.
    if tag is not None:
        merged["tags"] = list(tag)
    elif "tags" not in merged:
        merged["tags"] = []

    # Timestamps: created_at preserved (or seeded), last_review refreshed.
    merged.setdefault("created_at", today)
    merged["last_review"] = today
    return merged


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _emit_update_result(
    target: Path, wiki_root: Path, merged: dict[str, Any], *, raw: bool
) -> None:
    """Print the success Panel (or ``--raw`` JSON) for a completed update."""
    final_title = str(merged.get("title", target.stem))
    final_module = str(merged.get("module", "(none)"))
    final_tags = list(merged.get("tags") or [])
    if raw:
        typer.echo(
            json.dumps(
                {
                    "ok": True,
                    # ``as_posix()`` so Windows backslashes don't leak into
                    # machine-readable output — cross-platform consistency.
                    "path": target.relative_to(wiki_root).as_posix(),
                    "title": final_title,
                    "module": final_module,
                    "tags": final_tags,
                },
                ensure_ascii=False,
            )
        )
        return
    console.print(
        Panel(
            f"[green]updated[/green] [bold]{target}[/bold]\n"
            f"  title : {final_title}\n"
            f"  module: {final_module}\n"
            f"  tags  : {', '.join(final_tags) if final_tags else '[dim](none)[/dim]'}\n\n"
            f"Try: [cyan]lorewiki search \"{final_title}\"[/cyan]",
            title="lorewiki update",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@app.command()
def update(
    doc_path: Annotated[
        str,
        typer.Argument(
            help="Relative path of the doc to update (e.g. 'patterns/python-design.md').",
        ),
    ],
    body: Annotated[
        str | None,
        typer.Option(
            "--body",
            "-b",
            help="New Markdown body. Mutually exclusive with --file / stdin.",
        ),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option(
            "--file",
            "-f",
            help="Path to a local file to import as the new body.",
        ),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", "-t", help="New document title."),
    ] = None,
    module: Annotated[
        str | None,
        typer.Option("--module", "-m", help="New module / category (slugified)."),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option(
            "--tag",
            help="New tag (may be passed multiple times; replaces existing tags).",
        ),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Project / wiki path."),
    ] = None,
    topic: Annotated[
        str | None,
        typer.Option(
            "--topic",
            "-T",
            help="Topic vault that owns the doc (project topic or 'shared'). "
            "Must match the vault used when the note was created.",
        ),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Emit a machine-readable JSON object on success."),
    ] = False,
) -> None:
    """Modify an existing knowledge note in place and re-index the wiki.

    Only the options you pass are applied; omitted ones preserve the
    existing frontmatter / body. After a successful write, an
    incremental ``build_index`` runs so the change is immediately
    retrievable via ``lorewiki search``.
    """
    # ---- 1. resolve paths ---------------------------------------------------
    wiki_root = _resolve_wiki_root(path, topic_arg=topic)
    if not wiki_root.is_dir():
        console.print(f"[red]wiki path not found:[/red] {wiki_root}")
        raise typer.Exit(code=2)

    # ---- 2. path-traversal safety net -------------------------------------
    try:
        target = resolve_doc_target(doc_path, wiki_root)
    except ValueError as exc:
        console.print(
            Panel(
                f"[red]Refusing to write outside the wiki root:[/red]\n"
                f"  {exc}\n"
                f"Pass a doc_path inside the wiki.",
                title="path-traversal blocked",
                border_style="red",
            )
        )
        raise typer.Exit(code=3) from exc

    if not _is_safe_target(wiki_root, target):
        console.print(
            Panel(
                f"[red]Refusing to write outside the wiki root:[/red]\n"
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
                f"Use [cyan]lorewiki add[/cyan] to create a new note.",
                title="lorewiki update",
                border_style="red",
            )
        )
        raise typer.Exit(code=4)

    # ---- 4. load existing doc + merge metadata -----------------------------
    try:
        # utf-8-sig transparently strips a leading BOM (PowerShell
        # Out-File default) — same rationale as the indexer's parser.
        existing_post = frontmatter.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError) as exc:
        log.error("read failed {}: {}", target, exc)
        console.print(f"[red]read failed:[/red] {exc}")
        raise typer.Exit(code=5) from exc

    merged = _merge_metadata(
        existing_post.metadata,
        title=title,
        module=module,
        tag=tag,
        target_stem=target.stem,
    )

    # ---- 5. body: new content if provided, else preserve original ----------
    # New body (if any source provided) is surrogate-scrubbed; a missing
    # body falls back to the existing content so the user can update
    # frontmatter-only without re-supplying the body.
    new_body = _read_body_optional(body, file)
    new_body = _strip_surrogates(new_body) if new_body is not None else existing_post.content

    # ---- 6. write -----------------------------------------------------------
    post = frontmatter.Post(new_body, **merged)
    try:
        target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    except (OSError, UnicodeEncodeError) as exc:
        log.error("write failed {}: {}", target, exc)
        console.print(f"[red]write failed:[/red] {exc}")
        raise typer.Exit(code=5) from exc

    # ---- 7. re-index --------------------------------------------------------
    try:
        if topic is not None and topic.strip():
            from lorewiki.config import load_config as _update_load_config  # noqa: PLC0415
            cfg = _update_load_config(overrides={"topic": topic.strip()})
        else:
            cfg = resolve_config(path)
        build_index(cfg, rebuild=False)
    except Exception as exc:
        # A failed reindex shouldn't swallow a successful write. Surface
        # the warning and let the user re-run ``lorewiki index`` later.
        log.warning("post-write reindex failed: {}", exc)
        console.print(
            f"[yellow]warning: reindex failed[/yellow] (the file is on disk, "
            f"but you may want to run `lorewiki index`): {exc}"
        )

    # ---- 8. output ---------------------------------------------------------
    _emit_update_result(target, wiki_root, merged, raw=raw)


__all__ = ["update"]
