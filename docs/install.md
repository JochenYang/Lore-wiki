# Installing, upgrading, and uninstalling LoreWiki

> LoreWiki is a Python tool and lives on **PyPI** as the canonical
> source. The same release is also published to **npm** as a thin
> Node shim that proxies to the Python wheel. **Either** install
> path is supported:
>
> - **Python user** (recommended, full feature set): `uv tool install lorewiki`
> - **Node user** (familiar `npm install -g` flow, same CLI): `npm install -g lorewiki`

## TL;DR

### Python (recommended)

```bash
# Install (isolated, per-tool venv):
uv tool install lorewiki

# Install with all optional features (FastAPI / MCP / vector):
uv tool install 'lorewiki[all]'

# Upgrade:
uv tool upgrade lorewiki

# Uninstall:
uv tool uninstall lorewiki
```

If you don't have `uv` yet:

```bash
# Install uv once (any platform):
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or on Windows:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Node (npm shim)

```bash
# Install — the postinstall hook calls `uv tool install lorewiki`
# (or pipx / pip as fallback) so the same Python wheel ends up on
# your PATH:
npm install -g lorewiki

# Upgrade (re-runs postinstall with the new version):
npm install -g lorewiki@latest

# Uninstall (also runs `uv tool uninstall lorewiki` if the wheel
# version matches the npm version):
npm uninstall -g lorewiki
```

The npm package contains no real logic — it spawns the Python
`lorewiki` binary that the postinstall hook installed. See
[README.npm.md](../README.npm.md) for the full story and fallback
behavior when no Python package manager is on `PATH`.

## Why `uv tool` and not `pip install --user`?

| Install method                                | Isolation            | PATH handling            | Notes                                                      |
|----------------------------------------------|----------------------|--------------------------|------------------------------------------------------------|
| **`uv tool install lorewiki`** (recommended) | own venv, per-tool   | automatic                | Doesn't touch system Python; clean uninstall               |
| `pipx install lorewiki`                      | own venv, per-tool   | automatic                | Older alternative; `uv tool` is faster and ships with uv     |
| `pip install --user lorewiki`               | shared user-site     | manual (PATH)            | Slow; conflicts with system Python                          |
| `pip install lorewiki` (system)              | **none**             | system PATH             | ❌ Avoid — can break the system Python                      |
| `npm install -g lorewiki` (npm shim)         | own venv, per-tool   | automatic                | Node-friendly entry point; the wheel is still the artifact — postinstall calls `uv tool install lorewiki` for you. Use this if you have npm but not `uv`; once it runs once you can ignore npm and treat `lorewiki` as a normal CLI. |

`uv tool install` is what the project uses during development
(`.venv` is identical) and what the README documents. Stick with it.

## Optional dependencies (extras)

`lorewiki` keeps the **core** install tiny (wheel is ~70 KB and
needs only `typer`, `rich`, `loguru`, `pydantic`, `httpx`, etc.).
Optional features are behind extras:

| Extra            | What it adds                                                  | When you need it                                                                                              |
|------------------|--------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| `lorewiki[rest]`   | FastAPI + Uvicorn                                             | You want a REST API (`lorewiki rest`, OpenAPI at `/docs`)                                                    |
| `lorewiki[mcp]`    | MCP stdio server                                              | You want Claude Desktop / Cursor / opencode to talk to lorewiki via the Model Context Protocol              |
| `lorewiki[vector]` | sqlite-vec + sentence-transformers (note: vector retrieval not yet implemented — opt-in for future) | When phase-7 vector retrieval lands                                                                          |

> **Note**: LoreWiki no longer ships a built-in web UI in 0.1.0.
> The `[ui]` extra and the `lorewiki ui` subcommand are gone.
> Consume the data via the REST API, the MCP server, or by opening
> the active topic's vault directory in any Markdown editor
> (Obsidian, VS Code, etc.).
| `lorewiki[dev]`    | pytest / pytest-cov / pytest-asyncio / ruff                   | You want to run the test suite locally                                                                        |
| `lorewiki[all]`    | `lorewiki[ui,rest,mcp,vector]`                                | Kitchen-sink install                                                                                          |

```bash
# Single extra:
uv tool install 'lorewiki[mcp]'

# Multiple extras (comma-separated):
uv tool install 'lorewiki[ui,rest,mcp]'

# Everything:
uv tool install 'lorewiki[all]'
```

After `uv tool install 'lorewiki[rest]'`, the `lorewiki rest`
subcommand becomes available.

## Where does the data live?

`lorewiki` keeps **all** user data under `~/.lorewiki/`:

```
~/.lorewiki/
├── config.toml                      # global config (LLM keys, retrieval mode, etc.)
├── current                          # text file: name of the active topic
└── topics/
    ├── react/                       # one topic = one vault
    │   ├── .lorewiki/
    │   │   └── index.db
    │   ├── api/
    │   └── patterns/
    └── wechat-mp/
        └── ...
```

Uninstalling `lorewiki` does **not** delete `~/.lorewiki/`. Your
data is yours; remove it manually if you want a clean slate:

```bash
rm -rf ~/.lorewiki   # WARNING: deletes ALL topics and config
```

To back up before uninstalling:

```bash
# Archive the whole lorewiki state
tar czf lorewiki-backup-$(date +%Y%m%d).tar.gz ~/.lorewiki
```

## Verifying the install

```bash
lorewiki --version
# expect: LoreWiki 0.1.0

lorewiki --help
# expect: full help text with the 7 root subcommands

# Quick smoke test
lorewiki topic list
# expect: 'No topics yet.' panel + a hint to run `lorewiki topic create`
```

## Common install errors

| Symptom                                          | Cause                                                                                          | Fix                                                                                                                       |
|--------------------------------------------------|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| `command not found: lorewiki`                   | `uv tool` install finished but `~/.local/bin` (or `%USERPROFILE%\.local\bin`) isn't on PATH | `uv tool install` prints a hint at the end; re-source the shell or add the directory to PATH                                |
| `ModuleNotFoundError: streamlit` running `lorewiki --web` | You installed `lorewiki` after a release that still had a Streamlit UI | LoreWiki dropped the built-in web UI in 0.1.0. The `--web` flag is now a no-op that prints a migration hint. Use the REST API, the MCP server, or your Markdown editor instead. |
| `Wheel ... located at ... does not appear to be valid` (`twine check`) | Malformed `pyproject.toml` after edits                                                       | Re-run `python -m build` from a clean tree; if it persists, paste the full error into a GitHub issue                   |
| `403 Forbidden` uploading to PyPI                  | Wrong API token (or expired)                                                                  | Generate a per-project token at <https://pypi.org/manage/account/token/>; the username **must** be `__token__`          |

## Publishing (maintainers only)

End users **do not** need this section. If you maintain lorewiki and
want to push a new release, see:

- `scripts/publish.sh` (macOS / Linux)
- `scripts/publish.ps1` (Windows PowerShell)

Both scripts:

1. Run `pytest -q` and `ruff check` (skip with `--skip-tests`).
2. Build wheel + sdist (skip with `--skip-build`).
3. Run `twine check` to validate the metadata.
4. Upload to **TestPyPI first** (always — safety net).
5. Verify the install in a clean throwaway venv.
6. Wait 5 s; then upload to **live PyPI**.
7. Then `npm publish` (the same release version, so the npm
   postinstall hook can find the matching wheel on PyPI).

To do a TestPyPI-only run (no live push), pass `--test` /
`-Test`. For npm, run `npm login` once on the machine (or set
`$NPM_TOKEN` to an automation token) before invoking the script.

If `npm` is not on `PATH` (e.g. on a server-only CI box), the
script logs a clear warning and exits 0 — the PyPI release is
still considered complete, and the npm step can be run later
from a developer machine with Node installed.

## Versioning

LoreWiki follows [Semantic Versioning](https://semver.org/) —
`MAJOR.MINOR.PATCH`:

- `MAJOR` — incompatible API changes (e.g. `lorewiki config` shape changes)
- `MINOR` — backward-compatible new features (e.g. a new subcommand)
- `PATCH` — backward-compatible bug fixes

Bumping the version: edit `version` in **both** `pyproject.toml`
and `package.json` (they must match — the npm postinstall calls
`uv tool install lorewiki==<version>` with the npm package
version). Then run `scripts/publish.sh`, push the resulting git
tag (`git tag v0.1.1 && git push --tags`).

## Channels (future)

We may publish a `lorewiki-canary` channel on TestPyPI for
preview releases; today, **all** releases go to **stable** on PyPI
and `latest` on npm. Nightly / canary builds are out of scope
for v0.1.x.
