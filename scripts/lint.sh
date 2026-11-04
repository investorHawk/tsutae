#!/usr/bin/env bash
# lint: ruff + black --check（backend, scripts）と prettier --check（frontend）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
.venv/bin/ruff check backend scripts
.venv/bin/black --check --quiet backend scripts
if [ -d frontend/src ]; then
  (cd frontend && npx prettier --check "src/**/*.{ts,tsx,css}")
fi
