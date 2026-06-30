# How LoreWiki works — operational deep-dive

> Applies to lorewiki **0.4.x**. Companion to `architecture.md`. Where
> `architecture.md` is the bird's-eye view (what lives where, who calls
> who), this document follows **one query end-to-end** through the code,
> and then digs into how configuration actually takes effect (especially
> the LLM).

## 1. End-to-end: a single `lorewiki search "限流方案" --human`

You run, from any directory:

```bash
lorewiki search "限流方案" --mode mix --top-k 5 --human
```

Here is the full chain of what happens, in order, with file:line
references where it helps.

### 1.1 CLI dispatch

The `lorewiki/cli/` package is built with Typer. The root
`@app.callback` reads `--topic` and stashes it into the process
environment:

```python
# lorewiki/cli/apps.py, in @app.callback
if topic:
    os.environ["LOREWIKI_TOPIC"] = topic
```

This is the "dirty but cheap" plumbing — see §3 below for why
`load_config` reads it from `os.environ` instead of `ctx.obj`.

`search` is then dispatched to `cli/commands.py::search` with
`query`, `--mode`, `--top-k`, `--human` resolved by Typer.

### 1.2 Config resolution (the part that surprises most newcomers)

`search` calls `_resolve_config(path_arg)`, which calls
`load_config()`. `load_config` (`lorewiki/config.py:121`) does
**seven** things in order:

1. **User global TOML** — `~/.lorewiki/config.toml` (always
   present after the user's first `lorewiki config set` or
   `lorewiki init`).
2. **Topic-level TOML** — `~/.lorewiki/topics/<active>/config.toml`,
   if an active topic exists (`~/lorewiki/current` points at it).
3. **Project-level TOML** — `<cwd or --path>/.lorewiki/config.toml`,
   if it exists (legacy per-project mode).
4. **Project dir** — `<cwd or --path>` itself.
5. **Env vars** — `LOREWIKI_*` (`LOREWIKI_WIKI_PATH`,
   `LOREWIKI_LLM__BACKEND`, `LOREWIKI_LLM__OLLAMA_MODEL`, etc.).
6. **CLI overrides** — passed in via `overrides={"wiki_path": ...}`
   when `--path` is used.
7. **`LoreWikiConfig(**merged)`** — pydantic-settings validates
   the whole tree, applies defaults, and runs the `_resolve_paths`
   `@model_validator`.

The merged `LoreWikiConfig` instance now has:

- `wiki_path` — absolute path to the wiki source
- `db_path` — absolute path to the SQLite DB (resolved by
  `_resolve_paths` based on the rules in §3.1)
- `retrieval_mode`, `rrf_k`, `chunk_max_tokens`, ...
- `llm` — the full `LLMConfig` sub-model
- `vector` — the `VectorConfig` sub-model

The config is read once per command and **never re-read**. Mutate
the TOML between two CLI invocations and the second one will see
the change.

### 1.3 Index sanity check

`search` (via `_run_search`) opens the DB with
`open_db(cfg.db_path, auto_init=False)`. If the file is missing
or the schema is uninitialised, every data endpoint (REST,
MCP, CLI search) returns **HTTP 503 / clear panel** — never
500 with a stack trace. The user gets:

> Run `lorewiki index` first.

…instead of a crash.

### 1.4 Retriever selection

`mode` is validated against `SUPPORTED_MODES = {bm25, hierarchy,
mix, vector}`. `vector` falls back to `mix` with a yellow notice
(graceful degradation, because the `VectorRetriever` is not
implemented yet — see the limitations in
`production-readiness.md`).

For `mix`:

```python
# lorewiki/retriever/search.py::run_search  (called from cli/commands.py::search)
bm25 = BM25Retriever.from_config(cfg)
hier = HierarchyRetriever.from_config(cfg)
per_retriever = {"bm25": bm25.search(q), "hierarchy": hier.search(q)}
fused = RRFFusion(k=cfg.rrf_k, weights=cfg.mix_weights).fuse(per_retriever, top_k=top_k)
```

`BM25Retriever.from_config(cfg.db_path, cfg.snippet_chars)` and
`HierarchyRetriever.from_config(cfg.db_path, cfg.snippet_chars)`
are thin constructors — they don't open the DB, they just hold the
path; the DB is opened per-`.search()` call inside a
`with open_db(...) as conn:` block. The `RRFFusion` is stateless.

### 1.5 BM25 (FTS5) path

`BM25Retriever.search()` (`lorewiki/retriever/bm25.py`) runs
**three sub-queries** in order, taking the first non-empty result:

1. **Phrase match** — `SELECT ... FROM docs_fts WHERE docs_fts MATCH '限流方案'` (FTS5 phrase operator)
2. **OR trigrams** — `MATCH '限 OR 流 OR 方 OR 案 OR 限流 OR 方案 OR ...'` (FTS5 trigram tokenizer ANDs each; we ask OR them)
3. **LIKE fallback** — `SELECT ... WHERE title LIKE '%限%' OR title LIKE '%流%' ...` (in-Python, scored by count of matching terms)

Each tier returns `list[SearchHit]` with `score` in the rank
range for that tier (BM25 ≈ 0-10, LIKE ≤ 0.5 — RRF normalises by
rank, not score).

### 1.6 Hierarchy path

`HierarchyRetriever.search()` (`lorewiki/retriever/hierarchy.py`)
does **not** use FTS5 (the `title` and `summary` columns are too
short to warrant an FTS5 index). It:

1. Loads all `hierarchy` rows where `level > 0` (skipping the
   synthetic root).
2. Tokenises the query into **unigrams + bigrams + trigrams** (a
   2-character CJK term like `重试` becomes the trigrams `重` /
   `试` / `重试`).
3. For each node, scores:
   `title_hits * 3 + summary_hits * 1 + 1 / (level + 1)`
   (title is the highest-signal field — it's frontmatter).
4. Collects all docs under any matched node, de-dupes, and
   returns the per-doc chunk list.

The bigram generation step is the single most important line in
the file — without it, 2-character CJK terms cannot match titles,
and hierarchy Recall drops from 90 % to 50 %. (See
`docs/critique/phase-2.md` issue #1.)

### 1.7 RRF fusion

`RRFFusion.fuse(per_retriever: Mapping[str, Iterable[SearchHit]], *, top_k)`
walks each retriever's hit list (keyed by name in the mapping),
sums `weight / (k + rank)` for each chunk, sorts by combined
score, and returns the top-N. Default `k=60`, default
weights `bm25=1.0`, `hierarchy=0.8`.

The `weight` is **per-retriever**, not per-chunk — so a chunk that
ranks well in both retrievers wins big, a chunk that ranks well
in only one is demoted, a chunk that ranks well in neither is
absent. This is the entire "consensus boost" idea.

### 1.8 Output formatting

For default output (the agent path):

```json
[
  {
    "chunk_id": "patterns/rate-limit.md#2",
    "doc_path": "patterns/rate-limit.md",
    "title": "Rate Limiting Patterns",
    "heading_path": "Rate Limiting Patterns > Token Bucket",
    "module": "patterns",
    "snippet": "...",
    "score": 0.0294,
    "retriever": "mix"
  },
  ...
]
```

For `--human` (the human path): a Rich table with the same
fields, `score` formatted to 3 decimal places, `snippet`
clipped to `cfg.snippet_chars` (default 240) and rendered in
the terminal width.

### 1.9 The full call graph, in one image

```
user
 └─> lorewiki CLI (Typer)
      ├─> @app.callback: stash --topic to env
      └─> search subcommand
           ├─> _resolve_config
           │    └─> load_config (7-layer merge, pydantic validation)
           │         └─> LoreWikiConfig.__init__ → _resolve_paths validator
           ├─> open_db(cfg.db_path, auto_init=False)   ← 503 if missing
           ├─> build retrievers (BM25Retriever, HierarchyRetriever)
           ├─> mode-dispatch:
           │    bm25      → BM25Retriever.search → top-k
           │    hierarchy → HierarchyRetriever.search → top-k
           │    mix       → BM25.search ∪ Hierarchy.search → RRFFusion.fuse → top-k
           │    vector    → fallback to mix (with notice)
           ├─> format: JSON (default) | Rich table (--human)
           └─> sys.stdout.write(...)
```

---

## 2. End-to-end: a single `lorewiki ask "..." --raw`

The `ask` path is `search` + `AnswerGenerator`:

```
lorewiki ask "..."
 ├─> load_config (same as above)
 ├─> AnswerGenerator(cfg).ask(question)
 │    ├─> build retriever(s) based on cfg.retrieval_mode
 │    ├─> retrieve top-k chunks
 │    ├─> build_client(cfg.llm)             ← Disabled | Ollama | OpenAI
 │    ├─> if client.available():
 │    │    └─> client.generate(prompt_with_chunks)
 │    └─> else:
 │    │    └─> return fallback(used_llm=False, degraded_reason="llm_unavailable")
 ├─> format: Rich panel with answer + sources | JSON (--raw)
 └─> exit 0
```

`Answer` dataclass (`lorewiki/llm/generator.py`) holds:

```python
@dataclass
class Answer:
    question: str
    answer: str              # LLM text or fallback formatted top-K panel
    hits: list[SearchHit]    # always populated, even on fallback
    used_llm: bool
    backend: str             # "ollama" | "openai" | "disabled"
    degraded_reason: str | None
    extra: dict[str, Any]
```

The `used_llm` / `degraded_reason` fields in `--raw` let the agent
distinguish "real LLM answer" from "fallback top-K panel" without
guessing.

---

## 3. How config actually takes effect

### 3.1 Path resolution rules (in `_resolve_paths` validator)

```python
# lorewiki/config.py
if self.db_path is not None:
    self.db_path = Path(self.db_path).expanduser().resolve()
    return self                          # explicit override wins
if self.topic:
    self.db_path = (USER_TOPICS_ROOT / self.topic / ".lorewiki" / "index.db").resolve()
    return self
self.db_path = (self.wiki_path / ".lorewiki" / "index.db").resolve()
```

So:

- **`db_path` explicitly set in TOML / env / CLI** → use it
- **`topic` set** (via `topic create / use`, `--topic` flag, `LOREWIKI_TOPIC` env, or `~/lorewiki/current`) → db lives at `~/.lorewiki/topics/<topic>/.lorewiki/index.db`
- **Neither** → legacy per-wiki path: `<wiki_path>/.lorewiki/index.db`

The wiki root `wiki_path` is **always** whatever the user /
config says, regardless of topic. Topics only own the db
location and the source markdown layout.

### 3.2 LLM config (the part that surprises people)

`LLMConfig` (`lorewiki/config.py`):

```python
class LLMConfig(BaseModel):
    enabled: bool = False
    backend: Literal["ollama", "openai"] = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    openai_api_key: str = ""
    openai_base_url: str = ""        # empty → use OpenAI's default
    openai_model: str = "gpt-4o-mini"
    timeout_seconds: float = 30.0
```

#### How to configure, all three ways

**Option A — TOML file** (recommended for humans):

```toml
# ~/.lorewiki/config.toml
[llm]
enabled = true
backend = "ollama"
ollama_model = "qwen2.5:7b"
# ollama_url = "http://localhost:11434"  # default; uncomment to override
# timeout_seconds = 60.0                  # default 30; raise for slow models
```

Or for OpenAI-compatible:

```toml
[llm]
enabled = true
backend = "openai"
openai_api_key = "sk-..."                # or set LOREWIKI_LLM__OPENAI_API_KEY
openai_model = "gpt-4o-mini"
# openai_base_url = "https://api.openai.com/v1"   # default; uncomment to use a proxy
```

**Option B — environment variables** (recommended for CI / agents):

```bash
export LOREWIKI_LLM__ENABLED=true
export LOREWIKI_LLM__BACKEND=ollama
export LOREWIKI_LLM__OLLAMA_MODEL=qwen2.5:7b
# or:
export LOREWIKI_LLM__BACKEND=openai
export LOREWIKI_LLM__OPENAI_API_KEY=sk-...
export LOREWIKI_LLM__OPENAI_MODEL=gpt-4o-mini
# topic override for one-off queries:
export LOREWIKI_TOPIC=react
```

Note the **double underscore** (`LOREWIKI_LLM__OPENAI_API_KEY`):
pydantic-settings uses `__` to descend into nested models.
Single `_` is the conventional env-var separator and is stripped
before parsing.

**Option C — CLI ad-hoc** (recommended for one-shot experiments):

```bash
lorewiki --topic react ask "props drilling 对比" --model qwen2.5:7b
```

The `--model` flag:
1. Sets `cfg.llm.backend` to `"ollama"` if the model name
   doesn't look like an OpenAI model (heuristic: contains `/` or
   `gpt-` or starts with `o1/o3/o4`), else `"openai"`.
2. Sets `cfg.llm.<backend>_model = <name>`.
3. Forces `cfg.llm.enabled = True` so the override takes effect
   even if the user has `enabled = false` in their global TOML.

It does **not** override `ollama_url` or `openai_api_key` —
those are still read from the config / env.

#### How the LLM client is chosen (`build_client`)

`lorewiki/llm/client.py::build_client(llm_cfg)` is the single
place where `LLMConfig` becomes a concrete `BaseLLMClient`:

```python
def build_client(cfg: LLMConfig) -> BaseLLMClient:
    if not cfg.enabled:
        return DisabledLLMClient(reason="llm disabled in config")
    if cfg.backend == "ollama":
        return OllamaClient(url=cfg.ollama_url, model=cfg.ollama_model,
                            timeout=cfg.timeout_seconds)
    if cfg.backend == "openai":
        if not cfg.openai_api_key:
            return DisabledLLMClient(reason="openai backend selected but no api_key")
        return OpenAIClient(api_key=cfg.openai_api_key,
                            base_url=cfg.openai_base_url or None,
                            model=cfg.openai_model,
                            timeout=cfg.timeout_seconds)
    return DisabledLLMClient(reason=f"unknown backend {cfg.backend!r}")
```

Three return paths, all `BaseLLMClient` subclasses:

| Class                | When                                                                | `available()` does                  |
|----------------------|---------------------------------------------------------------------|--------------------------------------|
| `DisabledLLMClient`  | `enabled=False` / missing key / unknown backend                     | returns `False` (no network)         |
| `OllamaClient`       | `backend="ollama"`                                                  | `GET /api/tags` against `ollama_url` |
| `OpenAIClient`        | `backend="openai"` + `openai_api_key` set                            | `GET <base>/v1/models`               |

`AnswerGenerator` doesn't care which subclass it gets; it calls
`client.available()` first, returns the fallback panel if False,
otherwise calls `client.generate(prompt, chunks)`.

#### Why pure `httpx` instead of the OpenAI / Ollama SDKs?

- **No SDK-version drift** — `httpx` is the only transport, and
  we hand-write the JSON schema. Compatible with any OpenAI-
  protocol proxy (OpenRouter, Azure, self-hosted vLLM) without
  per-vendor plumbing.
- **Single network path to test** — the test suite mocks one
  `httpx.Client.post`, not three SDK classes.
- **No async-required dependencies** — sync today; switching to
  `httpx.AsyncClient` for FastAPI concurrency is a 30-line change
  in `OpenAIClient` / `OllamaClient` (see phase-7 roadmap).

---

## 4. Failure modes — what you see, what to do

| Symptom                                                  | Likely cause                                                    | What to do                                                       |
|----------------------------------------------------------|-----------------------------------------------------------------|------------------------------------------------------------------|
| `No index found at <path>` (CLI) / `503` (REST)           | `lorewiki index` hasn't been run, or `wiki_path` is wrong      | Run `lorewiki index [--path ...]`; or check the `wiki_path` in `lorewiki config list` |
| `LLM is not available; here are the top matching chunks` | LLM disabled, missing key, or `OllamaClient.available()` returns False | `lorewiki config set llm.enabled true` + verify the LLM is reachable |
| `?` characters where CJK should be (PowerShell only)      | Pre-v0.1.1 bug or terminal code page is cp936                  | `uv tool upgrade lorewiki`; or `chcp 65001 | lorewiki ...`     |
| Mix-mode returns `vector` retriever tag in JSON         | `vector` was selected but isn't implemented; fell back to `mix` | Set `retrieval_mode = "mix"` explicitly, or wait for phase 7      |
| `topic create` rejects name like `My Topic`             | Topic names are `[a-z0-9][a-z0-9-]{0,62}[a-z0-9]` (lowercase)  | `lorewiki topic suggest "My Topic"` to get slug candidates         |

---

## 5. Where to read the code, in dependency order

If you want to read the codebase, follow the order below. Each
file builds on the previous.

1. `lorewiki/config.py` — `LoreWikiConfig`, `load_config`, the
   4-layer merge.
2. `lorewiki/topic.py` — `TopicManager`, the second-brain
   abstraction.
3. `lorewiki/db/connection.py` + `lorewiki/db/schema.sql` — the
   SQLite layer.
4. `lorewiki/indexer/parser.py` + `chunker.py` + `indexer.py` —
   the indexing pipeline.
5. `lorewiki/retriever/bm25.py` + `hierarchy.py` + `fusion.py` —
   the retrieval pipeline.
6. `lorewiki/llm/client.py` + `generator.py` — the LLM layer.
7. `lorewiki/cli/` package — the dispatch table, calling into all
   of the above.
8. `lorewiki/server/rest_api.py` + `mcp_server.py` + `ui.py` —
   the alternative entry points; they all re-use the same
   `load_config` + retriever + LLM stack.

The order mirrors the layered architecture diagram in
`docs/architecture.md` §5.
