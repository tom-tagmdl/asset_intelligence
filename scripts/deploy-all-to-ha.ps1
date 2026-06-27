param(
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$assetScript = "R:\HomesPlatformRepos\asset_intelligence\scripts\deploy-to-ha.ps1"
$conciergeScript = "R:\HomesPlatformRepos\concierge\scripts\deploy-to-ha.ps1"

if (-not (Test-Path -LiteralPath $assetScript -PathType Leaf)) {
    throw "Asset deploy script not found: $assetScript"
}

if (-not (Test-Path -LiteralPath $conciergeScript -PathType Leaf)) {
    throw "Concierge deploy script not found: $conciergeScript"
}

$params = @{}
if ($DryRun) {
    $params["DryRun"] = $true
}

Write-Host "Starting Deploy-All"
& $assetScript @params
& $conciergeScript @params
Write-Host "Deploy-All completed"