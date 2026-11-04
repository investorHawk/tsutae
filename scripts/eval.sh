#!/usr/bin/env bash
# 精度評価（Anthropic API を呼ぶ）。先生が `! make eval` で実行する。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec .venv/bin/python -m tsutae.eval.run "$@"
