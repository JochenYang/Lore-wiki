"""Debug FTS5 rank values and BM25Retriever scores."""

from pathlib import Path

from lorewiki.config import LoreWikiConfig
from lorewiki.db import open_db
from lorewiki.retriever import BM25Retriever


def main() -> None:
    cfg = LoreWikiConfig(wiki_path=Path("example_wiki"))
    assert cfg.db_path is not None
    print("db_path:", cfg.db_path)

    with open_db(cfg.db_path, auto_init=False) as conn:
        rows = conn.execute(
            "SELECT d.id, rank FROM docs_fts "
            "JOIN documents d ON d.rowid = docs_fts.rowid "
            "WHERE docs_fts MATCH ? ORDER BY rank LIMIT 5",
            ('"用户认证 API"',),
        ).fetchall()
        print("\n--- raw FTS5 ---")
        for r in rows:
            print(f"  id={r['id']:<40} rank={r['rank']!r}")

    retr = BM25Retriever.from_config(cfg)
    hits = retr.search("用户认证 API", top_k=5)
    print("\n--- BM25Retriever ---")
    for h in hits:
        print(f"  retriever={h.retriever:<15} score={h.score!r}  doc={h.doc_path}")


if __name__ == "__main__":
    main()
