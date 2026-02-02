#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Linting python files (syntax check)..."
python -m compileall app
