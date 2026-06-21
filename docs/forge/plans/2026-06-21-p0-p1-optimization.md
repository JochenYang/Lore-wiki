# P0 + P1 优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use forge:subagent (recommended) or forge:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决 Lorewiki 项目的 3 个 P0 问题和 8 个 P1 问题，提升性能、可维护性和代码质量。

**Architecture:** 
- P0 聚焦性能瓶颈：连接复用、批量写入、LIKE 查询优化
- P1 聚焦代码质量：消除重复代码、改进类型安全、增强错误处理
- 所有修改保持向后兼容，不改变公共 API

**Tech Stack:** Python 3.10+, SQLite, loguru, pydantic

---

## 文件结构

### 修改的文件

| 文件路径                                      | 修改内容                                    |
| --------------------------------------------- | ------------------------------------------- |
| `lorewiki/db/connection.py`                     | 添加连接缓存 + schema 缓存                  |
| `lorewiki/indexer/indexer.py`                   | 批量写入 + 去重复 cleaning + 流水线优化     |
| `lorewiki/retriever/bm25.py`                    | LIKE 查询优化（只搜 title/heading）         |
| `lorewiki/retriever/hierarchy.py`               | 合并双重全表扫描                            |
| `lorewiki/config.py`                            | 导出 `_deep_merge`                            |
| `lorewiki/cli/helpers.py`                       | 移除重复 `deep_merge`，导入使用               |
| `lorewiki/indexer/patterns.py`（新建）           | 统一管理正则模式                            |
| `lorewiki/indexer/chunker.py`                   | 使用统一的 H1_RE                            |
| `lorewiki/indexer/parser.py`                    | 使用统一的 H1_RE                            |
| `lorewiki/cli/add.py`                           | 使用统一的 H1_RE                            |
| `lorewiki/utils/logger.py`                      | 改进 `get_logger` 返回类型                    |
| `lorewiki/cli/config_cmds.py`                   | 捕获 ValidationError                        |
| `lorewiki/topic.py`                             | 添加 `shutil.rmtree` 错误处理                 |

### 新建的文件

| 文件路径                           | 职责                     |
| ---------------------------------- | ------------------------ |
| `lorewiki/indexer/patterns.py`       | 统一管理正则表达式模式   |
| `tests/test_connection_pool.py`    | 测试连接缓存功能         |
| `tests/test_batch_insert.py`       | 测试批量写入功能         |
| `tests/test_patterns.py`           | 测试统一正则模式         |

---

## Task 1: 创建统一正则模式模块 [P1-5]

**Covers:** 消除 H1_RE 重复定义

**Files:**
- Create: `lorewiki/indexer/patterns.py`
- Modify: `lorewiki/indexer/chunker.py:28`
- Modify: `lorewiki/indexer/parser.py:17`
- Modify: `lorewiki/cli/add.py:135`
- Test: `tests/test_patterns.py`

- [ ] **Step 1: 创建 patterns.py 模块**

```python
# lorewiki/indexer/patterns.py
"""Unified regex patterns for markdown parsing."""

from __future__ import annotations

import re

# Matches H1 headings: # Title
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# Matches H2 headings: ## Title
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# Matches fenced code blocks
CODE_FENCE_RE = re.compile(r"^```")

__all__ = ["H1_RE", "H2_RE", "CODE_FENCE_RE"]
```

- [ ] **Step 2: 更新 chunker.py 使用统一模式**

```python
# lorewiki/indexer/chunker.py:28-30
# 从:
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
CODE_FENCE_RE = re.compile(r"^```")

# 改为:
from lorewiki.indexer.patterns import H1_RE, H2_RE, CODE_FENCE_RE
```

- [ ] **Step 3: 更新 parser.py 使用统一模式**

```python
# lorewiki/indexer/parser.py:17
# 从:
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# 改为:
from lorewiki.indexer.patterns import H1_RE
```

- [ ] **Step 4: 更新 add.py 使用统一模式**

```python
# lorewiki/cli/add.py:135
# 从:
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# 改为:
from lorewiki.indexer.patterns import H1_RE
```

- [ ] **Step 5: 编写测试**

```python
# tests/test_patterns.py
"""Tests for unified regex patterns."""

from lorewiki.indexer.patterns import H1_RE, H2_RE, CODE_FENCE_RE


def test_h1_re_matches_heading():
    assert H1_RE.search("# Hello World").group(1) == "Hello World"


def test_h1_re_multiline():
    text = "Some text\n# Heading\nMore text"
    assert H1_RE.search(text).group(1) == "Heading"


def test_h2_re_matches_heading():
    assert H2_RE.search("## Section Title").group(1) == "Section Title"


def test_code_fence_re():
    assert CODE_FENCE_RE.match("```python")
    assert CODE_FENCE_RE.match("```")
    assert not CODE_FENCE_RE.match("not code")
```

- [ ] **Step 6: 运行测试验证**

```bash
pytest tests/test_patterns.py -v
```

---

## Task 2: 改进 get_logger 返回类型 [P1-6]

**Covers:** 消除 `get_logger` 返回 `Any` 丢失类型信息

**Files:**
- Modify: `lorewiki/utils/logger.py:73`

- [ ] **Step 1: 更新 get_logger 返回类型**

```python
# lorewiki/utils/logger.py:73-78
# 从:
def get_logger(name: str | None = None) -> Any:
    """Return a loguru logger bound to ``name`` (defaults to caller module)."""
    _configure()
    if name:
        return _logger.bind(scope=name)
    return _logger

# 改为:
from loguru import Logger

def get_logger(name: str | None = None) -> Logger:
    """Return a loguru logger bound to ``name`` (defaults to caller module)."""
    _configure()
    if name:
        return _logger.bind(scope=name)
    return _logger
```

- [ ] **Step 2: 移除未使用的 Any 导入**

```python
# lorewiki/utils/logger.py:19
# 从:
from typing import Any

# 改为:
# 删除这行（如果其他地方不用 Any）
```

- [ ] **Step 3: 运行类型检查验证**

```bash
python -m mypy lorewiki/utils/logger.py --ignore-missing-imports
```

---

## Task 3: 导出 deep_merge 并消除重复 [P1-4]

**Covers:** 统一 deep_merge 实现

**Files:**
- Modify: `lorewiki/config.py:132`
- Modify: `lorewiki/cli/helpers.py:128-135`

- [ ] **Step 1: 在 config.py 中导出 _deep_merge**

```python
# lorewiki/config.py:273-283
__all__ = [
    "PROJECT_CONFIG_REL",
    "USER_CONFIG_PATH",
    "LLMConfig",
    "LoreWikiConfig",
    "MixWeights",
    "VectorConfig",
    "_deep_merge",  # 添加这行
    "default_config_toml",
    "load_config",
    "save_config",
]
```

- [ ] **Step 2: 更新 helpers.py 使用 config.py 的实现**

```python
# lorewiki/cli/helpers.py:128-135
# 从:
def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out

# 改为:
from lorewiki.config import _deep_merge as deep_merge
```

- [ ] **Step 3: 更新 helpers.py 的 __all__**

```python
# lorewiki/cli/helpers.py:149-162
__all__ = [
    "console",
    "deep_merge",  # 保留，因为是从 config 导入的
    "discover_project_dir",
    "flatten_config",
    "format_value",
    "human_bytes",
    "log",
    "parse_toml_literal",
    "print_phase_status",
    "resolve_config",
    "safe_load_toml",
    "unflatten",
]
```

- [ ] **Step 4: 运行测试验证**

```bash
pytest tests/test_config.py -v
pytest tests/test_cli.py -v
```

---

## Task 4: 捕获 config_set 的 ValidationError [P1-7]

**Covers:** 改进用户体验

**Files:**
- Modify: `lorewiki/cli/config_cmds.py:87`

- [ ] **Step 1: 添加 ValidationError 捕获**

```python
# lorewiki/cli/config_cmds.py:84-89
# 从:
    # Merge with whatever already lives in the project config file.
    existing = safe_load_toml(target) if target.exists() else {}
    merged = deep_merge(existing, nested)
    new_cfg = LoreWikiConfig(**merged)
    save_config(new_cfg, target)
    console.print(f"[green]set[/green] {key} = {parsed_value!r}  ->  {target}")

# 改为:
    # Merge with whatever already lives in the project config file.
    existing = safe_load_toml(target) if target.exists() else {}
    merged = deep_merge(existing, nested)
    try:
        new_cfg = LoreWikiConfig(**merged)
    except ValidationError as exc:
        console.print(f"[red]invalid configuration:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    save_config(new_cfg, target)
    console.print(f"[green]set[/green] {key} = {parsed_value!r}  ->  {target}")
```

- [ ] **Step 2: 添加 ValidationError 导入**

```python
# lorewiki/cli/config_cmds.py:8-9
# 从:
import typer
from rich.table import Table

# 改为:
import typer
from pydantic import ValidationError
from rich.table import Table
```

- [ ] **Step 3: 测试验证**

```bash
pytest tests/test_cli.py -v -k "config"
```

---

## Task 5: 添加 TopicManager.delete 错误处理 [P1-11]

**Covers:** Windows 文件锁定问题

**Files:**
- Modify: `lorewiki/topic.py:572`

- [ ] **Step 1: 添加 onerror 回调**

```python
# lorewiki/topic.py:568-576
# 从:
        validate_name(name)
        topic_root = self.root / name
        if not topic_root.is_dir():
            raise FileNotFoundError(f"topic {name!r} not found at {topic_root}")
        shutil.rmtree(topic_root)
        log.info("deleted topic {name!r} at {root}", name=name, root=topic_root)

# 改为:
        validate_name(name)
        topic_root = self.root / name
        if not topic_root.is_dir():
            raise FileNotFoundError(f"topic {name!r} not found at {topic_root}")
        
        def _on_error(func, path, exc_info):
            """Log error but continue deletion."""
            log.warning("failed to delete {}: {}", path, exc_info[1])
        
        shutil.rmtree(topic_root, onerror=_on_error)
        log.info("deleted topic {name!r} at {root}", name=name, root=topic_root)
```

- [ ] **Step 2: 测试验证**

```bash
pytest tests/test_topic.py -v -k "delete"
```

---

## Task 6: 连接池化 + Schema 缓存 [P0-1]

**Covers:** 消除重复 schema 初始化

**Files:**
- Modify: `lorewiki/db/connection.py`
- Test: `tests/test_connection_pool.py`

- [ ] **Step 1: 添加连接缓存**

```python
# lorewiki/db/connection.py:23-29
# 添加模块级缓存:
SCHEMA_RESOURCE = ("lorewiki.db", "schema.sql")
_SCHEMA_CACHE: str | None = None
_CONNECTION_CACHE: dict[Path, sqlite3.Connection] = {}


def _load_schema_sql() -> str:
    """Read the bundled schema.sql via importlib.resources (works after install)."""
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE
    package, name = SCHEMA_RESOURCE
    _SCHEMA_CACHE = resources.files(package).joinpath(name).read_text(encoding="utf-8")
    return _SCHEMA_CACHE
```

- [ ] **Step 2: 添加连接获取函数**

```python
# lorewiki/db/connection.py:50-67
# 在 init_db 后添加:
def _get_connection(db_path: Path) -> sqlite3.Connection:
    """Get or create a cached connection to the database."""
    if db_path in _CONNECTION_CACHE:
        return _CONNECTION_CACHE[db_path]
    conn = sqlite3.connect(db_path)
    _apply_pragmas(conn)
    _CONNECTION_CACHE[db_path] = conn
    return conn


def close_all_connections() -> None:
    """Close all cached connections. Call at process exit."""
    for conn in _CONNECTION_CACHE.values():
        try:
            conn.close()
        except Exception:
            pass
    _CONNECTION_CACHE.clear()
```

- [ ] **Step 3: 修改 open_db 使用缓存**

```python
# lorewiki/db/connection.py:70-86
# 从:
@contextmanager
def open_db(db_path: Path, *, auto_init: bool = True) -> Iterator[sqlite3.Connection]:
    """Open a connection to ``db_path``, optionally running the schema first.

    Usage::

        with open_db(Path("./wiki.db")) as conn:
            conn.execute("SELECT 1")
    """
    if auto_init:
        init_db(db_path)
    conn = sqlite3.connect(db_path)
    _apply_pragmas(conn)
    try:
        yield conn
    finally:
        conn.close()

# 改为:
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
```

- [ ] **Step 4: 更新 __all__**

```python
# lorewiki/db/connection.py:119-125
__all__ = [
    "close_all_connections",
    "get_meta",
    "init_db",
    "open_db",
    "schema_version",
    "set_meta",
]
```

- [ ] **Step 5: 编写测试**

```python
# tests/test_connection_pool.py
"""Tests for connection pooling and schema caching."""

import sqlite3
from pathlib import Path

import pytest

from lorewiki.db.connection import (
    _SCHEMA_CACHE,
    _CONNECTION_CACHE,
    close_all_connections,
    open_db,
)


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up caches after each test."""
    yield
    close_all_connections()
    import lorewiki.db.connection as conn_mod
    conn_mod._SCHEMA_CACHE = None
    conn_mod._CONNECTION_CACHE.clear()


def test_schema_cache_is_populated(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with open_db(db_path) as conn:
        conn.execute("SELECT 1")
    assert _SCHEMA_CACHE is not None


def test_connection_is_cached(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with open_db(db_path) as conn1:
        pass
    with open_db(db_path) as conn2:
        pass
    assert conn1 is conn2


def test_close_all_connections(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with open_db(db_path) as conn:
        pass
    assert db_path in _CONNECTION_CACHE
    close_all_connections()
    assert len(_CONNECTION_CACHE) == 0
```

- [ ] **Step 6: 运行测试验证**

```bash
pytest tests/test_connection_pool.py -v
pytest tests/test_db.py -v
```

---

## Task 7: 索引批量写入 [P0-2]

**Covers:** 消除逐行 INSERT

**Files:**
- Modify: `lorewiki/indexer/indexer.py:196-219`
- Test: `tests/test_batch_insert.py`

- [ ] **Step 1: 修改 build_index 使用 executemany**

```python
# lorewiki/indexer/indexer.py:195-219
# 从:
            # Wipe previous chunks for this doc, then insert fresh rows.
            conn.execute("DELETE FROM documents WHERE doc_path = ?", (parsed.path,))
            for row in new_rows:
                conn.execute(
                    """
                    INSERT INTO documents
                      (id, doc_path, chunk_index, title, heading_path,
                       content, module, tags, token_count, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.id,
                        row.doc_path,
                        row.chunk_index,
                        row.title,
                        row.heading_path,
                        row.content,
                        row.module,
                        row.tags_csv(),
                        row.token_count,
                        row.content_hash,
                    ),
                )
            stats.files_indexed += 1
            stats.chunks_written += len(new_rows)

# 改为:
            # Wipe previous chunks for this doc, then insert fresh rows.
            conn.execute("DELETE FROM documents WHERE doc_path = ?", (parsed.path,))
            conn.executemany(
                """
                INSERT INTO documents
                  (id, doc_path, chunk_index, title, heading_path,
                   content, module, tags, token_count, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.id,
                        row.doc_path,
                        row.chunk_index,
                        row.title,
                        row.heading_path,
                        row.content,
                        row.module,
                        row.tags_csv(),
                        row.token_count,
                        row.content_hash,
                    )
                    for row in new_rows
                ],
            )
            stats.files_indexed += 1
            stats.chunks_written += len(new_rows)
```

- [ ] **Step 2: 批量写入 hierarchy 节点**

```python
# lorewiki/indexer/indexer.py:222-241
# 从:
        # Hierarchy is fully rebuilt each run: cheap, always consistent.
        conn.execute("DELETE FROM hierarchy")
        nodes = _build_hierarchy_nodes(parsed_docs)
        for node in nodes:
            conn.execute(
                """
                INSERT INTO hierarchy
                  (id, parent_id, node_type, title, summary, path, level, doc_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.parent_id,
                    node.node_type,
                    node.title,
                    node.summary,
                    node.path,
                    node.level,
                    node.doc_id,
                ),
            )
        stats.nodes_written = len(nodes)

# 改为:
        # Hierarchy is fully rebuilt each run: cheap, always consistent.
        conn.execute("DELETE FROM hierarchy")
        nodes = _build_hierarchy_nodes(parsed_docs)
        conn.executemany(
            """
            INSERT INTO hierarchy
              (id, parent_id, node_type, title, summary, path, level, doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    node.id,
                    node.parent_id,
                    node.node_type,
                    node.title,
                    node.summary,
                    node.path,
                    node.level,
                    node.doc_id,
                )
                for node in nodes
            ],
        )
        stats.nodes_written = len(nodes)
```

- [ ] **Step 3: 运行测试验证**

```bash
pytest tests/test_indexer.py -v
pytest tests/test_indexer_end_to_end.py -v
```

---

## Task 8: 消除索引时重复 clean_markdown [P1-9]

**Covers:** 避免重复计算

**Files:**
- Modify: `lorewiki/indexer/indexer.py:74-127`

- [ ] **Step 1: 修改 _build_hierarchy_nodes 接受 cleaned_body**

```python
# lorewiki/indexer/indexer.py:74-127
# 从:
def _build_hierarchy_nodes(parsed_docs: list[ParsedDocument]) -> list[HierarchyNode]:
    """Construct hierarchy nodes for every directory and every document.
    ...
    """
    nodes: dict[str, HierarchyNode] = {}
    root_id = "__root__"
    nodes[root_id] = HierarchyNode(
        id=root_id,
        parent_id=None,
        node_type="root",
        title="LoreWiki",
        path="",
        level=0,
        summary="Synthetic root node",
    )

    for parsed in parsed_docs:
        parts = parsed.path.split("/")
        accumulated: list[str] = []
        cleaned_body = cleaning.clean_markdown(parsed.body)
        cleaned_title = cleaning.clean_title(parsed.title)
        ...

# 改为:
def _build_hierarchy_nodes(
    parsed_docs: list[ParsedDocument],
    cleaned_bodies: dict[str, str],
) -> list[HierarchyNode]:
    """Construct hierarchy nodes for every directory and every document.
    ...
    """
    nodes: dict[str, HierarchyNode] = {}
    root_id = "__root__"
    nodes[root_id] = HierarchyNode(
        id=root_id,
        parent_id=None,
        node_type="root",
        title="LoreWiki",
        path="",
        level=0,
        summary="Synthetic root node",
    )

    for parsed in parsed_docs:
        parts = parsed.path.split("/")
        accumulated: list[str] = []
        cleaned_body = cleaned_bodies.get(parsed.path, cleaning.clean_markdown(parsed.body))
        cleaned_title = cleaning.clean_title(parsed.title)
        ...
```

- [ ] **Step 2: 修改 build_index 传递 cleaned_bodies**

```python
# lorewiki/indexer/indexer.py:156-180
# 从:
    parsed_docs: list[ParsedDocument] = []
    chunks_per_doc: dict[str, list[Chunk]] = {}
    for file_path in files:
        try:
            parsed = parse_markdown(file_path, rel_to=wiki_path)
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("skip {}: {}", file_path, exc)
            stats.files_skipped += 1
            continue
        cleaned_body = cleaning.clean_markdown(parsed.body)
        chunks = chunk_markdown(...)
        parsed_docs.append(parsed)
        chunks_per_doc[parsed.path] = chunks

# 改为:
    parsed_docs: list[ParsedDocument] = []
    chunks_per_doc: dict[str, list[Chunk]] = {}
    cleaned_bodies: dict[str, str] = {}
    for file_path in files:
        try:
            parsed = parse_markdown(file_path, rel_to=wiki_path)
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("skip {}: {}", file_path, exc)
            stats.files_skipped += 1
            continue
        cleaned_body = cleaning.clean_markdown(parsed.body)
        cleaned_bodies[parsed.path] = cleaned_body
        chunks = chunk_markdown(...)
        parsed_docs.append(parsed)
        chunks_per_doc[parsed.path] = chunks
```

```python
# lorewiki/indexer/indexer.py:222-223
# 从:
        nodes = _build_hierarchy_nodes(parsed_docs)

# 改为:
        nodes = _build_hierarchy_nodes(parsed_docs, cleaned_bodies)
```

- [ ] **Step 3: 运行测试验证**

```bash
pytest tests/test_indexer.py -v
```

---

## Task 9: Hierarchy 检索器优化 [P1-8]

**Covers:** 消除双重全表扫描

**Files:**
- Modify: `lorewiki/retriever/hierarchy.py:55-71`

- [ ] **Step 1: 修改 search 方法只加载一次**

```python
# lorewiki/retriever/hierarchy.py:55-71
# 从:
    def search(self, query: str, *, top_k: int = 5) -> Sequence[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []
        terms = _tokenize(query)
        if not terms:
            return []

        with open_db(self.db_path, auto_init=False) as conn:
            nodes = self._score_nodes(conn, terms)
            if not nodes:
                return []
            # Top-N nodes feed into chunk expansion; we then trim chunks
            # to ``top_k`` in the final sort.
            chunks = self._chunks_for_nodes(conn, nodes, top_k=top_k * 3)

        return self._merge_and_rank(chunks, nodes, top_k=top_k)

# 改为:
    def search(self, query: str, *, top_k: int = 5) -> Sequence[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []
        terms = _tokenize(query)
        if not terms:
            return []

        with open_db(self.db_path, auto_init=False) as conn:
            # Load all hierarchy nodes once for both scoring and chunk expansion
            all_hierarchy = conn.execute(
                "SELECT id, parent_id, node_type, title, summary, path, level, doc_id "
                "FROM hierarchy"
            ).fetchall()
            
            nodes = self._score_nodes(all_hierarchy, terms)
            if not nodes:
                return []
            chunks = self._chunks_for_nodes(conn, all_hierarchy, nodes, top_k=top_k * 3)

        return self._merge_and_rank(chunks, nodes, top_k=top_k)
```

- [ ] **Step 2: 修改 _score_nodes 接受预加载数据**

```python
# lorewiki/retriever/hierarchy.py:75-116
# 从:
    def _score_nodes(
        self, conn: sqlite3.Connection, terms: list[str]
    ) -> list[tuple[float, sqlite3.Row]]:
        """Return ``[(score, row)]`` for every hierarchy row hit by any term.
        ...
        """
        rows = conn.execute(
            "SELECT id, parent_id, node_type, title, summary, path, level, doc_id "
            "FROM hierarchy WHERE level > 0"
        ).fetchall()
        ...

# 改为:
    def _score_nodes(
        self, all_hierarchy: list[sqlite3.Row], terms: list[str]
    ) -> list[tuple[float, sqlite3.Row]]:
        """Return ``[(score, row)]`` for every hierarchy row hit by any term.
        ...
        """
        rows = [r for r in all_hierarchy if r["level"] > 0]
        ...
```

- [ ] **Step 3: 修改 _chunks_for_nodes 接受预加载数据**

```python
# lorewiki/retriever/hierarchy.py:118-157
# 从:
    def _chunks_for_nodes(
        self,
        conn: sqlite3.Connection,
        scored_nodes: list[tuple[float, sqlite3.Row]],
        *,
        top_k: int,
    ) -> list[tuple[float, sqlite3.Row, str]]:
        """For each scored node, collect the chunks living under its subtree.
        ...
        """
        # Build a parent → children map so we can DFS without recursive SQL.
        all_nodes = conn.execute(
            "SELECT id, parent_id, doc_id FROM hierarchy"
        ).fetchall()
        children: dict[str | None, list[sqlite3.Row]] = {}
        for n in all_nodes:
            children.setdefault(n["parent_id"], []).append(n)
        ...

# 改为:
    def _chunks_for_nodes(
        self,
        conn: sqlite3.Connection,
        all_hierarchy: list[sqlite3.Row],
        scored_nodes: list[tuple[float, sqlite3.Row]],
        *,
        top_k: int,
    ) -> list[tuple[float, sqlite3.Row, str]]:
        """For each scored node, collect the chunks living under its subtree.
        ...
        """
        # Build a parent → children map so we can DFS without recursive SQL.
        children: dict[str | None, list[sqlite3.Row]] = {}
        for n in all_hierarchy:
            children.setdefault(n["parent_id"], []).append(n)
        ...
```

- [ ] **Step 4: 运行测试验证**

```bash
pytest tests/test_retriever_hierarchy_and_fusion.py -v
```

---

## Task 10: LIKE 查询优化 [P0-3]

**Covers:** 限制 LIKE 只搜 title/heading

**Files:**
- Modify: `lorewiki/retriever/bm25.py:105-136`

- [ ] **Step 1: 修改 _like_pass 只搜 title 和 heading_path**

```python
# lorewiki/retriever/bm25.py:105-136
# 从:
    def _like_pass(
        self, conn: sqlite3.Connection, query: str, top_k: int
    ) -> Iterable[SearchHit]:
        like = f"%{query}%"
        rows = conn.execute(
            """
            SELECT id AS chunk_id, doc_path, title, heading_path, module,
                   content AS snippet, length(content) AS clen
            FROM documents
            WHERE title LIKE ? OR content LIKE ? OR heading_path LIKE ?
            LIMIT ?
            """,
            (like, like, like, top_k * 2),
        ).fetchall()
        ...

# 改为:
    def _like_pass(
        self, conn: sqlite3.Connection, query: str, top_k: int
    ) -> Iterable[SearchHit]:
        like = f"%{query}%"
        # Only search title and heading_path for better performance
        # (avoids full content scan)
        rows = conn.execute(
            """
            SELECT id AS chunk_id, doc_path, title, heading_path, module,
                   content AS snippet, length(content) AS clen
            FROM documents
            WHERE title LIKE ? OR heading_path LIKE ?
            LIMIT ?
            """,
            (like, like, top_k * 2),
        ).fetchall()
        ...
```

- [ ] **Step 2: 运行测试验证**

```bash
pytest tests/test_retriever_bm25.py -v
```

---

## Task 11: 添加缓存和微优化 [P2]

**Covers:** 性能优化

**Files:**
- Modify: `lorewiki/indexer/chunker.py:47-53`

- [ ] **Step 1: 预编译 estimate_tokens 的正则**

```python
# lorewiki/indexer/chunker.py:47-53
# 从:
def estimate_tokens(text: str) -> int:
    """Heuristic token count: CJK chars + whitespace-separated words."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_runs = re.findall(r"[A-Za-z0-9_]+", text)
    return cjk + len(ascii_runs)

# 改为:
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def estimate_tokens(text: str) -> int:
    """Heuristic token count: CJK chars + whitespace-separated words."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_runs = _ASCII_TOKEN_RE.findall(text)
    return cjk + len(ascii_runs)
```

- [ ] **Step 2: 运行测试验证**

```bash
pytest tests/test_chunker.py -v
```

---

## 执行顺序建议

1. **Task 1-5**（P1 代码质量）- 独立，可并行
2. **Task 6**（P0 连接缓存）- 基础设施，后续任务依赖
3. **Task 7-8**（P0/P1 索引优化）- 依赖 Task 6
4. **Task 9-10**（P0/P1 检索优化）- 依赖 Task 6
5. **Task 11**（P2 微优化）- 可选

## 验证清单

- [ ] 所有现有测试通过
- [ ] 新增测试通过
- [ ] 类型检查通过（mypy）
- [ ] Lint 检查通过（ruff）
- [ ] 性能基准测试（可选）

## 风险评估

| 风险     | 概率 | 影响 | 缓解措施                       |
| -------- | ---- | ---- | ------------------------------ |
| 连接泄漏 | 低   | 高   | 添加 close_all_connections 清理 |
| 测试失败 | 中   | 中   | 逐步实施，每步验证             |
| 类型错误 | 低   | 低   | 使用 mypy 验证                 |
