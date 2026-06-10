# Changelog

All notable changes to LoreWiki are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and this
project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- All public-facing documentation translated to English
  (with `docs/README_zh-CN.md` preserved for Chinese users).
- `docs/` documentation unified under English; `docs/lorewiki
  dev document.md` retained as the original-language source of
  truth for the design plan.
- All `.md` files now carry a UTF-8 BOM so Windows PowerShell
  and Notepad identify the encoding correctly.

### Removed
- `wiki/` directory (leftover from the very first `lorewiki init`
  test; never used by the recommended workflow).
- Dead constant `EXAMPLE_WIKI_RELATIVE` from `cli.py`.
- `outFile` / `Set-Content`-hostile BOM trap examples from
  `skills/lorewiki/SKILL.md`.

## [0.1.0] — 2026-06-10

Initial open-source release.

### Added
- Phase 0 — bootstrap / CLI skeleton.
- Phase 1 — SQLite FTS5 indexer + BM25 retriever with
  trigram tokenizer and CJK-friendly LIKE fallback.
- Phase 2 — Hierarchy retriever + Reciprocal Rank Fusion.
- Phase 3 — LLM integration (Ollama + OpenAI-compatible + disabled)
  with graceful degradation to top-K hits.
- Phase 4 — Streamlit UI (lazy import) + FastAPI REST (6
  endpoints, 503 fallback, OpenAPI).
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
- 198 tests, ~92 % coverage on critical-path modules, ruff 0
  errors.
