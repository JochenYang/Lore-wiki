"""FastAPI REST tests using the TestClient (no live server)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")  # the [rest] extra; CI installs it via -e ".[dev,rest,mcp]"

from fastapi.testclient import TestClient

from lorewiki.config import LoreWikiConfig
from lorewiki.indexer import build_index
from lorewiki.server.rest_api import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    wiki = tmp_path / "wiki"
    (wiki / "api" / "user").mkdir(parents=True)
    (wiki / "patterns").mkdir(parents=True)
    (wiki / "api" / "user" / "auth.md").write_text(
        "---\ntitle: Auth\nmodule: api/user\n---\n\n# Auth\n\n"
        "## Login\n\nThe login endpoint signs and returns a JWT token pair "
        "for the user.\n\n"
        "## Refresh\n\nRefresh rotates the long-lived refresh token.\n",
        encoding="utf-8",
    )
    (wiki / "patterns" / "retry.md").write_text(
        "---\ntitle: Retry\nmodule: patterns\n---\n\n# Retry\n\n"
        "## Backoff\n\nExponential backoff with full jitter avoids retry "
        "storms.\n",
        encoding="utf-8",
    )
    # Third small file so the fixture produces enough chunks (3+) for
    # tests that assert on chunk counts. The small-doc fast path in
    # chunk_markdown keeps each of these as one chunk, so we need
    # three separate files instead of one large one.
    (wiki / "patterns" / "circuit.md").write_text(
        "---\ntitle: Circuit\nmodule: patterns\n---\n\n# Circuit\n\n"
        "## Trip\n\nTrip the circuit after N consecutive failures.\n",
        encoding="utf-8",
    )
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=tmp_path / "index.db")
    build_index(cfg, rebuild=True)
    return TestClient(create_app(cfg))


def test_health_endpoint(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_status_endpoint(client: TestClient) -> None:
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert body["documents"] >= 2
    assert body["chunks"] >= 3
    assert body["last_indexed_at"] is not None
    assert body["retrieval_mode"] == "mix"


def test_search_endpoint_basic(client: TestClient) -> None:
    r = client.post("/search", json={"query": "login", "top_k": 3, "mode": "bm25"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "bm25"
    assert body["hits"]
    assert any("auth.md" in h["doc_path"] for h in body["hits"])
    for h in body["hits"]:
        assert h["retriever"].startswith("bm25")
        assert h["score"] > 0


def test_search_endpoint_mix_mode(client: TestClient) -> None:
    r = client.post("/search", json={"query": "login", "top_k": 3, "mode": "mix"})
    assert r.status_code == 200
    body = r.json()
    assert body["hits"]
    assert all(h["retriever"] == "mix" for h in body["hits"])


def test_search_endpoint_validation_rejects_bad_mode(client: TestClient) -> None:
    r = client.post("/search", json={"query": "x", "mode": "not-a-mode"})
    assert r.status_code == 422


def test_search_endpoint_rejects_empty_query(client: TestClient) -> None:
    r = client.post("/search", json={"query": "", "top_k": 3})
    assert r.status_code == 422


def test_ask_endpoint_returns_fallback_without_llm(client: TestClient) -> None:
    r = client.post("/ask", json={"query": "how does login work?", "top_k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["used_llm"] is False
    assert body["backend"] == "fallback"
    assert body["degraded_reason"] == "llm_unavailable"
    assert body["hits"]


def test_list_modules(client: TestClient) -> None:
    r = client.get("/modules")
    assert r.status_code == 200
    body = r.json()
    paths = {m["path"] for m in body}
    assert "api" in paths
    assert "patterns" in paths
    for m in body:
        assert m["level"] == 1
        assert m["chunk_count"] >= 0


def test_module_detail(client: TestClient) -> None:
    r = client.get("/module/api")
    assert r.status_code == 200
    body = r.json()
    paths = {m["path"] for m in body}
    # Sub-tree must contain at least api/user and the leaf doc.
    assert "api" in paths
    assert "api/user" in paths
    assert "api/user/auth.md" in paths


def test_module_detail_unknown_returns_404(client: TestClient) -> None:
    r = client.get("/module/does/not/exist")
    assert r.status_code == 404


def test_openapi_docs_available(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    # Every promised endpoint must be in the spec.
    paths = set(schema["paths"].keys())
    assert "/search" in paths
    assert "/ask" in paths
    assert "/modules" in paths
    assert "/status" in paths


def test_endpoints_503_when_db_missing(tmp_path: Path) -> None:
    """If the index db doesn't exist yet, endpoints must surface a clear
    503 instead of crashing the worker."""
    cfg = LoreWikiConfig(
        wiki_path=tmp_path / "empty-wiki",
        db_path=tmp_path / "nope.db",
    )
    app = create_app(cfg)
    test_client = TestClient(app)
    r = test_client.post("/search", json={"query": "x", "top_k": 1})
    assert r.status_code == 503
    assert "index database not found" in r.text.lower()
