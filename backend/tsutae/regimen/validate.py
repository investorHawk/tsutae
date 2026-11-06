"""フォームの値の検査（spec 9.1「投与スケジュールの検査」「値の形の検査」）。

- `validate_form`: 入っている値だけを見る（下書きの途中でも使える。`set_fields`・PATCH）
- `missing_fields`: 採用・描画の前に要るもの（必須の欄・Day1 の点滴・体温の質問）
- `validate_complete_form`: 両方。描画（render.py）と採用はこれが空でないと進まない

掛かった欄は `FieldIssue(field_id, code, message)` で返す。message に入力の文面は入れない
（H1 に掛かった文をそのまま画面・ログに戻さない）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from functools import lru_cache
from itertools import pairwise
from typing import Any

from tsutae.regimen.form import DayRange, DrugRow, RegimenForm, SideEffectRow
from tsutae.regimen.text_checks import (
    FieldIssue,
    identifier_issue,
    text_issues,
    yaml_issue,
)
from tsutae.schemas import QUESTION_KEY_PATTERN, REGIMEN_CODE_PATTERN
from tsutae.synthetic import load_terms

CYCLE_DAYS_MIN, CYCLE_DAYS_MAX = 7, 42
TIMES_PER_DAY_MIN, TIMES_PER_DAY_MAX = 1, 4
MAX_CODE = 30
MAX_DISPLAY_NAME = 40
MAX_TARGET = 40
MAX_DRUG_NAME = 40
MAX_START_NOTE = 40
MAX_PHRASE = 40
MAX_LABEL = 20
MAX_QUESTION_TEXT = 200
MAX_NOTES = 2000
MAX_DRUGS, MAX_SIDE_EFFECTS, MAX_QUESTIONS = 10, 30, 20
MAX_RANGES, MAX_PHRASES, MAX_TERMS = 10, 5, 5

ROW_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,31}$"
_ROW_ID_RE = re.compile(ROW_ID_PATTERN)
_CODE_RE = re.compile(REGIMEN_CODE_PATTERN)
_QUESTION_KEY_RE = re.compile(QUESTION_KEY_PATTERN)
# 描画で frontmatter に入る文の形（値を {v} に入れて YAML で読み戻す）
DESCRIPTION_TEMPLATE = (
    "{v} の投与スケジュール・クローズ質問集・固定規則。記録の変換時に使う"
)


@lru_cache(maxsize=1)
def known_terms() -> frozenset[str]:
    """選べる用語（ctcae_terms.json）。"""
    return frozenset(item["term"] for item in load_terms())


def _filled(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def _identifier_issues(
    field_id: str, value: str, yaml_checks: tuple[tuple[str, Any], ...]
) -> Iterator[FieldIssue]:
    """書式（正規表現）を通った識別名・key の H1 と YAML の読み戻し。

    YAML 1.1 では NO・null・on などが真偽・null に読めるので、書式に合っても
    frontmatter（`regimen:`・`questions[].key`・`term_keys` の値・`question_key`）に
    入れると文字列に戻らない。
    """
    for issue in (identifier_issue(field_id, value), yaml_issue(field_id, yaml_checks)):
        if issue is not None:
            yield issue


def key_yaml_checks(key: str) -> tuple[tuple[str, Any], ...]:
    """質問の key が入る frontmatter の形（questions のフロー形式・ブロックの値）。"""
    return (
        (
            f"- {{key: {key}, text: t, answer_type: three_level}}",
            [{"key": key, "text": "t", "answer_type": "three_level"}],
        ),
        (f"term: {key}", {"term": key}),
    )


# ---------------------------------------------------------------------------
# 行の id
# ---------------------------------------------------------------------------


def _row_id_issues(section: str, rows: Iterable[Any]) -> Iterator[FieldIssue]:
    seen: set[str] = set()
    for i, row in enumerate(rows):
        if not _ROW_ID_RE.fullmatch(row.row_id):
            yield FieldIssue(f"{section}.#{i}", "row_id", "行の id の書式が違う")
        elif row.row_id in seen:
            yield FieldIssue(
                f"{section}.{row.row_id}", "duplicate_row", "行の id が重複"
            )
        seen.add(row.row_id)


def _count_issue(section: str, rows: list[Any], limit: int) -> Iterator[FieldIssue]:
    if len(rows) > limit:
        yield FieldIssue(section, "too_many", f"{limit} 行までにする")


# ---------------------------------------------------------------------------
# 基本
# ---------------------------------------------------------------------------


def _basic_issues(form: RegimenForm) -> Iterator[FieldIssue]:
    basic = form.basic
    if _filled(basic.display_name):
        v = basic.display_name or ""
        yield from text_issues(
            "basic.display_name",
            v,
            max_len=MAX_DISPLAY_NAME,
            yaml_checks=(
                (f"display_name: {v}", {"display_name": v}),
                (
                    "description: " + DESCRIPTION_TEMPLATE.format(v=v),
                    {"description": DESCRIPTION_TEMPLATE.format(v=v)},
                ),
            ),
        )
    if _filled(basic.code):
        code = basic.code or ""
        if len(code) > MAX_CODE or not _CODE_RE.fullmatch(code):
            yield FieldIssue(
                "basic.code",
                "pattern",
                f"英大文字で始め、英大文字・数字・「-」で {MAX_CODE} 字まで",
            )
        else:
            yield from _identifier_issues(
                "basic.code", code, ((f"regimen: {code}", {"regimen": code}),)
            )
    if _filled(basic.target):
        yield from text_issues("basic.target", basic.target or "", max_len=MAX_TARGET)
    days = basic.cycle_days
    if days is not None and not CYCLE_DAYS_MIN <= days <= CYCLE_DAYS_MAX:
        yield FieldIssue(
            "basic.cycle_days",
            "out_of_range",
            f"{CYCLE_DAYS_MIN}〜{CYCLE_DAYS_MAX} 日にする",
        )


# ---------------------------------------------------------------------------
# 投与スケジュール
# ---------------------------------------------------------------------------


def _range_issues(
    fid: str, ranges: list[DayRange], cycle_days: int | None
) -> Iterator[FieldIssue]:
    if len(ranges) > MAX_RANGES:
        yield FieldIssue(fid, "too_many", f"Day の範囲は {MAX_RANGES} 個まで")
    limit = cycle_days if cycle_days is not None else CYCLE_DAYS_MAX
    for r in ranges:
        if r.start > r.end:
            yield FieldIssue(fid, "reversed", "範囲の始まりが終わりより後")
        if r.start < 1 or r.end > limit:
            yield FieldIssue(fid, "out_of_range", "Day は 1 から 1コースの日数まで")
    for prev, cur in pairwise(ranges):
        if cur.start < prev.start:
            yield FieldIssue(fid, "order", "Day の範囲は早い順に並べる")
        elif cur.start <= prev.end:
            yield FieldIssue(fid, "overlap", "Day の範囲が重なっている")
        elif cur.start == prev.end + 1:
            yield FieldIssue(fid, "adjacent", "隣り合う Day の範囲は1つにつなげる")


def _drug_issues(
    drug: DrugRow, cycle_days: int | None, counts: dict[str, int]
) -> Iterator[FieldIssue]:
    base = f"drugs.{drug.row_id}"
    if _filled(drug.name):
        yield from text_issues(f"{base}.name", drug.name or "", max_len=MAX_DRUG_NAME)
    yield from _range_issues(f"{base}.days", drug.days, cycle_days)
    if drug.route == "pump":
        counts["pump"] += 1
        if counts["pump"] > 1:
            yield FieldIssue(f"{base}.route", "too_many_pumps", "持続ポンプは1剤まで")
        if drug.days and (len(drug.days) != 1 or drug.days[0].start != 1):
            yield FieldIssue(
                f"{base}.days", "pump_range", "持続ポンプは Day1 から始まる範囲1つ"
            )
    if drug.route == "oral":
        counts["oral"] += 1
        if counts["oral"] > 1:
            yield FieldIssue(f"{base}.route", "too_many_orals", "内服は1剤まで")
        times = drug.times_per_day
        if times is not None and not TIMES_PER_DAY_MIN <= times <= TIMES_PER_DAY_MAX:
            yield FieldIssue(
                f"{base}.times_per_day",
                "out_of_range",
                f"1日 {TIMES_PER_DAY_MIN}〜{TIMES_PER_DAY_MAX} 回にする",
            )
        if _filled(drug.start_note):
            yield from text_issues(
                f"{base}.start_note", drug.start_note or "", max_len=MAX_START_NOTE
            )
    else:
        if drug.times_per_day is not None:
            yield FieldIssue(
                f"{base}.times_per_day", "not_oral", "内服の薬だけに入れる"
            )
        if _filled(drug.start_note):
            yield FieldIssue(f"{base}.start_note", "not_oral", "内服の薬だけに入れる")


def _schedule_issues(form: RegimenForm) -> Iterator[FieldIssue]:
    yield from _count_issue("drugs", form.drugs, MAX_DRUGS)
    yield from _row_id_issues("drugs", form.drugs)
    counts = {"pump": 0, "oral": 0}
    for drug in form.drugs:
        yield from _drug_issues(drug, form.basic.cycle_days, counts)


# ---------------------------------------------------------------------------
# 副作用と質問
# ---------------------------------------------------------------------------


def _side_effect_issues(
    row: SideEffectRow, question_keys: set[str], used_terms: set[str]
) -> Iterator[FieldIssue]:
    base = f"side_effects.{row.row_id}"
    if len(row.phrases) > MAX_PHRASES:
        yield FieldIssue(f"{base}.phrases", "too_many", f"{MAX_PHRASES} 個まで")
    seen_phrases: set[str] = set()
    for phrase in row.phrases:
        if not _filled(phrase):
            yield FieldIssue(f"{base}.phrases", "empty_item", "空の言い方がある")
        else:
            yield from text_issues(f"{base}.phrases", phrase, max_len=MAX_PHRASE)
            if phrase in seen_phrases:
                yield FieldIssue(
                    f"{base}.phrases", "duplicate_phrase", "同じ言い方が2つある"
                )
        seen_phrases.add(phrase)
    if len(row.ctcae_terms) > MAX_TERMS:
        yield FieldIssue(f"{base}.ctcae_terms", "too_many", f"{MAX_TERMS} 個まで")
    terms = known_terms()
    for term in row.ctcae_terms:
        if term not in terms:
            yield FieldIssue(
                f"{base}.ctcae_terms", "unknown_term", "用語の一覧に無い語"
            )
        elif term in used_terms:
            yield FieldIssue(
                f"{base}.ctcae_terms", "duplicate_term", "同じ用語が別の行にもある"
            )
        used_terms.add(term)
    key = row.question_key
    if key is not None and key not in question_keys:
        yield FieldIssue(
            f"{base}.question_key", "unknown_question", "このレジメンの質問に無い"
        )


def _question_issues(form: RegimenForm) -> Iterator[FieldIssue]:
    yield from _count_issue("questions", form.questions, MAX_QUESTIONS)
    yield from _row_id_issues("questions", form.questions)
    seen_keys: set[str] = set()
    temperature = 0
    for q in form.questions:
        base = f"questions.{q.row_id}"
        if q.key is not None:
            if not _QUESTION_KEY_RE.fullmatch(q.key):
                yield FieldIssue(
                    f"{base}.key", "pattern", "英小文字で始め、英小文字・数字・下線"
                )
            elif q.key in seen_keys:
                yield FieldIssue(f"{base}.key", "duplicate", "質問の key が重複")
            else:
                yield from _identifier_issues(
                    f"{base}.key", q.key, key_yaml_checks(q.key)
                )
            seen_keys.add(q.key)
        if _filled(q.label):
            yield from text_issues(f"{base}.label", q.label or "", max_len=MAX_LABEL)
        if _filled(q.text):
            text = q.text or ""
            yield from text_issues(
                f"{base}.text",
                text,
                max_len=MAX_QUESTION_TEXT,
                yaml_checks=(
                    (
                        f"- {{key: qkey, text: {text}, answer_type: three_level}}",
                        [{"key": "qkey", "text": text, "answer_type": "three_level"}],
                    ),
                ),
            )
        if q.answer_type == "temperature":
            temperature += 1
            if temperature > 1:
                yield FieldIssue(
                    f"{base}.answer_type",
                    "too_many_temperature",
                    "体温の質問は1つだけ",
                )


def _notes_issues(form: RegimenForm) -> Iterator[FieldIssue]:
    if _filled(form.notes):
        yield from text_issues("notes", form.notes, max_len=MAX_NOTES, multiline=True)


def _prose_issues(form: RegimenForm) -> Iterator[FieldIssue]:
    prose = form.prose
    if prose is None:
        return
    texts = [
        prose.intro_note,
        prose.cycle_note,
        prose.day1_note,
        prose.pump_sentence or "",
        prose.no_pump_note,
        prose.oral_note,
        *(prose.improving_examples or []),
    ]
    example = prose.contradiction_example
    if example is not None:
        texts += [example.closed_label, example.question_key, example.quote]
    if any("\n" in t or "\r" in t or "|" in t for t in texts):
        yield FieldIssue("prose", "line_break", "描画用の文に改行・「|」がある")


# ---------------------------------------------------------------------------
# 公開
# ---------------------------------------------------------------------------


def validate_form(form: RegimenForm) -> list[FieldIssue]:
    """入っている値の検査（空の欄は咎めない）。掛かった欄の id と理由を返す。"""
    question_keys = {q.key for q in form.questions if q.key is not None}
    used_terms: set[str] = set()
    issues = [*_basic_issues(form), *_schedule_issues(form)]
    issues += _count_issue("side_effects", form.side_effects, MAX_SIDE_EFFECTS)
    issues += _row_id_issues("side_effects", form.side_effects)
    for row in form.side_effects:
        issues += _side_effect_issues(row, question_keys, used_terms)
    issues += [*_question_issues(form), *_notes_issues(form), *_prose_issues(form)]
    return issues


def _required(field_id: str, message: str = "入力が要る") -> FieldIssue:
    return FieldIssue(field_id, "required", message)


def _missing_drug_fields(drug: DrugRow) -> Iterator[FieldIssue]:
    base = f"drugs.{drug.row_id}"
    if not _filled(drug.name):
        yield _required(f"{base}.name")
    if drug.route is None:
        yield _required(f"{base}.route")
    if not drug.days:
        yield _required(f"{base}.days")
    if drug.route == "oral":
        if drug.times_per_day is None:
            yield _required(f"{base}.times_per_day")
        if not _filled(drug.start_note):
            yield _required(f"{base}.start_note")


def _missing_schedule(form: RegimenForm) -> Iterator[FieldIssue]:
    if not form.drugs:
        yield _required("drugs", "薬を1剤以上入れる")
        return
    for drug in form.drugs:
        yield from _missing_drug_fields(drug)
    day1 = any(
        d.route == "infusion" and any(r.start <= 1 <= r.end for r in d.days)
        for d in form.drugs
    )
    if not day1:
        yield FieldIssue(
            "drugs", "day1_infusion", "Day1 に点滴を1剤以上置く（Day1 = 実投与日）"
        )


def _missing_rows(form: RegimenForm) -> Iterator[FieldIssue]:
    if not form.side_effects:
        yield _required("side_effects", "注意する症状を1つ以上入れる")
    for row in form.side_effects:
        base = f"side_effects.{row.row_id}"
        if not row.phrases:
            yield _required(f"{base}.phrases")
        if not row.ctcae_terms:
            yield _required(f"{base}.ctcae_terms")
    if not form.questions:
        yield _required("questions", "質問を1問以上入れる")
    for q in form.questions:
        base = f"questions.{q.row_id}"
        for name in ("key", "label", "text"):
            if not _filled(getattr(q, name)):
                yield _required(f"{base}.{name}")
        if q.answer_type is None:
            yield _required(f"{base}.answer_type")
    if not any(q.answer_type == "temperature" for q in form.questions):
        yield FieldIssue(
            "questions", "temperature_required", "体温の質問（38.0℃の固定規則）が要る"
        )


def missing_fields(form: RegimenForm) -> list[FieldIssue]:
    """採用・描画の前に要るものの欠け（必須の欄・Day1 の点滴・体温の質問）。"""
    basic = form.basic
    issues = [
        _required(f"basic.{name}")
        for name in ("display_name", "code")
        if not _filled(getattr(basic, name))
    ]
    if basic.cycle_days is None:
        issues.append(_required("basic.cycle_days"))
    return [*issues, *_missing_schedule(form), *_missing_rows(form)]


def validate_complete_form(form: RegimenForm) -> list[FieldIssue]:
    """`validate_form` ＋ `missing_fields`。空なら描画・採用に進める。"""
    return [*validate_form(form), *missing_fields(form)]
