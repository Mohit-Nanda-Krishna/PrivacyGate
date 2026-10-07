$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/ and rerun this script."
}

Push-Location (Join-Path $PSScriptRoot "..")
try {
    Write-Host "Syncing Python 3.11 dependencies. uv may download Python if it is missing."
    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit $LASTEXITCODE)." }

    & uv run --locked python scripts/check_env.py
    if ($LASTEXITCODE -ne 0) { throw "Environment diagnostic failed (exit $LASTEXITCODE)." }

    Write-Host "Setup complete. Run: uv run streamlit run app.py"
    Write-Host "Run tests: uv run pytest"
    Write-Host "The pinned English spaCy model is included. System Tesseract is installed separately."
}
finally {
    Pop-Location
}
