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

### Tools

[![uv](https://img.shields.io/badge/uv-pkg%20%2B%20tool-5C2D91?logo=astral&logoColor=white&style=for-the-badge)](https://docs.astral.sh/uv/)
[![ruff](https://img.shields.io/badge/ruff-0%20errors-D7FF64?logo=ruff&logoColor=black&style=for-the-badge)](https://docs.astral.sh/ruff/)
[![pytest](https://img.shields.io/badge/pytest-373%20passed-0A9EDC?logo=pytest&logoColor=white&style=for-the-badge)](tests/)

<!-- Test commit for release workflow validation -->
[![License](https://img.shields.io/badge/License-MIT-22B14C?style=for-the-badge)](LICENSE)

---

LoreWiki indexes your team's Markdown wiki and exposes it through a single
CLI plus an [opencode](https://opencode.ai) skill consumable by Codex /
Aider / Claude Code / any shell-using LLM agent. The vault is also a
plain folder of `.md` files, so Obsidian / Logseq / VS Code can open
it directly.

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
- **Single-binary CLI + opencode skill**: one command surface, one
  opencode skill (or any shell-using agent) for AI consumption, and
  the on-disk vault as the "UI". No server processes, no extra
  dependencies.
- **One `lorewiki add`** to author a note end-to-end (body via
  `--body` / `--file` / stdin) with auto-reindex so the new doc is
  immediately retrievable.
- **Second-brain / topics**: one isolated vault per knowledge domain
  under `~/lorewiki/topics/`, shared across every project.
- **Zero external services**: SQLite is the only dependency for retrieval.
  LLM is opt-in.
- **Single-package install**: `pip install lorewiki` and you have
  everything; the data lives in your home and is fully owned.

## Installation

LoreWiki ships as a single Python wheel on **PyPI** (the only
distribution channel). Pick your preferred installer:

### uv (recommended, full feature set)

```bash
# Install — isolated per-tool venv, the lorewiki.exe (Windows)
# or lorewiki binary (macOS/Linux) is added to your PATH.
uv tool install lorewiki

# With the optional vector-retrieval extra (sqlite-vec + sentence-transformers):
uv tool install 'lorewiki[vector]'

# Upgrade:
uv tool upgrade lorewiki

# Uninstall (does NOT touch ~/.lorewiki/ — your data is yours):
uv tool uninstall lorewiki
```

If you don't have `uv` yet:

```bash
# macOS / Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell):
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Plain `pip` works too (the `lorewiki.exe` entry point is the same):

```bash
pip install lorewiki              # core CLI
pip install 'lorewiki[vector]'    # opt-in: vector retrieval
```

> The `[rest]` and `[mcp]` extras from 0.1.x are gone as of 0.2.0.
> The CLI + opencode skill replaced the FastAPI / MCP server surface.
> The `[all]` extra is now an alias for `[vector]`.

### From source (for contributors)

```bash
git clone https://github.com/JochenYang/Lore-wiki
cd Lore-wiki
uv tool install --editable .              # dev install
uv tool install --editable '.[dev]'       # + pytest / ruff / coverage
```

Python **3.10+** is required. After install, `lorewiki --version`
should print a banner ending with `v0.2.x`.

> **Windows PowerShell + CJK note**: starting with 0.2.0, LoreWiki
> forces UTF-8 on stdout/stderr unconditionally — CJK characters
> round-trip cleanly through the shell without `chcp 65001`. If you
> hit garbled output on an older release, upgrade with
> `uv tool upgrade lorewiki` or prefix the command with
> `chcp 65001 |`.

For deeper install info (PATH troubleshooting, where data lives,
backups, common errors, how publishing works), see
[`docs/install.md`](docs/install.md).

## Quickstart

```bash
# 1. Create a wiki + sample Markdown
lorewiki init --path ./my-wiki

# 2. Index the Markdown into SQLite + FTS5 (one-time, then incremental)
lorewiki index --path ./my-wiki

# 3. Search (default output is structured JSON for agents; --human for Rich Table)
lorewiki search "用户登录接口" --path ./my-wiki --mode mix --top-k 5
lorewiki search "用户登录接口" --path ./my-wiki --mode mix --top-k 5 --human

# 4. Ask (LLM-assisted answer, gracefully falls back to top chunks)
lorewiki ask "如何实现幂等重试" --path ./my-wiki

# 5. Author a note from the CLI (writes + re-indexes in one go)
#    Three equivalent ways to provide the body:
lorewiki add --title "Python Design" --module "patterns" --tag python,design \
    --body "Some deep details about Python design patterns." \
    --path ./my-wiki

#    --file: read the body from a file
lorewiki add --title "From File" --module "patterns" \
    --file ./drafts/python-design.md --path ./my-wiki

#    stdin pipe (any of these is fine on Windows + PowerShell, even
#    with CJK content; 0.2.2+ scrubs UTF-16 surrogates automatically)
echo "Some deep details about Python design patterns." \
  | lorewiki add --title "From Pipe" --module "patterns" --path ./my-wiki

# 6. Browse the index / hierarchy / status
lorewiki status --path ./my-wiki
lorewiki tree   --path ./my-wiki      # Rich-Tree view of the hierarchy
lorewiki show   index.md --path ./my-wiki   # print a doc body (cleaned)
```

**Config resolution** combines global settings, project bindings, and explicit
overrides. For topic selection, LoreWiki now uses this priority:

1. `--topic <name>` — explicit one-shot topic.
2. `LOREWIKI_TOPIC` — environment override.
3. `<cwd-or-ancestor>/.lorewiki/config.toml` with `default_topic = "name"`.
4. `~/.lorewiki/current` — fallback set by `lorewiki topic use <name>`.
5. Legacy `--path <WIKI_ROOT>` / `wiki_path` mode for standalone wiki folders.

Edit config with `lorewiki config list / get / set` (TOML-aware, no
hand-editing required).

## Topics — your second brain

The per-wiki mode above is fine for standalone folders. The
**shared-brain** workflow is **topics** — isolated vaults under
`~/lorewiki/topics/`. A code project can bind to one topic while agents
can still query shared/common topics explicitly:

```bash
lorewiki topic create lorewiki                            # empty project vault
lorewiki topic create shared                              # common cross-project vault
lorewiki topic create react --source ~/notes/react        # copy mode (default)
lorewiki topic create react --source ~/notes/react --link # symlink mode

# Bind the current code project to its default topic:
lorewiki config set default_topic lorewiki

# Inside the bound project, these use the project topic automatically:
lorewiki index
lorewiki search "config resolution"
lorewiki ask "how does topic resolution work?"

# Query common knowledge explicitly when needed:
lorewiki --topic shared search "python packaging pitfalls"
```

Layout produced:

```
~/lorewiki/                          # central root
├── config.toml                      # global: LLM key, retrieval mode
├── current                          # text: manual fallback topic
└── topics/
    └── lorewiki/                    # one topic = one vault
        ├── .lorewiki/index.db       # hidden lorewiki metadata
        ├── api/auth.md
        └── architecture.md
```

The legacy per-project / per-wiki mode is **permanently supported** — no
migration required. Topics and project `default_topic` are the recommended
workflow for LLM-assisted development.

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

The FastAPI / REST surface was removed in 0.2.0. The CLI is the only
programmatic surface; agents consume it through the opencode skill
(see below) or by shelling out.

## The Markdown vault as your "UI"

LoreWiki no longer ships a built-in web UI in 0.1.0. The recommended
ways to consume the data are:

- **The CLI** (this document) — the single source of truth.
- **The active topic's vault directory** — every topic is a plain
  folder of `.md` files under `~/.lorewiki/topics/<name>/` (or
  `<wiki>/.lorewiki/...` in per-wiki mode). Open it in Obsidian,
  VS Code, Cursor, or any Markdown editor for the full rendered
  view, no extra tooling required.
- **The opencode skill** (below) — for AI agents.

## opencode skill (Codex / Aider / any shell-using agent)

For agents that can already run shell commands, the CLI is lighter-weight
than MCP. LoreWiki ships an official [opencode](https://opencode.ai) skill
in [`skills/lorewiki/SKILL.md`](skills/lorewiki/SKILL.md).

One-time install (after `uv tool install --editable .` puts `lorewiki` on your PATH):

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
│            CLI + opencode skill · vault-as-folder          │
├─────────────────────────────────────────────────────────────┤
│  Indexer  │  Retriever (BM25 + Hierarchy + RRF)  │  LLM    │
├─────────────────────────────────────────────────────────────┤
│  SQLite + FTS5 (documents · docs_fts · hierarchy · edges)  │
└─────────────────────────────────────────────────────────────┘
```

See `docs/lorewiki dev document.md` for the full design plan and
`docs/critique/phase-{0..6}.md` for per-phase self-critique notes.

## LLM Integration

LoreWiki supports three layers of LLM integration, from most seamless
to most universal. All three can coexist — pick the one your tool
supports.

### Layer 1: MCP Server (auto-discovery)

For MCP-compatible tools (Claude Desktop, Cursor, Continue.dev), the
LLM **automatically discovers** lorewiki's tools — no rules or skills
needed.

```bash
# Install with MCP support
pip install 'lorewiki[mcp]'

# Start the MCP server (stdio transport)
lorewiki mcp serve
```

**Claude Desktop config** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "lorewiki": {
      "command": "lorewiki",
      "args": ["mcp", "serve"]
    }
  }
}
```

The LLM will see 6 tools: `search` (find docs), `show` (read full doc +
related docs), `tree` (browse hierarchy), `add` (create new note),
`update` (modify existing note), `delete` (remove note). Tool
descriptions tell the LLM when to call them. Requires the `mcp`
optional dependency: `pip install 'lorewiki[mcp]'`.

### Layer 2: Auto-Inject (transparent context)

For tools with hook support (opencode, custom scripts), inject
relevant wiki context at session start — the LLM doesn't even need to
know lorewiki exists.

```bash
# Scan project code → extract keywords → search wiki → output context block
lorewiki inject --project . --format markdown

# Use in opencode session-start hook:
lorewiki inject --project . >> "$CONTEXT_FILE"

# Use in .cursorrules or CLAUDE.md:
$(lorewiki inject --project . --format markdown)
```

The injected block looks like:

```markdown
## Knowledge Base Context (auto-injected)

Based on your project's code, the following wiki docs may be relevant:
- **wx.login** [API] (api/open-api/login/wx.login.md): 调用接口获取登录凭证code
- **wx.request** [API] (api/network/request/wx.request.md): 发起HTTPS网络请求

Use `lorewiki show <doc_path>` to read full content.
```

### Layer 3: opencode Skill (universal fallback)

For all other tools, install the skill that tells the LLM when and how
to use lorewiki:

```bash
lorewiki install --all    # install to all detected AI tool directories
```

The skill includes **auto-trigger rules** — the LLM should search the
wiki without asking when it encounters an unfamiliar API, a user
mentions a concept, or it's about to guess.

### Three-layer comparison

| Layer | Setup              | LLM awareness           | Best for                  |
|-------|--------------------|-------------------------|---------------------------|
| MCP   | One config entry   | Knows tools exist       | Claude Desktop, Cursor    |
| Inject | One hook line     | Doesn't know, context just there | opencode, custom    |
| Skill | `lorewiki install` | Knows from skill rules  | All other tools           |

## Development

```bash
pip install -e ".[dev]"
ruff check lorewiki skills tests  # lint
pytest -q                        # 373 unit + integration tests
pytest --cov=lorewiki            # coverage report
```

The `example_wiki/` directory is a curated 5-file benchmark
fixture — not a starter. See `example_wiki/README.md` for what
it is and how to use it.

## Roadmap

- **Vector retrieval** (sqlite-vec + sentence-transformers) — opt-in,
  via `pip install lorewiki[vector]`.
- **Incremental file-watcher** (`lorewiki index --watch`, experimental in 0.3.0).
- **PDF / Word ingestion** beyond Markdown.
- **Atomic write of `~/lorewiki/current`** (currently best-effort).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow. Bug
reports and feature requests go to the issue tracker; PRs are
welcome — see the testing / linting commands above.

## License

[MIT](LICENSE) · Copyright (c) 2026 LoreWiki contributors.
