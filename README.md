<p align="center">
  <img src="https://raw.githubusercontent.com/JochenYang/Lore-wiki/main/assets/logo.png" alt="LoreWiki" width="320" />
</p>

<p align="center">
  <b><a href="README.md">English</a></b> · <a href="docs/README_zh-CN.md">中文</a>
</p>

> Local-first knowledge base for LLM-assisted coding, with hybrid retrieval
> over SQLite FTS5.

### Build with

[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white&style=for-the-badge)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/SQLite-+FTS5-003B57?logo=sqlite&logoColor=white&style=for-the-badge)](https://www.sqlite.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST-009688?logo=fastapi&logoColor=white&style=for-the-badge)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Web_UI-FF4B4B?logo=streamlit&logoColor=white&style=for-the-badge)](https://streamlit.io/)
[![MCP](https://img.shields.io/badge/MCP-1.x-1E90FF?logo=modelcontextprotocol&logoColor=white&style=for-the-badge)](https://modelcontextprotocol.io/)

### Tools

[![uv](https://img.shields.io/badge/uv-pkg%20%2B%20tool-5C2D91?logo=astral&logoColor=white&style=for-the-badge)](https://docs.astral.sh/uv/)
[![ruff](https://img.shields.io/badge/ruff-0%20errors-D7FF64?logo=ruff&logoColor=black&style=for-the-badge)](https://docs.astral.sh/ruff/)
[![pytest](https://img.shields.io/badge/pytest-198%20passed-0A9EDC?logo=pytest&logoColor=white&style=for-the-badge)](tests/)
[![License](https://img.shields.io/badge/License-MIT-22B14C?style=for-the-badge)](LICENSE)

---

LoreWiki indexes your team's Markdown wiki and exposes it through a CLI,
optional Web UI, REST API, and an MCP server consumable by Claude Desktop /
Cursor / other LLM clients.

**Key numbers from the example_wiki benchmark** (10 hand-authored queries):

| Mode          | Recall@5 | Avg latency |
|---------------|----------|-------------|
| BM25          | 80%      | 1.7 ms      |
| Hierarchy     | 90%      | 0.8 ms      |
| **Mix (RRF)** | **100%** | 3.0 ms      |

## Features

- **Hybrid retrieval**: FTS5 BM25 + hierarchy tree navigation, fused via
  Reciprocal Rank Fusion (no score normalisation needed).
- **Chinese + English friendly**: trigram tokenizer + bigram/LIKE fallback for
  short CJK queries (e.g. `"幂等"` (idempotent), `"认证"` (auth)).
- **Optional LLM integration** (Ollama or OpenAI-compatible). Gracefully
  degrades to "return the top-k chunks" when the LLM is offline.
- **Five entry points** sharing one core: CLI, REST (FastAPI), Web UI
  (Streamlit), MCP stdio (for Claude Desktop / Cursor / etc.),
  agent skill (for opencode / Codex / Aider / any shell-using agent).
- **Second-brain / topics**: one isolated vault per knowledge domain
  under `~/lorewiki/topics/`, shared across every project.
- **Zero external services**: SQLite is the only dependency for retrieval.
  LLM is opt-in.
- **Single-package install**: `pip install lorewiki` and you have
  everything; the data lives in your home and is fully owned.

## Installation

```bash
# Editable install (recommended for active development)
uv tool install --editable . --with fastapi --with "uvicorn[standard]" --with mcp

# Or plain pip
pip install -e .                 # core CLI + REST + MCP
pip install -e ".[ui]"           # add Streamlit Web UI
pip install -e ".[dev]"          # add pytest / ruff / coverage
pip install -e ".[all]"          # everything
```

Python **3.10+** required. After install, `lorewiki --version`
should print `LoreWiki 0.1.0`.

> Windows PowerShell users: if CJK characters show as `?` in
> `lorewiki search --raw` output, prefix the command with
> `chcp 65001 |` to force the shell code page to UTF-8, or upgrade
> to v0.1.1+ which forces UTF-8 stdout automatically.

## Quickstart

```bash
# 1. Create a wiki + config
lorewiki init --path ./my-wiki

# 2. Author Markdown under ./my-wiki/, then index it
lorewiki index --path ./my-wiki

# 3. Search
lorewiki search "用户登录接口" --path ./my-wiki --mode mix --top-k 5

# 4. Ask (LLM-assisted answer, gracefully falls back to top chunks)
lorewiki ask "如何实现幂等重试" --path ./my-wiki

# 5. Browse the index status
lorewiki status --path ./my-wiki
```

The default config lives in `<wiki>/.lorewiki/config.toml`; user-wide
overrides live in `~/.lorewiki/config.toml`; env vars `LOREWIKI_*` override
both.

## Topics — your second brain

The per-wiki mode above is fine for a single project. The
**shared-brain** workflow is **topics** — isolated vaults under
`~/lorewiki/topics/`, queryable from any project:

```bash
lorewiki topic create react                              # empty vault
lorewiki topic create react --source ~/notes/react       # copy mode (default)
lorewiki topic create react --source ~/notes/react --link  # symlink mode
lorewiki topic use react                                 # activate
lorewiki index                                           # index the active topic
lorewiki search "useState closure"                       # query the active topic
lorewiki ask "props drilling 对比"                       # LLM answer from active topic
```

Layout produced:

```
~/lorewiki/                          # central root
├── config.toml                      # global: LLM key, retrieval mode
├── current                          # text: name of active topic
└── topics/
    └── react/                       # one topic = one vault
        ├── .lorewiki/index.db       # hidden lorewiki metadata
        ├── api/auth.md
        └── architecture.md
```

**Topic resolution priority** (later wins): `--topic` flag →
`LOREWIKI_TOPIC` env → `~/lorewiki/current` file → `--path` (legacy
per-wiki mode) → cwd `.lorewiki/config.toml` (legacy per-project mode).

The legacy per-project mode is **permanently supported** — no
migration required. Topics are a convenience, not a replacement.

The vault root is plain Markdown with a hidden `.lorewiki/`
directory, so **Obsidian / Logseq / VS Code can open it directly**
without lorewiki installed. That cross-tool friendliness is the
whole point of the "second brain" framing.

Topic names: lowercase ASCII, digits, hyphens, 1-64 chars, no
leading/trailing hyphens. Reserved names (`init`, `index`,
`current`, Windows device names) are rejected.

## How it works

For a one-query end-to-end walkthrough (CLI dispatch → config
resolution → retriever selection → RRF fusion → output) plus a
deep dive on **how the LLM config actually takes effect**
(three configuration paths, `build_client` dispatch, why pure
`httpx` instead of SDKs), see [`docs/how-it-works.md`](docs/how-it-works.md).

A higher-level architecture overview lives in
[`docs/architecture.md`](docs/architecture.md). Per-phase
self-critique notes are in `docs/critique/phase-{0..6}.md`.

## Configuration

```toml
# ./my-wiki/.lorewiki/config.toml

retrieval_mode = "mix"            # mix | bm25 | hierarchy | vector
rrf_k = 60
chunk_max_tokens = 800
chunk_overlap_tokens = 100
chunk_min_chars = 40
snippet_chars = 240

[mix_weights]
bm25 = 1.0
hierarchy = 0.8
vector = 0.5

[llm]
enabled = false                   # set true to enable `ask`'s LLM path
backend = "ollama"                # ollama | openai
ollama_url = "http://localhost:11434"
ollama_model = "llama3.2"
openai_api_key = ""
openai_base_url = ""              # leave blank for api.openai.com
openai_model = "gpt-4o-mini"
timeout_seconds = 30.0
```

Programmatic access:

```bash
lorewiki config list --path ./my-wiki
lorewiki config get llm.backend --path ./my-wiki
lorewiki config set retrieval_mode '"bm25"' --path ./my-wiki
```

## LLM setup

### Ollama (local, recommended)

```bash
ollama pull llama3.2
lorewiki config set llm.enabled true     --path ./my-wiki
lorewiki config set llm.backend '"ollama"' --path ./my-wiki
lorewiki ask "what's our retry policy?" --path ./my-wiki
```

### OpenAI-compatible (any provider that speaks the `/v1/chat/completions` schema)

> **Note on Azure OpenAI**: Azure's path is different
> (`/openai/deployments/<deployment>/chat/completions?api-version=...`)
> and is **not** currently supported. Use OpenRouter or a self-hosted
> vLLM-compatible endpoint, or wait for the phase-7 Azure support
> (or open an issue if you need it sooner).

```bash
lorewiki config set llm.enabled true     --path ./my-wiki
lorewiki config set llm.backend '"openai"' --path ./my-wiki
lorewiki config set llm.openai_api_key '"sk-..."' --path ./my-wiki
# Optional: point at a compatible proxy (OpenRouter, Azure, vLLM, ...).
lorewiki config set llm.openai_base_url '"https://openrouter.ai/api/v1"' --path ./my-wiki
```

If the LLM is unreachable, `ask` returns the top-K chunks with a clear
"degraded" notice — your workflow never breaks because the model is down.

## REST API

```bash
lorewiki rest --port 8000 --path ./my-wiki
# Swagger UI:    http://127.0.0.1:8000/docs
# OpenAPI JSON:  http://127.0.0.1:8000/openapi.json
```

Endpoints (all return JSON):

| Method | Path                  | Description                                               |
|--------|-----------------------|-----------------------------------------------------------|
| GET    | `/health`             | Liveness probe (`{"status": "ok"}`)                       |
| GET    | `/status`             | Index statistics (chunks, docs, last-indexed-at, db size) |
| POST   | `/search`             | `{query, top_k, mode}` → ranked hits                      |
| POST   | `/ask`                | `{query, top_k}` → answer + citations                     |
| GET    | `/modules`            | Top-level module list                                     |
| GET    | `/module/{path:path}` | Sub-tree of a hierarchy node                              |

Example:

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "幂等设计", "top_k": 3, "mode": "mix"}'
```

## Web UI (Streamlit)

```bash
pip install lorewiki[ui]
lorewiki ui --port 8501 --path ./my-wiki
# Opens http://127.0.0.1:8501 in your browser.
```

Four pages in the sidebar: **Search** (with optional "ask" mode), **Browse**
(hierarchy tree + Markdown render), **Config** (read-only view of the merged
config), **Status** (index metrics).

## MCP server (Claude Desktop / Cursor)

In your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS, `%APPDATA%/Claude/claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "lorewiki": {
      "command": "lorewiki",
      "args": ["mcp", "--path", "/absolute/path/to/my-wiki"]
    }
  }
}
```

Exposed tools:

- `search_lorewiki(query, top_k=5, mode="mix")` — returns ranked chunks.
- `get_module_summary(module_path="")` — explores the hierarchy tree.

## opencode skill (Codex / Aider / any shell-using agent)

For agents that can already run shell commands, the CLI is lighter-weight
than MCP. LoreWiki ships an official [opencode](https://opencode.ai) skill
in [`skills/lorewiki/SKILL.md`](skills/lorewiki/SKILL.md).

One-time install (after `uv tool install --editable . --with fastapi --with "uvicorn[standard]" --with mcp` puts `lorewiki` on your PATH):

```powershell
# Windows
.\skills\install.ps1            # copy mode
.\skills\install.ps1 -Symlink   # symlink mode (lets you edit SKILL.md live)
```

```bash
# macOS / Linux
./skills/install.sh             # copy mode
./skills/install.sh --symlink   # symlink mode
```

Restart opencode and the agent will auto-trigger the skill on cues like
`查 wiki` / `search the wiki` / `lorewiki ...`. See
[`skills/README.md`](skills/README.md) for full details.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│           CLI · REST · Streamlit UI · MCP stdio             │
├─────────────────────────────────────────────────────────────┤
│  Indexer  │  Retriever (BM25 + Hierarchy + RRF)  │  LLM    │
├─────────────────────────────────────────────────────────────┤
│        SQLite + FTS5 (documents · docs_fts · hierarchy)     │
└─────────────────────────────────────────────────────────────┘
```

See `docs/lorewiki dev document.md` for the full design plan and
`docs/critique/phase-{0..6}.md` for per-phase self-critique notes.

## Development

```bash
pip install -e ".[dev]"
ruff check lorewiki skills tests  # lint
pytest -q                        # 198 unit + integration tests
pytest --cov=lorewiki            # coverage report
```

Benchmarks (require `example_wiki/`):

```bash
python scripts/recall_phase2.py  # BM25 vs Hierarchy vs Mix recall comparison
```

The `example_wiki/` directory is a curated 5-file benchmark
fixture — not a starter. See `example_wiki/README.md` for what
it is and how to use it.

## Roadmap

- **Vector retrieval** (sqlite-vec + sentence-transformers) — opt-in.
- **Async LLM client** — non-blocking REST `/ask` for concurrent requests.
- **Streaming `ask` endpoint** (SSE).
- **Incremental file-watcher** (`lorewiki update --watch`).
- **PDF / Word ingestion** beyond Markdown.
- **Read-only Config page** → editable form in the Streamlit UI.
- **Atomic write of `~/lorewiki/current`** (currently best-effort).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow. Bug
reports and feature requests go to the issue tracker; PRs are
welcome — see the testing / linting commands above.

## License

[MIT](LICENSE) · Copyright (c) 2026 LoreWiki contributors.
