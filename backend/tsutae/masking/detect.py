"""二次の検出。一次（replace.py）の**後の**文に掛け、伏せ字漏れの候補を見つける。

一次とは別の、より厳しい規則（同じ規則だと二次が永遠に発火しない）。迷ったら
検出する（誤検知はその記録が院内画面 D6 に回るだけ、見逃しは識別子が外に出る）:

- unknown_before_honorific: 敬称の直前の語（2字以上）が「○○」でも許可語でもない
  （一次は辞書の姓だけを伏せる。辞書にない姓・ひらがなの姓はここで拾う）
  → detect_honorific.py
- long_digits: 7桁以上の数字列（区切り記号を除いて数える。日付・時刻・小数は対象外）
  （一次は 0 始まり 10〜11 桁の電話番号だけを伏せる）
- at_mark: `@`・全角`＠`（一次はメールアドレスの形のものだけを伏せる）。患者の文
  （check_text）には例外が無い。依頼文全体（H1）では、埋め込まれた PipelineInput の
  JSON のキー付きの Skill の版（`"regimen_skill_version": "regimen-folfox@1"`）だけを
  除く。患者の文は JSON の中で `"` が `\"`（空白とみなす）になるので、この形を作れない
- before_facility: 「病院／医院／クリニック／センター」の直前の語で「[病院]」に
  なっていないもの（一次は「医療センター」だけで、他の「〜センター」は伏せない。
  ひらがなの施設名も一次より広く拾う）→ detect_facility.py
- address_number: 都道府県・市区町村の後に番地らしい数字が続く（空白・改行を挟んでも）、
  または単位の無い N-N-N・N丁目・N番地 → detect_address.py
- id_like: 英字1〜2字＋ハイフン類＋英数字3字以上（A-023・P-DEMO0001 の取り残し）
  → detect_id.py

入口は2つ（architecture.md §5 W2b の決定）:
- detect_identifiers: 依頼文全体（H1・convert②）用。JSON の文字列エスケープ
  （\\n \\t \\r \\" \\\\ \\uXXXX 等）を同じ長さの空白とみなしてから検出し、
  Skill の版のキーの値の `@` だけを数えない
- detect_in_patient_text: 患者の文（一次の後）用。例外なし。check_text はこちらを使う

Detection は位置と規則名だけを持つ（文面は持たない。ログにも文面を残さない）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tsutae.masking.detect_address import address_spans
from tsutae.masking.detect_facility import facility_spans
from tsutae.masking.detect_honorific import honorific_spans
from tsutae.masking.detect_id import id_like_spans

RULE_UNKNOWN_BEFORE_HONORIFIC = "unknown_before_honorific"
RULE_LONG_DIGITS = "long_digits"
RULE_AT_MARK = "at_mark"
RULE_BEFORE_FACILITY = "before_facility"
RULE_ADDRESS_NUMBER = "address_number"
RULE_ID_LIKE = "id_like"
RULES = (
    RULE_UNKNOWN_BEFORE_HONORIFIC,
    RULE_LONG_DIGITS,
    RULE_AT_MARK,
    RULE_BEFORE_FACILITY,
    RULE_ADDRESS_NUMBER,
    RULE_ID_LIKE,
)

MIN_DIGITS = 7


@dataclass(frozen=True)
class Detection:
    rule: str
    start: int
    end: int


# ---------------------------------------------------------------------------
# long_digits
# ---------------------------------------------------------------------------

_D = "[0-9０-９]"
_DIGIT_CHARS = frozenset("0123456789０１２３４５６７８９")
# 区切り: ハイフン・括弧・ドット・中黒・スラッシュ・読点・カンマ（090、1234、5678）と、
# 空白の全て（改行・タブ・NBSP・全角空白。\s は Unicode の空白）。区切りの字数は
# 問わない（空白4字・改行4つ・混在でも1つの並び。数字の数だけで決める）。区切りの字と
# 数字は重ならないので総当たりにならない
_SEP = "[\\s\\-‐‑‒–—―−－ー()（）.．・/／、,，､]"
_DIGIT_RUN_RE = re.compile(f"{_D}+(?:{_SEP}+{_D}+)*")
# 漢数字の並び（九〇一二三四五六七八）。十・百 等の位取りの字は数字として数えない
_KANJI_DIGITS = "〇零一二三四五六七八九"
_KANJI_DIGIT_RUN_RE = re.compile(f"[{_KANJI_DIGITS}](?:{_SEP}*[{_KANJI_DIGITS}])*")
# 数える前に伏せる日付・時刻・小数（同じ長さの別の文字に置き換え、位置はずらさない）
_DATE_TIME_RES = (
    re.compile(
        f"(?:19|20|１９|２０){_D}{{2}}[-/.／－年]{_D}{{1,2}}[-/.／－月]{_D}{{1,2}}日?"
    ),
    re.compile(f"{_D}{{1,2}}[/／月]{_D}{{1,2}}日?"),
    re.compile(f"{_D}{{1,2}}[:：]{_D}{{2}}(?:[:：]{_D}{{2}})?"),
    re.compile(f"{_D}{{1,2}}時(?:{_D}{{1,2}}分)?"),
    # 体温・体重・量の小数（37.9、52.3、0.5）。090.1234 のような続きは消さない
    re.compile(
        f"(?<![0-9０-９.．]){_D}{{1,3}}[.．]{_D}{{1,2}}(?![0-9０-９]|[.．]{_D})"
    ),
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
    for m in _KANJI_DIGIT_RUN_RE.finditer(text):
        if sum(ch in _KANJI_DIGITS for ch in m.group(0)) >= MIN_DIGITS:
            found.append(Detection(RULE_LONG_DIGITS, m.start(), m.end()))
    return found


# ---------------------------------------------------------------------------
# at_mark
# ---------------------------------------------------------------------------

_AT_RE = re.compile("[@＠﹫]")
# 依頼文に埋め込まれる PipelineInput の JSON の Skill の版（キーと引用符まで一致したもの）。
# 開きの引用符の前が \ でない（JSON の文字列の中の \" ではない）ことを確かめる
_SKILL_VERSION_FIELD_RE = re.compile(
    r'(?<!\\)"(?:regimen_skill_version|report_skill_version|skill_version)"'
    r'[ ]?:[ ]?"(?:regimen|report-format)-[a-z0-9-]{1,40}@\d{1,4}"'
)


def _at_detections(text: str, *, skill_fields: bool) -> list[Detection]:
    scratch = _blank(text, (_SKILL_VERSION_FIELD_RE,)) if skill_fields else text
    return [
        Detection(RULE_AT_MARK, m.start(), m.end()) for m in _AT_RE.finditer(scratch)
    ]


# ---------------------------------------------------------------------------
# JSON の文字列エスケープ（依頼文全体のときだけ）
# ---------------------------------------------------------------------------

# 左から順に読む（\\" は「\\」＋本物の閉じ引用符）。\uXXXX の16進も字として数えない
_JSON_ESCAPE_RE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])')


# 改行を表すエスケープ（\n・\r・\u000a・\u000d・\u2028・\u2029）
_JSON_LINE_BREAKS = frozenset(
    {"\\n", "\\r", "\\u000a", "\\u000d", "\\u2028", "\\u2029"}
)


def _blank_escape(m: re.Match[str]) -> str:
    # 改行のエスケープは「改行＋空白」にする（患者の文と同じく、改行の後の例外が働く）
    escape = m.group(0)
    if escape.lower() in _JSON_LINE_BREAKS:
        return "\n" + " " * (len(escape) - 1)
    return " " * len(escape)


def blank_json_escapes(text: str) -> str:
    """JSON の文字列エスケープを同じ長さの空白にした文（位置はずらさない）。

    改行のエスケープだけは先頭を改行にする（「だるい\\n医院へ」を患者の文と同じに扱う）。
    """
    return _JSON_ESCAPE_RE.sub(_blank_escape, text)


# ---------------------------------------------------------------------------
# まとめ
# ---------------------------------------------------------------------------


def detect_identifiers(text: str) -> list[Detection]:
    """伏せ字漏れの候補を位置順に返す。空なら送ってよい。

    依頼文全体（H1・convert②）用。JSON の文字列エスケープを同じ長さの空白とみなし、
    JSON のキー付きの Skill の版だけは `@` として数えない。位置は元の text のもの。
    患者の文だけを見るときは detect_in_patient_text（例外なし）を使う。
    """
    _require_str(text)
    return _detect(blank_json_escapes(text), skill_fields=True)


def detect_in_patient_text(text: str) -> list[Detection]:
    """患者の文（一次の後）の伏せ字漏れの候補。detect_identifiers と違い例外が無い。"""
    _require_str(text)
    return _detect(text, skill_fields=False)


def _require_str(text: object) -> None:
    if not isinstance(text, str):
        raise TypeError("detect_identifiers は str だけを受け付ける")


def _detect(text: str, *, skill_fields: bool) -> list[Detection]:
    found = (
        [
            Detection(RULE_UNKNOWN_BEFORE_HONORIFIC, s, e)
            for s, e in honorific_spans(text)
        ]
        + _digit_detections(text)
        + _at_detections(text, skill_fields=skill_fields)
        + [Detection(RULE_BEFORE_FACILITY, s, e) for s, e in facility_spans(text)]
        + [Detection(RULE_ADDRESS_NUMBER, s, e) for s, e in address_spans(text)]
        + [Detection(RULE_ID_LIKE, s, e) for s, e in id_like_spans(text)]
    )
    return sorted(found, key=lambda d: (d.start, d.end, RULES.index(d.rule)))
