"""経過表（Grid）の組み立て。決定的な純関数。docs/architecture.md §7b。

- セルはその日の記録のクローズ回答から決める。AI の結果は ○（free_text_mark）と
  「回」（recalled_mark）だけに使い、それも今コースの行だけ。出来事は
  validate.usable_events で照合済みのもの（行は用語一覧の question_key と一致した
  ものだけ、「回」は記録日と出来事の日付からコードで決め直した値）
- 欠けを区別する: 記録なし=no_input、その質問の回答が無く too_sick の記録がある日=
  too_sick（自由記載だけの記録が同じ日にあっても）、その日の記録の版の質問集に無い
  質問=not_asked、記録はあるがその質問の回答が無い=no_input
- 版の質問集は questions_by_version（今の regimen Skill の版は Skill の質問集でよい）。
  それ以外の版が無ければ ReportBuildError（未設問と入力なしを取り違えない）
- 体温の質問（answer_type temperature）は体温行（question_key "temperature"）に畳む。
  測った=present（temperature に最高値）、測っていない=none
- そのコースの範囲外（受診日より後・そのコースに無い Day）のセルは作らない
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from tsutae import course as course_mod
from tsutae.report.errors import ReportBuildError
from tsutae.report.labels import TEMPERATURE_ROW_KEY, question_label
from tsutae.schemas import (
    CellState,
    ClosedAnswer,
    Course,
    CourseSchedule,
    Entry,
    Grid,
    GridCell,
    GridColumn,
    GridRow,
    Question,
    RegimenSkill,
    ReportFormatSkill,
    TimelineEvent,
)

Records = Mapping[date, tuple[Entry, ...]]
Marks = Mapping[tuple[str, int], bool]  # (行の key, Day) -> ○ が全て回想由来か

_THREE_LEVEL_RANK: Mapping[str, int] = {"none": 0, "present": 1, "hard": 2}
_THREE_LEVEL_STATE: Mapping[str, CellState] = {
    "none": "none",
    "present": "present",
    "hard": "hard",
}
_TEMPERATURE_VALUES = frozenset({"measured", "not_measured"})
_MARKED_STATUSES = frozenset({"present", "improving"})


@dataclass(frozen=True)
class RowSpec:
    key: str  # GridRow.question_key（体温行は "temperature"）
    label: str
    question: Question


@dataclass(frozen=True)
class CourseSpan:
    """経過表に載せる1コース分の Day の範囲。until より後の日はセルを作らない。"""

    schedule: CourseSchedule
    days: tuple[int, ...]
    until: date | None = None

    def date_of(self, day: int) -> date:
        return self.schedule.day1_date + timedelta(days=day - 1)

    def has_cell(self, day: int) -> bool:
        if day not in self.days:
            return False
        return self.until is None or self.date_of(day) <= self.until


@dataclass(frozen=True)
class QuestionSets:
    """版ごとの質問 key。知らない版は補わない（asked が ReportBuildError）。"""

    by_version: Mapping[str, frozenset[str]]

    @classmethod
    def build(
        cls,
        questions_by_version: Mapping[str, Sequence[Question]],
        current: RegimenSkill,
    ) -> QuestionSets:
        by_version = {
            v: frozenset(q.key for q in qs) for v, qs in questions_by_version.items()
        }
        by_version.setdefault(
            current.skill_version, frozenset(q.key for q in current.questions)
        )
        return cls(by_version=by_version)

    def asked(self, skill_version: str, key: str) -> bool:
        keys = self.by_version.get(skill_version)
        if keys is None:
            raise ReportBuildError(
                "unknown_skill_version", f"{skill_version} の質問集が無い"
            )
        return key in keys


def group_by_date(entries: Sequence[Entry]) -> dict[date, tuple[Entry, ...]]:
    """記録日ごとに、記録日時順（同時刻は id 順）に束ねる。"""
    grouped: dict[date, list[Entry]] = {}
    for e in sorted(entries, key=lambda x: (x.recorded_at, x.id)):
        grouped.setdefault(e.record_date, []).append(e)
    return {d: tuple(es) for d, es in sorted(grouped.items())}


def row_specs(
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
    labels: Mapping[str, str] | None = None,
) -> list[RowSpec]:
    """3択の質問（Skill の順）＋体温行（show_temperature_row のとき、最初の体温の質問）。

    labels は版の form の短い名前（labels.question_label の順に使う）。
    """
    questions = list(regimen_skill.questions)
    rows = [
        RowSpec(q.key, question_label(q.key, questions, labels), q)
        for q in questions
        if q.answer_type == "three_level"
    ]
    temperature = next((q for q in questions if q.answer_type == "temperature"), None)
    if report_skill.show_temperature_row and temperature is not None:
        label = question_label(TEMPERATURE_ROW_KEY, questions, labels)
        rows.append(RowSpec(TEMPERATURE_ROW_KEY, label, temperature))
    return rows


def _merge_answers(
    answers: Sequence[ClosedAnswer], question: Question
) -> tuple[CellState, float | None] | None:
    """同じ日の回答をまとめる。3択は重い方（hard > present > none）、体温は最高値。"""
    if question.answer_type == "temperature":
        valid = [a for a in answers if a.value in _TEMPERATURE_VALUES]
        if not valid:
            return None
        temps = [a.temperature for a in valid if a.temperature is not None]
        return ("present", max(temps)) if temps else ("none", None)
    values = [a.value for a in answers if a.value in _THREE_LEVEL_RANK]
    if not values:
        return None
    return _THREE_LEVEL_STATE[max(values, key=_THREE_LEVEL_RANK.__getitem__)], None


def cell_state(
    day_entries: Sequence[Entry], question: Question, sets: QuestionSets
) -> tuple[CellState, float | None]:
    """その日のセル。回答 → too_sick → 未設問 → 入力なし の順に決める。"""
    if not day_entries:
        return "no_input", None
    answering = [e for e in day_entries if e.kind != "too_sick"]
    answers = [
        a for e in answering for a in e.answers if a.question_key == question.key
    ]
    merged = _merge_answers(answers, question)
    if merged is not None:
        return merged
    if len(answering) < len(day_entries):  # too_sick の記録がある
        return "too_sick", None
    if not any(sets.asked(e.skill_version, question.key) for e in answering):
        return "not_asked", None
    return "no_input", None


def event_marks(
    events: Sequence[TimelineEvent],
    schedule: CourseSchedule,
    courses: Sequence[Course],
    rows: Sequence[RowSpec],
) -> dict[tuple[str, int], bool]:
    """今コースの出来事（present/improving）から ○ を置く (行, Day) と「回」の有無。

    events は validate.usable_events を通したもの（recalled はコードで決め直した値）。
    Day は AI の day ではなく出来事の暦日から数え直す。今コースより前の日は載せない。
    「回」は、その ○ を支える出来事が全て回想のときだけ。
    """
    row_of = {spec.question.key: spec.key for spec in rows}
    found: dict[tuple[str, int], list[bool]] = {}
    for ev in events:
        if ev.status not in _MARKED_STATUSES or ev.question_key not in row_of:
            continue
        day = course_mod.day_of(ev.date, schedule, courses=courses)
        if day is None:
            continue
        found.setdefault((row_of[ev.question_key], day), []).append(ev.recalled)
    return {k: all(flags) for k, flags in sorted(found.items())}


def _course_rows(
    span: CourseSpan,
    rows: Sequence[RowSpec],
    records: Records,
    sets: QuestionSets,
    marks: Marks,
    *,
    is_previous: bool,
) -> list[GridRow]:
    result = []
    for spec in rows:
        cells = []
        for day in span.days:
            if not span.has_cell(day):
                continue
            state, temp = cell_state(
                records.get(span.date_of(day), ()), spec.question, sets
            )
            mark = (spec.key, day) in marks
            cells.append(
                GridCell(
                    day=day,
                    state=state,
                    free_text_mark=mark,
                    recalled_mark=mark and marks[(spec.key, day)],
                    temperature=temp,
                )
            )
        result.append(
            GridRow(
                course_no=span.schedule.course_no,
                question_key=spec.key,
                label=spec.label,
                is_previous_course=is_previous,
                cells=cells,
            )
        )
    return result


def _column(day: int, current: CourseSpan, records: Records) -> GridColumn:
    if day not in current.days:
        return GridColumn(day=day, date=None)
    d = current.date_of(day)
    recs = records.get(d, ()) if current.has_cell(day) else ()
    return GridColumn(
        day=day,
        date=d,
        by_proxy=any(e.by_proxy for e in recs),
        too_sick=any(e.kind == "too_sick" for e in recs),
    )


def build_grid(
    *,
    current: CourseSpan,
    previous: CourseSpan | None,
    rows: Sequence[RowSpec],
    records: Records,
    sets: QuestionSets,
    marks: Marks,
) -> Grid:
    """今コースの行＋（あれば）前コースの行。前コースは marks を使わない（クローズのみ）。"""
    days = sorted(set(current.days) | set(previous.days if previous else ()))
    grid_rows = _course_rows(current, rows, records, sets, marks, is_previous=False)
    if previous is not None:
        grid_rows += _course_rows(previous, rows, records, sets, {}, is_previous=True)
    return Grid(
        days=days,
        columns=[_column(day, current, records) for day in days],
        rows=grid_rows,
    )
