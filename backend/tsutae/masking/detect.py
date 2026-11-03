"""二次の検出。一次（replace.py）の**後の**文に掛け、伏せ字漏れの候補を見つける。

一次とは別の、より厳しい規則（同じ規則だと二次が永遠に発火しない）:

- unknown_before_honorific: 敬称の直前の語（2字以上）が「○○」でも許可語でもない
  （一次は辞書の姓だけを伏せる。辞書にない姓はここで拾う）
- long_digits: 7桁以上の数字列（区切り記号を除いて数える。日付・時刻は対象外）
  （一次は 0 始まり 10〜11 桁の電話番号だけを伏せる）
- at_mark: `@`・全角`＠`（一次はメールアドレスの形のものだけを伏せる）
- before_facility: 「病院／医院／クリニック／センター」の直前の語で「[病院]」に
  なっていないもの（一次は「医療センター」だけで、他の「〜センター」は伏せない）

Detection は位置と規則名だけを持つ（文面は持たない。ログにも文面を残さない）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tsutae.masking.replace import (
    PARTICLES,
    hiragana_name_start,
    is_allowed,
    is_ascii_or_wide_alnum,
    is_hiragana,
    is_japanese,
    is_kanji_or_katakana,
    run_start,
)

RULE_UNKNOWN_BEFORE_HONORIFIC = "unknown_before_honorific"
RULE_LONG_DIGITS = "long_digits"
RULE_AT_MARK = "at_mark"
RULE_BEFORE_FACILITY = "before_facility"
RULES = (
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    RULE_LONG_DIGITS,
    RULE_AT_MARK,
    RULE_BEFORE_FACILITY,
)

MIN_DIGITS = 7


@dataclass(frozen=True)
class Detection:
    rule: str
    start: int
    end: int


# ---------------------------------------------------------------------------
# unknown_before_honorific
# ---------------------------------------------------------------------------

# 敬称の候補。同様・模様の「様」、様子、さんぽ・さんざん、「行くんです」の「くん」は除く
_HONORIFIC_RE = re.compile(
    "(?<![同模多異仕一各左])様(?![子々])|さん(?!ぽ|ざん)|先生"
    "|くん(?!です|だ|で|じゃ|でしょ|か(?!ら))|ちゃん"
)
# 漢字・カタカナ・ひらがなが混ざった語（まり子さん・さくらちゃん）を見る敬称
_MIXED_HONORIFICS = ("さん", "ちゃん")
# 先生・様は漢字・カタカナだけを見る。くん・「ちゃんと」は助詞の後のひらがなも見る
_KANA_SEGMENT_HONORIFICS = ("くん", "ちゃんと")


def _kana_segment_start(text: str, end: int, limit: int) -> int | None:
    """助詞の後ろの独立したひらがな（孫のゆうくん）の開始位置。送り仮名なら None。"""
    start = run_start(text, end, is_hiragana, limit)
    cut = max(text.rfind(p, start, end) for p in PARTICLES)
    if cut >= 0:
        start = cut + 1
    elif start > limit and is_kanji_or_katakana(text[start - 1]):
        return None  # 「続いてくん…」のような活用の一部
    return start if end - start >= 2 else None


def _honorific_candidate_start(text: str, m: re.Match[str], limit: int) -> int:
    """敬称の直前の語の開始位置。前の敬称（limit）より前へは戻らない。"""
    honorific = m.group(0)
    if text.startswith("ちゃんと", m.start()):
        honorific = "ちゃんと"
    if honorific in _MIXED_HONORIFICS:
        return run_start(text, m.start(), is_japanese, limit)
    if honorific in _KANA_SEGMENT_HONORIFICS:
        kana_start = _kana_segment_start(text, m.start(), limit)
        if kana_start is not None:
            return kana_start
    return run_start(text, m.start(), is_kanji_or_katakana, limit)


def _honorific_detections(text: str) -> list[Detection]:
    found = []
    prev_end = 0
    for m in _HONORIFIC_RE.finditer(text):
        start = _honorific_candidate_start(text, m, prev_end)
        prev_end = m.end()
        candidate = text[start : m.start()]
        if len(candidate) < 2 or is_allowed(candidate, m.group(0)):
            continue
        span_start = start + _after_last_particle(candidate)
        found.append(Detection(RULE_UNKNOWN_BEFORE_HONORIFIC, span_start, m.end()))
    return found


def _after_last_particle(candidate: str) -> int:
    """報告する位置を助詞の後ろからにする（「母とさくらちゃん」→「さくらちゃん」）。"""
    cut = max(candidate.rfind(p) for p in PARTICLES)
    return cut + 1 if 0 <= cut < len(candidate) - 1 else 0


# ---------------------------------------------------------------------------
# long_digits
# ---------------------------------------------------------------------------

_D = "[0-9０-９]"
_DIGIT_CHARS = frozenset("0123456789０１２３４５６７８９")
_SEP = "[\\-‐‑‒–—―−－ー ()（）　]"
_DIGIT_RUN_RE = re.compile(f"{_D}+(?:{_SEP}{{1,3}}{_D}+)*")
# 数える前に伏せる日付・時刻（同じ長さの別の文字に置き換え、位置はずらさない）
_DATE_TIME_RES = (
    re.compile(
        f"(?:19|20|１９|２０){_D}{{2}}[-/.／－年]{_D}{{1,2}}[-/.／－月]{_D}{{1,2}}日?"
    ),
    re.compile(f"{_D}{{1,2}}[/／月]{_D}{{1,2}}日?"),
    re.compile(f"{_D}{{1,2}}[:：]{_D}{{2}}(?:[:：]{_D}{{2}})?"),
    re.compile(f"{_D}{{1,2}}時(?:{_D}{{1,2}}分)?"),
)


def _blank(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    for pattern in patterns:
        text = pattern.sub(lambda m: "x" * len(m.group(0)), text)
    return text


def _digit_detections(text: str) -> list[Detection]:
    scratch = _blank(text, _DATE_TIME_RES)
    found = []
    for m in _DIGIT_RUN_RE.finditer(scratch):
        if sum(ch in _DIGIT_CHARS for ch in m.group(0)) >= MIN_DIGITS:
            found.append(Detection(RULE_LONG_DIGITS, m.start(), m.end()))
    return found


# ---------------------------------------------------------------------------
# at_mark
# ---------------------------------------------------------------------------

_AT_RE = re.compile("[@＠﹫]")
# PipelineInput の skill_version（例 regimen-folfox@1）はプロンプトに入るので除く
_SKILL_VERSION_RE = re.compile(r"(?<![\w.])(?:regimen|report-format)-[a-z0-9-]+@\d+")


def _at_detections(text: str) -> list[Detection]:
    scratch = _blank(text, (_SKILL_VERSION_RE,))
    return [
        Detection(RULE_AT_MARK, m.start(), m.end()) for m in _AT_RE.finditer(scratch)
    ]


# ---------------------------------------------------------------------------
# before_facility
# ---------------------------------------------------------------------------

_FACILITY_RE = re.compile("病院|医院|クリニック|センター")


def _is_facility_name_char(ch: str) -> bool:
    return is_kanji_or_katakana(ch) or is_ascii_or_wide_alnum(ch)


def _facility_candidate_start(text: str, m: re.Match[str]) -> int | None:
    start = run_start(text, m.start(), _is_facility_name_char)
    if start < m.start():
        candidate = text[start : m.start()]
        return None if is_allowed(candidate, m.group(0)) else start
    kana_start = hiragana_name_start(text, m.start())
    return kana_start if kana_start < m.start() else None


def _facility_detections(text: str) -> list[Detection]:
    found = []
    for m in _FACILITY_RE.finditer(text):
        start = _facility_candidate_start(text, m)
        if start is not None:
            found.append(Detection(RULE_BEFORE_FACILITY, start, m.end()))
    return found


# ---------------------------------------------------------------------------
# まとめ
# ---------------------------------------------------------------------------


def detect_identifiers(text: str) -> list[Detection]:
    """伏せ字漏れの候補を位置順に返す。空なら送ってよい。"""
    if not isinstance(text, str):
        raise TypeError("detect_identifiers は str だけを受け付ける")
    found = (
        _honorific_detections(text)
        + _digit_detections(text)
        + _at_detections(text)
        + _facility_detections(text)
    )
    return sorted(found, key=lambda d: (d.start, d.end, RULES.index(d.rule)))
