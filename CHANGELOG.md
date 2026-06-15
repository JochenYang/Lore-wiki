# Changelog

All notable changes to LoreWiki are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and this
project follows [Semantic Versioning](https://semver.org/).

# Changelog

All notable changes to LoreWiki are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and this
project follows [Semantic Versioning](https://semver.org/).

## [0.2.4] — 2026-06-15

Documentation-accuracy fix. 0.2.0 through 0.2.3's `lorewiki --help`,
README, and `docs/install.md` all described an `npm install -g
lorewiki` install path as if it were live, but the project has
never actually been published to npm — the `NPM_TOKEN` GitHub
secret is unset, so the CI `Publish to npm` step has been skipped
on every release to date, and `https://registry.npmjs.org/lorewiki`
returns 404. This release removes the npm shim infrastructure and
all npm install instructions so the docs match reality.

### Removed
- `package.json` — npm manifest (only ever consumed by npm, not
  by the wheel build, which goes through hatchling on
  `pyproject.toml`).
- `bin/lorewiki.js` — npm shim that spawned the Python wheel.
- `scripts/postinstall.js` — npm `postinstall` hook that called
  `uv tool install lorewiki`.
- `scripts/preuninstall.js` — npm `preuninstall` hook that called
  `uv tool uninstall lorewiki`.
- `scripts/publish.sh` / `scripts/publish.ps1` — manual release
  pipeline (was already replaced by `.github/workflows/publish.yml`;
  this just removes the dead code and the dead-code reference in
  `scripts/_README.md`).
- `README.npm.md` — npm-only README.
- `.npmignore` — npm packaging config.

### Changed
- `README.md`, `docs/README_zh-CN.md`, `docs/install.md` — removed
  every `npm install -g lorewiki` reference, every "Node (npm
  shim)" subsection, the "Why uv tool vs npm" table row, and the
  "(Optional) npm" step in the maintainer publishing checklist.
  The `lorewiki` project is now documented as a single-channel
  PyPI distribution.
- `.github/workflows/publish.yml` — removed the `Publish to npm`
  step (was guarded by `if: env.NPM_TOKEN` and always skipped).
- `scripts/_README.md` — replaced the "publish.sh / publish.ps1"
  reference with a pointer at the GitHub Actions workflow.

### Migration
- Anyone who installed via `npm install -g lorewiki` is
  unaffected: the npm package was never published, so the
  command `lorewiki` on their `PATH` either came from a Python
  install they did themselves or is a 404. They can verify
  with `Get-Command lorewiki` (PowerShell) or `which lorewiki`
  (Unix) and reinstall from PyPI per the new README.

## [0.2.3] — 2026-06-15

UX polish on the CLI help surface. No behaviour change. The
`lorewiki --help` banner and the per-command help text are both
sourced from in-source docstrings, so this is a wheel-affecting
change despite touching no runtime logic.

### Changed
- `lorewiki/cli/apps.py`: rewrote the `--topic` / `-t` global
  option help to (1) make it explicit that the option REQUIRES a
  topic name and (2) call out the difference between the OPTION
  form (`--topic react search "useState"`) and the SUBCOMMAND
  form (`lorewiki topic list`). The previous wording was the
  cause of a 0.2.x UX bug report — `--topic` without an argument
  errored with "Option '--topic' requires an argument", which
  did not point users at the `topic` subcommand.
- `lorewiki/cli/commands.py`: clarified the `index`, `update`,
  and `ask` docstrings so `lorewiki --help` shows a clear
  distinction between `index` (build / rebuild) and `update`
  (currently a stub for the future watcher) and explains that
  `ask` falls back to top-k chunks when the LLM is unreachable
  instead of crashing.

## [0.2.2] — 2026-06-15

Bug-fix release. 0.2.1 shipped the `lorewiki add` command, but
on Windows + PowerShell piping a CJK body into stdin crashed
with `UnicodeEncodeError: surrogates not allowed` and left a
0-byte file on disk. No data loss (the write was atomic at the
file level), but the empty file then tripped the "target
exists" check on every retry. 0.2.2 fixes both the crash and
the leftover-file footgun.

### Fixed
- `lorewiki/cli/add.py`: scrub lone UTF-16 surrogate codepoints
  (U+D800..U+DFFF) out of the body before it reaches
  `frontmatter.dumps()` and `write_text(..., 'utf-8')`. Windows
  PowerShell pipes strings as UTF-16 LE; the child Python
  surface them as lone surrogates that UTF-8 cannot encode.
  Surrogates are replaced with U+FFFD (the official replacement
  character) so the user knows the original character didn't
  make it, instead of failing silently.
- `lorewiki/cli/add.py`: widen the `try / except OSError` around
  the write to also catch `UnicodeEncodeError` (it is NOT a
  subclass of `OSError`, so the original except let it through).
  On any write failure, `target_path.unlink(missing_ok=True)`
  cleans up the partial file so a subsequent `add` doesn't trip
  the "target exists" check against an empty file.

### Tests
- `tests/test_cli_add.py::test_cli_add_strips_surrogates_from_stdin`:
  regression covering both the unit-level `_strip_surrogates`
  helper and the end-to-end `add --body` path with a body that
  contains lone surrogates mixed with CJK. The actual
  PowerShell-pipe round-trip is Windows-specific and intentionally
  left to manual smoke; the CliRunner path exercises the same
  `_strip_surrogates` → `frontmatter.dumps` → `write_text('utf-8')`
  code path.

## [0.2.1] — 2026-06-15

CI-fix release. The 0.2.0 tag triggered a successful test run
but `ruff check` failed with 14 lint errors, blocking the
PyPI publish step. No user-facing changes.

### Fixed
- `pyproject.toml`: added `PLR0911` / `PLR0912` / `PLR0915` to
  the `ruff.lint.ignore` list (these are blunt complexity metrics;
  splitting `clean` or `build_index` would only create artificial
  seams). Removed the now-redundant `# noqa: PLR0912[,PLR0915]`
  markers in `lorewiki/topic.py` and `skills/install.py`.
- `lorewiki/cli/commands.py`: moved four function-scoped
  `lorewiki.*` imports (`run_search`, `clean_markdown_file`,
  `parse_markdown`, `typing.Any`) to the top of the module.
- `lorewiki/cli/commands.py`: broke two `> 100` char lines
  (`lorewiki show` arg help, dense `__root__` lookup in
  `lorewiki tree`).
- `lorewiki/indexer/cleaning.py`: renamed the per-segment loop
  variable in `clean_heading_path` to `cleaned_seg` so the inner
  reassignment no longer shadows the loop target (PLW2901).
- `tests/test_cli_add.py`, `tests/test_topic.py`: added
  `# noqa: PLC0415` to function-scoped imports (standard
  convention for conditional test imports).

## [0.2.0] — 2026-06-15

CLI + opencode-skill surface. The REST and MCP server code paths
are removed in this release — downstream consumers that need
real-time tool-calling should use the opencode skill
(`skills/lorewiki/SKILL.md`) over the CLI.

### Added
- `lorewiki show <doc_path>` — print a single document's body
  (cleaned by default; `--raw` for on-disk verbatim).
- `lorewiki tree [prefix]` — Rich-Tree view of the wiki hierarchy
  with optional depth limit.
- `lorewiki clean [--dry-run] [--no-backup]` — rewrite on-disk
  `.md` files to drop scraper boilerplate (anchor markup,
  blockquote meta, translation footer, internal `.html`).
- `lorewiki add --title T --body B` — author a single note
  end-to-end: writes a Markdown file with frontmatter into
  `<wiki>/<module>/<slug>.md`, then triggers an incremental
  `build_index` so the new doc is immediately retrievable.
  Path-traversal protection refuses any `--module` that
  resolves outside the wiki root.
- `lorewiki.indexer.cleaning` module: `clean_markdown`, `split_frontmatter`,
  `clean_markdown_file`, `clean_title`, `clean_heading_path`,
  `clean_snippet` — the same cleaning rules used at index time
  are now exposed as a library so `clean` can rewrite disk files.
- Unified `lorewiki.retriever.search.run_search(cfg, query, *, mode, top_k)`
  — the dispatch logic that used to be open-coded in the CLI
  is now a single import.
- `lorewiki.retriever.vector.VectorRetriever` placeholder that
  raises `NotImplementedError` on `.search()` — the CLI's
  `--mode vector` still falls back to `mix` silently.
- `lorewiki.utils.topic_shared.read_current_topic` (and the
  shared `CURRENT_FILE` / `USER_CONFIG_DIR` / `USER_TOPICS_ROOT`
  constants) — single source of truth for the active topic
  pointer. `lorewiki.config` and `lorewiki.topic` no longer
  duplicate the read logic.
- `py.typed` marker (PEP 561) included in the wheel so downstream
  type checkers see our inline type hints.
- `lorewiki.config.snippet_chars` default is now `240` (was `0`).

### Changed
- `lorewiki search` is the canonical READ entry: default output is
  structured JSON, no `--raw` flag required.
- Retriever output is post-processed: `title` no longer carries a
  leading `#`, `heading_path` segments have `[#](#anchor)` markup
  removed, `snippet` has the leading breadcrumb prefix stripped
  and the translation footer trimmed.
- `lorewiki topic show` no longer prints the `name` field twice
  (regression test added).
- Runtime `assert cfg.db_path is not None` calls in
  `indexer` / `BM25Retriever` / `HierarchyRetriever` are now
  `ValueError`; `assert` is silently stripped under `python -O`.

### Removed (BREAKING)
- `lorewiki rest` command and the FastAPI REST server module
  (`lorewiki/server/rest_api.py` and its dependencies in
  `[rest]` extra). Use the opencode skill or a Python script
  calling the CLI.
- `lorewiki mcp` command and the MCP stdio server module
  (`lorewiki/server/mcp_server.py` and its dependencies in
  `[mcp]` extra). MCP support is dropped in this release; the
  CLI is the only programmatic surface.
- The `lorewiki` and `mcp` keywords from `pyproject.toml` and
  `package.json`; the package list is now CLI + opencode skill
  only.
- The `rest` and `mcp` optional-dependency groups;
  `pip install lorewiki[all]` now resolves to `[vector]`.
- The `__pycache__/lorewiki/server/` cache left over from
  FastAPI / MCP imports.

### Migration
- If you were using `lorewiki rest` for browser/UI consumption,
  open the topic's vault directory in Obsidian / Logseq / VS Code
  directly — the on-disk format is plain Markdown, no lorewiki
  daemon required.
- If you were using `lorewiki mcp` from Claude Desktop / Cursor,
  point the client at the `lorewiki` CLI via the opencode skill
  (`skills/lorewiki/SKILL.md`). The skill ships trigger keywords
  the LLM matches against user intent.

## [0.1.0] — 2026-06-10

Initial open-source release.

### Added
- Phase 0 — bootstrap / CLI skeleton.
- Phase 1 — SQLite FTS5 indexer + BM25 retriever with
  trigram tokenizer and CJK-friendly LIKE fallback.
- Phase 2 — Hierarchy retriever + Reciprocal Rank Fusion.
- Phase 3 — LLM integration (Ollama + OpenAI-compatible + disabled)
  with graceful degradation to top-K hits.
- Phase 4 — FastAPI REST server (6 endpoints, 503 fallback,
  OpenAPI at `/docs`).
- Phase 5 — MCP stdio server (`search_lorewiki` +
  `get_module_summary`).
- Phase 6 — Topics / second-brain model: `~/lorewiki/topics/<name>/`
  vaults shared across projects; `lorewiki topic
  {list,create,use,show,delete,rename,suggest}` subcommand
  group; `--topic/-t` global flag; `TopicManager(root=...)`
  rejects paths outside `USER_TOPICS_ROOT` by default.
- Multi-tool agent skill (`skills/lorewiki/SKILL.md`) installable
  into opencode / Claude Code / Codex / Cursor / Gemini /
  Antigravity with `--all` auto-detection and dedup between
  Cursor + Gemini (the `~/.agents/skills/` interop path).
- ASCII banner with a LOREWIKI block-character wordmark printed
  on `lorewiki --version` and `lorewiki --help`; cyan + bold via
  rich. The text lives in `assets/lorewiki_ascii.txt` for the
  repo but is inlined in `lorewiki/cli.py` to keep the wheel
  self-contained.
- Block-character LOREWIKI logo committed as
  `assets/lorewiki_ascii.txt` for use in `README.md` /
  GitHub repo banners; the in-CLI banner uses the same
  characters.
- 199 pytest tests pass; ruff check reports zero issues.
- `lorewiki` console script installed via `uv tool install`
  (isolated venv, no system-Python pollution).
- npm thin shim: 7 files / 10.5 KB tarball that proxies to the
  PyPI wheel via `uv` / `pipx` / `pip` postinstall.
- `scripts/publish.sh` + `scripts/publish.ps1`: pytest → ruff →
  build → twine check → TestPyPI → verify-install → live PyPI →
  npm publish, with a 5 s abort window before the live push.

### Changed
- All public-facing documentation translated to English
  (with `docs/README_zh-CN.md` preserved for Chinese users).
- `docs/` documentation unified under English; `docs/lorewiki
  dev document.md` retained as the original-language source of
  truth for the design plan.
- All `.md` files now carry a UTF-8 BOM so Windows PowerShell
  and Notepad identify the encoding correctly.
- `lorewiki search` now honours the project config's
  `retrieval_mode` (default `mix`) instead of the previous
  hard-coded `bm25` default; `--mode` on the CLI still wins.
- `lorewiki status` (no `-t`, no `--path`) after
  `lorewiki topic use <name>` now resolves to
  `~/.lorewiki/topics/<name>/` (the topic vault) instead of
  falling back to the legacy `~/wiki` default.
- `_force_utf8_streams()` now also calls
  `kernel32.SetConsoleOutputCP(65001)` on Windows so the
  block-character banner and any CJK payload round-trip
  cleanly through the console host.

### Removed
- `wiki/` directory (leftover from the very first `lorewiki init`
  test; never used by the recommended workflow).
- Dead constant `EXAMPLE_WIKI_RELATIVE` from `cli.py`.
- `outFile` / `Set-Content`-hostile BOM trap examples from
  `skills/lorewiki/SKILL.md`.
- **The Streamlit web UI and the `[ui]` optional extra.** LoreWiki
  no longer ships a built-in web UI; users consume the data
  through the CLI, the REST API (`lorewiki rest --port 8000`,
  OpenAPI at `/docs`), the MCP server (`lorewiki mcp`), or by
  opening the active topic's vault directory in any Markdown
  editor (Obsidian, VS Code, etc.). The `--web` top-level flag
  is kept as a no-op alias that prints a migration hint.
  Removes 80 MB of dependencies (streamlit, pandas, numpy,
  pyarrow, pydeck) and ~360 lines of `lorewiki/cli.py` +
  `lorewiki/server/ui.py`.

