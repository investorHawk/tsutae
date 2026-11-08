"""README の「テスト件数」行を JUnit XML から更新する（scripts/test.sh が呼ぶ）。

日本語版（README.md）と英語版（README.en.md）の両方を同じ数で書き換える。
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_JA = ROOT / "README.md"
README_EN = ROOT / "README.en.md"
ROW_JA = re.compile(r"^\| テスト件数 \|.*\|$", re.MULTILINE)
ROW_EN = re.compile(r"^\| Test count \|.*\|$", re.MULTILINE)


def count(path: Path) -> tuple[int, int]:
    """(通った件数, 全件数)。ファイルが無ければ (0, 0)。"""
    if not path.exists():
        return 0, 0
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = failed = skipped = 0
    for s in suites:
        total += int(s.get("tests", 0))
        failed += int(s.get("failures", 0)) + int(s.get("errors", 0))
        skipped += int(s.get("skipped", 0))
    return total - failed - skipped, total


def rows(py: tuple[int, int], fe: tuple[int, int]) -> tuple[str, str]:
    """(日本語の行, 英語の行)。"""
    (py_ok, py_total), (fe_ok, fe_total) = py, fe
    ok, total = py_ok + fe_ok, py_total + fe_total
    ja = (
        f"| テスト件数 | {ok}件 通過 / 全{total}件"
        f"（backend {py_ok}/{py_total}、frontend {fe_ok}/{fe_total}。"
        f"`make test` が自動更新。API を呼ぶテストはキーが無いと skip） |"
    )
    en = (
        f"| Test count | {ok} passed / {total} total"
        f" (backend {py_ok}/{py_total}, frontend {fe_ok}/{fe_total}."
        f" Updated automatically by `make test`."
        f" Tests that call the API are skipped without a key) |"
    )
    return ja, en


def replace_row(path: Path, pattern: re.Pattern[str], row: str) -> bool:
    """path の該当行を row に置き換える。行が無ければ False（ファイルは変えない）。"""
    text = path.read_text(encoding="utf-8")
    if not pattern.search(text):
        print(f"{path.name} にテスト件数の行が見つからない", file=sys.stderr)
        return False
    path.write_text(pattern.sub(lambda _: row, text, count=1), encoding="utf-8")
    return True


def main(argv: list[str]) -> int:
    py = count(Path(argv[1])) if len(argv) > 1 else (0, 0)
    fe = count(Path(argv[2])) if len(argv) > 2 else (0, 0)
    ja, en = rows(py, fe)
    ok_ja = replace_row(README_JA, ROW_JA, ja)
    ok_en = replace_row(README_EN, ROW_EN, en)
    print(ja)
    print(en)
    return 0 if ok_ja and ok_en else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
