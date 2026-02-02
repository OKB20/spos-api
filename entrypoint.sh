#!/usr/bin/env bash
set -euo pipefail

PORT_VALUE="${PORT:-8000}"

exec /app/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT_VALUE}"
