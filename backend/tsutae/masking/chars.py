"""文字の種類の判定（一次・二次で共有する）。"""

from __future__ import annotations

from collections.abc import Callable

KANJI_CLASS = "㐀-䶿一-鿿々〆ヵヶ"
KATAKANA_CLASS = "ァ-ヺーｦ-ﾟ"

# 助詞になりうる1字。ひらがなの名前の中にも出る（みなと・のぞみ）ので、
# 「ここで語が切れる」とは決めつけない
PARTICLES = "のにでをはがとへもや"
# 名前の最後にはまず来ない助詞（「きょうは」「くすりを」の後ろは別の語）
NON_NAME_FINAL_PARTICLES = "のにをはがへ"

SPACES = " 　\t\r\n"


def is_kanji(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or ch in "々〆ヵヶ"


def is_katakana(ch: str) -> bool:
    """カタカナ（長音を含む。中黒「・」は区切りなので含めない）。"""
    return "ァ" <= ch <= "ヺ" or ch == "ー" or "ｦ" <= ch <= "ﾟ"


def is_hiragana(ch: str) -> bool:
    return "ぁ" <= ch <= "ゖ" or ch in "ゝゞ"


def is_kanji_or_katakana(ch: str) -> bool:
    return is_kanji(ch) or is_katakana(ch)


def is_japanese(ch: str) -> bool:
    return is_kanji_or_katakana(ch) or is_hiragana(ch)


def is_latin_letter(ch: str) -> bool:
    return ("A" <= ch <= "Z" or "a" <= ch <= "z") or (
        "Ａ" <= ch <= "Ｚ" or "ａ" <= ch <= "ｚ"
    )


def is_ascii_or_wide_alnum(ch: str) -> bool:
    return is_latin_letter(ch) or "0" <= ch <= "9" or "０" <= ch <= "９"


def run_start(text: str, end: int, pred: Callable[[str], bool], limit: int = 0) -> int:
    """text[:end] の末尾で pred を満たす文字が続く範囲の開始位置（limit より前へは戻らない）。"""
    start = end
    while start > limit and pred(text[start - 1]):
        start -= 1
    return start


def is_space(ch: str) -> bool:
    """空白・改行（NBSP・全角空白 等の Unicode の空白を含む）。"""
    return ch in SPACES or ch.isspace()


def skip_spaces_back(text: str, end: int, limit: int = 0) -> int:
    """text[:end] の末尾の空白・改行を飛ばした位置。"""
    return run_start(text, end, is_space, limit)


def is_hard_boundary(text: str, pos: int, limit: int = 0) -> bool:
    """pos が語の始まりとみなせる境界か（文頭・前の敬称の後・記号や空白の後）。

    漢字・カタカナの直後は送り仮名の続きなので境界ではない。
    """
    return pos <= limit or not is_japanese(text[pos - 1])


def has_line_break(text: str, start: int, end: int) -> bool:
    """text[start:end]（飛ばした空白）に改行があるか（normalize_text の後は `\\n` だけ）。"""
    return "\n" in text[start:end]
