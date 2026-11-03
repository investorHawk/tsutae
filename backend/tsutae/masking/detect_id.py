"""二次 id_like: 英字1〜2字＋ハイフン類＋英数字3字以上（受付番号 A-023、仮名ID の
取り残し P-DEMO0001X 等）。architecture.md §5 W2b の決定。

ハイフン類の前後の空白・改行（Unicode の空白。NBSP・全角空白を含む）は何字でも許す
（「P - DEMO0001」「A -\n023」）。依頼文の JSON では改行が `\n` の2字になるが、
detect_identifiers がそれを改行＋空白とみなしてから掛けるので同じく拾える。

一次（replace.py の ID_RE）はちょうどの形の仮名ID だけを「[ID]」にする。こちらは
形が崩れたものや受付番号も拾う。英字が3字以上（regimen-folfox・HER-2）、後ろが2字以下
（PD-L1・S-1）、数字で始まる（5-FU・CA19-9）ものは対象外。
"""

from __future__ import annotations

import re

_LETTER = "A-Za-zＡ-Ｚａ-ｚ"
_ALNUM = "A-Za-z0-9Ａ-Ｚａ-ｚ０-９"
_HYPHEN = "\\-‐‑‒–—―−－ー"

# 空白とハイフン類・英数字は重ならないので、\s* を足しても総当たりにならない
ID_LIKE_RE = re.compile(
    rf"(?<![{_ALNUM}])[{_LETTER}]{{1,2}}\s*[{_HYPHEN}]\s*[{_ALNUM}]{{3,}}(?![{_ALNUM}])"
)


def id_like_spans(text: str) -> list[tuple[int, int]]:
    """id_like の (開始, 終わり) の一覧。"""
    return [(m.start(), m.end()) for m in ID_LIKE_RE.finditer(text)]
