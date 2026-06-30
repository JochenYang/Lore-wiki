"""Tests for db connection / schema / meta helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lorewiki.db import get_meta, init_db, open_db, schema_version, set_meta


def test_init_db_creates_tables(tmp_path: Path) -> None:
    db = tmp_path / "wiki.db"
    init_db(db)
    assert db.exists()
    with open_db(db, auto_init=False) as conn:
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {
            "documents",
            "docs_fts",
            "hierarchy",
            "meta",
            "schema_version",
            "doc_summaries",
            "edges",
        } <= tables
        assert schema_version(conn) == 3


def test_meta_upsert(tmp_path: Path) -> None:
    db = tmp_path / "wiki.db"
    with open_db(db) as conn:
        assert get_meta(conn, "x") is None
        assert get_meta(conn, "x", default="fallback") == "fallback"
        set_meta(conn, "x", "v1")
        conn.commit()
        assert get_meta(conn, "x") == "v1"
        set_meta(conn, "x", "v2")
        conn.commit()
        assert get_meta(conn, "x") == "v2"


def test_fts_trigger_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "wiki.db"
    with open_db(db) as conn:
        conn.execute(
            "INSERT INTO documents(id, doc_path, chunk_index, title, content, module) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("a.md#0", "a.md", 0, "Hello", "world body 内容", "root"),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT title FROM docs_fts WHERE docs_fts MATCH ?", ('"hello"',)
        ).fetchall()
        assert rows and rows[0]["title"] == "Hello"

        # Update should propagate to the FTS index.
        conn.execute("UPDATE documents SET title = ? WHERE id = ?", ("Updated", "a.md#0"))
        conn.commit()
        hits_old = conn.execute(
            "SELECT title FROM docs_fts WHERE docs_fts MATCH ?", ('"hello"',)
        ).fetchall()
        assert hits_old == []
        hits_new = conn.execute(
            "SELECT title FROM docs_fts WHERE docs_fts MATCH ?", ('"updated"',)
        ).fetchall()
        assert hits_new and hits_new[0]["title"] == "Updated"


def test_sqlite_row_contains_checks_values_not_keys() -> None:
    """Regression guard: ``in`` on ``sqlite3.Row`` matches *values*.

    This is the trap that produced a silent ``score=0.0`` bug in
    :class:`BM25Retriever._row_to_hit`. Any future change that relies on
    ``column in row`` must use ``row.keys()`` instead.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 1 AS a, 'foo' AS b").fetchone()
    assert "a" not in row  # surprising but correct
    assert "foo" in row  # because 'foo' is one of the row's values
    assert "a" in row.keys()  # noqa: SIM118 - the bug we are guarding against
    conn.close()


@pytest.mark.parametrize("auto_init", [True, False])
def test_open_db_auto_init_flag(tmp_path: Path, auto_init: bool) -> None:
    db = tmp_path / "wiki.db"
    if not auto_init:
        # Without auto_init the db must already exist.
        init_db(db)
    with open_db(db, auto_init=auto_init) as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
