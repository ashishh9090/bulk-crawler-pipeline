#!/usr/bin/env bash
# ==============================================================================
# Bulk Data Acquisition Pipeline - Automated Runner & Validator
# ==============================================================================
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=== 1. Activating Virtual Environment ==="
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Virtual environment .venv not found. Creating..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
fi

echo "=== 2. Running Automated Test Suite (pytest) ==="
pytest -v tests/

echo ""
echo "=== 3. Running Data Inspection Utility ==="
python inspect_data.py

echo ""
echo "=== 4. Ready! Run './main.py --help' or 'python -m crawler.pipeline --help' for CLI options ==="
