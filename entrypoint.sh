#!/usr/bin/env bash
set -euo pipefail

PORT_VALUE="${PORT:-8000}"
HOST_VALUE="${HOST:-0.0.0.0}"

exec /app/.venv/bin/uvicorn app.main:app --host "${HOST_VALUE}" --port "${PORT_VALUE}"
