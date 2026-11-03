#!/usr/bin/env bash
# テストを走らせる。引数なし = 全件（backend + frontend）と README のテスト件数更新。
# 引数あり = pytest にそのまま渡す（例: scripts/test.sh backend/tests/test_course.py）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${TMPDIR:-/tmp}/tsutae-test"
mkdir -p "$OUT"

PYTEST=(.venv/bin/pytest -c backend/pytest.ini --rootdir backend)

if [ "$#" -gt 0 ]; then
  exec "${PYTEST[@]}" "$@"
fi

"${PYTEST[@]}" backend/tests --junitxml="$OUT/pytest.xml"
if [ -f frontend/vitest.config.ts ] || [ -f frontend/vite.config.ts ]; then
  (cd frontend && npx vitest run --reporter=default --reporter=junit --outputFile.junit="$OUT/vitest.xml")
fi
.venv/bin/python scripts/update_readme_count.py "$OUT/pytest.xml" "$OUT/vitest.xml"
