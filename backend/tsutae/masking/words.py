"""辞書（surnames.txt / allow_words.txt）と、「許可語で説明できるか」の判定。

一次（replace.py）と二次（detect_*.py）で共有する。判定の考え方:
- 敬称・施設語の直前の語が許可語で終わっても、その許可語の前に別の語が
  切れ目なく続くなら許可しない（「磯鷲看護師さん」「さとうさん」の「とうさん」）
- 切れ目とみなすもの: 文頭・記号・助詞・ひらがな→漢字の変わり目・接頭辞「お・ご」
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tsutae.masking.chars import (
    NON_NAME_FINAL_PARTICLES,
    PARTICLES,
    is_hiragana,
    is_japanese,
    is_kanji_or_katakana,
    run_start,
)

_HERE = Path(__file__).resolve().parent

# 活用・接続の切れ目（この後ろから別の語が始まる）
CLAUSE_ENDINGS = (
    "たら",
    "なら",
    "から",
    "ので",
    "けど",
    "けれど",
    "れば",
    "ても",
    "でも",
    "より",
    "だけ",
    "しか",
    "まで",
    "って",
    "ため",
    "とき",
    "あと",
    "まま",
    "て",
)
_PREFIXES = ("お", "ご")
_MAX_TRAILING_PARTICLES = 2


def _read_words(filename: str) -> tuple[str, ...]:
    lines = (_HERE / filename).read_text(encoding="utf-8").splitlines()
    words = (line.strip() for line in lines)
    return tuple(dict.fromkeys(w for w in words if w and not w.startswith("#")))


@cache
def load_surnames() -> tuple[str, ...]:
    """一般的な日本の姓（多い順）。"""
    return _read_words("surnames.txt")


@cache
def surname_set() -> frozenset[str]:
    return frozenset(load_surnames())


@cache
def max_surname_len() -> int:
    return max((len(s) for s in load_surnames()), default=0)


@cache
def allowed_prefix_chars() -> frozenset[str]:
    """許可語の左に1字だけ残してよい字（allow_prefixes.txt。新・前・元 等）。"""
    return frozenset(w for w in _read_words("allow_prefixes.txt") if len(w) == 1)


@cache
def load_allow_words() -> tuple[str, ...]:
    """許可語（長い順）。"""
    return tuple(sorted(_read_words("allow_words.txt"), key=len, reverse=True))


@cache
def allow_set() -> frozenset[str]:
    return frozenset(load_allow_words())


@cache
def max_allow_len() -> int:
    return max((len(w) for w in load_allow_words()), default=0)


def leading_allowed_len(text: str) -> int:
    """text の先頭から続く許可語（2字以上）の長さの合計（「今日」「昨日」など）。"""
    words, longest = allow_set(), max_allow_len()
    pos = 0
    while pos < len(text):
        size = next(
            (
                n
                for n in range(min(longest, len(text) - pos), 1, -1)
                if text[pos : pos + n] in words
            ),
            0,
        )
        if size == 0:
            break
        pos += size
    return pos


# ---------------------------------------------------------------------------
# 漢字・カタカナの並び
# ---------------------------------------------------------------------------


def kanji_run_explained(run: str, right_len: int) -> bool:
    """漢字・カタカナの並び run を、許可語の連なりで覆い尽くせるか。

    左端の1字だけは残してよい（「新看護師」）。ただし、その右隣の語が2字以上で、
    残る1字が allow_prefixes.txt の字（新・前・元 等）のときに限る（「島看護師」
    「鷲薬剤師」は不可。right_len は run の右に続く語の run 内に掛かる字数。
    「守屋」の「屋」のような1字の語の左には何も残せない）。
    """
    words, longest = allow_set(), max_allow_len()
    n = len(run)
    # reach[i]: run[i:] が覆えたときの、i から始まる語が2字以上か（の集合）
    reach: list[set[bool]] = [set() for _ in range(n + 1)]
    reach[n].add(right_len >= 2)
    for end in range(n, 0, -1):
        if not reach[end]:
            continue
        for size in range(1, min(longest, end) + 1):
            if run[end - size : end] in words:
                reach[end - size].add(size >= 2)
    if reach[0]:
        return True
    return n >= 1 and True in reach[1] and run[0] in allowed_prefix_chars()


# ---------------------------------------------------------------------------
# ひらがなの並び
# ---------------------------------------------------------------------------


def _hiragana_reach(word: str) -> list[bool]:
    """reach[i]: word[i:] が「許可語＋助詞0〜2字」の連なりで覆えるか。"""
    words, longest = allow_set(), max_allow_len()
    n = len(word)
    reach = [False] * (n + 1)
    reach[n] = True
    for end in range(n, 0, -1):
        if not reach[end]:
            continue
        for particles in range(_MAX_TRAILING_PARTICLES + 1):
            word_end = end - particles
            if word_end <= 0 or (particles and word[word_end] not in PARTICLES):
                break
            for size in range(2, min(longest, word_end) + 1):
                if word[word_end - size : word_end] in words:
                    reach[word_end - size] = True
    return reach


def explained_suffixes(word: str) -> list[bool]:
    """result[i]: word[i:] が名前らしくない（許可語・助詞・活用の切れ目で説明できる）か。

    word[i:] = X + Y で、Y が「許可語＋助詞」の連なり（空でない）、X が空か、
    助詞・活用の切れ目（たら・ので・て 等）で終わる。word 自体が切れ目で終われば全て真。
    """
    n = len(word)
    if word.endswith(CLAUSE_ENDINGS):
        return [True] * (n + 1)
    reach = _hiragana_reach(word)
    result = [False] * (n + 1)
    boundary_after = False  # i より右に「切れ目の直後から Y が始まる」位置があるか
    for i in range(n - 1, -1, -1):
        t = i + 1
        if t < n and reach[t] and _is_break_before(word, t):
            boundary_after = True
        result[i] = reach[i] or boundary_after
    result[n] = False
    return result


def _is_break_before(word: str, pos: int) -> bool:
    return word[pos - 1] in PARTICLES or word[:pos].endswith(CLAUSE_ENDINGS)


def hiragana_explained(word: str) -> bool:
    return bool(word) and explained_suffixes(word)[0]


# ---------------------------------------------------------------------------
# 敬称・施設語の直前の語
# ---------------------------------------------------------------------------


def _covers(candidate: str, tail: str) -> list[int]:
    """candidate の末尾を覆う許可語の、candidate 内の字数（長い順）。

    許可語は tail（敬称・施設語）まで含んでよい（「看護師さん」「保健センター」）。
    """
    words, longest = allow_set(), max_allow_len()
    full = candidate + tail
    found: set[int] = set()
    for size in range(1, min(longest, len(full)) + 1):
        if size > len(tail) and full[-size:] in words:
            found.add(size - len(tail))
        if size <= len(candidate) and candidate[-size:] in words:
            found.add(size)
    return sorted(found, reverse=True)


def _rest_explained(rest: str, head: str, covered: int) -> bool:
    """許可語（先頭の字 head、candidate 内 covered 字）の前に残った rest が切れ目か。"""
    if not rest or rest[-1] in NON_NAME_FINAL_PARTICLES or not is_japanese(rest[-1]):
        return True
    if is_kanji_or_katakana(rest[-1]):
        run = rest[run_start(rest, len(rest), is_kanji_or_katakana) :]
        return kanji_run_explained(run, covered)
    seg_start = run_start(rest, len(rest), is_hiragana)
    segment = rest[seg_start:]
    in_word = [ch in PARTICLES for ch in segment]
    okurigana = not any(in_word) and not segment.startswith(_PREFIXES)
    if seg_start > 0 and (okurigana or all(in_word)):
        # 漢字の送り仮名（優しい看護師さん・優しいばあちゃん）、漢字の後の助詞（母と）。
        # 「磯鷲お＋ばあちゃん」の「お」は送り仮名ではない
        return True
    if head in _PREFIXES:
        return True  # 接頭辞「お・ご」で語が始まる（やさしいおばあさん）
    return _hiragana_tail_explained(segment, at_word_start=seg_start == 0)


def _hiragana_tail_explained(segment: str, *, at_word_start: bool) -> bool:
    """許可語の前のひらがな segment が、どこかの語の頭から説明できるか。

    語の頭の候補は助詞の字の後ろと（at_word_start なら）先頭。助詞の字は語の中にも
    出る（やさしい の や）ので、どれか1つで説明できればよい（「さとう」は不可）。
    """
    explained = explained_suffixes(segment)
    starts = [0] if at_word_start else []
    starts += [
        i + 1
        for i, ch in enumerate(segment)
        if ch in PARTICLES and not (at_word_start and i <= 1)
    ]
    return any(explained[s] for s in starts if s < len(segment))


def _inflected_allowed_adjective(word: str) -> bool:
    """許可語の形容詞（だるい・きつい 等）の連用形・過去形（だるく・きつかった）か。

    語尾だけでは決めない。語幹＋「い」が allow_words.txt にあるときだけ真。
    """
    words = allow_set()
    for ending in ("かった", "く"):
        stem = word[: -len(ending)]
        if word.endswith(ending) and len(stem) >= 1 and stem + "い" in words:
            return True
    return False


def excused_before_line_break(word: str) -> bool:
    """改行の前のひらがなの語 word が、明示の許可語・助詞・活用の切れ目で終わるか。

    改行をまたいで施設語・敬称の前の語を見るとき、この語なら名前の候補にしない
    （「だるい\\n医院へ」「やっと\\n病院」「きつかった\\nクリニック」）。architecture §5
    W2b の「形容詞・副詞・助詞の後の改行」の例外。語尾の形（〜い・〜く）だけで推測しない
    （「みらい\\n病院」「さくらい\\n先生」は検出する）。通常の空白には使わない。
    """
    if not word:
        return False
    if word[-1] in NON_NAME_FINAL_PARTICLES or word.endswith(CLAUSE_ENDINGS):
        return True
    return hiragana_explained(word) or _inflected_allowed_adjective(word)


def is_allowed(candidate: str, tail: str) -> bool:
    """敬称・施設語（tail）の直前の語 candidate が、許可語で説明できるか。

    例: 「訪問看護師」+さん は可、「林看護師」+さん・「守屋」+さん・「さとう」+さん は不可。
    """
    for covered in _covers(candidate, tail):
        rest = candidate[: len(candidate) - covered]
        if _rest_explained(rest, candidate[len(rest)], covered):
            return True
    return False
