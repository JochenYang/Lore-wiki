"""Contract tests for the optional vector retriever.

Live fastembed / sqlite-vec integration is opt-in (``lorewiki[vector]``).
These tests pin the SQL/row_factory contract so the broken
``d.embedding_distance`` regression cannot return silently, and prove
graceful degradation when the extra is not installed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lorewiki.config import LoreWikiConfig, VectorConfig
from lorewiki.retriever.vector import (
    DEFAULT_EMBEDDING_MODEL,
    VECTOR_SEARCH_SQL,
    VectorRetriever,
)


def test_vector_search_sql_uses_doc_vec_distance_not_documents_column() -> None:
    """sqlite-vec exposes ``distance`` on the virtual table, not on documents."""
    assert "doc_vec.distance" in VECTOR_SEARCH_SQL
    assert "d.embedding_distance" not in VECTOR_SEARCH_SQL
    assert "embedding MATCH" in VECTOR_SEARCH_SQL
    assert "AND k =" in VECTOR_SEARCH_SQL


def test_vector_config_default_model_matches_retriever() -> None:
    cfg = VectorConfig()
    assert cfg.embedding_model == DEFAULT_EMBEDDING_MODEL
    assert cfg.embedding_dim == 384


def test_from_config_uses_vector_embedding_model(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    db.write_bytes(b"")  # existence only; search will no-op without extension
    cfg = LoreWikiConfig(
        wiki_path=tmp_path / "wiki",
        db_path=db,
        vector=VectorConfig(embedding_model="custom/model-name"),
    )
    retr = VectorRetriever.from_config(cfg)
    assert retr.embedding_model == "custom/model-name"


def test_from_config_env_overrides_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "index.db"
    db.write_bytes(b"")
    monkeypatch.setenv("LOREWIKI_VECTOR_MODEL", "env/override-model")
    cfg = LoreWikiConfig(
        wiki_path=tmp_path / "wiki",
        db_path=db,
        vector=VectorConfig(embedding_model="config/model"),
    )
    retr = VectorRetriever.from_config(cfg)
    assert retr.embedding_model == "env/override-model"


def test_search_returns_empty_when_sqlite_vec_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without sqlite-vec installed, search must not raise."""
    db = tmp_path / "index.db"
    db.write_bytes(b"")
    retr = VectorRetriever(db)

    real_import = __import__

    def _block_sqlite_vec(name, *args, **kwargs):
        if name == "sqlite_vec" or name.startswith("sqlite_vec."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block_sqlite_vec)
    # Reset availability cache after patching import.
    retr._available = None
    assert retr.search("hello world", top_k=3) == []


def test_search_maps_rows_with_row_factory_style_access(tmp_path: Path) -> None:
    """When SQL returns Row-like objects, hits must use name-based columns."""
    db = tmp_path / "index.db"
    db.write_bytes(b"")
    retr = VectorRetriever(db)
    retr._available = True

    fake_row = {
        "chunk_index": 0,
        "doc_path": "api/auth.md",
        "title": "Auth",
        "heading_path": "Auth",
        "content": "token refresh body " * 20,
        "module": "api",
        "distance": 0.25,
    }

    class _Row:
        def __getitem__(self, key: str):
            return fake_row[key]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [_Row()]
    mock_conn.close = MagicMock()

    class _Vec(list):
        def tolist(self):
            return list(self)

    with (
        patch.object(retr, "_load_model") as load_model,
        patch.object(retr, "_open_with_vec", return_value=mock_conn),
    ):
        load_model.return_value.embed.return_value = iter([_Vec([0.1] * 384)])
        hits = retr.search("auth token", top_k=5)

    assert len(hits) == 1
    assert hits[0].doc_path == "api/auth.md"
    assert hits[0].score == pytest.approx(0.75)
    assert hits[0].retriever == "vector"
    # Confirm the contract SQL was used.
    sql_arg = mock_conn.execute.call_args[0][0]
    assert "doc_vec.distance" in sql_arg
    assert "d.embedding_distance" not in sql_arg
