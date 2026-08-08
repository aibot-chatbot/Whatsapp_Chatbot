[CmdletBinding()]
param(
    [string]$Remote = "origin",
    [string]$Branch = "",
    [switch]$SkipGitUpdate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not $SkipGitUpdate) {
    & (Join-Path $repoRoot "scripts\sync-from-github.ps1") -Remote $Remote -Branch $Branch
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment was not found at '$python'. Create .venv and install requirements first."
}

Push-Location $repoRoot
try {
    # This console runs a GBK codepage, so the emoji in run.py's banner would
    # raise UnicodeEncodeError and kill the app on startup.
    $env:PYTHONIOENCODING = "utf-8"
    & $python "run.py"
    if ($LASTEXITCODE -ne 0) {
        throw "The application exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
