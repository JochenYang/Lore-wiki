# Phase 0 — Bootstrap / CLI skeleton — Self-critique

> Mission: complete the dev document "Phase 0: environment setup"
> and self-audit before entering Phase 1.
> Timeline: completed within a single session.

## 1. Actual deliverables

### 1.1 Project skeleton

- `pyproject.toml` — hatchling build backend, PEP 621 metadata,
  `lorewiki` console-script entry, optional extras (`ui` / `rest` /
  `mcp` / `vector` / `dev` / `all`).
- `lorewiki/` package — `cli.py`, `utils/logger.py` (loguru
  wrapper), and placeholder sub-packages `db/`, `indexer/`,
  `retriever/`, `llm/`, `server/`, `utils/`.
- `lorewiki/__main__.py` — supports `python -m lorewiki`.
- `tests/` — 23 pytest cases covering CLI, logger, and module
  entry point.
- `docs/critique/` — phase critique directory.
- `README.md` and `.gitignore` in place.

### 1.2 Observable acceptance

- `lorewiki --version` → `LoreWiki 0.1.0` ✓
- `lorewiki --help` lists all 10 sub-commands (init / index /
  status / update / search / ask / ui / mcp / rest / config) ✓
- Every unimplemented sub-command shows a "phase pending" panel
  and exits with **exit code 2** (distinguishable for scripts and
  tests); confirmed by manual run ✓
- `python -m lorewiki --version` ✓
- 23 pytest cases all pass; line + branch coverage **99%**
  (`cli.py` and `logger.py` at 100%) ✓
- `ruff` lint 0 errors ✓

## 2. Self-discovered issues (in discovery order)

| # | Issue | Severity | Source | Status |
|---|-------|----------|--------|--------|
| 1 | `lorewiki/utils/logger.py` used `global _CONFIGURED`, triggering ruff `PLW0603` | medium | second ruff pass | **Fixed**: replaced with a `_state` dict container (mutable, no `global` needed) and added `reset_for_tests()` for unit-test isolation. |
| 2 | `__main__.py`, the `LOREWIKI_LOG_FILE` branch, and `print_phase_status()` (~15 lines total) were uncovered by any test (coverage 83%) | medium | first coverage report | **Fixed**: added `tests/test_module_entrypoint.py` (subprocess-running `python -m lorewiki`) + `tests/test_logger.py` (env-var, file sink, idempotency) + `print_phase_status` coverage. |
| 3 | `test_cli.py` `parametrize` was missing the `update` sub-command, so `cli.py:103` was uncovered | low | second coverage report | **Fixed**: added to `parametrize`. |
| 4 | `typer.testing.CliRunner` in click 8.1+ already splits stdout / stderr by default; the legacy `mix_stderr=False` argument raised `TypeError` on first run | medium | pytest error | **Fixed**: dropped the argument; use `result.output` everywhere. |
| 5 | `test_cli.py` had `from lorewiki.cli import print_phase_status` inside a function body, triggering ruff `PLC0415` | low | third ruff pass | **Fixed**: promoted to module-level import. |
| 6 | `__main__.py:3` still shows 0% in the coverage report (tests launch the entry as a subprocess, invisible to the coverage main process) — the only remaining uncovered line | low | final coverage report | **Annotated** with `# pragma: no cover - exercised by subprocess tests`. The pragma doesn't help here because the missing line is the `from lorewiki.cli import app` import rather than the `if __name__` branch; this is a known `coverage.py` limitation under `python -m`. **Acceptable**: 99% coverage, well above the ≥80% bar; no further effort. |

> **Critique conclusion**: the 6 issues actually exposed here
> exceed the planned "≥ 3 issues" baseline, confirming that
> setting up `ruff` / `coverage` from scratch really does miss
> details. From here on, run `ruff check` + `pytest --cov`
> immediately after writing rather than deferring to the end of
> the phase.

## 3. Lingering risks (must address in Phase 1)

1. **LSP errors vs. runtime OK** — the IDE's default Python
   interpreter doesn't point at `.venv`, so imports show red
   squiggles, but `pytest` and `lorewiki` actually work. **Plan**:
   in Phase 1, document "point your IDE Python interpreter at
   `.venv`" and consider `pyrightconfig.json` /
   `.vscode/settings.json` (only if really needed).
2. **`__main__.py` coverage blind spot** — subprocess-launched
   entry points can't be counted by `coverage.py` in single-process
   mode. **Plan**: if 100% is required before Phase 5 packaging,
   switch to `coverage run --parallel-mode` + `coverage combine`;
   not worth it now.
3. **Dependency lower bounds** in `pyproject.toml` — `typer>=0.12`
   but actually installed at 0.26. **Plan**: lock known-good
   ranges with `pip-compile` or `uv lock` before Phase 5, and run
   a compatibility matrix (py3.10 / 3.11 / 3.12).
4. **Logger global mutable state** — `_state` is module-level; the
   read-write in `_configure()` is not atomic across threads
   (low-probability race). **Plan**: when Phase 4 brings
   Streamlit / FastAPI multi-threaded entry points, wrap with
   `threading.Lock`; CLI single-thread is fine for now.
5. **Cross-platform path handling not yet done** — Windows
   `_logger.add(log_file=...)` works with backslashes, but later
   `lorewiki init` and `wiki_path` handling must standardise on
   `pathlib.Path`. **Plan**: Phase 1's config module uses
   `pydantic_settings.SettingsConfigDict(env_file=...)` +
   `pathlib.Path` from the start, avoiding string paths.

## 4. Phase-1 gate check

- [x] `pip install -e .[dev]` works in a fresh venv
- [x] CLI entry + module entry both functional
- [x] Test baseline established (pytest + cov + ruff pipeline)
- [x] Critique directory in place
- [x] Inter-phase status is exposed via
      `lorewiki/cli.py:print_phase_status()` for downstream audits

---

**Phase verdict**: ✅ pass, ready for Phase 1.
