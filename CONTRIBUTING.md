# Contributing to LoreWiki

Thanks for your interest in making LoreWiki better. This document
covers the day-to-day workflow: setting up a dev environment, the
test / lint expectations, and how to send a change back.

## Development environment

```bash
git clone <repo> && cd Lorewiki
uv venv .venv
.venv\Scripts\activate             # or `source .venv/bin/activate`

# editable install with every optional dep
uv pip install -e ".[all,dev]"

# verify the install
lorewiki --version                # LoreWiki 0.1.0
```

Python **3.10+** required. The project ships a `pyproject.toml`
(hatchling backend) — no setuptools boilerplate.

## Before every commit

```bash
ruff check lorewiki skills tests  # must be 0 errors
pytest -q                          # must be all green
pytest --cov=lorewiki              # coverage should not regress
```

CI runs the same three commands. The coverage bar is ≥ 80% overall
and the critical-path modules (`db/`, `indexer/`, `retriever/`,
`llm/`, `topic/`) should be ≥ 90%. Pull requests that drop coverage
on a critical-path module need a justification in the description.

## Code style

- **Functions ≤ 50 lines, files 200-400 lines preferred, ≤ 800 hard limit, nesting depth ≤ 4.** Enforced by ruff.
- **Type hints everywhere.** `from __future__ import annotations` at the top of every module.
- **No `any` unless at an explicit boundary.** (Checked via `mypy` / IDE in your editor.)
- **Comments explain *why*, not *what*.** Good comment: "trigram ANDs each 3-gram by default; we OR them so recall survives the strict phrase mode." Bad comment: "split the query into 3-grams."
- **Tests live in `tests/test_<module>.py`** and follow `AAA` (arrange / act / assert). One test class per behavior, not per file.

## Module map (where new code goes)

| You want to ...                       | Edit                                  |
| ------------------------------------- | ------------------------------------- |
| Add a new CLI subcommand                | `lorewiki/cli.py` (one Typer `@app.command`) |
| Add a new retriever                     | `lorewiki/retriever/<name>.py` + register in `lorewiki/cli.py::_run_search` |
| Add a new LLM backend                   | `lorewiki/llm/client.py` (subclass `BaseLLMClient`, add to `build_client` factory) |
| Add a new HTTP endpoint                 | `lorewiki/server/rest_api.py`          |
| Add a new MCP tool                      | `lorewiki/server/mcp_server.py`        |
| Add a new Streamlit page                | `lorewiki/server/ui.py` (lazy import!) |
| Change config schema                   | `lorewiki/config.py` (pydantic model)   |
| Add a new self-critique document        | `docs/critique/phase-N.md`             |

## Per-phase discipline

LoreWiki was built in **phases**, each with a self-critique doc in
`docs/critique/`. The pattern is: ship the phase, then write
`phase-N.md` with at least 3 self-discovered issues, half of which
must be either fixed immediately or explicitly deferred with
rationale. Continue this practice for any new phase.

## Commit messages

We follow the [Conventional Commits](https://www.conventionalcommits.org/)
style:

```
feat(retriever): add bigram tokens for 2-character CJK
fix(cli): force UTF-8 stdout on Windows
docs: explain path resolution priority
test(topic): add ingest-summary coverage
chore: bump pyproject to 0.1.1
```

Scope is the primary module; the subject is imperative-mood, no
period, ≤ 72 chars. Body explains *why*, not *what* (the diff shows
the what).

## Pull request checklist

- [ ] One logical change per PR (split unrelated cleanups into separate PRs)
- [ ] `ruff check` 0 errors
- [ ] `pytest` all green
- [ ] New / changed behaviour covered by tests
- [ ] If you changed a user-facing command, updated the relevant
      section of `README.md`, `docs/architecture.md`, or
      `docs/how-it-works.md`
- [ ] If you added a new public API, added it to the right place
      (CLI command → README, REST endpoint → README, MCP tool →
      README, agent skill section → `skills/lorewiki/SKILL.md`)
- [ ] Self-critique doc if you shipped a phase (≥ 3 self-discovered
      issues; ≥ half fixed or explicitly deferred)

## Reporting a bug

Open an issue with:

1. LoreWiki version (`lorewiki --version`)
2. OS + Python version (`python --version`)
3. The exact command you ran
4. What you expected vs. what happened
5. The output of `lorewiki config list` and (if relevant) the first
   few lines of the relevant log line (raise verbosity with
   `LOREWIKI_LOG_FILE=/tmp/lw.log`)

## Reporting a security issue

Please email the maintainers directly (see the commit history for
current addresses) rather than opening a public issue. We aim to
acknowledge within 48 hours.
