"""Compare unicode61 vs trigram tokenizers on Chinese + mixed queries."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

DOCS = [
    ("auth.md", "用户认证 API", "本文档描述用户认证体系：login / logout / refresh, JWT 双 Token 方案。"),
    ("retry.md", "重试与幂等设计", "指数退避 + 抖动 (Full Jitter) 是工程上最稳的选择。"),
    ("login.md", "登录流程", "用户输入账号密码后调用登录接口，服务端验证后签发 token。"),
    ("rate-limit.md", "限流方案", "令牌桶算法允许突发流量,漏桶算法输出绝对平滑。"),
]

QUERIES = [
    "用户登录",
    "幂等",
    "认证",
    "登录",
    "JWT",
    "Token",
    "令牌桶",
    "幂等重试",
    "Full Jitter",
    "指数退避",
]


def build_db(tokenizer: str, tmp: Path) -> sqlite3.Connection:
    """Build a tiny FTS5 db using the requested tokenizer string."""
    db = sqlite3.connect(tmp / f"{tokenizer.replace(' ', '_')}.db")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE docs(rowid INTEGER PRIMARY KEY, doc_path TEXT, title TEXT, content TEXT)")
    db.execute(
        f"CREATE VIRTUAL TABLE fts USING fts5(title, content, content=docs, content_rowid=rowid, tokenize='{tokenizer}')"
    )
    db.execute(
        "CREATE TRIGGER docs_ai AFTER INSERT ON docs BEGIN "
        "INSERT INTO fts(rowid, title, content) VALUES(new.rowid, new.title, new.content); END"
    )
    for i, (path, title, content) in enumerate(DOCS, start=1):
        db.execute("INSERT INTO docs(rowid, doc_path, title, content) VALUES(?,?,?,?)", (i, path, title, content))
    db.commit()
    return db


def run_queries(db: sqlite3.Connection, label: str) -> None:
    print(f"\n=== {label} ===")
    for q in QUERIES:
        try:
            sql = "SELECT rowid, title, rank FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT 4"
            rows = db.execute(sql, (q,)).fetchall()
            hits = [(r["rowid"], r["title"]) for r in rows]
        except sqlite3.OperationalError as e:
            hits = f"ERROR: {e}"
        print(f"  q={q!r:<14} hits={hits}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for tok in ("trigram", "unicode61", "unicode61 remove_diacritics 2"):
            db = build_db(tok, tmp)
            run_queries(db, tok)
            db.close()


if __name__ == "__main__":
    main()
