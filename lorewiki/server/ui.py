"""Streamlit web UI for LoreWiki.

Run via ``lorewiki ui`` (which delegates to ``streamlit run`` under the
hood). Four pages laid out in the sidebar:

* Search   — query input + mode selector + result cards
* Browse   — hierarchy tree on the left, Markdown render on the right
* Config   — read-only view of the active configuration
* Status   — index statistics and DB size

The whole module imports ``streamlit`` lazily so the CLI can stay importable
even when the ``[ui]`` extra is not installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lorewiki.config import LoreWikiConfig, load_config
from lorewiki.db import get_meta, open_db
from lorewiki.llm import AnswerGenerator
from lorewiki.retriever import BM25Retriever, HierarchyRetriever, RRFFusion

# --- helpers shared by all pages ----------------------------------------


def _get_config() -> LoreWikiConfig:
    import streamlit as st  # noqa: PLC0415

    if "_lorewiki_cfg" not in st.session_state:
        st.session_state["_lorewiki_cfg"] = load_config()
    return st.session_state["_lorewiki_cfg"]


def _run_search(cfg: LoreWikiConfig, query: str, *, mode: str, top_k: int) -> list[Any]:
    retrievers = {
        "bm25": BM25Retriever.from_config(cfg),
        "hierarchy": HierarchyRetriever.from_config(cfg),
    }
    if mode == "vector":
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


# --- pages --------------------------------------------------------------


def render_search() -> None:
    import streamlit as st  # noqa: PLC0415

    st.header("Search")
    cfg = _get_config()
    cols = st.columns([4, 1, 1])
    with cols[0]:
        query = st.text_input("Query", "", placeholder="e.g. 用户登录接口")
    with cols[1]:
        mode = st.selectbox("Mode", ["mix", "bm25", "hierarchy"])
    with cols[2]:
        top_k = st.number_input("Top K", min_value=1, max_value=50, value=5)
    ask_mode = st.checkbox("Compose answer with LLM (ask mode)", value=False)

    if not query.strip():
        st.info("Enter a query above to search the wiki.")
        return

    db_path = cfg.db_path
    if db_path is None or not db_path.exists():
        st.error(
            f"No index found at {db_path}. "
            f"Run `lorewiki index --path {cfg.wiki_path}` first."
        )
        return

    if ask_mode:
        gen = AnswerGenerator(cfg)
        answer = gen.ask(query, top_k=int(top_k))
        st.subheader("Answer")
        if answer.used_llm:
            st.success(f"Model: {answer.backend} / {answer.model}")
        else:
            st.warning(f"LLM not used ({answer.degraded_reason})")
        st.markdown(answer.text)
        st.subheader("Sources")
        _render_hits(answer.hits)
    else:
        hits = _run_search(cfg, query, mode=mode, top_k=int(top_k))
        st.caption(f"{len(hits)} hits ({mode} mode)")
        _render_hits(hits)


def _render_hits(hits: list[Any]) -> None:
    import streamlit as st  # noqa: PLC0415

    if not hits:
        st.info("No matching chunks.")
        return
    for i, h in enumerate(hits, start=1):
        with st.expander(
            f"{i}. {h.heading_path or h.title}  ·  "
            f"{h.doc_path}  ·  score={h.score:.3f}  ·  {h.retriever}"
        ):
            snippet = (h.snippet or "").replace("<<", "**").replace(">>", "**")
            st.markdown(snippet)


def render_browse() -> None:
    import streamlit as st  # noqa: PLC0415

    st.header("Browse")
    cfg = _get_config()
    db_path = cfg.db_path
    if db_path is None or not db_path.exists():
        st.error("No index found.")
        return

    with open_db(db_path, auto_init=False) as conn:
        nodes = conn.execute(
            "SELECT path, title, node_type, level FROM hierarchy "
            "WHERE level >= 1 ORDER BY level, path"
        ).fetchall()

    if not nodes:
        st.info("Index is empty.")
        return

    paths = [n["path"] for n in nodes]
    labels = [
        f"{'  ' * (n['level'] - 1)}[{n['node_type']}] {n['title']}  ({n['path']})"
        for n in nodes
    ]
    chosen_idx = st.sidebar.radio("Hierarchy", range(len(paths)), format_func=lambda i: labels[i])
    chosen_path = paths[chosen_idx]

    wiki_root = cfg.wiki_path
    file_path = wiki_root / chosen_path
    if file_path.is_file() and file_path.suffix.lower() == ".md":
        st.subheader(file_path.name)
        st.code(str(file_path), language="text")
        st.markdown(file_path.read_text(encoding="utf-8"))
    else:
        st.subheader(chosen_path)
        st.caption("Module node — listing chunks below.")
        with open_db(db_path, auto_init=False) as conn:
            rows = conn.execute(
                "SELECT id, doc_path, heading_path, token_count FROM documents "
                "WHERE doc_path = ? OR doc_path LIKE ? ORDER BY doc_path, chunk_index",
                (chosen_path, f"{chosen_path}/%"),
            ).fetchall()
        for r in rows:
            st.markdown(
                f"- **{r['heading_path'] or r['id']}**  "
                f"·  `{r['doc_path']}`  ·  {r['token_count']} tokens"
            )


def render_config() -> None:
    import streamlit as st  # noqa: PLC0415

    st.header("Configuration")
    cfg = _get_config()
    st.caption(
        "Read-only view of the merged config (user-level + project-level + env + defaults). "
        "Edit `.lorewiki/config.toml` or run `lorewiki config set` to change values."
    )
    payload = cfg.model_dump(mode="json", exclude_none=False)
    st.json(_stringify_paths(payload))


def render_status() -> None:
    import streamlit as st  # noqa: PLC0415

    st.header("Status")
    cfg = _get_config()
    db_path = cfg.db_path
    if db_path is None or not db_path.exists():
        st.warning("No index found.")
        return
    db_size = db_path.stat().st_size
    with open_db(db_path, auto_init=False) as conn:
        doc_count = conn.execute("SELECT COUNT(DISTINCT doc_path) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        node_count = conn.execute("SELECT COUNT(*) FROM hierarchy").fetchone()[0]
        last = get_meta(conn, "last_indexed_at", "(never)")
        modules = conn.execute(
            "SELECT module, COUNT(*) AS c FROM documents "
            "WHERE module IS NOT NULL GROUP BY module ORDER BY module"
        ).fetchall()

    cols = st.columns(4)
    cols[0].metric("Documents", doc_count)
    cols[1].metric("Chunks", chunk_count)
    cols[2].metric("Hierarchy nodes", node_count)
    cols[3].metric("DB size", _human_bytes(db_size))
    st.caption(
        f"Last indexed: {last}  ·  Mode: {cfg.retrieval_mode}  "
        f"·  LLM enabled: {cfg.llm.enabled}"
    )

    if modules:
        st.subheader("Chunks per module")
        st.table([{"module": m["module"], "chunks": m["c"]} for m in modules])


# --- entry point --------------------------------------------------------


def _stringify_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stringify_paths(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_paths(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _human_bytes(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num} B"


def main() -> None:
    """Streamlit application entry point.

    Streamlit calls this when running ``streamlit run lorewiki/server/ui.py``.
    """
    import streamlit as st  # noqa: PLC0415

    st.set_page_config(page_title="LoreWiki", page_icon=":books:", layout="wide")
    st.sidebar.title(":books: LoreWiki")
    page = st.sidebar.radio(
        "Page",
        ("Search", "Browse", "Config", "Status"),
    )
    st.sidebar.markdown("---")
    cfg = _get_config()
    st.sidebar.caption(f"Wiki: `{cfg.wiki_path}`")
    st.sidebar.caption(f"DB:   `{cfg.db_path}`")

    if page == "Search":
        render_search()
    elif page == "Browse":
        render_browse()
    elif page == "Config":
        render_config()
    elif page == "Status":
        render_status()


if __name__ == "__main__":  # pragma: no cover - exercised by `streamlit run`
    main()
