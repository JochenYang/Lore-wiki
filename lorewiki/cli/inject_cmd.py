"""lorewiki inject — auto-inject knowledge base context into LLM sessions.

Analyzes the current project's code to extract keywords (API names,
framework names, library imports), then searches the wiki for relevant
docs and outputs a "context block" that can be injected into LLM tools'
system prompts or context files.

Usage:
    lorewiki inject --project ./my-project
    lorewiki inject --project . --format markdown > .context/wiki-context.md
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from lorewiki.cli.apps import app, console, log
from lorewiki.cli.helpers import resolve_config
from lorewiki.config import LoreWikiConfig
from lorewiki.db.connection import open_db
from lorewiki.retriever import run_search

# File extensions to scan for keywords
_CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".swift",
              ".go", ".rs", ".rb", ".php", ".vue", ".svelte", ".cs", ".cpp", ".c"}

# Patterns to extract API/framework identifiers.
# _API_RE: WeChat mini-program API surface (wx.login, wx.request, ...).
#   Weighted highest because an explicit wx.* call is a strong intent signal.
# _IMPORT_RE: ES/Python/Go imports. Captures the leading module name so
#   `from foo.bar import baz` yields `foo`. `require('x')` (no space) is not
#   matched — JS code typically uses `import` in modern toolchains anyway.
# _FUNC_CALL_RE: generic function-call identifier. Low weight because it is
#   noisy (matches every call); used only to break ties between candidates.
_API_RE = re.compile(r"\bwx\.([a-zA-Z]+)\b")
_IMPORT_RE = re.compile(r"^\s*(?:import|from|require)\s+[\"']?([a-zA-Z_][\w.-]+)", re.MULTILINE)
_FUNC_CALL_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")

# Common language keywords / builtins that would otherwise dominate the
# frequency table. Filtering them keeps the keyword list meaningful.
_STOP_WORDS = frozenset({
    "function", "const", "let", "var", "if", "else", "for", "while",
    "return", "import", "from", "require", "export", "default",
    "class", "def", "async", "await", "new", "this", "self",
    "true", "false", "null", "none", "undefined", "void",
    "public", "private", "protected", "static", "final",
    "console", "print", "log", "error", "warn", "info",
    "string", "number", "boolean", "object", "array",
})


def _extract_keywords(project_dir: Path, max_keywords: int = 20) -> list[str]:
    """Scan project code files and extract API/framework keywords.

    Returns a deduplicated list of keywords sorted by frequency. Weights:
    ``wx.*`` API calls count 10x (strong signal), imports 5x, generic
    function calls 1x. Stop words are filtered before counting.
    """
    keywords: Counter[str] = Counter()

    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _CODE_EXTS:
            continue
        # Skip common non-source directories (deps, build artefacts, venvs).
        if any(part in {"node_modules", ".git", "__pycache__", ".venv",
                        "dist", "build", ".next", "vendor"}
               for part in path.relative_to(project_dir).parts):
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        # WeChat mini-program API surface (wx.login, wx.request, ...).
        for m in _API_RE.finditer(content):
            kw = f"wx.{m.group(1)}"
            keywords[kw] += 10

        # Import / require statements — module name only.
        for m in _IMPORT_RE.finditer(content):
            name = m.group(1).split(".")[0].lower()
            if name not in _STOP_WORDS and len(name) >= 2:
                keywords[name] += 5

        # Generic function calls — low weight, used only to break ties.
        for m in _FUNC_CALL_RE.finditer(content):
            name = m.group(1).lower()
            if name not in _STOP_WORDS and len(name) >= 3:
                keywords[name] += 1

    return [kw for kw, _ in keywords.most_common(max_keywords)]


def _search_wiki_for_keywords(
    cfg: LoreWikiConfig, keywords: list[str], top_k_per_kw: int = 2,
) -> list[dict]:
    """Search the wiki for each keyword and return unique doc summaries.

    De-duplicates by ``doc_path`` so a doc matching multiple keywords
    only appears once (the first matching keyword is recorded). After
    gathering hits, enriches each with ``summary`` / ``doc_type`` from
    the ``doc_summaries`` table — the same pattern used by the
    ``search`` command's default output.
    """
    if not keywords:
        return []

    seen: dict[str, dict] = {}

    for kw in keywords:
        hits = run_search(cfg, kw, mode="bm25", top_k=top_k_per_kw)
        for h in hits:
            if h.doc_path not in seen:
                seen[h.doc_path] = {
                    "doc_path": h.doc_path,
                    "title": h.title,
                    "module": h.module,
                    "matched_keyword": kw,
                    "score": h.score,
                }

    # Enrich with summaries from doc_summaries table (one row per doc).
    if cfg.db_path and seen:
        with open_db(cfg.db_path, auto_init=False) as conn:
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

    return list(seen.values())[:15]  # Cap at 15 docs to keep context block small


def _format_context_block(docs: list[dict], keywords: list[str]) -> str:
    """Format the injected context as a markdown block.

    The block is designed to be prepended/appended to an LLM system
    prompt or a ``.context/wiki-context.md`` file. Each doc line
    includes title, optional type tag, doc_path, and a 200-char
    summary excerpt so the model can decide which doc to read
    in full via ``lorewiki show <doc_path>``.
    """
    if not docs:
        return "## Knowledge Base Context\n\nNo relevant docs found in the wiki.\n"

    lines = [
        "## Knowledge Base Context (auto-injected)",
        "",
        "Based on your project's code, the following wiki docs may be relevant:",
        f"Detected keywords: {', '.join(keywords[:10])}",
        "",
    ]

    for doc in docs:
        summary = doc.get("summary", "")[:200]
        doc_type = doc.get("doc_type", "")
        type_tag = f" [{doc_type}]" if doc_type else ""
        lines.append(
            f"- **{doc['title']}**{type_tag} ({doc['doc_path']}): {summary}"
        )

    lines.append("")
    lines.append("Use `lorewiki show <doc_path>` to read full content.")

    return "\n".join(lines)


@app.command()
def inject(
    project: Annotated[
        str,
        typer.Option("--project", "-p", help="Project directory to analyze."),
    ] = ".",
    path: Annotated[
        str | None,
        typer.Option("--path", help="Wiki path (defaults to active topic)."),
    ] = None,
    max_keywords: Annotated[
        int,
        typer.Option("--max-keywords", help="Max keywords to extract from code."),
    ] = 20,
    format: Annotated[
        str,
        typer.Option("--format", help="Output format: markdown | json."),
    ] = "markdown",
) -> None:
    """Analyze project code and inject relevant wiki context.

    This command scans your project's source files, extracts API names
    and framework identifiers, then searches the wiki for matching docs.
    The output is a "context block" you can inject into LLM tools'
    system prompts or context files.

    Usage in opencode hooks:
        lorewiki inject --project . >> $CONTEXT_FILE

    Usage in .cursorrules or CLAUDE.md:
        $(lorewiki inject --project . --format markdown)
    """
    project_dir = Path(project).resolve()
    if not project_dir.is_dir():
        console.print(f"[red]Project directory not found:[/red] {project_dir}")
        raise typer.Exit(code=1)

    cfg = resolve_config(path)
    if cfg.db_path is None or not cfg.db_path.exists():
        console.print("[red]No wiki index found. Run `lorewiki index` first.[/red]")
        raise typer.Exit(code=2)

    # Step 1: Extract keywords from project code
    keywords = _extract_keywords(project_dir, max_keywords=max_keywords)
    if not keywords:
        console.print("[yellow]No keywords extracted from project code.[/yellow]")
        raise typer.Exit(code=0)

    log.info("extracted {} keywords: {}", len(keywords), ", ".join(keywords[:10]))

    # Step 2: Search wiki for each keyword
    docs = _search_wiki_for_keywords(cfg, keywords)

    # Step 3: Output context block
    if format == "json":
        payload = {
            "keywords": keywords,
            "matched_docs": docs,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        # Markdown format (default)
        context_block = _format_context_block(docs, keywords)
        typer.echo(context_block)


__all__ = ["inject"]
