"""README の「テスト件数」行を JUnit XML から更新する（scripts/test.sh が呼ぶ）。"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"
ROW = re.compile(r"^\| テスト件数 \|.*\|$", re.MULTILINE)


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


def main(argv: list[str]) -> int:
    py_ok, py_total = count(Path(argv[1])) if len(argv) > 1 else (0, 0)
    fe_ok, fe_total = count(Path(argv[2])) if len(argv) > 2 else (0, 0)
    row = (
        f"| テスト件数 | {py_ok + fe_ok}件 通過 / 全{py_total + fe_total}件"
        f"（backend {py_ok}/{py_total}、frontend {fe_ok}/{fe_total}。"
        f"`make test` が自動更新。API を呼ぶテストはキーが無いと skip） |"
    )
    text = README.read_text(encoding="utf-8")
    if not ROW.search(text):
        print("README にテスト件数の行が見つからない", file=sys.stderr)
        return 1
    README.write_text(ROW.sub(row, text, count=1), encoding="utf-8")
    print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
