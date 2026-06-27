param(
    [string]$Source = "R:\HomesPlatformRepos\asset_intelligence\custom_components\asset_intelligence",
    [string]$Destination = "H:\custom_components\asset_intelligence",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
    throw "Source path not found: $Source"
}

if (-not (Test-Path -LiteralPath (Split-Path -Path $Destination -Parent) -PathType Container)) {
    throw "Destination parent not found: $(Split-Path -Path $Destination -Parent)"
}

if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
    New-Item -ItemType Directory -Path $Destination | Out-Null
}

$robocopyArgs = @(
    $Source
    $Destination
    "/MIR"
    "/R:2"
    "/W:1"
    "/NFL"
    "/NDL"
    "/NP"
    "/XD"
    ".git"
    ".github"
    ".venv"
    "__pycache__"
    ".pytest_cache"
    ".mypy_cache"
    "tests"
    "docs"
    "/XF"
    "*.pyc"
)

if ($DryRun) {
    $robocopyArgs += "/L"
}

Write-Host "Syncing Asset Intelligence"
Write-Host "Source: $Source"
Write-Host "Destination: $Destination"
if ($DryRun) {
    Write-Host "Mode: DRY RUN"
}

& robocopy @robocopyArgs
$exitCode = $LASTEXITCODE

if ($exitCode -ge 8) {
    throw "Robocopy failed with exit code $exitCode"
}

Write-Host "Sync completed with robocopy exit code $exitCode"