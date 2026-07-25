---
name: lorewiki
description: "Local-first dual-layer personal knowledge base (per-project topic + shared) with hybrid retrieval (BM25 + hierarchy + RRF) and optional LLM answers. Use when recalling or saving project docs, cross-project patterns, decisions, runbooks, or postmortems. Match by intent (search/save/browse), not keywords. CLI: one shell call per command; JSON default for search/show/tree. Prefer project default_topic first, then --topic shared."
---

# lorewiki

Local-first Markdown knowledge base for a **complete personal LLM second
brain**: one isolated **project topic** per codebase, plus a cross-project
**`shared`** topic. Index `.md` into SQLite + FTS5; retrieve / answer /
browse / author via the `lorewiki` CLI (or optional MCP tools).

**Why this skill**: every command is one shell call, output is structured
JSON by default for `search`/`show`/`tree`, no daemon. Works inside
opencode / Codex / Aider / Claude Code / cron / CI.

**Output convention** (v0.2.0+):

| Command        | Default                  | Human-readable flag        |
|----------------|--------------------------|----------------------------|
| `search`       | JSON (for agents)        | `--human` (Rich Table)     |
| `tree`         | Rich Tree                | (always human)             |
| `show`         | Cleaned markdown body    | `--raw` (on-disk verbatim) |
| `ask`          | Markdown-rendered answer | `--raw` (JSON)             |
| `topic list`   | Rich panel               | `--raw` (JSON)             |
| `add`          | Rich panel               | `--raw` (JSON)             |

## When To Use

Invoke this skill whenever the user wants to:

- **Read** — search the wiki (`lorewiki search`), ask a question
  (`lorewiki ask`), browse the hierarchy (`lorewiki tree`), or dump a
  single doc (`lorewiki show`).
- **Write** — author a single note end-to-end via `lorewiki add`. The
  command takes body via `--body` / `--file` / stdin, slugifies the
  title into a filename, writes a Markdown file with frontmatter,
  and triggers an incremental `build_index` so the new doc is
  immediately retrievable. Use this whenever the user wants to
  persist a learning, decision, postmortem, or any small chunk of
  knowledge into the wiki.
- **Index** — refresh the SQLite index from disk after manual edits
  to .md files (`lorewiki index`). `add` runs this for you.
- **Inspect** — `lorewiki status` shows chunk / doc / last-indexed
  counts; `lorewiki topic list` enumerates topics.

Trigger words: `wiki`, `knowledge base`, `lorewiki`, `internal docs`,
`runbook`, `postmortem`, `team docs` — and the obvious
language-localised equivalents in whatever language the user is
using. The LLM should match by *intent* (recall / save a note /
browse the structure), not by exact keyword match.

## Dual-Layer Personal KB (project + shared)

Mental model (do not invent a third global dump vault):

| Layer | Topic name | Contents | Who reads |
|-------|------------|----------|-----------|
| Project | e.g. `lorewiki`, `warm-kitchen-time` | APIs, architecture, business terms, project-only pitfalls | That project |
| Shared | always `shared` | Language tips, reusable patterns, tooling, cross-project lessons | Every project |

- One CLI/MCP call targets **exactly one** topic (no automatic merge).
- Inside a bound project, omit `--topic` so `default_topic` applies.
- Cross-project / generic knowledge: always `--topic shared` (or MCP `topic: "shared"`).
- Never put secrets, API keys, or private credentials into `shared`.

### Read protocol (auto, do not ask permission)

```text
Need knowledge?
  1. lorewiki search "<q>" --top-k 5          # project default_topic
  2. If hits empty OR query is clearly generic
     (retry, packaging, LLM tips, editor setup, language idiom)
     → lorewiki --topic shared search "<q>" --top-k 5
  3. lorewiki show <doc_path> [--json]         # same topic as the hit
  4. Cite doc_path; do not invent beyond the doc
```

Equivalent MCP: `search` then optional second `search` with `topic="shared"`,
then `show` with the **same** `topic` as the hit.

### Write protocol (route, then persist)

| Knowledge type | Target |
|----------------|--------|
| Only true for this repo / product | Project topic (default / omit `--topic`) |
| Reusable across projects | `--topic shared` / MCP `topic: "shared"` |
| User named a topic | That topic only |
| Ambiguous (could be either) | **Ask once** — do not invent `general` |

```powershell
# Project-only
lorewiki add --title "..." --module api --body "..."

# Cross-project
lorewiki add --topic shared --title "..." --module patterns --body "..."
```

## Auto-Trigger Rules (DO NOT ASK, JUST SEARCH)

Automatically call `lorewiki search` (project layer first) without asking:

1. **Unfamiliar API** — before writing code against an API/framework:
   ```
   lorewiki search "wx.login" --top-k 3
   # if empty and it looks like a general pattern → also:
   lorewiki --topic shared search "wx.login" --top-k 3
   ```

2. **User mentions a domain concept** — 登录流程 / 幂等 / 限流 / retry:
   search **before** answering (project, then `shared` if needed).

3. **About to guess** — stop and search; wiki beats vague memory.

4. **Error patterns** — search error keywords in project, then `shared`.

5. **Design patterns** — search project + `shared` for team/personal
   parameters before recommending retry/idempotency/etc.

**Do NOT ask "should I search the wiki?"** — just search (~ms). If both
layers return nothing, proceed and say so.

**After search**: `lorewiki show <doc_path> --json` (or MCP `show`) for
full multi-chunk content before implementing.

## Prerequisites

The `lorewiki` CLI must be on the user's PATH. Check with:

```powershell
lorewiki --version    # expect: LoreWiki 1.2.0 (or newer)
```

If missing:

```powershell
# From the source repo (editable install — easiest for active development)
pip install -e D:/codes/Lorewiki

# Or, once published, via pipx for an isolated global install
pipx install lorewiki
```

The user must also have a wiki directory with at least `<wiki>/.lorewiki/config.toml`.
Initialise one if absent: `lorewiki init --path <PATH>`.

## Topic and Project Binding Convention

Bootstrap once per machine / project:

```powershell
# Global reusable layer (once)
lorewiki topic create shared
lorewiki --topic shared index

# Per code project (from that repo root)
lorewiki topic create <project-slug>    # e.g. lorewiki
lorewiki config set default_topic <project-slug>
lorewiki index                          # indexes the bound project topic
```

**Topic resolution priority** (highest first):

1. Explicit `--topic <name>` (or MCP `topic` argument).
2. `LOREWIKI_TOPIC` environment variable.
3. `<cwd-or-ancestor>/.lorewiki/config.toml` → `default_topic`.
4. `~/.lorewiki/current` (`lorewiki topic use <name>`).
5. Legacy `--path <WIKI_ROOT>` standalone wiki folders.

**Normal day-to-day (agents)**:

```powershell
# Inside a bound project — project layer
lorewiki search "config resolution" --top-k 5

# Cross-project / generic — shared layer
lorewiki --topic shared search "python packaging pitfalls" --top-k 5

# Read full doc (same topic as the hit)
lorewiki show api/auth.md --json
lorewiki --topic shared show patterns/retry.md --json
```

Use `--path` only for legacy standalone folders, not normal topic work.

## Topics (second-brain vaults)

Topics are isolated vaults under `~/lorewiki/topics/<name>/`, shared across
every project the user works in. Discovery flow when the user asks
"look up X in my react notes" or "search the cocos wiki":

1. `lorewiki topic list --raw` — enumerate. The active one is starred
   (`*`); its name is the value of `~/lorewiki/current`.
2. If the current project has `default_topic`, use it by default.
3. If the user wants another topic, pass `--topic <name>` for that call.
4. If the user mentions a topic that doesn't exist yet, follow the
   **Naming Protocol** below to pick a name and confirm with the user.
5. The active topic's wiki root doubles as an Obsidian / Logseq
   vault — the user may prefer to edit Markdown directly and just
   re-run `lorewiki index` (which is incremental).

### Naming Protocol

When the user says "make me a wiki for X" and X is a free-form
description (e.g. "react hooks learning", "wechat miniprogram dev"),
**do not** silently invent a name. Follow this protocol:

1. `lorewiki topic list --raw` — check for name collisions and pick
   the active topic (if any) for context.
2. `lorewiki topic suggest "<X description>"` — get 1-4 candidate
   slugs. The algorithm is rule-based (slugify + stopword removal);
   for CJK-only descriptions it returns nothing.
3. **Show the user the candidates and ask which to use.** Don't
   auto-pick. Example reply:
   > I can call this `wechat-mp`, `wechat-miniprogram`, or `mp`. Which
   > do you prefer? (Or pick your own name — rules: lowercase,
   > digits, hyphens, 1-64 chars.)
4. `lorewiki topic create <chosen> [--source <path-to-existing-md>]`.
   Default mode copies; `--link` symlinks instead.
5. If the user later dislikes the name, `lorewiki topic rename
   <old> <new>` renames in place (the index and config move with
   it; the active pointer is updated if applicable).

`topic suggest` is **English-friendly** by design. For CJK
descriptions, the command exits with code 1 and prints a panel that
tells the user to name the topic by hand. The agent should fall
back to asking the user explicitly in that case.

### Topic Selection Before Writing (the "ask, don't surprise" rule)

If the user says "save this to my wiki" / "记到 wiki 里" / "メモして"
**without naming a topic**, do **not** invent `general` or auto-create
a random vault. Prefer the dual-layer routing first:

```text
User: "save X to my wiki"  (no topic named)
  │
  ├── A. Content is clearly reusable across projects?
  │     → --topic shared (create shared once if missing, with user OK)
  │
  ├── B. Content is clearly only for the current codebase?
  │     ├── Project has default_topic → use it (no question)
  │     └── Else active topic (~/.lorewiki/current) → use it
  │
  ├── C. Ambiguous project vs shared → ASK once
  │
  └── D. No project binding and no active topic
        ├── topic list --raw
        ├── 1 topic → confirm "use <name>?"
        ├── 2+ → ask which (list project vs shared if present)
        └── 0 → Naming Protocol (suggest / user picks) then create
```

Never silently merge years of curated topics into a dump vault.

**Path resolution priority**:
1. `--topic` flag
2. `LOREWIKI_TOPIC` env var
3. cwd or ancestor `.lorewiki/config.toml` with `default_topic`
4. `~/lorewiki/current` file (set by `lorewiki topic use`)
5. `--path` / `wiki_path` legacy per-wiki mode

Topic names: lowercase ASCII, digits, hyphens, 1-64 chars, no
leading/trailing hyphens. The `lorewiki topic create` command will
reject anything else with a clear error.

**Important**: a `~/.lorewiki/topics/<name>/.lorewiki/index.db` only
exists *after* `lorewiki index` has been run. If the user asks to
search a brand-new topic, expect the `No index found` panel — point
them at `lorewiki topic use <name> && lorewiki index`.

## Core Workflows

### 1. Retrieve and cite (most common)

User asks something likely covered by team docs ⇒ search, then ground the
answer in the returned chunks with file-path citations.

```powershell
lorewiki search "<question or keywords>" `
    --path "<WIKI>" --mode mix --top-k 5
```

**No `--raw` flag** for `search` — JSON is the default. Pass `--human` if
you actually want a Rich Table for terminal eyeballing (rare for agents).

Returned JSON shape (parse it; don't grep the prettified panel):

```json
[
  {
    "chunk_id": "api/user/auth.md#0",
    "doc_path": "api/user/auth.md",
    "title": "Authentication API",
    "heading_path": "Auth API > Overview",
    "module": "api/user",
    "snippet": "...",
    "score": 0.029,
    "retriever": "mix"
  },
  ...
]
```

The `snippet` field contains the **full chunk body** (anchor markup, scraper
boilerplate, and the translation footer are stripped at index time — see
`lorewiki.indexer.cleaning` for the rules). The `title` has no leading `#`
and `heading_path` is ` > `-joined segments with anchors removed. The
breadcrumb prefix that the chunker adds for FTS recall is also stripped
from the snippet (it's already in `heading_path`).

Then compose an answer that:
- quotes the relevant snippets,
- cites each fact with its `doc_path` (and optionally `heading_path`),
- does NOT fabricate beyond what the snippets say.

### 2. LLM-assisted answer

When the user explicitly wants a synthesised answer (not just chunks),
use `ask`. It already does retrieval + prompt assembly + LLM call:

```powershell
lorewiki ask "<question>" --path "<WIKI>" --top-k 5 --raw
```

`ask` defaults to a Markdown-rendered panel (human-friendly); add
`--raw` to get the JSON shape with `answer`, `used_llm`, `degraded_reason`,
and `hits`. If `used_llm == false`, hand the `answer` text straight back
to the user — no need for a second tool call.

### 3. Discover the structure (before broad questions)

If the user's request is broad ("what's in the wiki?", "what modules do we
have?"), use the tree view:

```powershell
lorewiki tree                    # full hierarchy
lorewiki tree api/share --depth 3   # sub-tree with depth limit
```

For "show me everything under module X" style queries, search in hierarchy
mode (returns chunks grouped by the matched tree node):

```powershell
lorewiki search "<module name>" --path "<WIKI>" --mode hierarchy --top-k 10
```

### 4. Write a new note to the wiki (knowledge persistence)

Follow this template strictly so the indexer picks up the right metadata:

```markdown
---
title: "Decision: switch to Redis Streams for event bus"
module: decisions
tags: [decision, infra, redis]
owner: platform-team
last_review: 2026-06-10
---

# Decision: switch to Redis Streams

## Context
<why we are deciding this>

## Decision
<what we will do>

## Consequences
<trade-offs + follow-ups>
```

**Frontmatter rules** (the indexer reads these fields):

| Field         | Required        | Notes                                                                            |
|---------------|-----------------|----------------------------------------------------------------------------------|
| `title`         | best-effort      | Frontmatter wins, else first H1, else the filename. Always set it explicitly.    |
| `module`        | best-effort      | Logical hierarchy path (e.g. `decisions`, `api/user`). See §Path semantics below. |
| `tags`          | optional         | Free-form list; aids hierarchy search.                                          |
| `owner`         | optional         | Team or person responsible.                                                       |
| `last_review`   | optional         | ISO date; helps with staleness audits.                                            |

Place it under the right module directory, then re-index:

```powershell
# 1) Write the file (use the Write/Edit tool — never `Out-File`, BOM issues)
#    Target path example: D:/codes/Lorewiki/example_wiki/decisions/redis-streams.md

# 2) Re-index (incremental — only changed files are re-processed)
lorewiki index --path "<WIKI>"
```

Verify by searching for a distinctive phrase from the new doc:

```powershell
lorewiki search "Redis Streams decision" --path "<WIKI>" --mode mix --top-k 3
```

#### Path semantics (read this once, it shapes the whole vault)

The `module:` field is a **logical category**, not a physical file path.
The two don't have to match (the parser doesn't enforce it), but
**keep them aligned** so the hierarchy tree is useful for browsing:

- **Aligned** (recommended): file at `api/user/auth.md` has
  `module: api/user`. Walking the hierarchy gives you
  `api/ → api/user/ → docs` and the file shows up under
  `api/user` in `lorewiki status`.
- **Mis-aligned** (allowed, but degrades the UI): file at
  `patterns/rate-limit.md` with `module: patterns` — the
  hierarchy only shows one level (`patterns`), but the file still
  indexes and searches normally.

**Rule of thumb**: when in doubt, set `module` to the directory the
file is in (or a sensible parent).

#### Quality checklist for scraped / external content

If you are **fetching** documentation and writing it into the vault
(common workflow in the user's AI tools), the indexer will accept
anything but search quality collapses on certain patterns. **Don't**:

| Anti-pattern                                              | Why it breaks                                                                              | What to do instead                                                                          |
|-----------------------------------------------------------|--------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| Filename ending in `.html` (e.g. `wx.arrayBufferToBase64.html`) | Obsidian / Logseq render the file as raw HTML source; internal links fail to resolve | Strip the `.html` extension. The file is markdown, not HTML.                              |
| `_index.md` (underscore-prefixed)                         | LoreWiki has no special handling for `_index.md`; you'll get an empty `title: ""` and the indexer falls back to the first H1, which is often a quote or nav block | Use plain `index.md` (or a topic-specific name like `api-overview.md`).                   |
| `title: ""` (empty in frontmatter)                        | The indexer falls back to the first H1 — if the first H1 is a quote, a nav link, or a heading with special characters, search titles become ugly | Always fill `title` with a short, human-readable summary.                                |
| Internal links pointing to `.html` files                 | `(/api/base/wx.env.html)` — Obsidian and the indexer can't follow them                | Strip `.html` from the link target, or convert to the equivalent `.md` path.              |
| Module path with spaces / capital letters                | The hierarchy tree treats it as a distinct node; search ranks it as a separate entity | Use kebab-case lowercase segments: `api/user`, `patterns/rate-limit`, `decisions/redis`.    |
| Scrape artefact files in the vault root (e.g. `manifest.json`, `scrape.log`) | These pollute the Obsidian vault view; they don't index but they confuse the user | Put scrape artefacts in a separate cache directory (`~/.lorewiki/.scrape-cache/<topic>/`), not in the vault |

After the write, run `lorewiki index --path "<WIKI>"` and spot-check
with `lorewiki status --path "<WIKI>"` — the chunk count and
hierarchy depth will tell you if the structure is sensible.

### 5. Fresh wiki bootstrap

```powershell
lorewiki init --path "<NEW_WIKI_DIR>"
# Author Markdown files under <NEW_WIKI_DIR>/...
lorewiki index --path "<NEW_WIKI_DIR>" --rebuild
lorewiki status --path "<NEW_WIKI_DIR>"
```

### 6. Configuration inspection / change

> **Single source of truth**: all lorewiki config lives in **one**
> file: `~/.lorewiki/config.toml`. We **no longer** drop a
> `config.toml` into each topic root (it polluted the vault view
> in Obsidian / Logseq). If you need per-topic overrides, edit the
> global file with a `[topics.<name>]` section header.

There is **no config.toml to discover** until the user creates one.
The recommended way to bootstrap it:

```powershell
# Option A — interactive, recommended for humans
lorewiki config set llm.enabled true
lorewiki config set llm.backend '"openai"'
lorewiki config set llm.openai_api_key '"sk-..."'
lorewiki config set llm.openai_model '"gpt-4o-mini"'
# (each call writes ~/.lorewiki/config.toml; subsequent `lorewiki config list`
#  shows the merged result)

# Option B — write the file directly
# Recommended for headless / CI use, and the only way to set
# OpenAI-compatible endpoints that point at OpenRouter / vLLM / etc.
notepad ~/.lorewiki/config.toml     # or your editor of choice
```

A fully-populated `~/.lorewiki/config.toml` (every supported key
is shown, comments mark the lines you'll most often change):

```toml
# ~/.lorewiki/config.toml — LoreWiki's single config file.
# Anything you don't set here falls back to the in-code default.

# ----- Retrieval -----
retrieval_mode = "mix"                # mix | bm25 | hierarchy | vector
mix_weights_bm25 = 1.0
mix_weights_hierarchy = 0.8
mix_weights_vector = 0.5
rrf_k = 60                            # RRF smoothing constant
chunk_max_tokens = 800
chunk_overlap_tokens = 100
chunk_min_chars = 40
snippet_chars = 240

# ----- LLM (optional) -----
# Enabled = false by default. When false, `lorewiki ask` falls
# back to the top-K chunks panel (graceful degradation).
[llm]
enabled = false

# --- Option A: local Ollama ---
backend = "ollama"
ollama_url = "http://localhost:11434"
ollama_model = "qwen2.5:7b"

# --- Option B: OpenAI-compatible (any provider speaking ---
# ---   POST /v1/chat/completions)                       ---
# backend = "openai"
# openai_api_key = "sk-or-..."           # OpenRouter key, OpenAI key, etc.
# openai_base_url = "https://openrouter.ai/api/v1"   # <- any vLLM-compatible endpoint
# openai_model = "meta-llama/llama-3.1-8b-instruct:free"

# timeout_seconds = 30.0
```

Quick CLI:

```powershell
lorewiki config list                   # show the resolved config (with defaults)
lorewiki config get llm.backend        # get one key
lorewiki config set llm.enabled true   # set one key (auto-creates the file)
lorewiki config set llm.openai_base_url '"https://openrouter.ai/api/v1"'
# Note: when setting a string, quote it as a TOML literal.
```

> **Note on Azure OpenAI**: the Azure endpoint path is
> `/openai/deployments/<deployment>/chat/completions?api-version=...`
> and is **not** currently supported. Use OpenRouter or a
> self-hosted vLLM-compatible endpoint, or wait for phase-7 Azure
> support (open an issue if you need it sooner).

### 7. Write to the wiki — pick the right path

There are three honest ways to put content into the wiki. Pick the
smallest one that does the job — over-engineering hurts:

| Scenario                                                   | Use                                                                                           |
|------------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| **One-off note** (1-3 paragraphs, user just told you)       | `lorewiki add --title ... --body ...` — writes + auto-indexes in one step.                     |
| **A handful of related notes** (≤ ~20)                     | Run `lorewiki add` a few times in a loop. Don't write a script.                                |
| **Bulk scrape** (tens to thousands of files, e.g. scraping  | Either (a) drop the directory under the active topic and run `lorewiki index` (one-shot),   |
| a vendor's docs, importing a git repo, etc.)                | or (b) write a short Python script that writes `.md` files with frontmatter and call       |
|                                                            | `lorewiki index` once at the end.                                                             |
| **Topic bootstrap** (creating a new isolated vault)         | `lorewiki topic create <name> [--source <path>]` — the topic system is built for this.        |

**Auto-judgment rule for the LLM**: if the user pasted a single
short note, reach for `lorewiki add`. If the user gave you a list,
a URL, or a directory to capture, reach for a Python script (or
`lorewiki topic create --source`). Don't run `lorewiki add` in a
50-iteration loop — the per-invocation indexing cost adds up. The
user's language for "store this" / "capture these" / "记一下" /
"保存这些" / "メモして" / whatever is irrelevant to the rule; the
trigger is *shape* (paragraph vs list/URL/directory), not language.

#### `lorewiki add` quick reference

```powershell
# Inline body
lorewiki add `
  --title "Python Design" `
  --module patterns `
  --tag python --tag design `
  --body "Some deep details about Python design pattern."

# Pipe from stdin (no --body)
echo "# Inferred Title`n`nbody text" | lorewiki add --module notes

# Bulk scrape: short Python script
$urls = @("https://vendor.example.com/docs/a", "https://vendor.example.com/docs/b")
foreach ($u in $urls) {
    $md = (Invoke-WebRequest $u).Content | ./scrape.ps1
    $slug = ($u -split "/" | Select-Object -Last 1) -replace ".html$", ""
    lorewiki add --title $slug --module scraped --body $md --path $wiki
}
lorewiki index  # only if add was called many times; usually redundant
```

The file lands at `<wiki>/<module>/<slug>.md`; the slug is derived
from the title via ASCII-only normalisation (Chinese characters in
the title are stripped, so "RISC-V 工具链" becomes `risc-v` — see
[slug caveats](#slug-caveats) below). After a successful write,
an incremental `build_index` runs so the new doc is immediately
retrievable. Use `--raw` for machine-readable JSON output,
`--force` to overwrite an existing file. The path-traversal check
will reject any `--module` value that resolves outside the wiki
root.

#### Slug caveats

The slug is built with `[^a-z0-9]+` → `-`, lowercased, trimmed, then
capped at 64 chars. **Non-ASCII characters in the title are
stripped** — so a title like "RISC-V 工具链" produces the slug
`risc-v` (the CJK portion is gone). The body keeps everything;
only the filename is ASCII-folded. This affects every non-ASCII
script uniformly (CJK, Vietnamese, Thai, Korean, Cyrillic, etc.).
For better filename preservation, the user should pick an
English title and put the original-language text in `--body`.

## Modes (`--mode` flag for search / configured for ask)

| Mode      | Best for                                            | Notes                                       |
| --------- | --------------------------------------------------- | ------------------------------------------- |
| `mix`     | Almost everything (default).                        | RRF-fused BM25 + hierarchy. Highest recall. |
| `bm25`    | Exact-term / English / code-symbol queries.         | FTS5 trigram + LIKE fallback for short CJK. |
| `hierarchy` | "Show me everything under module X" style queries.| Walks the module tree from matched node.    |
| `vector`  | Not implemented yet — silently falls back to `mix`. | Reserved for the phase-6 sqlite-vec layer.  |

## Output Discipline

- **`search` already defaults to JSON** — no flag needed. Only `ask`,
  `topic list`, `topic suggest`, and `show` have a `--raw` (for those,
  `--raw` is *opt-in* to switch off the human-friendly default).
- **Cite by `doc_path`** in your final answer (`[api/user/auth.md]`), not by
  internal chunk IDs.
- If the wiki has nothing relevant (`hits == []`), say so plainly. Do NOT
  hallucinate content the wiki doesn't contain.
- For `ask` with `used_llm == false`, the returned `answer` already lists
  the chunks — you can pass it through unchanged.
- **Auto-judge the write path**: prefer `lorewiki add` for 1-3
  paragraphs the user just told you. Drop a directory + `lorewiki index`
  for bulk. **Never** wrap `add` in a 50-iteration loop when a
  short script + one index call would be cleaner.
- **Topic routing** (`--topic` / MCP `topic`):
  - **Read**: project first (omit topic if `default_topic` is set); then
    `--topic shared` for generic / empty project hits.
  - **Write**: project-only → project topic; reusable → `shared`; ambiguous → ask once.
  - MCP tools (`search` / `show` / `tree` / `add` / `update` / `delete`) all
    accept `topic` with the same dual-layer semantics.

## Common Pitfalls

| Pitfall                                                              | Avoidance                                                                                                                             |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Only searching the project layer for generic knowledge.              | Second call: `lorewiki --topic shared search "..."` (or MCP `topic: "shared"`). |
| Dumping every note into `shared` or inventing `general`.             | Route by reusability; ask once when ambiguous. |
| Reaching for `lorewiki add` in a tight loop for bulk ingestion.      | Drop the source directory and run `lorewiki index` once. |
| Searching with a 1-2 character CJK query and getting "0 hits".       | Longer query or `--mode bm25` (LIKE fallback). |
| Forgetting project binding and relying on a wrong active topic.      | Set `default_topic` in the project; prefer that over global `topic use` while coding. |
| Editing a `.md` and not re-indexing.                                 | `lorewiki index` is incremental — just run it. |
| Using PowerShell `Out-File` (BOM) for Markdown.                      | Agent Write/Edit or UTF-8 no-BOM write. |
| Assuming `ask` always used an LLM.                                   | Check `used_llm` in `ask --raw`. |
| Absolute paths outside the vault for update/delete.                  | Relative `doc_path` only; outside paths are rejected. |

## Quick Reference

```powershell
lorewiki --version
lorewiki topic create shared && lorewiki --topic shared index
lorewiki config set default_topic <project-slug>
lorewiki search   "<QUERY>" --top-k 5 --mode mix              # project layer (JSON)
lorewiki --topic shared search "<QUERY>" --top-k 5            # shared layer
lorewiki show     "<DOC_PATH>" --json                         # full multi-chunk body
lorewiki tree     [--depth N]
lorewiki add      --title "<T>" [--topic shared] --module <M> --body "..."
lorewiki ask      "<QUERY>" --raw
lorewiki topic    {list|use|create|show|delete|rename|suggest}
lorewiki config   {list|get|set}
lorewiki index    [--rebuild]
lorewiki mcp serve                                            # optional MCP stdio server
```

## Decision Cheat-Sheet

| User intent | Command / action |
| ----------- | ---------------- |
| Look up X in this project | `lorewiki search "X" --top-k 5` |
| Look up generic / cross-project X | `lorewiki --topic shared search "X" --top-k 5` |
| Project empty, might be general | Project search → then `shared` |
| Full content of a hit | `lorewiki show "<DOC_PATH>" --json` (same topic) |
| What's in this vault | `lorewiki tree` / `--topic shared tree` |
| Synthesised answer | `lorewiki ask "..." --raw` |
| Save project-only note | `lorewiki add --title ... --body ...` |
| Save reusable pattern | `lorewiki add --topic shared --title ... --body ...` |
| Save without clear vault | Dual-layer write tree (ask if ambiguous) |
| Bulk import folder | `topic create <name> --source <dir>` then `index` |
| No hits | Try `shared`, then `--mode bm25`; don't invent |

## MCP Server (same dual-layer rules)

```powershell
pip install 'lorewiki[mcp]'
lorewiki mcp serve
```

Tools: `search` / `show` / `tree` / `add` / `update` / `delete` — each accepts
optional `topic` (`shared` or project slug). Read: project first, then
`topic="shared"`. Write: route by reusability. Skill shell-out remains the
universal fallback when MCP is not configured.
