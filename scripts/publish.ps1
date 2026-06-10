# Publish lorewiki to PyPI (or TestPyPI first for a dry run).
#
# Usage:
#   .\scripts\publish.ps1                 # full: tests -> build -> TestPyPI -> verify -> PyPI -> npm
#   .\scripts\publish.ps1 -Test           # only upload to TestPyPI, skip the live push
#   .\scripts\publish.ps1 -SkipTests      # build + publish without re-running pytest / ruff
#   .\scripts\publish.ps1 -SkipBuild      # don't rebuild; just upload whatever is in dist/
#
# Requirements (one-time):
#   uv tool install twine
#   $env:TWINE_USERNAME = "__token__"
#   $env:TWINE_PASSWORD = "pypi-...your-api-token..."
#   # Optional for npm step (else uses interactive npm login):
#   $env:NPM_TOKEN = "npm_...your-automation-token..."
#
# Tokens live at https://pypi.org/manage/account/token/  (PyPI)
# and  https://test.pypi.org/manage/account/token/  (TestPyPI).
# and  https://www.npmjs.com/settings/<user>/tokens           (npm).
# Use a per-project scoped token.

[CmdletBinding()]
param(
    [switch]$Test,
    [switch]$SkipTests,
    [switch]$SkipBuild,
    [switch]$Help
)

if ($Help) {
    Get-Content "$PSScriptRoot\publish.ps1" |
        Select-String -Pattern '^#( |$)' |
        ForEach-Object { $_.Line -replace '^# \?', '' }
    return
}

$ErrorActionPreference = "Stop"

# --- 0.  Resolve repo root -----------------------------------------
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    throw "Python venv not found at $Py. Run: uv venv .venv ; uv pip install -e '.[dev]'"
}

# --- 1.  Pre-flight: test + lint -----------------------------------
if (-not $SkipTests) {
    Write-Host "==> 1a. running pytest ..." -ForegroundColor Cyan
    & (Join-Path $RepoRoot ".venv\Scripts\pytest.exe") -q
    if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

    Write-Host "==> 1b. running ruff ..." -ForegroundColor Cyan
    & (Join-Path $RepoRoot ".venv\Scripts\ruff.exe") check lorewiki skills tests
    if ($LASTEXITCODE -ne 0) { throw "ruff failed" }
}

# --- 2.  Build wheel + sdist ---------------------------------------
if (-not $SkipBuild) {
    Write-Host "==> 2. cleaning dist/ + building wheel + sdist ..." -ForegroundColor Cyan
    Remove-Item -LiteralPath (Join-Path $RepoRoot "dist") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $RepoRoot "build") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $RepoRoot "lorewiki.egg-info") -Recurse -Force -ErrorAction SilentlyContinue
    & $Py -m build
    if ($LASTEXITCODE -ne 0) { throw "build failed" }
}

$whl = Get-ChildItem -LiteralPath (Join-Path $RepoRoot "dist") -Filter "*.whl" -ErrorAction SilentlyContinue
if (-not $whl) {
    throw "dist/*.whl not found. Build first."
}

Write-Host "==> contents of dist/:" -ForegroundColor Cyan
Get-ChildItem -LiteralPath (Join-Path $RepoRoot "dist") | Format-Table Name, Length

# --- 3.  twine check ----------------------------------------------
Write-Host "==> 3. twine check ..." -ForegroundColor Cyan
& $Py -m twine check (Join-Path $RepoRoot "dist\*")
if ($LASTEXITCODE -ne 0) { throw "twine check failed" }

# --- 4.  Upload to TestPyPI (always) -----------------------------
if (-not $env:TWINE_USERNAME -or -not $env:TWINE_PASSWORD) {
    throw "TWINE_USERNAME and TWINE_PASSWORD must be set. Example:`n  `$env:TWINE_USERNAME = '__token__'`n  `$env:TWINE_PASSWORD = 'pypi-...'"
}

Write-Host "==> 4. uploading to TestPyPI (https://test.pypi.org) ..." -ForegroundColor Cyan
& $Py -m twine upload --repository testpypi --skip-existing (Join-Path $RepoRoot "dist\*")
if ($LASTEXITCODE -ne 0) { throw "TestPyPI upload failed" }

Write-Host "    verify on: https://test.pypi.org/project/lorewiki/" -ForegroundColor Green
Write-Host "    test install: uvx --index https://test.pypi.org/simple/ lorewiki --help" -ForegroundColor Green

# --- 5.  Verify install from TestPyPI in throwaway venv ----------
Write-Host "==> 5. verifying install in a clean venv ..." -ForegroundColor Cyan
$VerifyDir = Join-Path $env:TEMP "lorewiki-verify-$([guid]::NewGuid().ToString('N').Substring(0,8))"
uv venv "$VerifyDir\.venv" --python 3.12
& "$VerifyDir\.venv\Scripts\python.exe" -m pip install `
    --index-url https://test.pypi.org/simple/ `
    --extra-index-url https://pypi.org/simple/ `
    lorewiki
if ($LASTEXITCODE -ne 0) { throw "verify install failed" }
& "$VerifyDir\.venv\Scripts\lorewiki.exe" --version
& "$VerifyDir\.venv\Scripts\lorewiki.exe" --help | Select-Object -First 20
Remove-Item -LiteralPath $VerifyDir -Recurse -Force

if ($Test) {
    Write-Host ""
    Write-Host "==> -Test flag set; skipping live PyPI upload." -ForegroundColor Yellow
    Write-Host "    Re-run without -Test when ready." -ForegroundColor Yellow
    return
}

# --- 6.  Live PyPI upload (the real deal) -------------------------
Write-Host ""
Write-Host "==> 6. uploading to LIVE PyPI (https://pypi.org) ..." -ForegroundColor Cyan
Write-Host "    Press Ctrl-C within 5 seconds to abort." -ForegroundColor Yellow
Start-Sleep -Seconds 5

& $Py -m twine upload (Join-Path $RepoRoot "dist\*")
if ($LASTEXITCODE -ne 0) { throw "PyPI upload failed" }

Write-Host ""
Write-Host "==> DONE. Verify on https://pypi.org/project/lorewiki/" -ForegroundColor Green
Write-Host "    Recommended final-test from a fresh shell:" -ForegroundColor Green
Write-Host "      uv tool install lorewiki" -ForegroundColor Green
Write-Host "      lorewiki --version   # expect: LoreWiki 0.1.0" -ForegroundColor Green

# --- 7.  npm publish (the second distribution) ----------------------
# LoreWiki publishes to BOTH PyPI and npm. The npm package is a thin
# Node shim that calls `uv tool install lorewiki==<ver>` in its
# postinstall hook, so npm 0.1.0 must be published AFTER PyPI 0.1.0
# is live.
#
# Auth: run `npm login` once on this machine, or set NPM_TOKEN to
# an automation token from https://www.npmjs.com/settings/<user>/tokens
Write-Host ""
Write-Host "==> 7. publishing to npm registry (https://registry.npmjs.org) ..." -ForegroundColor Cyan

$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    Write-Warning "npm not found on PATH; skipping npm publish."
    Write-Host "    Install Node.js >= 18 and re-run, or publish manually:" -ForegroundColor Yellow
    Write-Host "      npm login" -ForegroundColor Yellow
    Write-Host "      npm publish" -ForegroundColor Yellow
    return
}

if (-not (npm whoami 2>$null)) {
    if (-not $env:NPM_TOKEN) {
        Write-Warning "npm publish skipped: not logged in and NPM_TOKEN not set."
        Write-Host "    Run 'npm login' once, or set `$env:NPM_TOKEN = '<automation-token>'." -ForegroundColor Yellow
        return
    }
    Write-Host "    using NPM_TOKEN from env" -ForegroundColor Green
    "//registry.npmjs.org/:_authToken=$($env:NPM_TOKEN)" |
        Out-File -LiteralPath "$env:USERPROFILE\.npmrc" -Encoding ascii
}

$who = npm whoami 2>$null
Write-Host "    npm whoami: $who" -ForegroundColor Green
$pkgVer = node -p 'require("./package.json").version' 2>$null
Write-Host "    package version (from package.json): $pkgVer" -ForegroundColor Green

Write-Host "==> 7a. npm pack dry-run (sanity check) ..." -ForegroundColor Cyan
npm pack --dry-run
Write-Host ""

Write-Host "==> 7b. publishing ... Press Ctrl-C within 5 seconds to abort." -ForegroundColor Yellow
Start-Sleep -Seconds 5

npm publish --access public
if ($LASTEXITCODE -ne 0) {
    throw "npm publish failed (exit $LASTEXITCODE). Common causes: name taken, version already published, or auth."
}

Write-Host ""
Write-Host "==> 8. ALL DONE." -ForegroundColor Green
Write-Host "    PyPI:  https://pypi.org/project/lorewiki/" -ForegroundColor Green
Write-Host "    npm:   https://www.npmjs.com/package/lorewiki" -ForegroundColor Green
Write-Host "    GitHub: https://github.com/JochenYang/Lore-wiki" -ForegroundColor Green
Write-Host ""
Write-Host "    Recommended final-test from a fresh shell:" -ForegroundColor Green
Write-Host "      # Python user:" -ForegroundColor Green
Write-Host "      uv tool install lorewiki" -ForegroundColor Green
Write-Host "      lorewiki --version   # expect: LoreWiki 0.1.0" -ForegroundColor Green
Write-Host ""
Write-Host "      # Node user:" -ForegroundColor Green
Write-Host "      npm install -g lorewiki" -ForegroundColor Green
Write-Host "      lorewiki --version   # expect: LoreWiki 0.1.0 (after postinstall)" -ForegroundColor Green
