"""Shared pytest fixtures and cleanup hooks.

The connection pool in ``lorewiki.db.connection`` caches connections
module-level for performance. In the test suite, each test uses a
``tmp_path`` database, so cached connections from one test can interfere
with the next. This fixture clears the cache after every test.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lorewiki.db.connection import close_all_connections


@pytest.fixture(autouse=True)
def _reset_connection_cache() -> Iterator[None]:
    """Clear the connection cache and schema cache before and after each test."""
    close_all_connections()
    yield
    close_all_connections()
