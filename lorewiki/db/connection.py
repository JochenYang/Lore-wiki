"""SQLite connection management with idempotent schema migration.

Public surface:

* :func:`open_db` — context manager that yields a configured ``sqlite3.Connection``.
* :func:`init_db` — applies the schema to an empty database.
* :func:`set_meta` / :func:`get_meta` — small helpers for the ``meta`` key/value
  table (we store ``last_indexed_at`` and similar bookkeeping here).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from importlib import resources
from pathlib import Path

from lorewiki.utils.logger import get_logger

log = get_logger(__name__)

SCHEMA_RESOURCE = ("lorewiki.db", "schema.sql")
_SCHEMA_CACHE: dict[str, str] = {}
_CONNECTION_CACHE: dict[Path, sqlite3.Connection] = {}


def _load_schema_sql() -> str:
    """Read the bundled schema.sql via importlib.resources (works after install)."""
    if "sql" in _SCHEMA_CACHE:
        return _SCHEMA_CACHE["sql"]
    package, name = SCHEMA_RESOURCE
    _SCHEMA_CACHE["sql"] = resources.files(package).joinpath(name).read_text(encoding="utf-8")
    return _SCHEMA_CACHE["sql"]


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Tuning PRAGMAs applied to every connection.

    Notes:
    * We intentionally keep ``journal_mode=DELETE`` (the default) instead of
      WAL. LoreWiki is single-process; WAL would add ``-wal`` and ``-shm``
      sidecar files that, on Windows, get held by the process even after
      ``close()``, breaking ``tempfile.TemporaryDirectory`` cleanup in tests.
      We can revisit if a future REST/UI deployment needs concurrent writers.
    * ``foreign_keys=ON`` is required for our ``hierarchy.parent_id`` CASCADE.
    """
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -64000")  # ~64 MB
    conn.row_factory = sqlite3.Row


def init_db(db_path: Path) -> None:
    """Create (if absent) and migrate ``db_path`` to the latest schema.

    Note: ``with sqlite3.connect(...) as conn:`` *commits* the transaction but
    does **not** close the connection — that's a Python stdlib quirk. We must
    close explicitly, otherwise on Windows the db file stays locked and
    ``tempfile.TemporaryDirectory`` cleanup fails.

    The ``doc_vec`` virtual table is NOT created here — it is created
    lazily in ``_populate_vector_index`` (see :mod:`lorewiki.indexer.indexer`)
    at index time. This avoids a Windows thread-pool deadlock that occurs
    when importing ``sqlite_vec`` inside :func:`asyncio.to_thread`. If the
    ``sqlite-vec`` extension isn't installed, vector search degrades to
    lexical-only.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = _load_schema_sql()
    conn = sqlite3.connect(db_path)
    try:
        _apply_pragmas(conn)
        conn.executescript(schema_sql)
        conn.commit()
        # doc_vec is created lazily in _populate_vector_index at index
        # time — see the docstring above for the rationale.
    finally:
        conn.close()
    log.debug("initialised db at {}", db_path)


def _get_connection(db_path: Path) -> sqlite3.Connection:
    """Get or create a cached connection to the database.

    ``check_same_thread=False`` allows the connection to be shared between
    the async event-loop thread and ``asyncio.to_thread`` worker threads.
    LoreWiki is single-process with explicit transaction boundaries via
    ``open_db`` — file-level locking from SQLite itself still prevents
    concurrent writes, so this is safe.
    """
    if db_path in _CONNECTION_CACHE:
        return _CONNECTION_CACHE[db_path]
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    _apply_pragmas(conn)
    _CONNECTION_CACHE[db_path] = conn
    return conn


def close_all_connections() -> None:
    """Close all cached connections. Call at process exit."""
    for conn in _CONNECTION_CACHE.values():
        with suppress(Exception):
            conn.close()
    _CONNECTION_CACHE.clear()


@contextmanager
def open_db(db_path: Path, *, auto_init: bool = True) -> Iterator[sqlite3.Connection]:
    """Open a connection to ``db_path``, optionally running the schema first.

    Uses connection caching to avoid repeated connection overhead.
    Schema initialization is only performed on first access.

    Usage::

        with open_db(Path("./wiki.db")) as conn:
            conn.execute("SELECT 1")
    """
    if auto_init:
        init_db(db_path)
    conn = _get_connection(db_path)
    try:
        yield conn
    finally:
        # Don't close - keep in cache for reuse
        pass


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Upsert a key/value pair into the ``meta`` table."""
    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return row["value"]


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the highest schema version present in the db (0 if empty)."""
    row = conn.execute(
        "SELECT MAX(version) AS v FROM schema_version"
    ).fetchone()
    if row is None or row["v"] is None:
        return 0
    return int(row["v"])


__all__ = [
    "close_all_connections",
    "get_meta",
    "init_db",
    "open_db",
    "schema_version",
    "set_meta",
]
