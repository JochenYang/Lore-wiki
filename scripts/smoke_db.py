"""Smoke test for db schema + FTS5 trigram tokenizer."""

from __future__ import annotations

import tempfile
from pathlib import Path

from lorewiki.db import get_meta, init_db, open_db, schema_version, set_meta


def main() -> None:
    # ignore_cleanup_errors needed because Windows is slow to release sqlite
    # file handles even after .close().
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        p = Path(tmp) / "wiki.db"
        init_db(p)
        with open_db(p, auto_init=False) as conn:
            print("schema_version:", schema_version(conn))
            set_meta(conn, "last_indexed_at", "2026-06-10T12:00:00Z")
            conn.commit()
            print("meta last_indexed_at:", get_meta(conn, "last_indexed_at"))

            conn.execute(
                """
                INSERT INTO documents
                  (id, doc_path, chunk_index, title, heading_path, content, module, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "api/user/auth.md#0",
                    "api/user/auth.md",
                    0,
                    "用户认证 API",
                    "概述",
                    "本文档描述用户认证体系：login / logout / refresh, JWT 双 Token 方案。",
                    "api/user",
                    "auth,jwt",
                ),
            )
            conn.execute(
                """
                INSERT INTO documents
                  (id, doc_path, chunk_index, title, heading_path, content, module, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "patterns/retry.md#0",
                    "patterns/retry.md",
                    0,
                    "重试与幂等设计模式",
                    "退避算法",
                    "指数退避 + 抖动 (Full Jitter) 是工程上最稳的选择。",
                    "patterns",
                    "retry,backoff",
                ),
            )
            conn.commit()

            rows = conn.execute("SELECT rowid, id, title FROM documents").fetchall()
            print("inserted rows:", [dict(r) for r in rows])

            queries = [
                "用户登录",
                "JWT",
                "幂等",
                "指数退避",
                "Token",
                "Full Jitter",
                "认证",
            ]
            for q in queries:
                sql = (
                    "SELECT rowid, title, "
                    "snippet(docs_fts, 1, '<', '>', '...', 8) AS snip, rank "
                    "FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank LIMIT 3"
                )
                res = conn.execute(sql, (q,)).fetchall()
                print(f"q={q!r} -> {[dict(r) for r in res]}")


if __name__ == "__main__":
    main()
