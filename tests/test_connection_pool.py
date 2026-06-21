"""Tests for connection pooling and schema caching."""

import sqlite3
from pathlib import Path

import pytest

import lorewiki.db.connection as conn_mod
from lorewiki.db.connection import (
    close_all_connections,
    open_db,
)


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up caches after each test."""
    yield
    close_all_connections()
    conn_mod._SCHEMA_CACHE.clear()
    conn_mod._CONNECTION_CACHE.clear()


def test_schema_cache_is_populated(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with open_db(db_path) as conn:
        conn.execute("SELECT 1")
    assert conn_mod._SCHEMA_CACHE.get("sql") is not None


def test_connection_is_cached(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with open_db(db_path) as conn1:
        pass
    with open_db(db_path) as conn2:
        pass
    assert conn1 is conn2


def test_close_all_connections(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with open_db(db_path) as conn:
        pass
    assert db_path in conn_mod._CONNECTION_CACHE
    close_all_connections()
    assert len(conn_mod._CONNECTION_CACHE) == 0