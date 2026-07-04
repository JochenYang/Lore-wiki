"""``lorewiki add`` — author a single knowledge note from the CLI.

The command takes a title (required) plus optional body/file/stdin
content, module, and tags, and writes a Markdown file with a YAML
frontmatter block into the active wiki. The index is re-built
afterwards so the new doc is immediately retrievable.

Path-traversal safety: the resolved target path is asserted to
live inside the wiki root before any write. Title and module are
slugified via the same rules used elsewhere (ascii / digits /
hyphens; no path separators).
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import frontmatter
import typer
from rich.panel import Panel

from lorewiki.cli.apps import app, console, log
from lorewiki.cli.helpers import resolve_config
from lorewiki.config import load_config
from lorewiki.indexer import build_index
from lorewiki.indexer.patterns import H1_RE

# ---------------------------------------------------------------------------
# Slug + path safety helpers
# ---------------------------------------------------------------------------

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_len: int = 64) -> str:
    """Turn ``"My Note!"`` into ``"my-note"``.

    The slug is used as a filename inside the topic. Rules:
    * Lowercase, ASCII alphanumerics + ``-`` only.
    * Collapse runs of non-alphanumerics into a single ``-``.
    * Trim leading / trailing ``-``.
    * Cap at ``max_len`` chars (default 64) so we don't bust the
      path component limit on Windows.
    """
    text = _SLUG_NON_ALNUM.sub("-", text.lower()).strip("-")
    return text[:max_len] or "untitled"


def _resolve_wiki_root(path_arg: str | None, topic_arg: str | None = None) -> Path:
    """Return the absolute path of the wiki root the add should land in.
    
    If ``topic_arg`` is given, the write always targets that topic's vault
    regardless of the active topic. This lets LLM agents explicitly choose
    which second-brain vault receives the note.
    """
    if topic_arg is not None and topic_arg.strip():
        # Route to a specific topic vault — ignore the active topic.
        cfg = load_config(overrides={"topic": topic_arg.strip()})
    else:
        cfg = resolve_config(path_arg)
    return cfg.wiki_path.resolve()


def _is_safe_target(wiki_root: Path, target: Path) -> bool:
    """True iff ``target`` lives under ``wiki_root`` after resolution.

    Blocks path-traversal attempts like ``--module ../../etc`` — the
    slugified module may still end up containing ``..`` if the
    caller asked for it literally, so we resolve both sides and
    walk the ``Path.parents`` chain.
    """
    try:
        target_resolved = target.resolve(strict=False)
    except OSError:
        return False
    try:
        root_resolved = wiki_root.resolve(strict=True)
    except OSError:
        return False
    if target_resolved == root_resolved:
        return False  # never write *at* the root itself
    return root_resolved in target_resolved.parents


# ---------------------------------------------------------------------------
# Body acquisition
# ---------------------------------------------------------------------------


def _read_body(body: str | None, file: Path | None) -> str:
    """Read the doc body from the first non-empty source.

    Priority: ``--body`` → ``--file`` → ``sys.stdin`` (if not a TTY).
    Returns the body text with a single trailing newline so the
    frontmatter/body separator renders cleanly.

    stdin content goes through :func:`_strip_surrogates` because
    Windows PowerShell pipes strings as UTF-16 LE, which Python's
    stdin reader can surface as **lone** surrogate codepoints
    (U+D800..U+DFFF). UTF-8 cannot encode lone surrogates, so
    leaving them in would crash the downstream ``write_text(..., 'utf-8')``
    call with ``UnicodeEncodeError``. ``--body`` and ``--file`` paths
    are already valid str (no surrogates), so they skip the scrub.
    """
    if body is not None and body.strip():
        return body.rstrip() + "\n"
    if file is not None:
        return file.read_text(encoding="utf-8").rstrip() + "\n"
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return data.rstrip() + "\n"
    msg = (
        "no content provided: pass --body, --file, or pipe data on stdin "
        "(stdin is only read when not a TTY)"
    )
    raise typer.BadParameter(msg)


# Lone-surrogate scrub. See the docstring of ``_read_body`` for why
# this is needed. Python 3.10 has no ``str.remove_surrogates()``
# (that helper landed in 3.11), so we do the regex replacement
# ourselves.
_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def _strip_surrogates(text: str) -> str:
    """Replace every lone UTF-16 surrogate codepoint with U+FFFD.

    Used by :func:`_read_body` on the stdin path. Idempotent: running
    it twice produces the same output as running it once.
    """
    return _SURROGATE_RE.sub("\ufffd", text)


# ---------------------------------------------------------------------------
# Title inference
# ---------------------------------------------------------------------------


def _extract_h1(body: str) -> str | None:
    """Return the first ``#`` heading of ``body``, or ``None``."""
    match = H1_RE.search(body)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------------------
# Frontmatter construction
# ---------------------------------------------------------------------------


def _build_frontmatter(
    *,
    title: str,
    module: str,
    tags: Iterable[str],
) -> dict[str, Any]:
    """Return a dict suitable for ``frontmatter.dumps``.

    The CLI always sets ``title`` and ``module``; ``tags`` is a
    list and serialises as a YAML list. ``created_at`` and
    ``last_review`` are pinned to the current UTC date so the
    note has a usable staleness anchor out of the box.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "title": title,
        "module": module,
        "tags": list(tags),
        "created_at": today,
        "last_review": today,
    }


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@app.command()
def add(
    title: Annotated[
        str,
        typer.Option(
            "--title",
            "-t",
            help="Document title. (Required, but can be auto-derived from "
            "the first H1 of the body when not given.)",
        ),
    ] = "",
    body: Annotated[
        str | None,
        typer.Option(
            "--body",
            "-b",
            help="Inline Markdown body. Mutually exclusive with --file / stdin.",
        ),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option(
            "--file",
            "-f",
            help="Path to a local file to import as the body.",
        ),
    ] = None,
    module: Annotated[
        str,
        typer.Option(
            "--module",
            "-m",
            help="Module / category directory (default: 'root').",
        ),
    ] = "root",
    tag: Annotated[
        list[str] | None,
        typer.Option(
            "--tag",
            help="Tag to attach (may be passed multiple times, e.g. "
            "--tag python --tag design).",
        ),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option(
            "--path",
            "-p",
            help="Project / wiki path. Defaults to the active topic.",
        ),
    ] = None,
    topic: Annotated[
        str | None,
        typer.Option(
            "--topic",
            "-T",
            help="Topic name. Write to this topic's vault instead of the active topic. "
            "Use this when the note belongs to a specific second-brain topic "
            "(e.g. '--topic warm-kitchen-time' for project-specific notes, "
            "'--topic shared' for cross-project patterns).",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing file at the target path.",
        ),
    ] = False,
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="Emit a machine-readable JSON object on success.",
        ),
    ] = False,
) -> None:
    """Author a single knowledge note and re-index the wiki.

    The body comes from one of (in priority order): ``--body``,
    ``--file``, then ``sys.stdin`` if it is not a TTY. The
    destination path is ``<wiki>/<module>/<slug>.md``; if that file
    already exists the command refuses unless ``--force`` is set.

    After a successful write, an incremental ``build_index`` runs so
    the new doc is immediately retrievable via ``lorewiki search``.
    """
    # ---- 1. body & title ----------------------------------------------------
    raw_body = _read_body(body, file)
    # Scrub lone UTF-16 surrogates that may have entered through any
    # path (stdin on Windows + PowerShell is the common case, but a
    # buggy ``--body`` from a script that decoded UTF-16 LE with the
    # wrong codec would hit the same problem). Idempotent — safe to
    # run on bodies that are already clean.
    raw_body = _strip_surrogates(raw_body)
    final_title = title.strip() or _extract_h1(raw_body) or slugify(raw_body[:64])

    # ---- 2. resolve paths ---------------------------------------------------
    wiki_root = _resolve_wiki_root(path, topic_arg=topic)
    if not wiki_root.is_dir():
        console.print(f"[red]wiki path not found:[/red] {wiki_root}")
        raise typer.Exit(code=2)

    module_slug = slugify(module) if module != "root" else "root"
    title_slug = slugify(final_title)
    target_dir = wiki_root / module_slug
    target_path = target_dir / f"{title_slug}.md"

    # ---- 3. path-traversal safety net -------------------------------------
    if not _is_safe_target(wiki_root, target_path):
        console.print(
            Panel(
                f"[red]Refusing to write outside the wiki root:[/red]\n"
                f"  target:  {target_path}\n"
                f"  wiki:    {wiki_root}\n"
                f"Pass a safe --module / --title.",
                title="path-traversal blocked",
                border_style="red",
            )
        )
        raise typer.Exit(code=3)

    # ---- 4. conflict detection ---------------------------------------------
    if target_path.exists() and not force:
        console.print(
            Panel(
                f"[red]File already exists:[/red] {target_path}\n"
                f"Pass [cyan]--force[/cyan] to overwrite.",
                title="add: target exists",
                border_style="red",
            )
        )
        raise typer.Exit(code=4)

    # ---- 5. write -----------------------------------------------------------
    tags = list(tag) if tag else []
    metadata = _build_frontmatter(title=final_title, module=module_slug, tags=tags)
    post = frontmatter.Post(raw_body, **metadata)
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        target_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    except (OSError, UnicodeEncodeError) as exc:
        # ``UnicodeEncodeError`` is NOT a subclass of ``OSError``, so
        # the original ``except OSError`` silently let it through and
        # left a 0-byte file on disk. Belt-and-braces: clean up so a
        # subsequent ``add`` invocation doesn't trip the
        # "target exists" check against an empty file.
        log.error("write failed {}: {}", target_path, exc)
        console.print(f"[red]write failed:[/red] {exc}")
        target_path.unlink(missing_ok=True)
        raise typer.Exit(code=5) from exc

    # ---- 6. re-index --------------------------------------------------------
    try:
        cfg = resolve_config(path)
        build_index(cfg, rebuild=False)
    except Exception as exc:
        # bug to swallow a successful write. Surface the warning and let the
        # user re-run ``lorewiki index`` later.
        log.warning("post-write reindex failed: {}", exc)
        console.print(
            f"[yellow]warning: reindex failed[/yellow] (the file is on disk, "
            f"but you may want to run `lorewiki index`): {exc}"
        )

    # ---- 7. output ---------------------------------------------------------
    if raw:
        typer.echo(
            json.dumps(
                {
                    "ok": True,
                    "title": final_title,
                    "module": module_slug,
                    # ``as_posix()`` so Windows backslashes don't sneak into
                    # machine-readable output — cross-platform consistency.
                    "path": target_path.relative_to(wiki_root).as_posix(),
                    "tags": tags,
                },
                ensure_ascii=False,
            )
        )
        return

    console.print(
        Panel(
            f"[green]wrote[/green] [bold]{target_path}[/bold]\n"
            f"  title : {final_title}\n"
            f"  module: {module_slug}\n"
            f"  tags  : {', '.join(tags) if tags else '[dim](none)[/dim]'}\n\n"
            f"Try: [cyan]lorewiki search \"{final_title}\"[/cyan]",
            title="lorewiki add",
            border_style="green",
        )
    )


__all__ = ["add", "slugify"]
