"""患者の文の正規化（check_text が最初に掛ける）。architecture.md §5 W2b の決定。

- 改行（CRLF・CR・U+2028・U+2029）→ `\\n`（改行は残す。引用は改行を含みうる）
- タブ → 空白1字
- それ以外の制御文字（Unicode の Cc。U+0085 も含む）と書式文字（Cf: U+200B・U+00AD・
  U+FEFF・U+2060 等）→ 削除（ゼロ幅の字で姓を割って二次をすり抜けるのを防ぐ）
"""

from __future__ import annotations

import re
import unicodedata

_LINE_BREAK_RE = re.compile("\r\n|[\r  ]")


def _keep(ch: str) -> bool:
    if ch in "\n ":
        return True
    return unicodedata.category(ch) not in ("Cc", "Cf")


def normalize_text(text: str) -> str:
    """改行を `\\n` に、タブを空白に揃え、他の制御文字・書式文字を消した文を返す。"""
    if not isinstance(text, str):
        raise TypeError("normalize_text は str だけを受け付ける")
    unified = _LINE_BREAK_RE.sub("\n", text).replace("\t", " ")
    return "".join(ch for ch in unified if _keep(ch))
