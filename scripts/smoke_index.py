"""End-to-end smoke test: index example_wiki and report stats."""

from __future__ import annotations

import tempfile
from pathlib import Path

from lorewiki.config import LoreWikiConfig
from lorewiki.db import open_db
from lorewiki.indexer import build_index


def main() -> None:
    project = Path(__file__).resolve().parent.parent
    wiki = project / "example_wiki"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "index.db"
        cfg = LoreWikiConfig(wiki_path=wiki, db_path=db_path)
        print(f"wiki_path = {cfg.wiki_path}")
        print(f"db_path   = {cfg.db_path}")

        stats = build_index(cfg, rebuild=True)
        print(f"\n--- IndexerStats ---")
        print(f"  files_scanned  = {stats.files_scanned}")
        print(f"  files_indexed  = {stats.files_indexed}")
        print(f"  files_skipped  = {stats.files_skipped}")
        print(f"  chunks_written = {stats.chunks_written}")
        print(f"  nodes_written  = {stats.nodes_written}")
        print(f"  duration       = {stats.duration_seconds:.3f}s")

        with open_db(db_path, auto_init=False) as conn:
            print(f"\n--- documents per doc ---")
            for row in conn.execute(
                "SELECT doc_path, COUNT(*) AS c, SUM(token_count) AS tt "
                "FROM documents GROUP BY doc_path ORDER BY doc_path"
            ).fetchall():
                print(f"  {row['doc_path']:40} chunks={row['c']:2}  total_tokens={row['tt']}")

            print(f"\n--- hierarchy ---")
            for row in conn.execute(
                "SELECT id, parent_id, node_type, level, title "
                "FROM hierarchy ORDER BY level, path"
            ).fetchall():
                indent = "  " * row["level"]
                print(
                    f"  [{row['level']}] {indent}{row['node_type']:<6} "
                    f"id={row['id']}  parent={row['parent_id']}  title={row['title']}"
                )

            print(f"\n--- BM25 search (FTS5 trigram) ---")
            queries = [
                "用户认证",         # 4 chars Chinese
                "JWT 双 Token",     # mixed
                "幂等设计",         # 4 chars Chinese
                "令牌桶 Redis",     # mixed
                "指数退避抖动",     # 6 chars Chinese
                "限流方案选型",     # 6 chars Chinese
            ]
            for q in queries:
                rows = conn.execute(
                    "SELECT rowid, title, heading_path, "
                    "snippet(docs_fts, 1, '<<', '>>', '...', 8) AS snip "
                    "FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank LIMIT 3",
                    (q,),
                ).fetchall()
                print(f"\n  q={q!r}  ->  {len(rows)} hits")
                for r in rows:
                    print(f"     - [{r['heading_path']}] {r['snip']}")


if __name__ == "__main__":
    main()
