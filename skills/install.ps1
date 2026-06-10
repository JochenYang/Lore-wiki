#!/usr/bin/env pwsh
# Thin wrapper for the cross-platform Python installer.
#
# Prefer running install.py directly:
#   python skills/install.py --all
#
# This wrapper exists so the existing Windows command (``.\skills\install.ps1``)
# keeps working while the canonical implementation lives in one place.

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PyArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Installer = Join-Path $RepoRoot "skills\install.py"

if (-not (Test-Path -LiteralPath $Installer)) {
    Write-Error "Installer not found at $Installer"
    exit 1
}

$py = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $py) {
    $py = (Get-Command python3 -ErrorAction SilentlyContinue)?.Source
}
if (-not $py) {
    Write-Error "python not found on PATH. Install Python 3.10+ and retry."
    exit 1
}

& $py $Installer @PyArgs
exit $LASTEXITCODE
