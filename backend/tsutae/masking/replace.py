"""一次の伏せ字（置換）。Claude に送る文から識別子を伏せる。

- 人名: 姓辞書（surnames.txt）＋敬称 →「○○さん」「○○先生」…（敬称は残す）
- 電話・メール・住所（都道府県＋市区町村＋番地）→「[伏せ字]」
- 「病院／医院／クリニック／医療センター」で終わる固有名 →「[病院]」
- 仮名ID（P-XXXXXXXX、大文字小文字・全角を問わない）→「[ID]」
- 残す: 日付・時刻・体温・「東京へ行った」程度の地域名・続柄

二次（detect.py）は別の、より厳しい規則で一次の漏れを拾う。
文字種の判定（chars.py）と許可語の照合（words.py）は二次と共有する。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from tsutae.masking.chars import (
    KANJI_CLASS,
    PARTICLES,
    is_ascii_or_wide_alnum,
    is_hard_boundary,
    is_hiragana,
    is_kanji_or_katakana,
    run_start,
)
from tsutae.masking.words import (
    leading_allowed_len,
    load_allow_words,
    load_surnames,
    max_surname_len,
    surname_set,
)

__all__ = [
    "COUNT_KEYS",
    "GENERIC_MASK",
    "HONORIFIC_PATTERN",
    "HOSPITAL_MASK",
    "ID_MASK",
    "NAME_MASK",
    "MaskResult",
    "facility_name_start",
    "hiragana_name_start",
    "load_allow_words",
    "load_surnames",
    "mask_text",
]

NAME_MASK = "○○"
GENERIC_MASK = "[伏せ字]"
HOSPITAL_MASK = "[病院]"
ID_MASK = "[ID]"
COUNT_KEYS = ("id", "name", "phone", "email", "address", "hospital")

# 契約の5つ（さん/先生/くん/ちゃん/様）に、せんせい・さま・君・氏・殿 を足す。
# 様子・様々、さまざま・冷ます、氏名・氏神、殿様・殿下 などは敬称ではない
HONORIFIC_PATTERN = (
    "さん|先生|せんせい|くん|ちゃん|様(?![子々])"
    "|さま(?!ざま|す|し|せ|そ|よう|たげ|[るっらりれろ])|君|氏(?!名|神|子)|殿(?!様|下|堂|場|方)"
)


@dataclass(frozen=True)
class MaskResult:
    masked: str
    counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 件数を後から書き換えられないように、写して読み取り専用にする
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))


# ---------------------------------------------------------------------------
# ひらがなの固有名（「さくらクリニック」の「さくら」）
# ---------------------------------------------------------------------------

_BAD_END_CHARS = frozenset(PARTICLES + "いなただるうくすつてずぐむぬぶしかねよわぞさぜ")
_BAD_END_WORDS = (
    "たら",
    "なら",
    "から",
    "れば",
    "けば",
    "えば",
    "より",
    "だけ",
    "しか",
)


def hiragana_name_start(text: str, end: int, limit: int = 0) -> int:
    """text[:end] の末尾のひらがなが固有名らしければその開始位置、でなければ end。

    助詞の後ろだけを見る。活用語尾・助詞で終わるもの（大きな／新しい／出たら）は除く。
    文頭・記号の直後の先頭2字以内の助詞の字は名前の一部とみなす（ことぶき・のぞみ）。
    """
    start = run_start(text, end, is_hiragana, limit)
    hard = is_hard_boundary(text, start, limit)
    lead = leading_allowed_len(text[start:end])
    start += lead
    segment = text[start:end]
    cut = max(segment.rfind(p) for p in PARTICLES)
    if cut >= 0 and not (hard and lead == 0 and cut <= 1):
        start += cut + 1
        segment = text[start:end]
    if len(segment) < 2 or segment[-1] in _BAD_END_CHARS:
        return end
    if segment.endswith(_BAD_END_WORDS):
        return end
    return start


# ---------------------------------------------------------------------------
# 規則
# ---------------------------------------------------------------------------

_D = "0-9０-９"
_HYPHEN = "\\-‐‑‒–—―−－ー"
_ALNUM = "A-Za-z0-9Ａ-Ｚａ-ｚ０-９"

# 局所部は並びの頭からだけ試す（後読み）。途中の位置から試し直すと「1-1-1-…」の
# ような長い入力で入力長の2乗に比例して遅くなる
EMAIL_RE = re.compile(
    rf"(?<![{_ALNUM}._%+\-])[{_ALNUM}._%+\-]+[@＠﹫][{_ALNUM}\-]+"
    rf"(?:[.．][{_ALNUM}\-]+)+"
)

# 区切り: ハイフン・空白（改行・タブ・NBSP を含む）・括弧・ドット・中黒・スラッシュ。
# 字数は問わない（空白4字・改行4つ・空白と改行の混在・「(03)  1234」）。
# 電話かどうかは数字のまとまり（0 始まり・1〜4・1〜4・3〜4桁）と総桁数（10〜11）で決める。
# 区切りの字と数字は重ならないので、何字でも総当たりにならない
_PHONE_SEP = f"[{_HYPHEN}\\s()（）.．・/／]*"
PHONE_RE = re.compile(
    rf"(?<![{_D}.．/／・])(?P<head>[+＋](?:81|８１){_PHONE_SEP}|[0０])"
    rf"[{_D}]{{1,4}}{_PHONE_SEP}[{_D}]{{1,4}}{_PHONE_SEP}[{_D}]{{3,4}}(?![{_D}])"
)

_PREFECTURES = (
    "北海道|東京都|京都府|大阪府|(?:青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|"
    "千葉|神奈川|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|兵庫|奈良|"
    "和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分|"
    "宮崎|鹿児島|沖縄)県"
)
_PLACE = f"[{KANJI_CLASS}ケ]"
_NUM = f"(?:[{_D}]+|[一二三四五六七八九十〇]+)"
_MARK = "(?:丁目|番地|番|号)"
# 部分の間の空白・改行（「東京都 千代田区 架空町 1-2-3」「架空町   1-2」）。字数は
# 問わない（Unicode の空白。NBSP・全角空白を含む）。番地のハイフン類の前後の空白も許す
# （「架空町 1 - 2」）。空白と地名・数字・ハイフン類は重ならないので総当たりにならない
_WS = "\\s*"
_HY = f"\\s*[{_HYPHEN}]\\s*"
_MARK_BLOCK = f"{_NUM}\\s*{_MARK}(?:{_WS}{_NUM}(?:{_MARK}|[{_HYPHEN}])?)*"
_PAIR_BLOCK = f"{_NUM}{_HY}{_NUM}(?:{_HY}{_NUM})*(?:{_MARK})?"
_TRIPLE_BLOCK = f"{_NUM}{_HY}{_NUM}{_HY}{_NUM}(?:{_HY}{_NUM})*(?:{_MARK})?"
# 市区町村の1単位。原子グループ（Python 3.11+）で「最短の地名＋市区町村」に決め打ちし、
# 地名の切り方の組み合わせを総当たりしない（「市」が長く続く文で遅くならない。ReDoS 対策）
_UNIT = f"(?>{_PLACE}{{1,8}}?(?:市|区|町|村|郡))"
_CITY = f"{_UNIT}(?:{_WS}{_UNIT}){{0,2}}{_PLACE}{{0,10}}?{_WS}"
_CITY2 = f"{_UNIT}(?:{_WS}{_UNIT}){{1,2}}{_PLACE}{{0,10}}?{_WS}"
# 都道府県が無く市区町村が1つだけのときは、丁目・番地 等か N-N-N（3組以上）に限る
# （「毎日市販薬1-2錠」を住所にしない。「架空市中区架空町1-2」は住所）
ADDRESS_RE = re.compile(
    f"(?:{_PREFECTURES}){_WS}{_CITY}(?:{_MARK_BLOCK}|{_PAIR_BLOCK})"
    f"|{_CITY2}(?:{_MARK_BLOCK}|{_PAIR_BLOCK})"
    f"|{_CITY}(?:{_MARK_BLOCK}|{_TRIPLE_BLOCK})"
)

FACILITY_SUFFIX_RE = re.compile("病院|医院|クリニック|医療センター")
# 施設語の前の1字の時の語（「朝病院へ」）。2字以上は allow_words.txt で扱う
ONE_CHAR_TIME_WORDS = frozenset("朝昼夜晩")


# 仮名ID（patients.id = "P-" + 英大文字数字8桁）。全角・小文字も同じ字とみなす。
# ちょうど8桁で前後が英数字でないものだけ（それ以外の形は二次の id_like が拾う）。
# ハイフン類の前後の空白・改行は何字でも許す（「P - DEMO0001」「P-\nDEMO0001」）
ID_RE = re.compile(
    rf"(?<![{_ALNUM}])[PpＰｐ]\s*[{_HYPHEN}]\s*[{_ALNUM}]{{8}}(?![{_ALNUM}])"
)


def _mask_ids(text: str) -> tuple[str, int]:
    return ID_RE.subn(ID_MASK, text)


def _mask_emails(text: str) -> tuple[str, int]:
    return EMAIL_RE.subn(GENERIC_MASK, text)


def _mask_addresses(text: str) -> tuple[str, int]:
    def repl(m: re.Match[str]) -> str:
        keep = leading_allowed_len(m.group(0))
        return m.group(0)[:keep] + GENERIC_MASK

    return ADDRESS_RE.subn(repl, text)


def _phone_digits_ok(m: re.Match[str]) -> bool:
    digits = sum(ch.isdigit() for ch in m.group(0))
    if m.group("head")[0] in "+＋":
        return 11 <= digits <= 12  # 81 + 9〜10桁
    return 10 <= digits <= 11


def _mask_phones(text: str) -> tuple[str, int]:
    count = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        if not _phone_digits_ok(m):
            return m.group(0)
        count += 1
        return GENERIC_MASK

    return PHONE_RE.sub(repl, text), count


def _is_facility_name_char(ch: str) -> bool:
    return is_kanji_or_katakana(ch) or is_ascii_or_wide_alnum(ch)


def _with_leading_kanji(text: str, start: int, limit: int) -> int:
    """ひらがなの名前の直前に続く漢字・カタカナ（架空さくら・東さくら）も名前に含める。

    残すと「架空[病院]」のように名前の一部が外に出る。先頭の「今日」等と
    1字の時の語（朝さくら病院）は含めない。
    """
    k_start = run_start(text, start, _is_facility_name_char, limit)
    if k_start == start or text[k_start:start] in ONE_CHAR_TIME_WORDS:
        return start
    return k_start + leading_allowed_len(text[k_start:start])


def facility_name_start(text: str, suffix_start: int, limit: int = 0) -> int:
    """施設語の直前の固有名の開始位置（無ければ suffix_start）。先頭の「今日」等は含めない。"""
    k_start = run_start(text, suffix_start, _is_facility_name_char, limit)
    if k_start == suffix_start:
        start = hiragana_name_start(text, suffix_start, limit)
        if start == suffix_start:
            return start
        return _with_leading_kanji(text, start, limit)
    if text[k_start:suffix_start] in ONE_CHAR_TIME_WORDS:
        return suffix_start
    start = hiragana_name_start(text, k_start, limit)
    if start == k_start:
        return start + leading_allowed_len(text[k_start:suffix_start])
    return _with_leading_kanji(text, start, limit)


def _mask_hospitals(text: str) -> tuple[str, int]:
    pieces: list[str] = []
    pos = 0
    count = 0
    for m in FACILITY_SUFFIX_RE.finditer(text):
        start = facility_name_start(text, m.start(), limit=pos)
        if start >= m.start():
            continue
        pieces += [text[pos:start], HOSPITAL_MASK]
        pos = m.end()
        count += 1
    pieces.append(text[pos:])
    return "".join(pieces), count


# ---------------------------------------------------------------------------
# 人名（姓辞書＋敬称）
# ---------------------------------------------------------------------------

_NAME_HONORIFIC_RE = re.compile(f"[ 　]?(?:{HONORIFIC_PATTERN})")


def _surname_start(text: str, end: int, limit: int) -> int | None:
    """敬称の直前の漢字・カタカナの並びが「許可語＋辞書の姓」なら、姓の開始位置。

    姓の左に許可語でない字が続くとき（小山田・磯鷲田中・ジョン鈴木）は伏せない
    （半端に伏せると二次が拾えなくなる。そのまま二次に任せる）。
    """
    run = text[run_start(text, end, is_kanji_or_katakana, limit) : end]
    surnames = surname_set()
    for size in range(min(len(run), max_surname_len()), 0, -1):
        prefix = run[:-size]
        if run[-size:] in surnames and leading_allowed_len(prefix) == len(prefix):
            return end - size
    return None


def _mask_names(text: str) -> tuple[str, int]:
    pieces: list[str] = []
    pos = 0  # 写し終えた位置
    limit = 0  # 前の敬称の終わり（姓はこれより前へ戻らない）
    count = 0
    for m in _NAME_HONORIFIC_RE.finditer(text):
        start = _surname_start(text, m.start(), limit)
        limit = m.end()
        if start is None:
            continue
        pieces += [text[pos:start], NAME_MASK]
        pos = m.start()
        count += 1
    pieces.append(text[pos:])
    return "".join(pieces), count


_STEPS: tuple[tuple[str, Callable[[str], tuple[str, int]]], ...] = (
    ("id", _mask_ids),
    ("email", _mask_emails),
    ("address", _mask_addresses),
    ("phone", _mask_phones),
    ("hospital", _mask_hospitals),
    ("name", _mask_names),
)


def mask_text(text: str) -> MaskResult:
    """一次の伏せ字。counts は規則ごとの置換件数（文面は含まない）。"""
    if not isinstance(text, str):
        raise TypeError("mask_text は str だけを受け付ける")
    counts = dict.fromkeys(COUNT_KEYS, 0)
    current = text
    for key, step in _STEPS:
        current, n = step(current)
        counts[key] = n
    return MaskResult(masked=current, counts=counts)
