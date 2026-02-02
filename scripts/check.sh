#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running backend checks..."
python -m compileall app
python -m pytest
