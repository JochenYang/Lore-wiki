# lorewiki

> A thin npm shim around the [lorewiki](https://github.com/JochenYang/Lore-wiki)
> Python package. This npm package contains no real logic — it
> installs the Python wheel via `uv` / `pipx` / `pip` and proxies
> the `lorewiki` binary.

## What you get

After `npm install -g lorewiki`, the `lorewiki` CLI is on your
PATH (courtesy of the postinstall hook), and you can type:

```bash
lorewiki --version
# -> LoreWiki 0.1.0

lorewiki topic list
lorewiki search "JWT" --raw
lorewiki ask "how does rate limiting work?" --raw
```

The CLI itself is Python; the npm package is just a familiar install
path for Node.js developers who already have npm but not `uv` /
`pipx` / `pip`.

## Install

```bash
# Recommended — global install, isolated venv under the hood:
npm install -g lorewiki

# Or, project-local:
npm install --save-dev lorewiki
# then call via npx:  npx lorewiki --version
```

## Requirements

The postinstall script needs **one** of:

- [`uv`](https://docs.astral.sh/uv/) (recommended; a single-binary download)
- `pipx` (older alternative)
- `pip` (last resort; no isolation)

If none of these are on `PATH` when `npm install` runs, the npm
install itself succeeds but `lorewiki --version` will print a
helpful error and exit 127. Install one of the above and re-run
`npm install -g lorewiki` to recover.

## Update

```bash
npm install -g lorewiki@latest
```

The postinstall hook detects the version mismatch and runs
`uv tool install lorewiki@<new>` (force-upgrade) to keep the
Python wheel in sync.

## Uninstall

```bash
npm uninstall -g lorewiki
```

The `preuninstall` hook removes the Python wheel **only** if the
version matches the npm version being uninstalled. If you
installed lorewiki independently (e.g. `pip install lorewiki`),
it's left alone.

## Why a shim and not a real Node implementation?

LoreWiki's data layer is SQLite-FTS5 + a 199-test retrieval core
(Recall@5 = 100 % on the included benchmark). Re-implementing in
TypeScript would lose all that. The shim lets Node users get the
same `lorewiki` binary via `npm install -g`, while Python users
keep using `uv tool install lorewiki` from
[PyPI](https://pypi.org/project/lorewiki/).

## License

[MIT](LICENSE).
