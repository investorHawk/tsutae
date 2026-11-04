"""二次 before_facility: 「病院／医院／クリニック／センター」の直前の語で「[病院]」に
なっていないもの。

一次（replace.py）とは別の規則にする。一次は活用語尾・助詞で終わるひらがな
（みらい・みなと・ひがし 等）を固有名とみなさないが、二次はそれらも候補にし、
許可語・助詞・活用の切れ目で説明できなければ検出する（迷ったら検出する）。

- 施設語・[病院] の前の空白・改行は飛ばす（「架空 病院」「架空\n病院」「みらい 病院」）。
  飛ばした中に改行があり、改行の前が明示の許可語の形容詞・副詞（とその活用）・助詞・
  活用の切れ目で終わるひらがな（だるい\n医院へ・やっと\n病院）のときだけ名前の候補に
  しない。通常の空白にはこの例外を使わない。語尾の形だけで推測しない（みらい\n病院は検出）
- 漢字・カタカナの直後のひらがな（架空こども・国立がん・東さくら）は、漢字・カタカナと
  合わせて1つの候補にする。送り仮名（大きな・新しい・行った・悪くなり 等）で
  説明できるものだけを通す
- [病院] の直前に漢字・カタカナが残っていれば、許可語（今日 等）でなければ検出する
"""

from __future__ import annotations

import re

from tsutae.masking.chars import (
    NON_NAME_FINAL_PARTICLES,
    PARTICLES,
    has_line_break,
    is_ascii_or_wide_alnum,
    is_hard_boundary,
    is_hiragana,
    is_kanji_or_katakana,
    run_start,
    skip_spaces_back,
)
from tsutae.masking.replace import HOSPITAL_MASK, ONE_CHAR_TIME_WORDS
from tsutae.masking.words import (
    CLAUSE_ENDINGS,
    allow_set,
    excused_before_line_break,
    explained_suffixes,
    is_allowed,
    kanji_run_explained,
)

_FACILITY_RE = re.compile("病院|医院|クリニック|センター")

# 漢字・カタカナの直後のひらがなが、まるごと送り仮名・活用語尾で説明できる形
_ADJ_STEM = "(?:[しきさかたなるろどわまら]|らか|やか|かし|ずかし|まし|らし|っぽ)"
_OKURIGANA_RE = re.compile(
    f"{_ADJ_STEM}?い"  # 新しい・大きい・遠い・少ない
    f"|{_ADJ_STEM}?かった"  # 近かった
    f"|{_ADJ_STEM}?く(?:な(?:い|く|り|る|った|って))?"  # 悪く・悪くなり
    "|(?:[きさか]|やか|らか|そう|よう|みたい)?な"  # 大きな・小さな・静かな
    "|[ぁ-ゖ]{0,6}[ただ]"  # 行った・入院した・紹介してもらった・休んだ
    "|[ぁ-ゖ]{0,3}[てで]い?る"  # 通っている・通ってる
    "|[えけせてねへめれべげぜでいきしちにひみりびぎじ]る"  # 食べる・見る・感じる
    "|[ぁ-ゖ]{0,3}(?:ない|ます|ず)"  # 行かない・通います・思わず
    "|[いん]で"  # 急いで・飛んで
    "|[ぁ-ゖ][でとも]"  # 痛みで・夜中も（名詞の後の助詞）
)


def _is_facility_name_char(ch: str) -> bool:
    return is_kanji_or_katakana(ch) or is_ascii_or_wide_alnum(ch)


def _inside_placeholder(text: str, m: re.Match[str]) -> bool:
    start = m.start() - 1
    return start >= 0 and text.startswith(HOSPITAL_MASK, start)


def _mixed_candidate_start(
    text: str, kana_start: int, end: int, tail: str, limit: int
) -> int | None:
    """漢字・カタカナ＋ひらがな（架空こども）を1つの候補にした開始位置（通すなら None）。"""
    k_start = run_start(text, kana_start, _is_facility_name_char, limit)
    kanji, kana = text[k_start:kana_start], text[kana_start:end]
    if k_start == kana_start or _OKURIGANA_RE.fullmatch(kana):
        return None
    if kanji in ONE_CHAR_TIME_WORDS or kanji_run_explained(kanji, 1):
        # 漢字の側は許可語（今日・母）。ひらがなの側だけを語の頭から見る
        return None if explained_suffixes(kana)[0] else kana_start
    return None if is_allowed(kanji + kana, tail) else k_start


def _kana_candidate_start(text: str, end: int, tail: str, limit: int) -> int | None:
    """施設語の直前のひらがなの語の開始位置（名前らしくなければ None）。

    候補は助詞の字の後ろ（右から。文頭・記号の直後の先頭2字以内の助詞の字は除く:
    やさしい・ことぶき）と、文頭・記号の後なら並びの頭。2字以上の最初の
    候補が許可語・助詞・活用の切れ目で説明できなければ検出する。漢字・カタカナの
    直後なら、それと合わせた並び全体を候補にする（_mixed_candidate_start）。
    """
    r0 = run_start(text, end, is_hiragana, limit)
    word = text[r0:end]
    if len(word) < 2 or word[-1] in NON_NAME_FINAL_PARTICLES:
        return None
    if word.endswith(CLAUSE_ENDINGS):
        return None
    hard = is_hard_boundary(text, r0, limit)
    if not hard and _OKURIGANA_RE.fullmatch(word):
        return None  # 漢字の送り仮名・活用語尾（紹介してもらった・痛みで）
    starts = [
        i + 1
        for i in range(len(word) - 1, -1, -1)
        if word[i] in PARTICLES and not (hard and i <= 1)
    ]
    if hard:
        starts.append(0)
    explained = explained_suffixes(word)
    for s in starts:
        if len(word) - s >= 2:
            return None if explained[s] else r0 + s
    if hard:
        return None
    return _mixed_candidate_start(text, r0, end, tail, limit)


def _candidate_start(text: str, end: int, tail: str, limit: int) -> int | None:
    """施設語（tail）・[病院] の直前（end まで）の候補の開始位置（通すなら None）。"""
    start = run_start(text, end, _is_facility_name_char, limit)
    if start == end:
        return _kana_candidate_start(text, end, tail, limit)
    candidate = text[start:end]
    if tail and candidate + tail in allow_set():
        # 施設の種類（医療センター・保健センター）。その前のひらがな（国立がん）を見る
        return _kana_candidate_start(text, start, candidate + tail, limit)
    if candidate in ONE_CHAR_TIME_WORDS or is_allowed(candidate, tail):
        return None
    return start


def _excused_gap(text: str, before: int, tail_start: int, limit: int) -> bool:
    """飛ばした空白（before〜tail_start）が改行を含み、その前が許可語等で終わるか。"""
    if not has_line_break(text, before, tail_start):
        return False
    word = text[run_start(text, before, is_hiragana, limit) : before]
    return excused_before_line_break(word)


def facility_spans(text: str) -> list[tuple[int, int]]:
    """before_facility の (開始, 終わり) の一覧。"""
    found = []
    limit = 0
    for m in _FACILITY_RE.finditer(text):
        if _inside_placeholder(text, m):
            # 一次の [病院] の前に名前の一部が残った形（母とこと[病院]・架空[病院]）
            tail_start, tail = m.start() - 1, ""
            end = tail_start + len(HOSPITAL_MASK)
        else:
            tail_start, tail, end = m.start(), m.group(0), m.end()
        before = skip_spaces_back(text, tail_start, limit)
        start = (
            None
            if _excused_gap(text, before, tail_start, limit)
            else _candidate_start(text, before, tail, limit)
        )
        limit = end
        if start is not None:
            found.append((start, end))
    return found
