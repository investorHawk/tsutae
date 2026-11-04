#!/usr/bin/env bash
# 整形: ruff --fix + black（backend, scripts）と prettier --write（frontend）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
.venv/bin/ruff check --fix --quiet backend scripts || true
.venv/bin/black --quiet backend scripts
if [ -d frontend/src ]; then
  (cd frontend && npx prettier --write --log-level warn "src/**/*.{ts,tsx,css}")
fi
