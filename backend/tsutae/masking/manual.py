"""医師の伏せ字（未処理の記載 D6 で医師が選んだ区間）と、確かめた語の許可。

- 医師は文を書かない。原文（生の自由記載）の中の区間 [start, end) だけを選ぶ。位置は
  Python の str の位置（code point。D6 の marks と同じ単位）
- `validate_spans`: 範囲内・空でない・昇順・重ならない（隣り合うのはよい）・個数の上限。
  合わなければ ManualSpanError（位置も文面も例外の本文に入れない）
- `apply_spans`: 各区間を `[伏せ字]`（GENERIC_MASK）1つに置き換えた新しい文を返す。
  区間の外の文字は変えない。原文の中身を変える手段はこれだけ（伏せることしかできない）。
  区間は原文の位置なので、正規化・一次（check_text）の**前に**当てる
- `without_allowed`: 「個人を特定する語は無いことを確かめた」記録で、許した部分文字列の
  出現に**完全に含まれる**検出だけを除く。許す一覧が空なら検出をそのまま返す（H1 の
  振る舞いは今と同じ）。はみ出す検出は残す（止める側に倒す）
- `prompt_form`: 依頼文（`json.dumps(..., ensure_ascii=False)`）の中での文字列の見え方。
  H1 は依頼文全体に掛かるので、許す語もこの形で探す
- `detect_in_prompt`: 依頼文全体の二次（detect_identifiers）から、許す語（prompt_form に
  直して探す）に完全に含まれる検出を除く。許す一覧が空なら detect_identifiers そのもの

伏せた後の `[伏せ字]さん` 等は二次検出に掛からない（`[` `]` の後の敬称は「敬称の前の
未知語」にならない。tests/test_masking_manual.py で固定）。
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence

from tsutae.masking.detect import Detection, detect_identifiers
from tsutae.masking.replace import GENERIC_MASK

__all__ = [
    "MAX_SPANS",
    "ManualSpanError",
    "Span",
    "apply_spans",
    "detect_in_prompt",
    "prompt_form",
    "validate_spans",
    "without_allowed",
]

Span = tuple[int, int]
# 1つの記録に選べる区間の上限（自由記載の上限より十分大きい）
MAX_SPANS = 200


class ManualSpanError(ValueError):
    """区間が原文に合わない（範囲の外・空・逆順・重なり・多すぎる）。"""


def _is_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_spans(text: str, spans: Sequence[Span]) -> tuple[Span, ...]:
    """区間を検査して tuple で返す（引数は書き換えない）。合わなければ ManualSpanError。"""
    if not isinstance(text, str):
        raise TypeError("text は str")
    if len(spans) > MAX_SPANS:
        raise ManualSpanError("区間が多すぎる")
    checked: list[Span] = []
    cursor = 0
    for span in spans:
        start, end = span
        if not (_is_index(start) and _is_index(end)):
            raise ManualSpanError("区間の位置が整数でない")
        if start < cursor or end <= start or end > len(text):
            raise ManualSpanError("区間が範囲の外・空・逆順・重なり")
        checked.append((start, end))
        cursor = end
    return tuple(checked)


def apply_spans(text: str, spans: Sequence[Span]) -> str:
    """各区間を `[伏せ字]` に置き換えた新しい文。区間は validate_spans で検査する。"""
    pieces: list[str] = []
    cursor = 0
    for start, end in validate_spans(text, spans):
        pieces.append(text[cursor:start])
        pieces.append(GENERIC_MASK)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def prompt_form(text: str) -> str:
    """依頼文（JSON。ensure_ascii=False）の文字列の中での見え方（前後の引用符を除く）。"""
    return json.dumps(text, ensure_ascii=False)[1:-1]


def _occurrences(text: str, needle: str) -> list[Span]:
    found: list[Span] = []
    start = text.find(needle)
    while start >= 0:
        found.append((start, start + len(needle)))
        start = text.find(needle, start + 1)
    return found


def without_allowed(
    text: str, detections: Sequence[Detection], allowed: Collection[str]
) -> list[Detection]:
    """許した部分文字列の出現に完全に含まれる検出を除いた新しい list。

    allowed が空（空白だけの語も数えない）なら detections をそのまま list にして返す。
    """
    needles = [a for a in allowed if isinstance(a, str) and a.strip()]
    if not needles:
        return list(detections)
    covers = [span for n in needles for span in _occurrences(text, n)]
    return [
        d for d in detections if not any(s <= d.start and d.end <= e for s, e in covers)
    ]


def detect_in_prompt(prompt: str, allowed: Collection[str] = ()) -> list[Detection]:
    """依頼文全体の二次検出から、確かめて許した語に含まれる検出を除いたもの。

    allowed が空なら `detect_identifiers(prompt)` をそのまま返す（H1 は今と同じ）。
    """
    found = detect_identifiers(prompt)
    if not allowed:
        return found
    return without_allowed(prompt, found, [prompt_form(a) for a in allowed])
