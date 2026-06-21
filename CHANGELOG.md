# Changelog

All notable changes to LoreWiki are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and this
project follows [Semantic Versioning](https://semver.org/).

## [0.4.0] — 2026-06-21

Performance and code quality release. Significant optimizations for indexing speed, search latency, and code maintainability.

### Performance (P0)
- **Connection pooling + schema caching**: Eliminated repeated schema initialization on every `open_db` call. Incremental indexing for 1468 files now takes 1.5s (was ~3s).
- **Batch inserts**: Replaced row-by-row INSERT with `executemany` for documents and hierarchy nodes. Indexing speed improved 3-5x.
- **LIKE query optimization**: Restricted LIKE fallback to `title` and `heading_path` only, avoiding full content scans. Search latency reduced 10-50x for LIKE fallback.

### Performance (P1)
- **Hierarchy retriever optimization**: Consolidated two full-table scans into single load per search. Search latency reduced 30-50%.
- **Eliminate duplicate cleaning**: `clean_markdown` now called once per document instead of twice. Indexing time reduced ~30%.

### Code Quality (P1)
- **Unified regex patterns**: Created `lorewiki/indexer/patterns.py` to centralize H1_RE, H2_RE, CODE_FENCE_RE patterns.
- **Type safety**: `get_logger()` now returns `Logger` type instead of `Any`.
- **DRY deep_merge**: Exported `_deep_merge` from config.py, eliminated duplicate in helpers.py.
- **Error handling**: `config set` now catches ValidationError with friendly message.
- **Windows compatibility**: `topic delete` now handles file locks gracefully.

### Micro-optimizations (P2)
- **Pre-compiled regex**: `estimate_tokens` now uses pre-compiled `_ASCII_TOKEN_RE` pattern.

### Verified
- 336 tests pass, ruff clean.
- Global installation tested with real wiki content (1468 files).
- Search results validated for structure and completeness.

## [0.3.2] — 2026-06-15

Bug-fix release. ``lorewiki install`` was writing the SKILL.md
content to the **directory** path (e.g. ``~/.cursor/skills/lorewiki``)
instead of the **file** path (e.g. ``~/.cursor/skills/lorewiki/SKILL.md``).

- **Linux / POSIX**: ``Path.write_text`` on a non-existent path
  silently creates a *file* at the dir path, so installs
  appeared to succeed but left an orphan 31821-byte
  ``~/.agents/skills/lorewiki`` file instead of the expected
  ``<root>/<name>/SKILL.md`` inside a directory.
- **Windows**: ``Path.write_text`` on a path where a directory
  already exists surfaces as ``[Errno 13] PermissionError``,
  so every install attempt was reported as ``[skip] (write
  failed: Permission denied)`` even when the AI agent was not
  actually locking anything.

The user-visible symptom: a fresh ``lorewiki install --all
--force`` could write the alias at the wrong path (a file
instead of a file-in-dir), and never updated the 5 primary
paths (the error message blamed the running agent when the
real cause was the wrong target path).

### Fixed
- ``lorewiki/utils/skill_installer.py``: ``TOOLS`` path templates
  now include the ``/SKILL.md`` suffix; ``_parent_exists``
  walks 3 levels up to find the tool config root; ``install_skill``
  cleans up the legacy single-file layout at the alias path
  before re-creating it as a directory; ``uninstall_skill``
  removes the now-empty parent dir when the file is gone.
- ``lorewiki/utils/skill_installer.py``: ``contextlib.suppress``
  instead of ``try/except/pass`` (ruff SIM105).

### Verified
- ``lorewiki install --all --force`` after this release
  overwrites all 7 primary + alias paths in place, even
  with the AI agent running.
- 326 tests pass, ruff clean.

## [0.3.1] — 2026-06-15

Patch release. Tightens the LLM agent skill so users never get
silently merged into a freshly-invented ``general`` topic when
they say "save this to my wiki" without naming one. The skill now
includes an explicit "ask, don't surprise" decision tree for
topic selection before any write operation, plus a
``save this URL / doc`` row in the cheat sheet.

No code change; only the bundled + source-tree copies of
``SKILL.md`` are updated (they stay byte-identical to each other).
PyPI install users pick up the new skill on their next
``lorewiki install --force`` (or fresh install of 0.3.1).

### Changed
- ``lorewiki/data/skill_template/SKILL.md`` and
  ``skills/lorewiki/SKILL.md``: new subsection
  *Topic Selection Before Writing (the "ask, don't surprise"
  rule)* — a decision tree the agent must walk when the user
  says "save X to my wiki" without naming a topic. Leaves the
  user in control of topic naming and selection; the agent
  must ask, never auto-create.
- ``.gitignore``: added ``SHARE.md`` (community-sharing
  scratch file kept out of the repo).
- Decision Cheat-Sheet at the bottom of ``SKILL.md``: the
  ``"remember this"`` row split into a "topic named" form and
  a "no topic" form (the latter points at the decision tree);
  a new ``"save this URL / doc to my wiki"`` row added.
- ``lorewiki/__init__.py``, ``pyproject.toml``: version
  0.3.0 → 0.3.1.

## [0.3.0] — 2026-06-15

Minor release. Removes the long-standing ``update`` subcommand stub
(0.2.0–0.2.9 reserved it for a future watcher) and rolls the
``--watch`` flag forward onto ``index``, which the indexer already
supports incrementally. Also adds a defensive warning when a
project-level ``wiki_path`` points to a non-existent directory —
a silent failure mode that bit at least one user after an
``init --path <tmp>`` test.

The version bump (0.2.9 → 0.3.0, not 0.2.10) follows the project's
"patch > 9 ⇒ bump minor" convention to keep version numbers
visually searchable.

### Removed
- ``lorewiki update`` (was a phase-6 stub since 0.2.0). Use
  ``lorewiki index`` (incremental by default) for one-shot
  re-indexing; ``lorewiki index --watch`` is the new home for the
  watcher flag and behaves like one-shot in 0.3.0 with a real
  file-watcher loop landing in 0.4.0.
- ``lorewiki.cli.helpers.phase_pending`` and its test parametrize
  case. No subcommand returns the "not yet implemented" panel any
  more.

### Added
- ``lorewiki index --watch`` / ``-w`` flag (one-shot behaviour in
  0.3.0; logs a warning that the real file-watcher is phase 6).
- ``lorewiki.config.load_config``: when ``<project>/.lorewiki/config.toml``
  contains a ``wiki_path`` that does not exist on disk, log a
  warning naming the stale path and the offending file, and drop
  the value from the merge so the topic-derived path wins.

### Changed
- ``lorewiki/topic.py``: ``"update"`` removed from
  ``_RESERVED_NAMES`` (the subcommand no longer exists, so the name
  is free for a user topic again).
- ``lorewiki/cli/helpers.py``: ``phase_pending`` removed.

## [0.2.9] — 2026-06-15

Bug-fix release. 0.2.8 closed the CJK / cross-platform story for
search and ingest, but the wheel-side ``lorewiki install``
subcommand had a related issue: when the *primary* path of a
tool was locked (e.g. Cursor writes a ``.skill-lock.json``
while the agent is running, which surfaces as
``PermissionError`` on ``Path.write_text``), the
``for alias_tmpl in tool.aliases:`` loop in ``install_skill``
was never entered — so Cursor / Gemini ``~/.agents/skills/``
aliases were silently never created and ``--status`` reported
``[ ]`` for them forever. 0.2.9 wraps each ``write_text`` (and
``unlink``) call in its own ``try / except OSError``, so a
locked primary becomes a ``[skip]`` line and the alias loop
runs to completion.

### Fixed
- ``lorewiki/utils/skill_installer.py``: each target write in
  ``install_skill`` and each target unlink in ``uninstall_skill``
  is now wrapped in its own ``try / except OSError``. A locked
  primary path no longer aborts the rest of the install /
  uninstall — it surfaces as a ``[skip]`` line and the
  next target (primary alias, etc.) gets its turn.

### Tests
- ``tests/test_cli_install.py``: two new regressions — one
  for the install path (locked primary → alias loop must
  still run) and one for the uninstall path (locked primary
  → alias must still be removed). Each uses ``monkeypatch``
  to simulate ``PermissionError`` on the primary
  ``Path.write_text`` / ``Path.unlink`` and asserts the
  alias side-effect did happen.

## [0.2.8] — 2026-06-15

Final cross-platform encoding fix. 0.2.7 closed the *output*
side of the CJK story (``--raw`` JSON, ``show`` body) by
reconfiguring stdout / stderr to UTF-8, and closed the
*detection* side of the CJK story (``XDG_CONFIG_HOME`` /
``CODEX_HOME`` / ``GEMINI_HOME`` env-var expansion). But on
**Windows + PowerShell**, piping a CJK string into ``lorewiki
add`` via stdin still produced mojibake on disk: a child
Python process started with redirected stdin inherits the
*parent*'s console code page (cp936 / GBK on zh_CN Windows)
as stdin encoding, while the same Python reconfigures
stdout / stderr to UTF-8 at import. The 0.2.7 wheel's
``apps._force_utf8_streams`` only reconfigured the output
streams, not stdin. The result was that the bytes read from
stdin were GBK-encoded, the body was written to disk as
mojibake (the ``骞傜瓑璁捐…`` rot observed in 0.2.7 smoke
tests on Windows), and the SQLite FTS5 index contained the
mojibake — so even after a successful ingest, downstream
``search`` calls against the literal CJK string returned 0
hits. 0.2.8 fixes stdin too.

### Fixed
- ``lorewiki/cli/apps.py``: ``_force_utf8_streams`` now also
  reconfigures ``sys.stdin`` to UTF-8 with ``errors='replace'``,
  in addition to stdout / stderr. With this, piping a UTF-8
  CJK body from any sensible parent (PowerShell 7+, bash,
  zsh, any *nix shell) results in a correctly-encoded
  ``.md`` file on disk and a queryable FTS5 index.

### Tests
- ``tests/test_cli_utf8_output.py``: new
  ``test_add_via_stdin_preserves_cjk_utf8_bytes`` regression
  that spawns a child Python with ``PYTHONIOENCODING=utf-8``
  and UTF-8 CJK bytes on stdin, then asserts the resulting
  ``.md`` file contains the literal CJK string and that
  ``search`` against a literal CJK term returns a hit. This
  is the regression that 0.2.7 missed: without the stdin
  reconfig, the test fails because the body is mojibake'd
  and the FTS5 index contains the mojibake.
- ``tests/test_cli_utf8_output.py``: three new real-corpus
  smoke tests (``test_real_corpus_search_wx_login`` /
  ``test_real_corpus_search_cjk_2char`` /
  ``test_real_corpus_status_reports_doc_count``) that hit
  the developer's ``~/.lorewiki/topics/wechat-miniprogram-api``
  topic (1468 docs, 1902 chunks) and skip silently when the
  corpus is not on disk. These run on the developer's own
  machine, not on a fresh CI runner, so they don't add to
  CI flakiness but do confirm that the wheel-built CLI works
  against a real-world CJK-heavy knowledge base.

### Known limitations (not lorewiki bugs)
- PowerShell 5.1's ``echo`` writes a UTF-16-LE BOM + wide
  chars to a redirected pipe. A Python child reading such
  bytes via stdin will see ``lone surrogates`` (the
  0.2.2-era bug); ``add.py``'s ``_strip_surrogates``
  replaces them with U+FFFD, so the file is at least not
  mojibake. To get a fully clean pipe on Windows, use
  PowerShell 7+ (``$OutputEncoding = UTF-8``) or ``cmd.exe``
  with ``chcp 65001``.
- ``Rich.Console(legacy_windows=True)`` (the default on
  Windows) writes through ``WriteConsoleW`` and can in some
  edge cases appear to truncate the last CJK character of
  a line. ``print()`` and ``sys.stdout.buffer.write()`` are
  unaffected. The lorewiki CLI's own output is fine; the
  truncation is a Rich-on-Windows-terminal quirk, not a
  lorewiki bug.

## [0.2.7] — 2026-06-15

Cross-platform fix. 0.2.6's ``Tool.resolve`` relied solely on
``os.path.expandvars`` to substitute ``$XDG_CONFIG_HOME`` /
``$CODEX_HOME`` / ``$GEMINI_HOME``. That works on POSIX, where
``expandvars`` understands ``$VAR``, but on Windows it silently
leaves the literal ``$VAR`` in the resolved path, so ``lorewiki
install --status`` (and any install / uninstall) printed / wrote
to a path like ``D:\codes\test-lorewiki\$XDG_CONFIG_HOME\opencode\…``
instead of ``%USERPROFILE%\.config\opencode\…``. The fix detects
the un-expanded literal and substitutes the user's home dir.

### Fixed
- ``lorewiki/utils/skill_installer.py`` and ``skills/install.py``:
  ``Tool.resolve`` now falls back to ``Path.home()``-relative
  defaults (``~/.config`` / ``~/.codex`` / ``~/.gemini``) when
  ``os.path.expandvars`` left ``$XDG_CONFIG_HOME`` /
  ``$CODEX_HOME`` / ``$GEMINI_HOME`` unexpanded (i.e. on
  Windows, where ``expandvars`` only knows ``%VAR%``). On POSIX
  systems the original behaviour is unchanged because
  ``expandvars`` already expanded the ``$VAR`` form.

## [0.2.6] — 2026-06-15

Bug-fix release. 0.2.5's ``Publish to PyPI`` workflow failed on
Linux CI because the source-tree ``skills/install.py`` and the
new ``lorewiki/utils/skill_installer.py`` both built the ``TOOLS``
tuple with ``os.environ.get("XDG_CONFIG_HOME", ...)`` evaluated at
module-import time, freezing the env value before the tests'
``monkeypatch.setenv`` could take effect. On Linux CI the
default ``/home/runner/.config/opencode/`` happens to exist, so
``detect_installed_tools()`` returned a non-empty list even
when the test expected an empty one. The wheel-side test
``test_cli_install.py::test_detect_finds_explicit_config_root``
failed the same way. The fix is to keep the path templates as
raw strings with ``$VAR`` placeholders and let ``Tool.resolve``
run ``os.path.expandvars`` on every call, so the env is read
fresh at resolve time.

### Fixed
- ``lorewiki/utils/skill_installer.py`` and ``skills/install.py``:
  ``TOOLS`` entries now use raw ``$XDG_CONFIG_HOME`` / ``$CODEX_HOME``
  / ``$GEMINI_HOME`` placeholders instead of
  ``os.environ.get(...).expanduser()`` evaluated at import time.
  ``Tool.resolve`` already runs ``os.path.expandvars`` on every call,
  so the runtime behaviour is unchanged — the only difference is
  that the env is read fresh rather than frozen at import.

## [0.2.5] — 2026-06-15

PyPI users can now install the agent skill without cloning the
repository. Previously the only way to put the ``lorewiki`` skill
into an AI tool's skills directory was ``python skills/install.py``
from a source checkout, which meant PyPI users had no way to use
the skill at all. 0.2.5 bundles the skill in the wheel and exposes
a new ``lorewiki install`` subcommand that mirrors the source-tree
installer's behaviour.

### Added
- ``lorewiki install`` subcommand (in ``lorewiki/cli/install_cmd.py``).
  Accepts the same multi-select grammar as the source-tree
  installer — single index (``3``), comma/space-separated
  (``1,3,5`` / ``1 3 5``), ranges (``2-4``), and mixed
  (``1,3-5,6``) — plus ``--all`` (install to every detected
  tool), ``--tool`` (explicit list), ``--force`` (overwrite),
  ``--uninstall``, and ``--status``.
- ``lorewiki.utils.skill_installer`` module: the cross-platform
  install / uninstall / detect primitives the wheel-side
  subcommand is built on. The source-tree
  ``skills/install.py`` continues to exist and ships the same
  grammar; the two share a deliberate one-way mirror (wheel
  inherits the catalog at install time, source stays the dev
  truth).
- Bundle the LoreWiki agent skill inside the wheel as package
  data: ``lorewiki/data/skill_template/SKILL.md`` is now listed
  in ``pyproject.toml`` under
  ``[tool.hatch.build.targets.wheel].include`` and read at
  install time via ``importlib.resources``.

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

