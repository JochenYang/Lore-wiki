# Installing, upgrading, and uninstalling LoreWiki

> LoreWiki is a Python tool and lives on **PyPI** as the canonical
> (and only) distribution channel.
>
> This document is the deep-dive companion to the README's
> [`## Installation`](../README.md#installation) section. Read the
> README for the quickstart; come here for PATH troubleshooting,
> where data lives, backups, common errors, and the publishing
> workflow for maintainers.

## TL;DR

```bash
# Install (isolated per-tool venv, lorewiki added to PATH):
uv tool install lorewiki

# Install with the optional vector-retrieval extra
# (sqlite-vec + sentence-transformers):
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

## Why `uv tool` and not `pip install --user`?

| Install method                                | Isolation            | PATH handling            | Notes                                                      |
|----------------------------------------------|----------------------|--------------------------|------------------------------------------------------------|
| **`uv tool install lorewiki`** (recommended) | own venv, per-tool   | automatic                | Doesn't touch system Python; clean uninstall               |
| `pipx install lorewiki`                      | own venv, per-tool   | automatic                | Older alternative; `uv tool` is faster and ships with uv     |
| `pip install --user lorewiki`               | shared user-site     | manual (PATH)            | Slow; conflicts with system Python                          |
| `pip install lorewiki` (system)              | **none**             | system PATH             | ❌ Avoid — can break the system Python                      |

## Optional dependencies (extras)

`lorewiki` keeps the **core** install tiny (wheel is ~80 KB and
needs only `typer`, `rich`, `loguru`, `pydantic`, `httpx`, etc.).
Optional features are behind extras:

| Extra              | What it adds                                                          | When you need it                                                                                                       |
|--------------------|-----------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| `lorewiki[vector]` | sqlite-vec + sentence-transformers                                    | You want vector retrieval. **Note**: vector retrieval is not yet implemented in the CLI; opt-in for a future release.  |
| `lorewiki[dev]`    | pytest / pytest-cov / pytest-asyncio / ruff                           | You want to run the test suite locally                                                                                 |
| `lorewiki[all]`    | Alias for `lorewiki[vector]`                                          | Kitchen-sink install (was `lorewiki[ui,rest,mcp,vector]` in 0.1.x; the first three were removed in 0.2.0)            |

> **Removed in 0.2.0**:
> - `[rest]` (FastAPI + Uvicorn) — REST API surface was dropped
> - `[mcp]` (MCP stdio server) — replaced by the opencode skill
> - `[ui]` (Streamlit) — built-in web UI was dropped in 0.1.0
>
> The CLI + opencode skill is the only programmatic surface as of
> 0.2.0. See the [README](../README.md) for the architecture diagram.

```bash
# Single extra:
uv tool install 'lorewiki[vector]'

# Multiple extras (comma-separated):
uv tool install 'lorewiki[vector,dev]'   # unusual combo, but legal

# Everything:
uv tool install 'lorewiki[all]'
```

After `uv tool install 'lorewiki[vector]'`, the `sqlite-vec` and
`sentence-transformers` packages are available; the vector retriever
itself lands in a future release.

## Verifying the install (from PyPI)

After installing from PyPI, the *gold standard* check is **proving
the wheel on your disk is byte-identical to what PyPI served**.
This catches "I'm sure I upgraded" mistakes that the `lorewiki
--version` banner cannot.

```powershell
# 1. Confirm the version banner:
lorewiki --version
# expect: banner ending with "v0.2.x"

# 2. Confirm the install was from a registry, not local:
#    A PyPI-installed wheel has NO direct_url.json in its dist-info.
#    An editable / local install DOES.
Get-ChildItem `
  "$env:USERPROFILE\AppData\Roaming\uv\tools\lorewiki\Lib\site-packages" `
  -Filter "direct_url.json" -Recurse -ErrorAction SilentlyContinue
# expect: empty (no matches)

# 3. Compare the wheel's SHA256 to PyPI's published hash:
$distInfo = Get-ChildItem `
  "$env:USERPROFILE\AppData\Roaming\uv\tools\lorewiki\Lib\site-packages" `
  -Directory -Filter "lorewiki-*.dist-info" | Select-Object -First 1
$record = Join-Path $distInfo.FullName "RECORD"
(Get-FileHash $record -Algorithm SHA256).Hash
# Then cross-check against PyPI's official hash for the same wheel:
#   https://pypi.org/pypi/lorewiki/json
# (look in `urls[].digests.sha256` for the wheel you installed).
```

```bash
# macOS / Linux equivalent:
lorewiki --version
ls -la ~/.local/share/uv/tools/lorewiki/lib/python*/site-packages/ | grep direct_url.json
# expect: no such file
shasum -a 256 ~/.local/share/uv/tools/lorewiki/lib/python*/site-packages/lorewiki-*.dist-info/RECORD
# cross-check at https://pypi.org/pypi/lorewiki/json
```

A quick smoke test:

```bash
lorewiki topic list
# expect: a table with your existing topics, or "No topics yet." if fresh
```

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

## Common install errors

| Symptom                                                | Cause                                                                                          | Fix                                                                                                                       |
|--------------------------------------------------------|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| `command not found: lorewiki`                          | `uv tool` install finished but `~/.local/bin` (or `%USERPROFILE%\.local\bin`) isn't on PATH   | `uv tool install` prints a hint at the end; re-source the shell or add the directory to PATH                                |
| `lorewiki add` crashes with `UnicodeEncodeError: surrogates not allowed` | You are on 0.2.1 (or earlier) and piping a CJK body into PowerShell | **Fixed in 0.2.2.** Upgrade with `uv tool upgrade lorewiki`. If you cannot upgrade, pass the body via `--body` or `--file` instead of stdin |
| `lorewiki add` leaves a 0-byte file on disk            | Same root cause as the row above; 0.2.1 swallowed the UnicodeEncodeError silently             | **Fixed in 0.2.2.** Upgrade, then delete the empty file (or re-run with `--force`)                                          |
| CJK characters show as `?` in `lorewiki search` output | You're on a release older than 0.2.0                                                          | Upgrade to 0.2.0+, which forces UTF-8 stdout/stderr unconditionally. Or prefix the command with `chcp 65001 |` (Windows) |
| `lorewiki.exe` version shows the old number after `uv tool upgrade` | The new binary is on PATH but the current PowerShell session cached the old one | Open a fresh PowerShell window, or `refreshenv` / `Remove-Item Env:Path*` (less reliable)                                     |
| `Wheel ... does not appear to be valid` (`twine check`) | Malformed `pyproject.toml` after edits                                                       | Re-run `python -m build` from a clean tree; if it persists, paste the full error into a GitHub issue                       |

## Publishing (maintainers only)

End users **do not** need this section. If you maintain lorewiki and
want to push a new release:

1. **Bump the version** in both package metadata files (they must match), and add a changelog entry:
   - `pyproject.toml` → `version = "X.Y.Z"`
   - `lorewiki/__init__.py` → `__version__ = "X.Y.Z"`
   - `CHANGELOG.md` → add a top-level `## [X.Y.Z] — YYYY-MM-DD` entry
2. **Verify locally**:
   ```bash
   ruff check lorewiki skills tests
   pytest -q
   python -m build              # wheel + sdist into dist/
   twine check dist/*
   ```
3. **Commit + tag + push**:
   ```bash
   git add -A
   git commit -m "build: bump version to X.Y.Z"
   git push origin main
   git tag -a vX.Y.Z -m "Release X.Y.Z: <one-line summary>"
    git push origin vX.Y.Z
    ```
4. **CI handles the rest**: the `Publish to PyPI` workflow is
   triggered by the tag push. It re-runs the tests + lint, builds
   the wheel/sdist, and uploads to **PyPI via Trusted Publishing
   (OIDC)** — no API token needed. PyPI's `pypi` environment
   constraint (configured in the PyPI control panel) ensures only
   the GitHub Actions run from the `pypi` environment can exchange
   an OIDC token for an upload token.

## Versioning

LoreWiki follows [Semantic Versioning](https://semver.org/) —
`MAJOR.MINOR.PATCH`:

- `MAJOR` — incompatible API changes (e.g. `lorewiki config` shape changes)
- `MINOR` — backward-compatible new features (e.g. a new subcommand)
- `PATCH` — backward-compatible bug fixes (e.g. 0.2.2's surrogate fix)

## Channels (future)

We may publish a `lorewiki-canary` channel on TestPyPI for
preview releases; today, **all** releases go to **stable** on PyPI.
Nightly / canary builds are out of scope for v0.2.x.
