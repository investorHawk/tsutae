"""二次 address_number: 都道府県・市区町村の後に番地らしい数字が続く。

一次（replace.py の ADDRESS_RE）とは別の規則。一次は都道府県＋市区町村＋番地が
続く形を伏せる。こちらは単位1つ（「架空町」「東京都」）の後に、空白・改行を挟んで
番地（N-N、N丁目・N番地・N番・N号）が続くものを拾う。空白・改行（Unicode の空白。
NBSP・全角空白を含む）の字数は問わず、番地のハイフン類の前後の空白も許す
（「架空町   1-2」「架空町 1 - 2」）。空白を挟まない「単位＋N-N」は単位の直後に限る
（「毎日市販薬1-2錠」を拾わない）。

W2b の決定で、単位の無い番地も拾う: N-N-N（3組以上）と N丁目・N番地（架空台2-3-4・
架空台3番地）。2組（1-2錠）や N番（3番目）は拾わない。N-N-N のうち日付として除くのは
「年（1900〜2099 の4桁）-月（1〜12）-日（1〜31）のちょうど3組」で、直前が地名の字
（漢字・カタカナ）でないものだけ（2026-11-03 は除く。架空台1234-5-6・架空台2026-5-6・
3000-1-2・2026-13-1 は拾う）。

空白と地名・数字・ハイフン類は重ならないので、空白の字数を問わなくても総当たりにならない。
"""

from __future__ import annotations

import re

from tsutae.masking.chars import KANJI_CLASS, is_kanji_or_katakana

_PREFECTURE = (
    "北海道|東京都|京都府|大阪府|(?:青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|"
    "千葉|神奈川|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|兵庫|奈良|"
    "和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分|"
    "宮崎|鹿児島|沖縄)県"
)
_PLACE = f"[{KANJI_CLASS}ケ]"
# 原子グループで「最短の地名＋単位」に決め打ちする（総当たりしない。ReDoS 対策）
_UNIT = f"(?:{_PREFECTURE}|(?>{_PLACE}{{1,8}}?(?:市|区|町|村|郡)))"
_NUM = "(?:[0-9０-９]+|[一二三四五六七八九十〇]+)"
_HYPHEN = "[\\-‐‑‒–—―−－ー]"
_HY = f"\\s*{_HYPHEN}\\s*"
_MARK = "(?:丁目|番地|番|号)"
_STREET = f"{_NUM}(?:{_HY}{_NUM}|\\s*{_MARK})"

ADDRESS_NUMBER_RE = re.compile(
    f"{_UNIT}(?:{_PLACE}{{0,6}}?\\s+{_STREET}"  # 架空町 1-2、架空町   1 - 2
    f"|{_PLACE}{{0,6}}?{_NUM}\\s*{_MARK}"  # 架空町2丁目
    f"|{_NUM}{_HY}{_NUM})"  # 架空町1-2、架空町1 - 2
)


_DIGITS = "[0-9０-９]"
_DIGIT_GROUP_RE = re.compile(f"{_DIGITS}+")
_BARE_TRIPLE_RE = re.compile(
    f"(?<![0-9０-９.．])(?P<first>{_DIGITS}{{1,4}})"
    f"(?:{_HY}{_DIGITS}{{1,4}}){{2,}}(?![0-9０-９])"
)
_BARE_MARK_RE = re.compile(f"{_NUM}\\s*(?:丁目|番地)")


def _is_valid_ymd(groups: list[str]) -> bool:
    """年（1900〜2099 の4桁）・月（1〜12）・日（1〜31）のちょうど3組か。"""
    if len(groups) != 3 or len(groups[0]) != 4:
        return False
    year, month, day = (int(g) for g in groups)  # int は全角数字も読む
    return 1900 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31


def _is_date(text: str, m: re.Match[str]) -> bool:
    """単位の無い N-N-N が日付か（妥当な年月日で、地名の字に続いていない）。"""
    if not _is_valid_ymd(_DIGIT_GROUP_RE.findall(m.group(0))):
        return False
    start = m.start()
    return start == 0 or not is_kanji_or_katakana(text[start - 1])  # 架空台2026-5-6


def address_spans(text: str) -> list[tuple[int, int]]:
    """address_number の (開始, 終わり) の一覧（位置順。他に含まれる範囲は除く）。"""
    spans = [(m.start(), m.end()) for m in ADDRESS_NUMBER_RE.finditer(text)]
    spans += [
        (m.start(), m.end())
        for m in _BARE_TRIPLE_RE.finditer(text)
        if not _is_date(text, m)
    ]
    spans += [(m.start(), m.end()) for m in _BARE_MARK_RE.finditer(text)]
    return _drop_contained(spans)


def _drop_contained(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """他の範囲に含まれる範囲を除く（開始の早い順、同じなら長い順に1回なめる）。"""
    kept: list[tuple[int, int]] = []
    reach = -1
    for start, end in sorted(set(spans), key=lambda se: (se[0], -se[1])):
        if end > reach:
            kept.append((start, end))
            reach = end
    return kept
