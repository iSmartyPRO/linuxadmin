#!/usr/bin/env bash
# Prefer: make run / make dev-backend
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/src/backend"
export PYTHONPATH=.
BIND_HOST="${LNXADMIN_BIND_HOST:-127.0.0.1}"
BIND_PORT="${LNXADMIN_BIND_PORT:-8000}"
exec .venv/bin/uvicorn app.main:app --host "$BIND_HOST" --port "$BIND_PORT" "$@"
