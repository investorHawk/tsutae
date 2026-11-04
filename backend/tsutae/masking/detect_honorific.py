"""二次 unknown_before_honorific: 敬称の直前の語が「○○」でも許可語でもない。

一次（replace.py）は辞書の姓が敬称の直前にあるときだけ伏せる。こちらは辞書を
見ずに、敬称の直前の語（漢字・カタカナ・ひらがな2字以上、ローマ字2字以上）を
全て候補にし、許可語で説明できなければ検出する。迷ったら検出する側に倒す。
"""

from __future__ import annotations

import re

from tsutae.masking.chars import (
    NON_NAME_FINAL_PARTICLES,
    PARTICLES,
    has_line_break,
    is_hard_boundary,
    is_hiragana,
    is_japanese,
    is_kanji,
    is_kanji_or_katakana,
    is_latin_letter,
    run_start,
    skip_spaces_back,
)
from tsutae.masking.replace import NAME_MASK
from tsutae.masking.words import (
    CLAUSE_ENDINGS,
    excused_before_line_break,
    hiragana_explained,
    is_allowed,
    kanji_run_explained,
)

# 敬称の候補。除くもの: 同様・模様 等（名前の末尾に来る 一・多 は除かない）、様子、
# さんぽ・さんざん、ひらがなの数（さんかい・さんじ・さんにち 等）、さまざま・冷ます
_HONORIFIC_RE = re.compile(
    "(?<![同模異仕各左])様(?![子々])"
    "|さん(?!ぽ|ざん|かい|じ(?!ゃ)|にち(?!ょ)|ばい|ぷん|しょく(?!じ)|にん(?!じん)"
    "|ど(?![うこ]))"
    "|先生|せんせい|くん|ちゃん"
    "|さま(?!ざま|す|し|せ|そ|よう|たげ|[るっらりれろ])|君|氏(?!名|神|子)|殿(?!様|下|堂|場|方)"
)
# 漢字・カタカナ・ひらがなが混ざった語（まり子さん・さくらちゃん）をまとめて見る敬称
_MIXED_HONORIFICS = frozenset({"さん", "ちゃん", "さま"})

# 1字の漢字の名でも検出する敬称（さんは _mixed_span が扱う）
_SHORT_NAME_HONORIFICS = frozenset({"くん", "ちゃん", "君"})

# 「〜くんです」が動詞（行くんです・長引くんです）かを見る
# 「〜くん」の直後がこれなら「〜く＋ん（の）」の動詞の形とみなす（行くんです・効くんよ・
# 書くん？・行くんや）。名＋くん の後に続く形（蓮くんが・蓮くんと）は含めない
_VERB_FORM_RE = re.compile(
    "です|だ|で|じゃ|でしょ|か(?!ら)|よ|や|ね|けど|けれど|なら|だろ|やろ|って|[？?！!。、]|$"
)
_KANA_VERB_STEMS = (
    "い",
    "ゆ",
    "ある",
    "つづ",
    "ながび",
    "ひ",
    "き",
    "か",
    "は",
    "うず",
    "ひび",
    "とど",
    "かわ",
    "あ",
    "お",
    "つ",
    "うご",
    "はたら",
    "ふらつ",
    "むかつ",
    "ちらつ",
    "ざらつ",
    "ぐらつ",
    "いらつ",
    "べたつ",
    "ねばつ",
    "かさつ",
    "おちつ",
    "な",
    "ぬ",
    "ふ",
    "ひら",
    "や",
    "む",
    "たた",
    "ま",
)
_VERB_KANJI = frozenset(
    "行書聞効歩続引届吐響疼渇乾空着動働開抜拭焼置履泣咲浮掻向剥傾驚招描磨除叩巻"
    "突吹湧炊敷弾輝嘆解説欠築導背退付"
)
_KANJI_VERB_STEMS = ("長引", "気付", "片付", "近付")
# 1字の擬態語（かくん・ちくん・ごくん・どくん）の頭
_ONOMATOPOEIA_HEADS = frozenset("かがきぎこごちぢつづとどぱぴぷぺぽばびぶべぼずじぞ")


# ---------------------------------------------------------------------------
# ひらがなの語の切り出し
# ---------------------------------------------------------------------------


def _particle_is_real(text: str, cut: int, word_start: int, limit: int) -> bool:
    """敬称の直前の助詞の字 text[cut] が本当に助詞か（名前の最後の字ではないか）。"""
    if text[cut] in NON_NAME_FINAL_PARTICLES:
        return True
    before = text[word_start:cut]
    if not before:
        # 「母と」のように漢字の直後なら助詞。「やまもと」の「と」は名前の字
        return word_start > limit and is_kanji_or_katakana(text[word_start - 1])
    return hiragana_explained(before)  # 「おかあさんと」


def kana_word_start(
    text: str, end: int, limit: int, *, trailing_fallback: bool, onomatopoeia: bool
) -> int | None:
    """text[:end] の末尾のひらがなの語の開始位置。名前らしくなければ None。

    助詞の字で切るが、切った後ろが1字以下なら、その字は名前の一部とみなして
    もっと前で切り直す（さとう・はると・ともくん）。文頭・記号の直後の先頭2字以内の
    助詞の字（やさしい・ことぶき）では切らない。漢字の直後の送り仮名は None。
    """
    r0 = run_start(text, end, is_hiragana, limit)
    if r0 == end:
        return None
    hard = is_hard_boundary(text, r0, limit)
    cuts = [
        i
        for i in range(end - 1, r0 - 1, -1)
        if text[i] in PARTICLES and not (hard and i - r0 <= 1)
    ]
    for idx, cut in enumerate(cuts):
        remain = end - (cut + 1)
        if remain >= 2:
            return cut + 1
        word_start = cuts[idx + 1] + 1 if idx + 1 < len(cuts) else r0
        real = _particle_is_real(text, cut, word_start, limit)
        if remain == 1:
            if onomatopoeia and real and text[cut + 1] in _ONOMATOPOEIA_HEADS:
                return None  # 「ひざがかくんと」「胸がちくんと」
            continue
        if not trailing_fallback or real:
            return None
    return r0 if hard else None


# ---------------------------------------------------------------------------
# 候補の切り出し
# ---------------------------------------------------------------------------


def _word_offset(candidate: str) -> int:
    """報告する位置を、名前らしい語の頭（助詞の後ろ）にする（母とさくら→さくら）。"""
    for cut in range(len(candidate) - 2, -1, -1):
        if candidate[cut] not in PARTICLES:
            continue
        remain = candidate[cut + 1 :]
        if len(remain) >= 2 or is_kanji_or_katakana(remain[0]):
            return cut + 1
    return 0


def _mixed_span(text: str, end: int, limit: int, honorific: str) -> int | None:
    start = run_start(text, end, is_japanese, limit)
    candidate = text[start:end]
    if len(candidate) == 1 and is_kanji(candidate):
        # 前置きの無い1字の名（翔さん・葵ちゃん）。続柄の1字（母さん・孫ちゃん）は許可語
        return None if is_allowed(candidate, honorific) else start
    if len(candidate) < 2 or candidate[-1] in "をはがへ":
        return None
    if is_allowed(candidate, honorific):
        return None
    return start + _word_offset(candidate)


def _prefix_is_break(prefix: str) -> bool:
    """動詞の語幹の前が語の切れ目か（あした＋いく、症状が＋つづく）。"""
    if not prefix or prefix[-1] in PARTICLES or prefix.endswith(CLAUSE_ENDINGS):
        return True
    if is_kanji_or_katakana(prefix[-1]):
        run = prefix[run_start(prefix, len(prefix), is_kanji_or_katakana) :]
        return kanji_run_explained(run, 1)
    return hiragana_explained(prefix[run_start(prefix, len(prefix), is_hiragana) :])


def _looks_like_verb(candidate: str) -> bool:
    """「〜くんです」の「〜く」が動詞か（行くんです・ふらつくんです・長引くんです）。"""
    if candidate.endswith(_KANJI_VERB_STEMS):
        return True
    if is_kanji_or_katakana(candidate[-1]):
        return candidate[-1] in _VERB_KANJI and _prefix_is_break(candidate[:-1])
    return any(
        candidate.endswith(stem) and _prefix_is_break(candidate[: -len(stem)])
        for stem in _KANA_VERB_STEMS
    )


def _word_span(text: str, end: int, m: re.Match[str], limit: int) -> int | None:
    """先生・様・くん 等: 直前の漢字・カタカナの語、無ければひらがなの語。"""
    honorific = m.group(0)
    is_kun = honorific == "くん"
    k_start = run_start(text, end, is_kanji_or_katakana, limit)
    if k_start < end:
        start: int | None = k_start
        if end - k_start == 1 and k_start > limit and is_hiragana(text[k_start - 1]):
            kana = kana_word_start(
                text, k_start, limit, trailing_fallback=False, onomatopoeia=False
            )
            start = kana if kana is not None else k_start  # ゆう太くん
    else:
        start = kana_word_start(
            text,
            end,
            limit,
            trailing_fallback=not text.startswith("ちゃんと", m.start()),
            onomatopoeia=is_kun,
        )
    if start is None:
        return None
    candidate = text[start:end]
    if is_kun and _VERB_FORM_RE.match(text, m.end()) and _looks_like_verb(candidate):
        return None
    if end - start < 2:
        # 1字の漢字の名＋くん・ちゃん（孫の蓮くん・娘の葵ちゃん）。続柄の1字
        # （孫ちゃん・兄ちゃん・赤ちゃん 等）は許可語で通す
        if honorific in _SHORT_NAME_HONORIFICS and is_kanji(candidate):
            return None if is_allowed(candidate, honorific) else start
        return None
    return None if is_allowed(candidate, honorific) else start


def _candidate_start(text: str, m: re.Match[str], limit: int) -> int | None:
    """敬称の直前の語の開始位置（検出しないなら None）。空白・改行は飛ばす。

    ただし飛ばした中に改行があり、改行の前が明示の許可語の形容詞・副詞（とその活用）・
    助詞で終わるひらがな（つらい\n先生に）なら見ない。通常の空白には使わない
    （みらい ちゃん・みらい\nちゃん は検出する）。
    """
    end = skip_spaces_back(text, m.start(), limit)
    if has_line_break(text, end, m.start()):
        word = text[run_start(text, end, is_hiragana, limit) : end]
        if excused_before_line_break(word):
            return None
    if end > limit and is_latin_letter(text[end - 1]):
        start = run_start(text, end, is_latin_letter, limit)
        return start if end - start >= 2 else None  # Tanakaさん（Aさんは除く）
    honorific = m.group(0)
    if honorific in _MIXED_HONORIFICS and not text.startswith("ちゃんと", m.start()):
        return _mixed_span(text, end, limit, honorific)
    return _word_span(text, end, m, limit)


def _short_name_start(text: str, m: re.Match[str], limit: int) -> int | None:
    """敬称の直前が「○○」か1字の漢字・カタカナ（名だけ）なら、その開始位置。"""
    end = skip_spaces_back(text, m.start(), limit)
    if end - len(NAME_MASK) >= limit and text.startswith(
        NAME_MASK, end - len(NAME_MASK)
    ):
        return end - len(NAME_MASK)
    if run_start(text, end, is_kanji_or_katakana, limit) == end - 1:
        return end - 1
    return None


def _spaced_surname_start(text: str, name_start: int, limit: int) -> int | None:
    """名の前に空白・改行を挟んで、許可語で説明できない語（姓）が続けばその開始位置。

    「磯鷲 南さん」は一次が辞書の1字の姓（南）だけを伏せて「磯鷲 ○○さん」になる。
    「今日 ○○さん」の「今日」のような許可語は通す。ひらがなの語（母と）は見ない。
    """
    before = skip_spaces_back(text, name_start, limit)
    if before == name_start or before <= limit:
        return None
    if is_latin_letter(text[before - 1]):
        return run_start(text, before, is_latin_letter, limit)  # Isowashi 南さん
    if not is_kanji_or_katakana(text[before - 1]):
        return None
    start = run_start(text, before, is_kanji_or_katakana, limit)
    return None if kanji_run_explained(text[start:before], 1) else start


def honorific_spans(text: str) -> list[tuple[int, int]]:
    """unknown_before_honorific の (開始, 終わり) の一覧。"""
    found = []
    limit = 0
    for m in _HONORIFIC_RE.finditer(text):
        start = _candidate_start(text, m, limit)
        if start is None:
            name_start = _short_name_start(text, m, limit)
            if name_start is not None:
                start = _spaced_surname_start(text, name_start, limit)
        limit = m.end()
        if start is not None:
            found.append((start, m.end()))
    return found
