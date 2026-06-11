# Changelog

All notable changes to LoreWiki are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and this
project follows [Semantic Versioning](https://semver.org/).

# Changelog

All notable changes to LoreWiki are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and this
project follows [Semantic Versioning](https://semver.org/).

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

