# LoreWiki — How it works & structure

> v0.1.x · A reference for maintainers and future contributors.

## 1. One-paragraph summary

> **LoreWiki = a SQLite FTS5 index + a directory of knowledge "topics"
> (vaults) under the user's home + multiple entry points (CLI / REST /
> UI / MCP / agent skill).**
> Data is yours, shared across every project, and the vault root is
> a plain folder that Obsidian / Logseq / VS Code can open directly.

## 2. Core principles

1. **Local-first** — every byte lives under `~/.lorewiki/`. Zero cloud
   dependency. Drop the folder into iCloud / OneDrive / git and it
   just syncs.
2. **Data ownership** — the vault root is a plain Markdown folder
   with **no lorewiki-specific file format**. `.lorewiki/` is hidden
   metadata, invisible to other tools.
3. **Cross-project** — topics live in `~/.lorewiki/topics/`, never
   inside any project. `lorewiki search` from project A or B hits
   the same active-topic index.
4. **Equal entry points** — CLI / REST / UI / MCP / agent skill
   share the same config and the same DB. There is no "secondary"
   entry point.
5. **Graceful degradation** — LLM down → `ask` returns top-K hits.
   BM25 index missing → prompt to rebuild. Windows shell with
   non-UTF-8 code page → stdout is auto-reconfigured.
6. **Permanent backward compatibility** — the legacy per-project
   wiki mode (`--path`) is **never** deprecated. New features are
   additive, not replacements.

## 3. Data flow (user view)

```text
  ┌──────────────────────────────────────────┐
  │  User writes / pastes Markdown            │
  │  (any editor: VSCode, Obsidian, vim)     │
  └────────────────┬─────────────────────────┘
                   │
                   ▼
  ┌──────────────────────────────────────────┐
  │  lorewiki index [active topic]           │
  │   parser  → chunker  → indexer (SQLite)  │
  │   FTS5 trigram tokenizer (CJK-friendly)  │
  └────────────────┬─────────────────────────┘
                   │
                   ▼
  ┌──────────────────────────────────────────┐
  │  lorewiki search QUERY [--topic X]        │
  │   BM25 (FTS5) + hierarchy (LIKE) + RRF    │
  │   + optional LLM (ollama / openai)        │
  └────────────────┬─────────────────────────┘
                   │
                   ▼
  ┌──────────────────────────────────────────┐
  │  Output                                    │
  │   --raw: JSON for agents                  │
  │   default: rich table / markdown panel    │
  │   + optional ask-LLM answer (fallback)    │
  └──────────────────────────────────────────┘
```

## 4. Directory layout (on disk)

### 4.1 Central root (one per user)

```text
~/.lorewiki/
├── config.toml                  # global config (LLM keys, retrieval mode, mix weights)
├── current                      # text file: name of the active topic
└── topics/
    ├── react/                   # one topic = one vault
    ├── wechat-mp/
    ├── cocos/
    └── ...
```

`config.toml` and `current` are lorewiki's own metadata; the content
of `topics/<name>/` is **transparent to other tools** (detailed
below).

### 4.2 A single topic's layout

Every topic is a **fully self-contained vault**:

```text
~/lorewiki/topics/react/                  # topic root
├── .lorewiki/                            # hidden: lorewiki-only metadata
│   └── index.db                          # SQLite FTS5 index
├── config.toml                           # optional: per-topic overrides
├── api/                                  # user-organised subdirectories (any depth)
│   ├── auth.md                           # markdown with frontmatter
│   └── user/
│       └── profile.md
├── patterns/
│   ├── retry.md
│   └── rate-limit.md
└── architecture.md
```

**Key points**:
- `api/` and `patterns/` are the user's own folder structure —
  lorewiki does not impose or expect any particular layout.
- `.lorewiki/index.db` is hidden, **invisible to Obsidian /
  Logseq / VS Code**.
- The topic root **is** a valid Obsidian vault — open
  `obsidian ~/lorewiki/topics/react` and it just works.
- Any `.md` may carry YAML frontmatter; lorewiki parses `title`,
  `module`, and `tags`:

```markdown
---
title: Authentication API          # "title: 用户认证 API" also valid
module: api/user
tags: [auth, jwt]
---

# Authentication API

This service implements a JWT dual-token scheme...
```

### 4.3 Full multi-topic layout (a typical "second brain")

A user might have all of these simultaneously:

```text
~/.lorewiki/
├── config.toml                  # global: [llm] enabled = true, ollama_model = "qwen2.5:7b"
├── current                      # contents: "react"
└── topics/
    ├── react/                   # ← currently active (current file points here)
    │   ├── .lorewiki/index.db
    │   ├── hooks/
    │   ├── patterns/
    │   └── tooling/
    ├── wechat-mp/
    │   ├── .lorewiki/index.db
    │   ├── api/
    │   ├── component/
    │   └── publish.md
    ├── cocos/
    │   ├── .lorewiki/index.db
    │   ├── creator/
    │   └── 2d-vs-3d.md
    └── notes/                   # misc notes
        ├── meetings/
        └── ideas.md
```

Each topic is **fully isolated**:
- its own DB (`topics/<name>/.lorewiki/index.db`)
- its own source markdown
- its own config overrides
- its own index timestamp

`lorewiki topic use cocos && lorewiki index && lorewiki search "动作系统"`
queries **only** the cocos topic.

## 5. Module map (code view)

```text
lorewiki/
├── __init__.py
├── cli.py                   # Typer CLI entry; 7 root commands + topic subcommand group
├── config.py                # pydantic-settings loader + topic resolution
├── topic.py                 # TopicManager: second-brain CRUD
├── db/
│   ├── schema.sql           # documents / docs_fts (FTS5 trigram) / hierarchy / meta
│   ├── connection.py        # open_db() context manager
│   └── __init__.py
├── indexer/
│   ├── parser.py            # frontmatter + body parsing
│   ├── chunker.py           # ## split + token budget + code-fence guard
│   └── indexer.py           # walker → parse → chunk → INSERT
├── retriever/
│   ├── bm25.py              # three-tier BM25: phrase → OR trigrams → LIKE
│   ├── hierarchy.py         # module/heading path matching (bigram + trigram)
│   └── fusion.py            # RRF (Reciprocal Rank Fusion)
├── llm/
│   ├── client.py            # BaseLLMClient + OllamaClient + OpenAIClient + DisabledLLMClient
│   └── generator.py         # AnswerGenerator: prompt assembly + invoke + parse
├── server/
│   ├── rest_api.py          # FastAPI: 6 endpoints + OpenAPI + 503 fallback
│   ├── mcp_server.py        # MCP stdio: search_lorewiki + get_module_summary
│   └── ui.py                # Streamlit: 4 pages (lazy import)
└── utils/
    └── logger.py            # loguru wrapper
```

### 5.1 Key module responsibilities

| Module                  | Responsibility                                                                                |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| `cli.py`                | Typer command tree; env / config / flag merging; `--topic` global flag injection             |
| `config.py`             | 4-layer config priority: defaults → user TOML → **topic TOML** → project TOML → env → overrides |
| `topic.py`              | Second-brain CRUD; `validate_name` defends against `../`-style path traversal; `TopicManager(root=...)` rejects paths outside `USER_TOPICS_ROOT` by default |
| `db/schema.sql`         | 4 tables + 3 triggers; FTS5 with **trigram tokenizer** (CJK-friendly)                        |
| `indexer/chunker.py`    | `##` split + token budget + tiny-merge + code-fence preservation                             |
| `retriever/bm25.py`     | Three-tier query: phrase ≥3 char → OR trigrams → LIKE fallback                               |
| `retriever/hierarchy.py` | Bigram + trigram tokenization so 2-character CJK terms can match titles                      |
| `retriever/fusion.py`   | RRF k=60 (no need to normalise across score scales)                                            |
| `llm/client.py`         | Pure httpx; auto-compatible with OpenAI-protocol proxies                                      |
| `server/rest_api.py`    | 503 fallback when DB / LLM missing                                                            |
| `server/mcp_server.py`  | Low-level `Server` API (not FastMCP, signature stability)                                    |

## 6. Config-loading priority

Every `lorewiki <cmd>` invocation merges config in this order
(later wins):

```text
1. pydantic field defaults           # in code
2. ~/.lorewiki/config.toml           # global user config
3. ~/.lorewiki/topics/<active>/config.toml   # active topic overrides
4. <cwd>/.lorewiki/config.toml       # project-level override (legacy per-project mode)
5. LOREWIKI_* env vars               # CI / agent use
6. CLI --topic / --path / etc        # explicit overrides
```

**Example**: in project A, run `lorewiki search "JWT"` with active
topic `react` →
- reads `~/.lorewiki/topics/react/config.toml` (if present)
- reads `A/.lorewiki/config.toml` (if present)
- **also** reads `~/.lorewiki/config.toml` (yes, layer 2 is not
  skipped)
- layers 1-2-3-4-5 are all merged; layer 6 overrides last

The legacy per-project mode (`lorewiki init --path ./wiki`) only
affects `wiki_path` and `db_path`; it does **not** affect LLM /
retrieval config.

## 7. Path-resolution priority

Every time lorewiki decides "which topic / wiki are we operating
on?", the priority from highest to lowest is:

```text
1. --topic <name>                  # command-line flag (highest)
2. LOREWIKI_TOPIC env var          # agent / shell injection
3. ~/.lorewiki/current file        # most recently `topic use`-activated
4. --path <dir>                    # legacy per-wiki mode
5. <cwd>/.lorewiki/config.toml     # legacy per-project mode
```

**Full data-flow example**: in project A, run `lorewiki search
"限流"`:
1. CLI reads `--topic` flag → `None`
2. Reads `LOREWIKI_TOPIC` env → `None`
3. Reads `~/.lorewiki/current` → `"react"`
4. Resolves to topic `react`
5. Queries `topics/react/.lorewiki/index.db`
6. Same react index, **shared** across project A and any other
   project ✅

## 8. Retrieval pipeline (detail)

```text
User query: "限流方案"            # (also: "rate limit" in English works equally)
        │
        ▼
┌───────────────────────────────────────┐
│ BM25Retriever.search()                │
│  - phrase match (FTS5) ≥3 char        │
│  - OR trigrams (FTS5) for short CJK   │
│  - LIKE fallback (in-Python)          │
└───────────┬───────────────────────────┘
            │ ranked list
            ▼
┌───────────────────────────────────────┐
│ HierarchyRetriever.search()           │
│  - module / heading path matching      │
│  - bigram+trigram tokenization         │
│  - LIKE on title + heading_path        │
└───────────┬───────────────────────────┘
            │ ranked list
            ▼
┌───────────────────────────────────────┐
│ RRFFusion.fuse()                      │
│  - k=60                               │
│  - combine = sum of 1/(k+rank)        │
│  - weights: mix_weights (1.0 / 0.8)  │
└───────────┬───────────────────────────┘
            │ fused ranked list
            ▼
┌───────────────────────────────────────┐
│ (optional) AnswerGenerator.generate()  │
│  - prompt: top-K chunks + question    │
│  - LLM via Ollama / OpenAI client     │
│  - graceful fallback if no LLM         │
└───────────────────────────────────────┘
```

## 9. Entry-point comparison (same query, different output)

| Entry point                          | Call                                                    | Output                                  |
| ------------------------------------ | ------------------------------------------------------- | --------------------------------------- |
| **CLI (human)**                       | `lorewiki search "限流"`                                  | Rich table (default) / JSON (`--raw`)   |
| **CLI (agent)**                       | `lorewiki --topic react search "限流" --raw`              | Pure JSON array (clean UTF-8)           |
| **REST API**                           | `GET /search?q=限流`                                     | JSON (OpenAPI at `/docs`)               |
| **Streamlit UI**                       | http://127.0.0.1:8501 "Search" page                     | Browser-rendered                        |
| **MCP stdio**                          | `search_lorewiki(query="限流")`                          | MCP JSON-RPC frame                      |
| **agent skill** (opencode et al.)     | agent reads SKILL.md, calls `lorewiki search --raw`      | agent parses the JSON itself            |

**All entry points** use the same DB, the same config, the same
retrieval logic — **no "secondary" entry**.

## 10. Backup & migration

The entire lorewiki state = 3 locations:

```text
1. ~/.lorewiki/config.toml          # global config
2. ~/.lorewiki/current              # active-topic pointer
3. ~/.lorewiki/topics/              # all topics + dbs + source markdown
```

**Backing up the whole lorewiki = tar/zip #3**. #1 and #2 are
small enough to ignore; many users' backup strategy is **just
back up `topics/`** (the DB is regenerable; the markdown is the
real data).

**Migrating to a new machine**:

```bash
# old machine
tar czf lorewiki-backup.tar.gz ~/.lorewiki/topics/

# new machine
mkdir -p ~/.lorewiki
tar xzf lorewiki-backup.tar.gz -C ~
# re-set config and the current pointer (or back them up too)
```

## 11. Security / permission boundaries

- **DB files**: under the user's home; file permissions follow the
  home directory (Unix 0600 / Windows user-only by default).
- **Hidden files / directories** (`.lorewiki/`): Unix 0700
  (owner-only).
- **Topic-name rules**: `^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$` — blocks
  `../`, reserved CLI subcommand names, and Windows device names.
- **`TopicManager(root=...)` defence**: by default rejects any root
  outside `USER_TOPICS_ROOT` (defence against MCP-driven
  injection).
- **CLI encoding**: Windows shells with non-UTF-8 code pages are
  auto-reconfigured at import time (defence against GBK mojibake).
- **No hardcoded secrets**: LLM keys come from env / TOML, never
  from source.

## 12. Known limits / out of scope

- **No LLM-driven web scraping** (project design decision) — users
  scrape and write markdown inside their AI tool of choice
  (Cursor / Claude Code / opencode), then call `lorewiki index`.
- **No built-in sync subcommand** — `topics/` is a plain folder;
  the user syncs with iCloud / OneDrive / git.
- **No soft-delete / recycle bin** — `topic delete` is a hard
  delete with confirmation.
- **No CJK-to-ASCII transliteration** — `topic suggest` returns
  empty for Chinese-only inputs and prompts the user to name the
  topic by hand.
- **No remote / multi-user** — lorewiki is a single-user local
  tool. Multi-user = each user installs their own.

## 13. Phase history

| Phase  | Topic                              | Status   |
| ------ | ---------------------------------- | -------- |
| 0      | bootstrap / CLI skeleton           | ✅ done  |
| 1      | index + BM25 search                | ✅ done  |
| 2      | hierarchy + RRF fusion             | ✅ done  |
| 3      | LLM integration                    | ✅ done  |
| 4      | Streamlit UI + REST                | ✅ done  |
| 5      | MCP server + packaging             | ✅ done  |
| 6      | **Topic / second-brain model**     | ✅ done  |
| 7+     | future iterations                  | ⏳ TBD  |

## 14. Cheat sheet

> Your wiki = `~/lorewiki/topics/<vault>/`.
> Adding content to a vault? Drop a `.md` and run `lorewiki index`.
> Starting a new topic? `lorewiki topic create <name>` or
> `lorewiki topic suggest "react hooks learning"`.
> Searching from any project? `lorewiki search "..."` — no need to
> pass any path; the active topic is used automatically.
