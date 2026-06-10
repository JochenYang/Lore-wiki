#!/usr/bin/env node
/*
 * npm postinstall hook for the `lorewiki` package.
 *
 * Goal: by the time `npm install -g lorewiki` returns, the user
 * can type `lorewiki --version` and get `LoreWiki 0.1.0`.
 *
 * Strategy (in order of preference):
 *   1. `uv tool install lorewiki` (clean, isolated, recommended)
 *   2. `pipx install lorewiki`   (legacy alternative)
 *   3. `pip install --user lorewiki` (no isolation, last resort)
 *
 * If none of the above work (no Python on PATH, no network, no
 * pip), we print a friendly error and exit 0 so the npm install
 * itself doesn't fail — the user can re-run `lorewiki-postinstall`
 * (which we leave behind) once they have Python.
 */
'use strict';

const { execFile, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PKG = 'lorewiki';
const VERSION = require(path.join(__dirname, '..', 'package.json')).version;

function sh(cmd, args, opts = {}) {
  try {
    const out = execFileSync(cmd, args, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      ...opts,
    });
    return { ok: true, stdout: out.trim() };
  } catch (e) {
    return {
      ok: false,
      code: e.status ?? 1,
      stdout: (e.stdout || '').toString(),
      stderr: (e.stderr || '').toString(),
    };
  }
}

function has(cmd) {
  return sh(cmd, ['--version']).ok || sh(cmd, ['-V']).ok;
}

function execOrDie(cmd, args) {
  console.log(`[lorewiki postinstall] ${cmd} ${args.join(' ')}`);
  const r = sh(cmd, args, { stdio: 'inherit' });
  if (!r.ok) {
    console.error(`[lorewiki postinstall] ${cmd} exited with code ${r.code}`);
    process.exit(1);
  }
}

function alreadyInstalled() {
  return sh('lorewiki', ['--version']).ok;
}

function tryInstall() {
  if (has('uv')) {
    console.log('[lorewiki postinstall] using uv (recommended)');
    execOrDie('uv', ['tool', 'install', `${PKG}==${VERSION}`, '--force']);
    return;
  }
  if (has('pipx')) {
    console.log('[lorewiki postinstall] using pipx');
    execOrDie('pipx', ['install', `${PKG}==${VERSION}`, '--force']);
    return;
  }
  if (has('pip')) {
    console.log('[lorewiki postinstall] uv / pipx not found; falling back to pip --user');
    console.warn(
      '[lorewiki postinstall] !! installing user-site is not isolated;',
    );
    console.warn(
      '[lorewiki postinstall] !! consider installing `uv` (https://astral.sh/uv) for a clean install.',
    );
    execOrDie('pip', ['install', '--user', `${PKG}==${VERSION}`]);
    return;
  }
  throw new Error('no Python package manager found (need uv, pipx, or pip)');
}

function main() {
  if (alreadyInstalled()) {
    const v = sh('lorewiki', ['--version']).stdout;
    console.log(`[lorewiki postinstall] lorewiki already on PATH: ${v}`);
    return;
  }
  try {
    tryInstall();
  } catch (e) {
    console.error('');
    console.error('===========================================================');
    console.error('  lorewiki postinstall FAILED');
    console.error('===========================================================');
    console.error(e.message);
    console.error('');
    console.error('You can retry any time by running:');
    console.error('  uv tool install lorewiki   # or');
    console.error('  pipx install lorewiki       # or');
    console.error('  pip install --user lorewiki');
    console.error('');
    console.error('The `npm install` itself succeeded; lorewiki just isn\'t on');
    console.error('PATH yet. The bin/lorewiki.js shim will retry on every');
    console.error('invocation and surface a clear error until you install it.');
    console.error('');
    // Don't fail npm install — the shim will keep working as soon
    // as the user installs lorewiki themselves.
  }
}

// npm invokes us with cwd = the package root, no args. Run main,
// but never throw (npm swallows non-zero exit from postinstall
// differently across versions; we want a clean best-effort).
try {
  main();
} catch (e) {
  console.error('[lorewiki postinstall] unexpected error:', e.message);
}
