"""変換の入力を作る（今コースの選別・通し番号・伏せ字・未処理の記録）。

- 今コースは `course.current_course(courses, visit_date)`。対象は Day1〜
  min(最終日, visit_date) の記録だけ（docs/architecture.md §7）
- 範囲外（Day1 より前・最終日より後・visit_date より後）の記録は**黙って外す**
  （`UnprocessedEntry` にしない。§7 W2b）。件数は logger があれば
  `input_prepared` の decision `out_of_range_count:N` に残す
- 送る記録だけに recorded_at 順で entry_no=1,2,… を振る（外した記録は番号を使わない）
- 自由記載は原文のまま `masking.check_text`（正規化 → 一次 → 二次）に掛ける。改行・
  制御文字・書式文字の正規化は masking の責務で、pipeline では整形しない。masked_texts は
  check_text の masked そのもの（改行を含みうる。H2 の部分一致と食い違わない）
- 外す記録（`UnprocessedEntry(entry_id, reason)`。原文は D6 だけに出る）:
  1. 自由記載に `exclude_literals`（service が渡す仮名ID・受付番号）を含む →
     `known_identifier`。NFKC＋casefold のあと文字・数字以外（区切り記号・空白・
     制御文字・書式文字・長音符）を全て除いて比べる（A023・P_DEMO0001 も一致）。
     一次が `[ID]` に置き換える前の原文で比べる
  2. 二次に掛かった → 最初の規則名
  3. 伏せ字後の文を JSON にした形（依頼文での見え方）で二次に掛かった → 最初の規則名
- 「つらくて書けない」の記録も入れる（too_sick=True、回答・自由記載なし）
- 仮名ID・受付番号は構造の項目に入れない。引数は書き換えない
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Sequence
from datetime import date

from tsutae.course import build_schedule, current_course, day_of
from tsutae.masking import check_text, detect_identifiers
from tsutae.pipeline.logs import EventLogger
from tsutae.schemas import (
    Course,
    CourseSchedule,
    Entry,
    MaskedEntry,
    PipelineInput,
    PreparedInput,
    RegimenSkill,
    ReportFormatSkill,
    UnprocessedEntry,
)

__all__ = [
    "REASON_KNOWN_IDENTIFIER",
    "PrepareInputError",
    "mask_free_text",
    "prepare_input",
]

REASON_KNOWN_IDENTIFIER = "known_identifier"
INPUT_PREPARED_EVENT = "input_prepared"
# 区切りに使われる長音符（Lm なので文字として残ってしまう）。半角 ｰ は NFKC で ー
_PROLONGED_MARKS = frozenset("ー")


class PrepareInputError(ValueError):
    """入力を作れない。`code` は短い英字（no_current_course / patient_mismatch）。"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


def _check_same_patient(courses: Sequence[Course], entries: Sequence[Entry]) -> None:
    patient_ids = {c.patient_id for c in courses} | {e.patient_id for e in entries}
    if len(patient_ids) > 1:
        raise PrepareInputError(
            "patient_mismatch", "別の患者の記録・コースが混ざっている"
        )


def _in_course(
    entries: Sequence[Entry],
    schedule: CourseSchedule,
    courses: Sequence[Course],
    until: date,
) -> list[tuple[Entry, int]]:
    """今コースの Day1〜until の記録を (記録, Day) で recorded_at 順に返す。"""
    picked = []
    for entry in sorted(entries, key=lambda e: (e.recorded_at, e.id)):
        if entry.record_date > until:
            continue
        day = day_of(entry.record_date, schedule, courses=courses)
        if day is not None:
            picked.append((entry, day))
    return picked


def _masked_entry(
    entry: Entry, entry_no: int, day: int, masked: str | None
) -> MaskedEntry:
    return MaskedEntry(
        entry_no=entry_no,
        record_date=entry.record_date,
        day=day,
        by_proxy=entry.by_proxy,
        too_sick=entry.kind == "too_sick",
        answers=list(entry.answers),
        masked_free_text=masked,
    )


def mask_free_text(text: str | None) -> tuple[str | None, str | None]:
    """(伏せ字後の文, 外す理由)。理由があれば送らない。空の文は (None, None)。

    prepare_input と同じ手順（exclude_literals の照合を除く）。report.gate もこれを呼ぶ
    （写しを持たない。正規化して空になる文を片方だけ '' にすると entry_mismatch）。
    """
    if not text or not text.strip():
        return None, None
    check = check_text(text)
    if check.reason is not None:
        return None, check.reason
    if not check.masked.strip():
        return None, None
    in_prompt = detect_identifiers(json.dumps(check.masked, ensure_ascii=False))
    if in_prompt:
        return None, in_prompt[0].rule
    return check.masked, None


def _fold(text: str) -> str:
    """識別子の比較用: NFKC → casefold → 文字（L 系）と数字（N 系）だけを残す。

    記号・句読点（P 系: ハイフン・下線・中黒・ピリオド・スラッシュ等、S 系）、制御・
    書式文字（C 系）、空白（Z 系）と長音符「ー」は全て除く。`A023`・`A・023`・
    `P_DEMO0001`・`P-\nDEMO0001` を `A-023`・`P-DEMO0001` と同じに扱う（一次・二次の
    正規表現は区切りの崩れた形を拾いきれない）。照合する側の文字列も同じく畳む。
    誤って一致した記録は送らないだけ（安全側）。
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if _is_id_char(ch))


def _is_id_char(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LN" and ch not in _PROLONGED_MARKS


def _fold_literals(literals: Sequence[str]) -> tuple[str, ...]:
    if isinstance(literals, str) or not isinstance(literals, Sequence):
        raise TypeError("exclude_literals は文字列の列（str そのものは不可）")
    if not all(isinstance(lit, str) for lit in literals):
        raise TypeError("exclude_literals の要素は str")
    return tuple(folded for folded in map(_fold, literals) if folded)


def _has_literal(text: str, folded_literals: tuple[str, ...]) -> bool:
    folded = _fold(text)
    return any(lit in folded for lit in folded_literals)


def _select(
    picked: list[tuple[Entry, int]], folded_literals: tuple[str, ...]
) -> tuple[list[MaskedEntry], dict[int, int], dict[int, str], list[UnprocessedEntry]]:
    """伏せ字を掛け、送る記録に entry_no を振る。外す記録は理由つきで返す。"""
    masked_entries: list[MaskedEntry] = []
    entry_ids: dict[int, int] = {}
    masked_texts: dict[int, str] = {}
    unprocessed: list[UnprocessedEntry] = []
    for entry, day in picked:
        masked: str | None = None
        if entry.free_text:
            if _has_literal(entry.free_text, folded_literals):
                reason: str | None = REASON_KNOWN_IDENTIFIER
            else:
                masked, reason = mask_free_text(entry.free_text)
            if reason is not None:
                unprocessed.append(UnprocessedEntry(entry_id=entry.id, reason=reason))
                continue
        entry_no = len(masked_entries) + 1
        masked_entries.append(_masked_entry(entry, entry_no, day, masked))
        entry_ids[entry_no] = entry.id
        if masked:
            masked_texts[entry_no] = masked
    return masked_entries, entry_ids, masked_texts, unprocessed


def _schedule_for(
    courses: Sequence[Course], regimen_skill: RegimenSkill, visit_date: date
) -> CourseSchedule:
    course = current_course(courses, visit_date)
    if course is None:
        raise PrepareInputError("no_current_course", "受診日より前の実投与日が無い")
    return build_schedule(
        courses,
        course.course_no,
        regimen_skill.cycle_days,
        regimen_skill.pump_removal_day,
    )


def prepare_input(
    *,
    courses: Sequence[Course],
    entries: Sequence[Entry],
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
    visit_date: date,
    exclude_literals: Sequence[str] = (),
    logger: EventLogger | None = None,
) -> PreparedInput:
    """受診日の今コースの記録から、Claude に送る入力を作る。"""
    folded_literals = _fold_literals(exclude_literals)
    _check_same_patient(courses, entries)
    schedule = _schedule_for(courses, regimen_skill, visit_date)
    until = min(schedule.last_day_date, visit_date)
    picked = _in_course(entries, schedule, courses, until)
    masked_entries, entry_ids, masked_texts, unprocessed = _select(
        picked, folded_literals
    )
    if logger is not None:
        out_of_range = len(entries) - len(picked)
        logger.event(
            INPUT_PREPARED_EVENT, decision=f"out_of_range_count:{out_of_range}"
        )
    return PreparedInput(
        input=PipelineInput(
            regimen=regimen_skill.regimen,
            regimen_skill_version=regimen_skill.skill_version,
            report_skill_version=report_skill.skill_version,
            schedule=schedule,
            questions=list(regimen_skill.questions),
            entries=masked_entries,
        ),
        entry_ids=entry_ids,
        masked_texts=masked_texts,
        unprocessed=unprocessed,
    )
