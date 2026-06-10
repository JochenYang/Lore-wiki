#!/usr/bin/env bash
# Publish lorewiki to PyPI (or TestPyPI first for a dry run).
#
# Usage:
#   ./scripts/publish.sh                # full: tests -> build -> TestPyPI -> verify -> PyPI -> npm
#   ./scripts/publish.sh --test         # only upload to TestPyPI, skip the live push
#   ./scripts/publish.sh --skip-tests   # build + publish without re-running pytest / ruff
#   ./scripts/publish.sh --skip-build   # don't rebuild; just upload whatever is in dist/
#
# Requirements (one-time):
#   uv tool install twine
#   export TWINE_USERNAME=__token__
#   export TWINE_PASSWORD=pypi-...your-api-token...
#   # Optional for npm step (else uses interactive npm login):
#   export NPM_TOKEN=npm_...your-automation-token...
#
# Tokens live at https://pypi.org/manage/account/token/  (PyPI)
# and  https://test.pypi.org/manage/account/token/  (TestPyPI).
# and  https://www.npmjs.com/settings/<user>/tokens           (npm).
# Use a per-project scoped token.

set -euo pipefail

# --- 0.  Argument parsing ---------------------------------------------
TEST_ONLY=0
SKIP_TESTS=0
SKIP_BUILD=0
for arg in "$@"; do
    case "$arg" in
        --test)         TEST_ONLY=1 ;;
        --skip-tests)   SKIP_TESTS=1 ;;
        --skip-build)   SKIP_BUILD=1 ;;
        -h|--help)
            grep -E '^#( |$)' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *)  echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# --- 1.  Pre-flight: clean + test + lint ---------------------------
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ "$SKIP_TESTS" -eq 0 ]; then
    echo "==> 1a. running pytest ..."
    .venv/bin/pytest -q

    echo "==> 1b. running ruff ..."
    .venv/bin/ruff check lorewiki skills tests
fi

# --- 2.  Build wheel + sdist ----------------------------------------
if [ "$SKIP_BUILD" -eq 0 ]; then
    echo "==> 2. cleaning dist/ + building wheel + sdist ..."
    rm -rf dist/ build/ lorewiki.egg-info/
    .venv/bin/python -m build
fi

if [ ! -f dist/lorewiki-*.whl ]; then
    echo "!!  dist/lorewiki-*.whl not found. Build first." >&2
    exit 2
fi

echo "==> contents of dist/:"
ls -lh dist/

# --- 3.  twine check (catches metadata errors before upload) -------
echo "==> 3. twine check ..."
.venv/bin/python -m twine check dist/*

# --- 4.  Upload to TestPyPI first (always; safety net) ------------
if [ -z "${TWINE_USERNAME:-}" ] || [ -z "${TWINE_PASSWORD:-}" ]; then
    echo "!!  TWINE_USERNAME and TWINE_PASSWORD must be exported" >&2
    echo "    export TWINE_USERNAME=__token__" >&2
    echo "    export TWINE_PASSWORD=pypi-...your-token..." >&2
    exit 2
fi

echo "==> 4. uploading to TestPyPI (https://test.pypi.org) ..."
.venv/bin/python -m twine upload \
    --repository testpypi \
    --skip-existing \
    dist/*

TESTPYPI_URL="https://test.pypi.org/project/lorewiki/"
echo "    verify on: $TESTPYPI_URL"
echo "    test install:  uvx --index https://test.pypi.org/simple/ lorewiki --help"

# --- 5.  Verify install from TestPyPI in a throwaway venv --------
echo "==> 5. verifying install in a clean venv ..."
VERIFY_DIR="$(mktemp -d)"
uv venv "$VERIFY_DIR/.venv" --python 3.12
UV="$VERIFY_DIR/.venv/bin/uv"
# Install from TestPyPI with PyPI as fallback for transitive deps
"$UV" pip install \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    lorewiki
echo "    installed:"
"$VERIFY_DIR/.venv/bin/lorewiki" --version
"$VERIFY_DIR/.venv/bin/lorewiki" --help | head -n 20
rm -rf "$VERIFY_DIR"

if [ "$TEST_ONLY" -eq 1 ]; then
    echo
    echo "==> --test flag set; skipping live PyPI upload."
    echo "    Manually run again without --test when ready."
    exit 0
fi

# --- 6.  Live PyPI upload (the real deal) ---------------------------
echo
echo "==> 6. uploading to LIVE PyPI (https://pypi.org) ..."
echo "    Press Ctrl-C within 5 seconds to abort."
sleep 5

.venv/bin/python -m twine upload dist/*

echo
echo "==> DONE. Verify on https://pypi.org/project/lorewiki/"
echo "    Recommended final-test from a fresh shell:"
echo "      uv tool install lorewiki"
echo "      lorewiki --version   # expect: LoreWiki 0.1.0"

# --- 7.  npm publish (the second distribution) ----------------------
# LoreWiki publishes to BOTH PyPI and npm. The npm package is a thin
# Node shim that calls `uv tool install lorewiki==<ver>` in its
# postinstall hook, so npm 0.1.0 must be published AFTER PyPI 0.1.0
# is live.
#
# Auth: run `npm login` once on this machine, or set NPM_TOKEN to
# an automation token from https://www.npmjs.com/settings/<user>/tokens
echo
echo "==> 7. publishing to npm registry (https://registry.npmjs.org) ..."
if ! command -v npm >/dev/null 2>&1; then
    echo "!!  npm not found on PATH; skipping npm publish." >&2
    echo "    Install Node.js >= 18 and re-run, or publish manually:" >&2
    echo "      npm login" >&2
    echo "      npm publish" >&2
    exit 0
fi

if ! npm whoami >/dev/null 2>&1; then
    if [ -z "${NPM_TOKEN:-}" ]; then
        echo "!!  npm publish skipped: not logged in and NPM_TOKEN not set." >&2
        echo "    Run \`npm login\` once, or export NPM_TOKEN=<automation-token>." >&2
        exit 0
    fi
    echo "    using NPM_TOKEN from env"
    echo "//registry.npmjs.org/:_authToken=${NPM_TOKEN}" > ~/.npmrc
fi

echo "    npm whoami: $(npm whoami)"
echo "    package version (from package.json): $(node -p 'require("./package.json").version')"

echo "==> 7a. npm pack dry-run (sanity check) ..."
npm pack --dry-run
echo

echo "==> 7b. publishing ... Press Ctrl-C within 5 seconds to abort."
sleep 5

npm publish --access public
NPM_EXIT=$?
if [ "$NPM_EXIT" -ne 0 ]; then
    echo "!!  npm publish exited with code $NPM_EXIT" >&2
    echo "    Common causes: name taken, version already published, or auth." >&2
    exit "$NPM_EXIT"
fi

echo
echo "==> 8. ALL DONE."
echo "    PyPI:  https://pypi.org/project/lorewiki/"
echo "    npm:   https://www.npmjs.com/package/lorewiki"
echo "    GitHub: https://github.com/JochenYang/Lore-wiki"
echo
echo "    Recommended final-test from a fresh shell:"
echo "      # Python user:"
echo "      uv tool install lorewiki"
echo "      lorewiki --version   # expect: LoreWiki 0.1.0"
echo
echo "      # Node user:"
echo "      npm install -g lorewiki"
echo "      lorewiki --version   # expect: LoreWiki 0.1.0 (after postinstall)"
