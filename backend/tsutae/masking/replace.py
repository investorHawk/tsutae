"""一次の伏せ字（置換）。Claude に送る文から識別子を伏せる。

- 人名: 姓辞書（surnames.txt）＋敬称 →「○○さん」「○○先生」…（敬称は残す）
- 電話・メール・住所（都道府県＋市区町村＋番地）→「[伏せ字]」
- 「病院／医院／クリニック／医療センター」で終わる固有名 →「[病院]」
- 残す: 日付・時刻・体温・「東京へ行った」程度の地域名・続柄

二次（detect.py）は別の、より厳しい規則で一次の漏れを拾う。
文字種の判定と許可語（allow_words.txt）の照合は二次と共有する。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

NAME_MASK = "○○"
GENERIC_MASK = "[伏せ字]"
HOSPITAL_MASK = "[病院]"
COUNT_KEYS = ("name", "phone", "email", "address", "hospital")

_HERE = Path(__file__).resolve().parent

# 様子・様々 の「様」は敬称ではない
HONORIFIC_PATTERN = "さん|先生|くん|ちゃん|様(?![子々])"


@dataclass(frozen=True)
class MaskResult:
    masked: str
    counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 文字の種類
# ---------------------------------------------------------------------------

KANJI_CLASS = "㐀-䶿一-鿿々〆ヵヶ"


def is_kanji(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or ch in "々〆ヵヶ"


def is_katakana(ch: str) -> bool:
    return "ァ" <= ch <= "ヺ" or ch in "ー・" or "ｦ" <= ch <= "ﾟ"


def is_hiragana(ch: str) -> bool:
    return "ぁ" <= ch <= "ゖ" or ch in "ゝゞ"


def is_kanji_or_katakana(ch: str) -> bool:
    return is_kanji(ch) or is_katakana(ch)


def is_japanese(ch: str) -> bool:
    return is_kanji_or_katakana(ch) or is_hiragana(ch)


def is_ascii_or_wide_alnum(ch: str) -> bool:
    return (ch.isascii() and ch.isalnum()) or (
        "０" <= ch <= "９" or "Ａ" <= ch <= "Ｚ" or "ａ" <= ch <= "ｚ"
    )


def run_start(text: str, end: int, pred: Callable[[str], bool], limit: int = 0) -> int:
    """text[:end] の末尾で pred を満たす文字が続く範囲の開始位置（limit より前へは戻らない）。"""
    start = end
    while start > limit and pred(text[start - 1]):
        start -= 1
    return start


# ---------------------------------------------------------------------------
# 辞書（surnames.txt / allow_words.txt）
# ---------------------------------------------------------------------------


def _read_words(filename: str) -> tuple[str, ...]:
    lines = (_HERE / filename).read_text(encoding="utf-8").splitlines()
    words = (line.strip() for line in lines)
    return tuple(dict.fromkeys(w for w in words if w and not w.startswith("#")))


@cache
def load_surnames() -> tuple[str, ...]:
    """一般的な日本の姓（多い順）。"""
    return _read_words("surnames.txt")


@cache
def load_allow_words() -> tuple[str, ...]:
    """許可語（長い順。最長一致に使う）。"""
    return tuple(sorted(_read_words("allow_words.txt"), key=len, reverse=True))


def _covered_by_allow_word(candidate: str, tail: str) -> int | None:
    """candidate＋tail の末尾に一致する最長の許可語が、candidate の何文字を覆うか。"""
    full = candidate + tail
    for word in load_allow_words():
        if len(word) > len(tail) and full.endswith(word):
            return min(len(word) - len(tail), len(candidate))
        if candidate.endswith(word):
            return len(word)
    return None


def is_covered(text: str) -> bool:
    """漢字・カタカナの並びが、右から許可語で覆い尽くせるか（残りが1字以下なら可）。"""
    rest = text
    while len(rest) >= 2:
        word = next((w for w in load_allow_words() if rest.endswith(w)), None)
        if word is None:
            return False
        rest = rest[: -len(word)]
    return True


def is_allowed(candidate: str, tail: str) -> bool:
    """敬称・施設語（tail）の直前の語 candidate が許可語で終わるか。

    許可語が漢字・カタカナで始まるときは、その直前に続く漢字・カタカナも
    許可語で覆えなければ不可（「磯鷲看護師さん」を「看護師さん」で通さない）。
    """
    covered = _covered_by_allow_word(candidate, tail)
    if covered is None:
        return False
    rest = candidate[: len(candidate) - covered]
    head = candidate[len(rest) : len(rest) + 1] or tail[:1]
    if not is_kanji_or_katakana(head):
        return True
    tail_run = rest[run_start(rest, len(rest), is_kanji_or_katakana) :]
    return is_covered(tail_run)


def leading_allowed_len(text: str) -> int:
    """text の先頭から続く許可語（2字以上）の長さの合計（「今日」「昨日」など）。"""
    pos = 0
    while pos < len(text):
        word = next(
            (w for w in load_allow_words() if len(w) >= 2 and text.startswith(w, pos)),
            None,
        )
        if word is None:
            break
        pos += len(word)
    return pos


# ---------------------------------------------------------------------------
# ひらがなの固有名（「さくらクリニック」の「さくら」）
# ---------------------------------------------------------------------------

PARTICLES = "のにでをはがとへもや"
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
    """
    start = run_start(text, end, is_hiragana, limit)
    start += leading_allowed_len(text[start:end])
    segment = text[start:end]
    cut = max(segment.rfind(p) for p in PARTICLES)
    if cut >= 0:
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

EMAIL_RE = re.compile(rf"[{_ALNUM}._%+\-]+[@＠﹫][{_ALNUM}\-]+(?:[.．][{_ALNUM}\-]+)+")

_PHONE_SEP = f"[{_HYPHEN} 　()（）]?"
PHONE_RE = re.compile(
    rf"(?<![{_D}.．])(?P<head>[+＋](?:81|８１){_PHONE_SEP}|[0０])"
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
_BLOCK = (
    f"(?:{_NUM}{_MARK}(?:{_NUM}(?:{_MARK}|[{_HYPHEN}])?)*"
    f"|{_NUM}[{_HYPHEN}]{_NUM}(?:[{_HYPHEN}]{_NUM})*(?:{_MARK})?)"
)
ADDRESS_RE = re.compile(
    f"(?:{_PREFECTURES})?(?:{_PLACE}{{1,8}}?(?:市|区|町|村|郡)){{1,3}}"
    f"{_PLACE}{{0,10}}?{_BLOCK}"
)

FACILITY_SUFFIX_RE = re.compile("病院|医院|クリニック|医療センター")


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


def facility_name_start(text: str, suffix_start: int, limit: int = 0) -> int:
    """施設語の直前の固有名の開始位置（無ければ suffix_start）。先頭の「今日」等は含めない。"""
    is_name = _is_facility_name_char
    k_start = run_start(text, suffix_start, is_name, limit)
    if k_start == suffix_start:
        return hiragana_name_start(text, suffix_start, limit)
    start = hiragana_name_start(text, k_start, limit)
    if start == k_start:
        start += leading_allowed_len(text[k_start:suffix_start])
    return start


def _is_facility_name_char(ch: str) -> bool:
    return is_kanji_or_katakana(ch) or is_ascii_or_wide_alnum(ch)


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


@cache
def _name_re() -> re.Pattern[str]:
    surnames = load_surnames()
    multi = sorted((s for s in surnames if len(s) > 1), key=len, reverse=True)
    single = [s for s in surnames if len(s) == 1]
    alternatives = ["|".join(map(re.escape, multi))]
    if single:
        # 1字の姓は漢字の後ろでは使わない（「磯森さん」を「磯○○さん」にしない）
        joined = "|".join(map(re.escape, single))
        alternatives.append(f"(?<![{KANJI_CLASS}])(?:{joined})")
    return re.compile(f"(?:{'|'.join(alternatives)})(?=(?:{HONORIFIC_PATTERN}))")


def _mask_names(text: str) -> tuple[str, int]:
    return _name_re().subn(NAME_MASK, text)


_STEPS: tuple[tuple[str, Callable[[str], tuple[str, int]]], ...] = (
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
