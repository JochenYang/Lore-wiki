"""End-to-end indexer: walk wiki tree → parse → clean → chunk → write SQLite + hierarchy."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from lorewiki.config import LoreWikiConfig
from lorewiki.db import open_db, set_meta
from lorewiki.db.models import DocumentChunk, HierarchyNode
from lorewiki.indexer import cleaning
from lorewiki.indexer.chunker import Chunk, chunk_markdown, estimate_tokens
from lorewiki.indexer.parser import ParsedDocument, parse_markdown
from lorewiki.utils.logger import get_logger

log = get_logger(__name__)

IGNORE_DIRS = {".git", ".lorewiki", "__pycache__", ".venv", ".idea", ".vscode", "node_modules"}
MARKDOWN_EXTS = {".md", ".markdown"}


@dataclass(slots=True)
class IndexerStats:
    files_scanned: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    chunks_written: int = 0
    nodes_written: int = 0
    duration_seconds: float = 0.0
    db_path: str = ""


def _iter_markdown_files(wiki_path: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(wiki_path.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in MARKDOWN_EXTS:
            continue
        if any(part in IGNORE_DIRS for part in path.relative_to(wiki_path).parts):
            continue
        out.append(path)
    return out


# Public alias (re-exported via __all__) so the ``lorewiki clean`` CLI can
# walk the same set of files the indexer would.
iter_markdown_files = _iter_markdown_files


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _chunk_to_row(parsed: ParsedDocument, chunk: Chunk) -> DocumentChunk:
    chunk_id = f"{parsed.path}#{chunk.chunk_index}"
    text = chunk.with_breadcrumb()
    return DocumentChunk(
        id=chunk_id,
        doc_path=parsed.path,
        chunk_index=chunk.chunk_index,
        title=cleaning.clean_title(parsed.title),
        heading_path=cleaning.clean_heading_path(chunk.heading_path),
        content=text,
        module=parsed.module,
        tags=parsed.tags,
        token_count=estimate_tokens(text),
        content_hash=_hash_text(text),
    )


def _build_hierarchy_nodes(
    parsed_docs: list[ParsedDocument],
    cleaned_bodies: dict[str, str],
) -> list[HierarchyNode]:
    """Construct hierarchy nodes for every directory and every document.

    A path ``api/user/auth.md`` produces nodes:

    * ``api``        (module, level 1)
    * ``api/user``   (module, level 2)
    * ``api/user/auth.md`` (doc, level 3, doc_id = ``api/user/auth.md#0``)

    A single synthetic root node (``id="__root__"``) parents every level-1
    module. The root is always inserted first.

    Doc-node summaries are derived from the **cleaned** body (no boilerplate
    blockquotes, no anchor markup, no translation footer) so the hierarchy
    retriever doesn't get polluted by common terms like "文档" / "framework"
    that appear in every WeChat-doc boilerplate.
    """
    nodes: dict[str, HierarchyNode] = {}
    root_id = "__root__"
    nodes[root_id] = HierarchyNode(
        id=root_id,
        parent_id=None,
        node_type="root",
        title="LoreWiki",
        path="",
        level=0,
        summary="Synthetic root node",
    )

    for parsed in parsed_docs:
        parts = parsed.path.split("/")
        accumulated: list[str] = []
        cleaned_body = cleaned_bodies.get(parsed.path, cleaning.clean_markdown(parsed.body))
        cleaned_title = cleaning.clean_title(parsed.title)
        for level, part in enumerate(parts, start=1):
            accumulated.append(part)
            node_path = "/".join(accumulated)
            if node_path in nodes:
                continue
            is_doc = level == len(parts)
            parent_path = "/".join(accumulated[:-1])
            parent_id = parent_path or root_id
            node = HierarchyNode(
                id=node_path,
                parent_id=parent_id,
                node_type="doc" if is_doc else "module",
                title=cleaned_title if is_doc else part,
                path=node_path,
                level=level,
                summary=(cleaned_body[:200].replace("\n", " ").strip() if is_doc else None),
                doc_id=f"{parsed.path}#0" if is_doc else None,
            )
            nodes[node_path] = node
    return list(nodes.values())


def build_index(cfg: LoreWikiConfig, *, rebuild: bool = False) -> IndexerStats:
    """Walk ``cfg.wiki_path``, (re)build the SQLite index, return stats.

    ``rebuild=True`` drops every existing row and re-indexes from scratch.
    ``rebuild=False`` (default) skips files whose latest chunk's content hash
    is unchanged, allowing fast incremental rebuilds.
    """
    started = time.perf_counter()
    wiki_path = cfg.wiki_path
    db_path = cfg.db_path
    if db_path is None:
        msg = "LoreWikiConfig.db_path must be resolved before indexing"
        raise ValueError(msg)

    if not wiki_path.exists():
        msg = f"wiki_path does not exist: {wiki_path}"
        raise FileNotFoundError(msg)
    if not wiki_path.is_dir():
        msg = f"wiki_path is not a directory: {wiki_path}"
        raise NotADirectoryError(msg)

    files = _iter_markdown_files(wiki_path)
    log.info("indexing {} markdown files from {}", len(files), wiki_path)

    stats = IndexerStats(files_scanned=len(files), db_path=str(db_path))

    parsed_docs: list[ParsedDocument] = []
    chunks_per_doc: dict[str, list[Chunk]] = {}
    cleaned_bodies: dict[str, str] = {}
    for file_path in files:
        try:
            parsed = parse_markdown(file_path, rel_to=wiki_path)
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("skip {}: {}", file_path, exc)
            stats.files_skipped += 1
            continue
        # Clean the body before chunking so the FTS5 index and hierarchy
        # summary are free of boilerplate ("相关文档:", "微信 Windows 版: 支持",
        # "The translations are provided by WeChat Translation…", and the
        # ``[​#​](#anchor)`` heading markup). The on-disk file is left
        # untouched; we keep an untouched copy of the parsed doc for
        # re-export (``lorewiki show``) use.
        cleaned_body = cleaning.clean_markdown(parsed.body)
        cleaned_bodies[parsed.path] = cleaned_body
        chunks = chunk_markdown(
            title=cleaning.clean_title(parsed.title),
            body=cleaned_body,
            max_tokens=cfg.chunk_max_tokens,
            overlap_tokens=cfg.chunk_overlap_tokens,
            min_chars=cfg.chunk_min_chars,
        )
        parsed_docs.append(parsed)
        chunks_per_doc[parsed.path] = chunks

    with open_db(db_path) as conn:
        if rebuild:
            conn.execute("DELETE FROM hierarchy")
            conn.execute("DELETE FROM documents")
            conn.commit()

        for parsed in parsed_docs:
            chunks = chunks_per_doc[parsed.path]
            new_rows = [_chunk_to_row(parsed, ch) for ch in chunks]
            if not _doc_needs_rewrite(conn, parsed.path, new_rows):
                stats.files_skipped += 1
                continue

            # Wipe previous chunks for this doc, then insert fresh rows.
            conn.execute("DELETE FROM documents WHERE doc_path = ?", (parsed.path,))
            conn.executemany(
                """
                INSERT INTO documents
                  (id, doc_path, chunk_index, title, heading_path,
                   content, module, tags, token_count, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.id,
                        row.doc_path,
                        row.chunk_index,
                        row.title,
                        row.heading_path,
                        row.content,
                        row.module,
                        row.tags_csv(),
                        row.token_count,
                        row.content_hash,
                    )
                    for row in new_rows
                ],
            )
            stats.files_indexed += 1
            stats.chunks_written += len(new_rows)

        # Hierarchy is fully rebuilt each run: cheap, always consistent.
        conn.execute("DELETE FROM hierarchy")
        nodes = _build_hierarchy_nodes(parsed_docs, cleaned_bodies)
        conn.executemany(
            """
            INSERT INTO hierarchy
              (id, parent_id, node_type, title, summary, path, level, doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    node.id,
                    node.parent_id,
                    node.node_type,
                    node.title,
                    node.summary,
                    node.path,
                    node.level,
                    node.doc_id,
                )
                for node in nodes
            ],
        )
        stats.nodes_written = len(nodes)

        set_meta(conn, "last_indexed_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        set_meta(conn, "wiki_path", str(wiki_path))
        set_meta(conn, "schema_version", "2")
        conn.commit()

    stats.duration_seconds = time.perf_counter() - started
    log.info(
        "index complete: scanned={} indexed={} skipped={} chunks={} nodes={} duration={:.3f}s",
        stats.files_scanned,
        stats.files_indexed,
        stats.files_skipped,
        stats.chunks_written,
        stats.nodes_written,
        stats.duration_seconds,
    )
    return stats


def _doc_needs_rewrite(conn, doc_path: str, new_rows: list[DocumentChunk]) -> bool:
    """Check if any chunk's content hash changed since the last index run."""
    existing = {
        row["chunk_index"]: row["content_hash"]
        for row in conn.execute(
            "SELECT chunk_index, content_hash FROM documents WHERE doc_path = ?", (doc_path,)
        ).fetchall()
    }
    if len(existing) != len(new_rows):
        return True
    return any(existing.get(row.chunk_index) != row.content_hash for row in new_rows)


__all__ = ["IndexerStats", "build_index", "iter_markdown_files"]
