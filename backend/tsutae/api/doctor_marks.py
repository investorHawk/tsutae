"""未処理の記載（D6）で、疑われた語の原文の中の位置（院内画面の `<mark>` 用）。

- 二次の検出（`masking.check_text`）は正規化＋一次（伏せ字）の**後の**文に掛かる。一次で
  長さが変わる（田中さん → ○○さん）ので、検出の位置はそのままでは原文に合わない。
  検出された区間の文字列（一次の置換を含まない部分）を原文から前から順に探し、見つかった
  原文の位置を返す。見つからない区間（改行の揃え・制御文字の削除をまたぐもの）は印を
  付けない（位置を推測しない）
- 二次で何も出ない記録（依頼文の JSON の形で初めて掛かったもの）は、JSON にした文の
  検出区間を同じく原文から探す（エスケープを含む区間は見つからず、印なし）
- `known_identifier`（この患者の仮名ID・受付番号が書かれている）は、その文字列を
  大文字小文字を区別せずに原文から探す（区切りの崩れた形 P_DEMO0001 は印なし）
- 位置は Python の str の位置（code point）で [start, end)。重なる区間はまとめる
- ログには何も残さない（文面も位置も）。返すのは院内画面の API だけ
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence

from tsutae.masking import check_text, detect_identifiers

__all__ = ["suspect_marks"]


def _locate(text: str, segments: Iterable[str]) -> list[tuple[int, int]]:
    """各区間の文字列を text から前から順に探す。見つからなければ先頭から探し直す。"""
    found: list[tuple[int, int]] = []
    cursor = 0
    for segment in segments:
        if not segment.strip():
            continue
        start = text.find(segment, cursor)
        if start < 0:
            start = text.find(segment)
        if start < 0:
            continue
        end = start + len(segment)
        found.append((start, end))
        cursor = end
    return found


def _detected_segments(text: str) -> list[str]:
    check = check_text(text)
    if check.detections:
        return [check.masked[d.start : d.end] for d in check.detections]
    if not check.masked.strip():
        return []
    in_prompt = json.dumps(check.masked, ensure_ascii=False)
    return [in_prompt[d.start : d.end] for d in detect_identifiers(in_prompt)]


def _literal_spans(text: str, literals: Sequence[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for literal in literals:
        cleaned = literal.strip()
        if not cleaned:
            continue
        pattern = re.compile(re.escape(cleaned), re.IGNORECASE)
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
    return spans


def _merge(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def suspect_marks(text: str, literals: Sequence[str]) -> list[dict[str, int]]:
    """原文 text の中の疑われた語の位置 `[{start, end}]`（位置順・重なりなし）。

    literals はこの患者の仮名ID・受付番号（known_identifier の印に使う）。
    """
    if not text:
        return []
    spans = _locate(text, _detected_segments(text)) + _literal_spans(text, literals)
    return [{"start": s, "end": e} for s, e in _merge(spans)]
