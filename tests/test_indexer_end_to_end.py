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
