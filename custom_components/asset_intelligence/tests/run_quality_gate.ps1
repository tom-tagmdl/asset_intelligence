$ErrorActionPreference = "Stop"

# Enforce a measurable quality gate and emit artifacts for review.
$CoverageFailUnder = 85
$ArtifactsDir = "tests\artifacts"

Push-Location "$PSScriptRoot\.."
try {
    if (!(Test-Path $ArtifactsDir)) {
        New-Item -ItemType Directory -Path $ArtifactsDir | Out-Null
    }

    cmd /c ".\.venv\Scripts\python.exe -m pip show pytest-cov >nul 2>nul"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Missing test dependency: pytest-cov. Install with '.\\.venv\\Scripts\\python.exe -m pip install pytest-cov'"
        exit 2
    }

    .\.venv\Scripts\python.exe -m pytest tests `
        --cov=custom_components\asset_intelligence `
        --cov-report=term-missing `
        --cov-report=xml:$ArtifactsDir\coverage.xml `
        --cov-report=html:$ArtifactsDir\htmlcov `
        --junitxml=$ArtifactsDir\pytest.xml `
        --cov-fail-under=$CoverageFailUnder

    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
