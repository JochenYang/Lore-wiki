-- LoreWiki SQLite schema (phase 1).
--
-- Design notes (deviations from the dev plan are documented inline):
--
-- 1. ``documents.rowid`` is INTEGER so FTS5 ``content=`` external-content mode
--    can join via ``content_rowid``. The dev plan kept ``id`` as the TEXT
--    primary key, but FTS5 requires an INTEGER rowid relationship. We keep
--    ``id`` as a UNIQUE business identifier (``"<doc_path>#<chunk_idx>"``).
--
-- 2. Each row in ``documents`` is a *chunk* of an original Markdown file, not
--    the whole file. ``(doc_path, chunk_index)`` is UNIQUE, and we expose
--    ``heading_path`` (e.g. "Overview > Design") so the retriever can show
--    breadcrumbs without re-parsing the source file.
--
-- 3. Tokenizer is ``trigram`` (SQLite 3.34+). This gives reasonable recall on
--    both English and Chinese text (the dev plan didn't pin a tokenizer; the
--    default ``unicode61`` would break Chinese phrases into single characters).
--
-- 4. Triggers follow the canonical FTS5 external-content pattern: on update
--    the old row is *deleted* from the FTS index using a special 'delete'
--    command before the new content is inserted.
--
-- 5. ``hierarchy`` keeps the dev-plan shape but uses CASCADE on parent FK so
--    rebuilding a sub-tree doesn't strand orphans.
--
-- 6. ``meta`` replaces the ``config`` table from the dev plan; configuration
--    lives on disk (TOML), the ``meta`` table only stores index statistics
--    such as last-index-time, doc count, schema version.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version(version) VALUES (1);

CREATE TABLE IF NOT EXISTS documents (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    doc_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    heading_path TEXT,
    content TEXT NOT NULL,
    module TEXT,
    tags TEXT,
    token_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(doc_path, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_documents_doc_path ON documents(doc_path);
CREATE INDEX IF NOT EXISTS idx_documents_module ON documents(module);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title, content, module, heading_path,
    content=documents,
    content_rowid=rowid,
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO docs_fts(rowid, title, content, module, heading_path)
    VALUES (new.rowid, new.title, new.content, new.module, new.heading_path);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content, module, heading_path)
    VALUES('delete', old.rowid, old.title, old.content, old.module, old.heading_path);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content, module, heading_path)
    VALUES('delete', old.rowid, old.title, old.content, old.module, old.heading_path);
    INSERT INTO docs_fts(rowid, title, content, module, heading_path)
    VALUES (new.rowid, new.title, new.content, new.module, new.heading_path);
END;

CREATE TABLE IF NOT EXISTS hierarchy (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    node_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    path TEXT NOT NULL UNIQUE,
    level INTEGER NOT NULL,
    doc_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(parent_id) REFERENCES hierarchy(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_hierarchy_parent ON hierarchy(parent_id);
CREATE INDEX IF NOT EXISTS idx_hierarchy_level ON hierarchy(level);
CREATE INDEX IF NOT EXISTS idx_hierarchy_doc ON hierarchy(doc_id);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
