"""FastAPI REST API for LoreWiki.

Exposes the same surface as the CLI:

* ``POST /search``   — retrieval (mix / bm25 / hierarchy / vector)
* ``POST /ask``      — retrieval + LLM answer
* ``GET  /modules``  — top-level module list
* ``GET  /module/{path:path}`` — module subtree + chunk count
* ``GET  /status``   — index statistics

The app loads the configuration once via :func:`load_config` at startup; the
DB connection is opened per-request (SQLite is cheap) so we don't have to
deal with thread-local state. For production deployments behind uvicorn the
RetrieverRegistry/GeneratorRegistry could be promoted to module globals, but
keeping per-request state means config reloads pick up cleanly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from lorewiki.config import LoreWikiConfig, load_config
from lorewiki.db import get_meta, open_db
from lorewiki.llm import AnswerGenerator
from lorewiki.retriever import BM25Retriever, HierarchyRetriever, RRFFusion
from lorewiki.utils.logger import get_logger

log = get_logger(__name__)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query.")
    top_k: int = Field(5, ge=1, le=100)
    mode: str = Field("mix", pattern="^(bm25|hierarchy|mix|vector)$")


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=20)


class SearchHitOut(BaseModel):
    chunk_id: str
    doc_path: str
    title: str
    heading_path: str | None = None
    module: str | None = None
    snippet: str = ""
    score: float
    retriever: str


class SearchResponse(BaseModel):
    query: str
    mode: str
    hits: list[SearchHitOut]


class AskResponse(BaseModel):
    question: str
    answer: str
    used_llm: bool
    backend: str
    model: str
    degraded_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    hits: list[SearchHitOut]


class ModuleEntry(BaseModel):
    path: str
    title: str
    node_type: str
    level: int
    chunk_count: int = 0


class StatusResponse(BaseModel):
    wiki_path: str
    db_path: str
    db_size_bytes: int
    documents: int
    chunks: int
    hierarchy_nodes: int
    last_indexed_at: str | None
    retrieval_mode: str
    llm_enabled: bool


def create_app(cfg: LoreWikiConfig | None = None) -> FastAPI:
    """Construct a FastAPI app bound to ``cfg`` (defaults to ``load_config()``)."""
    config = cfg or load_config()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        log.info("REST api starting, db={}", config.db_path)
        yield
        log.info("REST api shutting down")

    app = FastAPI(
        title="LoreWiki REST API",
        description=(
            "HTTP surface for LoreWiki. Same retrieval + answer pipeline as the "
            "CLI; designed to be consumed by web UIs, CI pipelines, or LLM "
            "tool-calling adapters."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        _ensure_db(config)
        assert config.db_path is not None
        db_size = config.db_path.stat().st_size
        with open_db(config.db_path, auto_init=False) as conn:
            doc_count = conn.execute(
                "SELECT COUNT(DISTINCT doc_path) FROM documents"
            ).fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            node_count = conn.execute("SELECT COUNT(*) FROM hierarchy").fetchone()[0]
            last_indexed = get_meta(conn, "last_indexed_at")
        return StatusResponse(
            wiki_path=str(config.wiki_path),
            db_path=str(config.db_path),
            db_size_bytes=db_size,
            documents=doc_count,
            chunks=chunk_count,
            hierarchy_nodes=node_count,
            last_indexed_at=last_indexed,
            retrieval_mode=config.retrieval_mode,
            llm_enabled=config.llm.enabled,
        )

    @app.post("/search", response_model=SearchResponse)
    def search(req: SearchRequest) -> SearchResponse:
        _ensure_db(config)
        hits = _run_search(config, req.query, mode=req.mode, top_k=req.top_k)
        return SearchResponse(
            query=req.query,
            mode=req.mode,
            hits=[_hit_to_out(h) for h in hits],
        )

    @app.post("/ask", response_model=AskResponse)
    def ask(req: AskRequest) -> AskResponse:
        _ensure_db(config)
        gen = AnswerGenerator(config)
        answer = gen.ask(req.query, top_k=req.top_k)
        return AskResponse(
            question=answer.question,
            answer=answer.text,
            used_llm=answer.used_llm,
            backend=answer.backend,
            model=answer.model,
            degraded_reason=answer.degraded_reason,
            prompt_tokens=answer.prompt_tokens,
            completion_tokens=answer.completion_tokens,
            hits=[_hit_to_out(h) for h in answer.hits],
        )

    @app.get("/modules", response_model=list[ModuleEntry])
    def list_modules() -> list[ModuleEntry]:
        _ensure_db(config)
        assert config.db_path is not None
        with open_db(config.db_path, auto_init=False) as conn:
            rows = conn.execute(
                "SELECT path, title, node_type, level FROM hierarchy "
                "WHERE level = 1 ORDER BY path"
            ).fetchall()
            counts = _chunk_counts_by_doc_path_prefix(conn, [r["path"] for r in rows])
        return [
            ModuleEntry(
                path=r["path"],
                title=r["title"],
                node_type=r["node_type"],
                level=r["level"],
                chunk_count=counts.get(r["path"], 0),
            )
            for r in rows
        ]

    @app.get("/module/{module_path:path}", response_model=list[ModuleEntry])
    def module_detail(
        module_path: str,
        max_depth: int = Query(5, ge=1, le=10),
    ) -> list[ModuleEntry]:
        _ensure_db(config)
        assert config.db_path is not None
        with open_db(config.db_path, auto_init=False) as conn:
            target = conn.execute(
                "SELECT path, level FROM hierarchy WHERE path = ?", (module_path,)
            ).fetchone()
            if target is None:
                raise HTTPException(status_code=404, detail=f"module not found: {module_path}")
            max_level = target["level"] + max_depth
            rows = conn.execute(
                "SELECT path, title, node_type, level FROM hierarchy "
                "WHERE (path = ? OR path LIKE ?) AND level <= ? "
                "ORDER BY level, path",
                (module_path, f"{module_path}/%", max_level),
            ).fetchall()
            counts = _chunk_counts_by_doc_path_prefix(conn, [r["path"] for r in rows])
        return [
            ModuleEntry(
                path=r["path"],
                title=r["title"],
                node_type=r["node_type"],
                level=r["level"],
                chunk_count=counts.get(r["path"], 0),
            )
            for r in rows
        ]

    return app


# ---- helpers ----


def _ensure_db(cfg: LoreWikiConfig) -> None:
    if cfg.db_path is None or not cfg.db_path.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                f"index database not found at {cfg.db_path}. "
                f"Run `lorewiki index --path {cfg.wiki_path}` first."
            ),
        )


def _run_search(cfg: LoreWikiConfig, query: str, *, mode: str, top_k: int) -> list[Any]:
    retrievers = {
        "bm25": BM25Retriever.from_config(cfg),
        "hierarchy": HierarchyRetriever.from_config(cfg),
    }
    if mode == "vector":
        # Vector mode falls back to mix until phase 6 lands sqlite-vec.
        mode = "mix"
    if mode in {"bm25", "hierarchy"}:
        return list(retrievers[mode].search(query, top_k=top_k))
    per_retriever = {
        name: list(r.search(query, top_k=top_k * 2)) for name, r in retrievers.items()
    }
    fuser = RRFFusion(
        k=cfg.rrf_k,
        weights={
            "bm25": cfg.mix_weights.bm25,
            "hierarchy": cfg.mix_weights.hierarchy,
        },
    )
    return list(fuser.fuse(per_retriever, top_k=top_k))


def _hit_to_out(hit) -> SearchHitOut:
    return SearchHitOut(
        chunk_id=hit.chunk_id,
        doc_path=hit.doc_path,
        title=hit.title,
        heading_path=hit.heading_path,
        module=hit.module,
        snippet=hit.snippet,
        score=hit.score,
        retriever=hit.retriever,
    )


def _chunk_counts_by_doc_path_prefix(conn, paths: list[str]) -> dict[str, int]:
    """Return ``{node_path: chunk_count}`` for each given hierarchy path.

    A node path is a prefix of doc paths under it (e.g. ``api`` covers
    ``api/user/auth.md`` etc.); for ``doc``-type nodes the path is the doc
    path itself.
    """
    out: dict[str, int] = {}
    for path in paths:
        if not path:
            out[path] = 0
            continue
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM documents WHERE doc_path = ? OR doc_path LIKE ?",
            (path, f"{path}/%"),
        ).fetchone()
        out[path] = int(row["c"]) if row else 0
    return out


def serve(host: str = "127.0.0.1", port: int = 8000, *, cfg: LoreWikiConfig | None = None) -> None:
    """Convenience entrypoint used by the CLI."""
    import uvicorn  # noqa: PLC0415

    app = create_app(cfg)
    uvicorn.run(app, host=host, port=port, log_level="info")


__all__ = [
    "AskRequest",
    "AskResponse",
    "ModuleEntry",
    "SearchHitOut",
    "SearchRequest",
    "SearchResponse",
    "StatusResponse",
    "create_app",
    "serve",
]
