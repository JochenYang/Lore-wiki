#!/usr/bin/env node
/*
 * npm preuninstall hook for the `lorewiki` package.
 *
 * Runs on `npm uninstall -g lorewiki` (and on `npm install -g lorewiki@new`
 * before the new version lands). Removes the Python wheel that the
 * postinstall script installed, so removing the npm package leaves
 * no orphan on the user's PATH.
 *
 * Only removes a wheel whose version matches the npm version we're
 * removing. If the user installed lorewiki separately (e.g. they
 * have `lorewiki==0.2.0` from a different channel), we leave it
 * alone.
 */
'use strict';

const { execFileSync } = require('node:child_process');
const path = require('node:path');

const PKG = 'lorewiki';
const VERSION = require(path.join(__dirname, '..', 'package.json')).version;

function sh(cmd, args) {
  try {
    execFileSync(cmd, args, { encoding: 'utf8', stdio: 'inherit' });
    return true;
  } catch (e) {
    return false;
  }
}

function getInstalledVersion() {
  if (!sh('lorewiki', ['--version'])) return null;
  try {
    const out = execFileSync('lorewiki', ['--version'], { encoding: 'utf8' });
    const m = out.match(/LoreWiki\s+(\S+)/);
    return m ? m[1] : null;
  } catch (e) {
    return null;
  }
}

function main() {
  const installed = getInstalledVersion();
  if (!installed) {
    console.log('[lorewiki preuninstall] lorewiki not on PATH; nothing to remove');
    return;
  }
  if (installed !== VERSION) {
    console.log(
      `[lorewiki preuninstall] installed version ${installed} != npm version ${VERSION};`,
    );
    console.log(
      '[lorewiki preuninstall]   leaving the wheel alone (user-installed independently).',
    );
    return;
  }
  // Version matches. Try the uninstallers in preference order.
  if (sh('uv', ['tool', 'uninstall', PKG])) {
    console.log(`[lorewiki preuninstall] uv tool uninstall ${PKG}: ok`);
    return;
  }
  if (sh('pipx', ['uninstall', PKG])) {
    console.log(`[lorewiki preuninstall] pipx uninstall ${PKG}: ok`);
    return;
  }
  if (sh('pip', ['uninstall', '-y', PKG])) {
    console.log(`[lorewiki preuninstall] pip uninstall ${PKG}: ok`);
    return;
  }
  console.warn(
    '[lorewiki preuninstall] could not find a Python package manager;',
  );
  console.warn(
    '[lorewiki preuninstall]   you may want to run `uv tool uninstall lorewiki` by hand.',
  );
}

try {
  main();
} catch (e) {
  console.error('[lorewiki preuninstall] unexpected error:', e.message);
}
