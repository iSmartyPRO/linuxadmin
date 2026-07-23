#!/usr/bin/env bash
# Prefer: make dev-frontend
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/src/frontend"
exec npm run dev -- --host 127.0.0.1 --port 5173 "$@"
