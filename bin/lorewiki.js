#!/usr/bin/env node
/*
 * `lorewiki` CLI shim — a thin Node wrapper around the Python wheel.
 *
 * The npm package itself contains no logic; it depends on the
 * `postinstall` script having run successfully, which installs
 * `lorewiki` from PyPI into a Python environment reachable on PATH.
 * This file just spawns the Python `lorewiki` binary and propagates
 * the exit code.
 *
 * Why a shim and not a real Node implementation? LoreWiki is a
 * SQLite-FTS5 + LLM tool; the data + retrieval core is Python
 * (well-tested, 199 unit tests, Recall@5 = 100%). Re-implementing
 * the data layer in TypeScript would lose all that. The shim lets
 * Node users get the same `lorewiki` binary with a familiar
 * `npm install -g` flow, while Python users keep using
 * `uv tool install lorewiki` from PyPI.
 */
'use strict';

const { spawn } = require('node:child_process');
const path = require('node:path');

// Resolve the lorewiki binary. The postinstall script symlinks /
// installs it into one of:
//   1. PATH (preferred — works because `uv tool install` and
//      `pipx install` both add the tool's bin dir to PATH for
//      the user).
//   2. The virtualenv's bin dir (e.g. /usr/lorewiki/.venv/bin/
//      lorewiki) — we remember this in scripts/postinstall.js.
//
// We don't bake the venv path in here because the user can move /
// re-install lorewiki at any time; spawning from PATH is the only
// way to track that.
const argv = process.argv.slice(2);
const result = spawn('lorewiki', argv, {
  stdio: 'inherit',
  windowsHide: true,
});

result.on('error', (err) => {
  if (err.code === 'ENOENT') {
    process.stderr.write(
      [
        '',
        'ERROR: `lorewiki` binary not found on PATH.',
        '',
        'The npm shim relies on the Python wheel being installed',
        'by the postinstall hook. Re-run install to recover:',
        '',
        '  npm install -g lorewiki@<version>',
        '  # or, if you prefer to install the wheel directly:',
        '  pip install lorewiki',
        '  uv tool install lorewiki',
        '',
        '(The Python tool is the only distribution today; the npm',
        ' package is a thin wrapper that calls the wheel installer.',
        ' See https://github.com/JochenYang/Lore-wiki for details.)',
        '',
      ].join('\n'),
    );
    process.exit(127);
  }
  process.stderr.write(`lorewiki shim: ${err.message}\n`);
  process.exit(1);
});

result.on('exit', (code, signal) => {
  if (signal) {
    // Forward SIGINT / SIGTERM semantics so Ctrl-C works the same
    // way as a native binary.
    process.exit(128 + (signal === 'SIGINT' ? 2 : 15));
  }
  process.exit(code ?? 0);
});
