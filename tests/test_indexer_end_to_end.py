"""End-to-end indexer tests using a small synthetic wiki on disk."""

from __future__ import annotations

from pathlib import Path

import pytest

from lorewiki.config import LoreWikiConfig
from lorewiki.db import open_db
from lorewiki.indexer import build_index


def _seed_wiki(root: Path) -> None:
    (root / "api" / "user").mkdir(parents=True)
    (root / "patterns").mkdir(parents=True)
    (root / "index.md").write_text(
        "---\ntitle: My Wiki\nmodule: root\n---\n\n# My Wiki\n\nWelcome to the demo wiki.\n",
        encoding="utf-8",
    )
    # auth.md is short enough to take the small-doc fast path and be
    # indexed as a single chunk — see chunker.chunk_markdown for the
    # max_tokens guard.
    (root / "api" / "user" / "auth.md").write_text(
        "---\ntitle: Auth\nmodule: api/user\n---\n\n# Auth\n\n"
        "## POST /login\n\n"
        "The login endpoint validates the username + password pair "
        "and returns a short-lived access token plus a longer-lived refresh "
        "token used for silent renewal.\n\n"
        "## POST /logout\n\n"
        "The logout endpoint accepts a refresh token and adds it to the "
        "Redis revocation list so subsequent refresh attempts fail with "
        "INVALID_REFRESH.\n",
        encoding="utf-8",
    )
    (root / "patterns" / "retry.md").write_text(
        "---\ntitle: Retry\nmodule: patterns\n---\n\n# Retry\n\n"
        "## Backoff\n\n"
        "Use exponential backoff with full jitter to avoid retry storms when "
        "many clients reconnect after a transient failure.\n",
        encoding="utf-8",
    )


def test_build_index_creates_chunks_and_hierarchy(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _seed_wiki(wiki)
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    stats = build_index(cfg, rebuild=True)
    assert stats.files_scanned == 3
    assert stats.files_indexed == 3
    assert stats.chunks_written >= 3

    assert cfg.db_path is not None
    with open_db(cfg.db_path, auto_init=False) as conn:
        chunks = conn.execute("SELECT doc_path, chunk_index FROM documents").fetchall()
        # auth.md is small enough to be kept as a single chunk (the
        # small-doc fast path); just verify it produced at least one.
        auth_chunks = [c for c in chunks if c["doc_path"] == "api/user/auth.md"]
        assert len(auth_chunks) >= 1

        # Hierarchy has root + modules + docs.
        nodes = conn.execute("SELECT node_type, path, level FROM hierarchy").fetchall()
        types = {n["node_type"] for n in nodes}
        assert {"root", "module", "doc"} <= types
        # root level 0, modules level 1, docs level 1 or 3.
        assert any(n["level"] == 0 for n in nodes)
        assert any(n["level"] == 3 for n in nodes)  # api/user/auth.md


def test_incremental_index_skips_unchanged_files(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _seed_wiki(wiki)
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    first = build_index(cfg, rebuild=True)
    second = build_index(cfg, rebuild=False)
    assert second.files_skipped == first.files_indexed
    assert second.files_indexed == 0


def test_incremental_index_reindexes_modified_file(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _seed_wiki(wiki)
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    build_index(cfg, rebuild=True)
    target = wiki / "api" / "user" / "auth.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n## Refresh\n\nrotate refresh tokens.\n",
        encoding="utf-8",
    )
    stats = build_index(cfg, rebuild=False)
    assert stats.files_indexed == 1
    assert stats.files_skipped == 2


def test_rebuild_drops_old_rows(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _seed_wiki(wiki)
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    build_index(cfg, rebuild=True)

    deleted = wiki / "patterns" / "retry.md"
    deleted.unlink()
    build_index(cfg, rebuild=True)
    assert cfg.db_path is not None
    with open_db(cfg.db_path, auto_init=False) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) AS c FROM documents WHERE doc_path = ?", ("patterns/retry.md",)
        ).fetchone()
        assert rows["c"] == 0


def test_incremental_index_purges_orphan_documents(tmp_path: Path) -> None:
    """Hand-deleted .md files must leave no ghost rows after incremental index.

    ``build_index(rebuild=False)`` only walks files that still exist; without
    an explicit orphan purge, search would keep returning the deleted doc.
    """
    wiki = tmp_path / "wiki"
    _seed_wiki(wiki)
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    build_index(cfg, rebuild=True)

    deleted = wiki / "patterns" / "retry.md"
    assert deleted.exists()
    deleted.unlink()

    build_index(cfg, rebuild=False)
    assert cfg.db_path is not None
    with open_db(cfg.db_path, auto_init=False) as conn:
        leftover = [
            r["doc_path"]
            for r in conn.execute("SELECT DISTINCT doc_path FROM documents").fetchall()
        ]
        assert "patterns/retry.md" not in leftover
        assert "api/user/auth.md" in leftover
        assert "index.md" in leftover
        # Hierarchy / summaries rebuilt from live files only.
        hier = conn.execute(
            "SELECT COUNT(*) AS c FROM hierarchy WHERE path = ?",
            ("patterns/retry.md",),
        ).fetchone()
        assert hier["c"] == 0


def test_missing_wiki_path_raises(tmp_path: Path) -> None:
    cfg = LoreWikiConfig(wiki_path=tmp_path / "does-not-exist")
    with pytest.raises(FileNotFoundError):
        build_index(cfg)


def test_file_path_acts_as_dir_raises(tmp_path: Path) -> None:
    file_path = tmp_path / "file.md"
    file_path.write_text("# x\n", encoding="utf-8")
    cfg = LoreWikiConfig(wiki_path=file_path)
    with pytest.raises(NotADirectoryError):
        build_index(cfg)


def test_build_index_writes_summaries_and_edges(tmp_path: Path) -> None:
    """Cover T3/T4/T5: doc_summaries + edges + frontmatter ``type``.

    This is the only end-to-end assertion that the new tables are actually
    populated by ``build_index``; without it the writer code paths added
    for T3/T4 would be unexercised (a green test suite that proves nothing
    about the new behaviour).
    """
    wiki = tmp_path / "wiki"
    (wiki / "decisions").mkdir(parents=True)
    (wiki / "api").mkdir(parents=True)
    (wiki / "patterns").mkdir(parents=True)
    # 001.md: frontmatter description wins for summary; ``type`` is decision;
    # body links to ../api/auth.md (relative) and an external https link that
    # must be skipped.
    (wiki / "decisions" / "001.md").write_text(
        "---\n"
        "title: Decision 001\n"
        "type: decision\n"
        "description: Decision summary\n"
        "---\n\n"
        "# Decision 001\n\n"
        "See [auth](../api/auth.md) and [ext](https://example.com).\n",
        encoding="utf-8",
    )
    # auth.md: no description, so summary falls back to the first paragraph;
    # ``type`` is API (mixed-case to confirm we keep the author's casing).
    (wiki / "api" / "auth.md").write_text(
        "---\ntitle: Auth\ntype: API\n---\n\n# Auth\n\nAuth paragraph.\n\n"
        "## See also\n\nLink to [retry](../patterns/retry.md).\n",
        encoding="utf-8",
    )
    # retry.md: no frontmatter ``type`` → doc_type must be NULL.
    (wiki / "patterns" / "retry.md").write_text(
        "# Retry\n\nRetry paragraph.\n", encoding="utf-8"
    )
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    build_index(cfg, rebuild=True)

    assert cfg.db_path is not None
    with open_db(cfg.db_path, auto_init=False) as conn:
        summaries = {
            r["doc_path"]: (r["summary"], r["doc_type"])
            for r in conn.execute(
                "SELECT doc_path, summary, doc_type FROM doc_summaries"
            ).fetchall()
        }
        # One row per document, not per chunk.
        assert set(summaries) == {
            "decisions/001.md",
            "api/auth.md",
            "patterns/retry.md",
        }
        # Priority 1: frontmatter description wins when present.
        assert summaries["decisions/001.md"] == ("Decision summary", "decision")
        # Priority 2: first paragraph fallback when no description.
        assert summaries["api/auth.md"][0] == "Auth paragraph."
        assert summaries["api/auth.md"][1] == "API"
        # No frontmatter ``type`` → NULL (SQLite returns None).
        assert summaries["patterns/retry.md"][1] is None

        edges = {
            (r["source_doc"], r["target_doc"]): r["link_text"]
            for r in conn.execute(
                "SELECT source_doc, target_doc, link_text FROM edges"
            ).fetchall()
        }
        # ../api/auth.md resolved against decisions/ → api/auth.md.
        assert edges[("decisions/001.md", "api/auth.md")] == "auth"
        # ../patterns/retry.md resolved against api/ → patterns/retry.md.
        assert edges[("api/auth.md", "patterns/retry.md")] == "retry"
        # External https link must NOT be captured as an edge.
        assert not any(
            target == "https://example.com" for (_, target) in edges
        )
