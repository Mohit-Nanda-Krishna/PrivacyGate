#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/ and rerun this script." >&2
    exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."
echo "Syncing Python 3.11 dependencies. uv may download Python if it is missing."
uv sync --locked
uv run --locked python scripts/check_env.py
echo "Setup complete. Run: uv run streamlit run app.py"
echo "Run tests: uv run pytest"
echo "Tesseract and spaCy language models are not installed by this script."
