#!/usr/bin/env bash
set -euo pipefail

PORT_VALUE="${PORT:-8000}"
HOST_VALUE="${HOST:-0.0.0.0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOTENV_FILE="${SCRIPT_DIR}/.env"
if [ -f "${DOTENV_FILE}" ]; then
  set -a
  # shellcheck source=/dev/null
  . "${DOTENV_FILE}"
  set +a
fi

exec /app/.venv/bin/uvicorn app.main:app --host "${HOST_VALUE}" --port "${PORT_VALUE}"
