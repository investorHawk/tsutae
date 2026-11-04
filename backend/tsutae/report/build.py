"""ReportData の組み立て（決定的: 同じ入力なら同じ出力）。docs/architecture.md §7b。

- 入口で patient_id・courses・entries・prepared・Skill の対応を確かめる
  （gate.check_inputs）。合わなければ ReportBuildError
- ヘッダ・経過表・要確認の発熱／つらくて書けない／未処理は、記録（entries）と
  コース日程からコードで決める。AI の結果（result.timeline / picks）を使うのは
  経過表の ○・「回」、要確認の食い違い、症状別の時系列だけ。どれも記録・出来事と
  照合してから使う（validate.py）
- 今コースの範囲は経過表と同じ: Day1〜max(最終日, 受診日) のうち受診日まで。次コース
  未登録で受診日が最終日より後なら Day15, 16… も数える（course.grid_days）
- AI 変換なし（result.fallback、または timeline が無い）のときは AI の部分を全て空にする
- 引用は伏せ字後の自由記載（prepared.masked_texts。入口で元の記録と照合済み）。Day は
  記録日から数える。未処理の記録（prepared.unprocessed。AI 側の値は使わない）は
  載せない。上限で切るときは受診直前の記載を残す（並びは Day 順）
- 発熱は Skill の体温の質問（answer_type temperature）への「測った」だけを見る
- 引数は書き換えない。entries・courses の並び順は結果に影響しない
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from tsutae import course as course_mod
from tsutae.report.gate import check_inputs
from tsutae.report.grid import (
    CourseSpan,
    QuestionSets,
    Records,
    build_grid,
    event_marks,
    group_by_date,
    row_specs,
)
from tsutae.report.validate import (
    usable_events,
    verified_contradictions,
    verified_per_symptom,
)
from tsutae.schemas import (
    AttentionItem,
    ConversionResult,
    Course,
    DoctorMask,
    Entry,
    Grid,
    PreparedInput,
    Question,
    QuoteItem,
    RegimenSkill,
    ReportData,
    ReportFormatSkill,
    ReportHeader,
    SymptomSummary,
    Timeline,
    TimelineEvent,
)


@dataclass(frozen=True)
class _Context:
    courses: tuple[Course, ...]
    current: CourseSpan
    previous: CourseSpan | None  # show_previous_course に関わらず、前コースがあれば
    visit_date: date
    records: Records
    by_id: Mapping[int, Entry]
    prepared: PreparedInput
    timeline: Timeline | None  # AI 変換なしなら None
    events: tuple[TimelineEvent, ...]  # 記録と照合できた出来事だけ（usable_events）


def _span(
    courses: Sequence[Course],
    course_no: int,
    skill: RegimenSkill,
    until: date | None,
) -> CourseSpan:
    schedule = course_mod.build_schedule(
        courses, course_no, skill.cycle_days, skill.pump_removal_day
    )
    days = tuple(course_mod.grid_days(schedule, until=until))
    return CourseSpan(schedule=schedule, days=days, until=until)


def _context(
    *,
    patient_id: str,
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
    courses: Sequence[Course],
    entries: Sequence[Entry],
    visit_date: date,
    prepared: PreparedInput,
    result: ConversionResult,
    questions_by_version: Mapping[str, Sequence[Question]],
    doctor_masks: Mapping[int, DoctorMask],
) -> _Context:
    checked = check_inputs(
        patient_id=patient_id,
        regimen_skill=regimen_skill,
        report_skill=report_skill,
        courses=courses,
        entries=entries,
        visit_date=visit_date,
        prepared=prepared,
        questions_by_version=questions_by_version,
        doctor_masks=doctor_masks,
    )
    ordered = checked.courses
    course_no = prepared.input.schedule.course_no
    prev_course = course_mod.previous_course(ordered, course_no)
    ai_used = not result.fallback and result.timeline is not None
    timeline = result.timeline if ai_used else None
    return _Context(
        courses=ordered,
        current=_span(ordered, course_no, regimen_skill, visit_date),
        previous=(
            _span(ordered, prev_course.course_no, regimen_skill, None)
            if prev_course is not None
            else None
        ),
        visit_date=visit_date,
        records=group_by_date(entries),
        by_id=checked.by_id,
        prepared=prepared,
        timeline=timeline,
        events=(
            tuple(usable_events(timeline, prepared, checked.by_id))
            if timeline is not None
            else ()
        ),
    )


def _current_dates(ctx: _Context) -> list[tuple[int, date]]:
    """今コースで受診日までの (Day, 日付)。ヘッダ・要確認・経過表で同じ範囲を使う。"""
    span = ctx.current
    return [(day, span.date_of(day)) for day in span.days if span.has_cell(day)]


def _has_too_sick(records: Records, d: date) -> bool:
    return any(e.kind == "too_sick" for e in records.get(d, ()))


def _header(
    ctx: _Context,
    *,
    reception_no: str,
    patient_id: str,
    regimen_skill: RegimenSkill,
) -> ReportHeader:
    schedule = ctx.current.schedule
    dates = [d for _, d in _current_dates(ctx)]
    recorded = [d for d in dates if ctx.records.get(d)]
    return ReportHeader(
        reception_no=reception_no,
        patient_id=patient_id,
        regimen=regimen_skill.regimen,
        course_no=schedule.course_no,
        course_start=schedule.day1_date,
        course_end=max([schedule.last_day_date, *dates]),
        recorded_days=len(recorded),
        total_days=len(dates),
        no_input_days=len(dates) - len(recorded),
        too_sick_days=sum(1 for d in dates if _has_too_sick(ctx.records, d)),
        delay_note=course_mod.delay_note(schedule),
        fallback=ctx.timeline is None,
    )


def _fever_items(
    ctx: _Context, regimen_skill: RegimenSkill, threshold: float
) -> list[AttentionItem]:
    keys = {q.key for q in regimen_skill.questions if q.answer_type == "temperature"}
    items = []
    for day, d in _current_dates(ctx):
        measured = [
            a
            for e in ctx.records.get(d, ())
            if e.kind != "too_sick"
            for a in e.answers
            if a.question_key in keys
            and a.value == "measured"
            and a.temperature is not None
        ]
        if not measured:
            continue
        top = max(measured, key=lambda a: (a.temperature, a.question_key))
        if top.temperature is not None and top.temperature >= threshold:
            items.append(
                AttentionItem(
                    kind="fever",
                    day=day,
                    question_key=top.question_key,
                    temperature=top.temperature,
                )
            )
    return items


def _too_sick_items(ctx: _Context) -> list[AttentionItem]:
    items = []
    prev = ctx.previous
    for day, d in _current_dates(ctx):
        if not _has_too_sick(ctx.records, d):
            continue
        same = (
            prev is not None
            and day in prev.days
            and _has_too_sick(ctx.records, prev.date_of(day))
        )
        items.append(
            AttentionItem(kind="too_sick", day=day, previous_course_same_day=same)
        )
    return items


def _unprocessed_ids(ctx: _Context) -> set[int]:
    """コードの選別（prepared.unprocessed）だけ。timeline 側の値は引用・件数に使わない。"""
    return {u.entry_id for u in ctx.prepared.unprocessed}


def _contradiction_items(ctx: _Context) -> list[AttentionItem]:
    if ctx.timeline is None:
        return []
    return verified_contradictions(
        ctx.timeline,
        ctx.prepared,
        ctx.by_id,
        schedule=ctx.current.schedule,
        courses=ctx.courses,
    )


def _attention(
    ctx: _Context,
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
    unprocessed: set[int],
) -> list[AttentionItem]:
    """食い違い → 発熱 → つらくて書けない → 未処理（件数のみ）の順。"""
    items = [
        *_contradiction_items(ctx),
        *_fever_items(ctx, regimen_skill, report_skill.fever_attention_celsius),
        *_too_sick_items(ctx),
    ]
    if unprocessed:
        items.append(AttentionItem(kind="unprocessed", count=len(unprocessed)))
    return items


def _quotes(ctx: _Context, unprocessed: set[int], max_items: int) -> list[QuoteItem]:
    """Day 順。上限を超えたら受診直前の max_items 件を残す。Day は記録日から数える。"""
    prepared = ctx.prepared
    schedule = ctx.current.schedule
    items = []
    for me in sorted(prepared.input.entries, key=lambda e: (e.record_date, e.entry_no)):
        text = prepared.masked_texts.get(me.entry_no)
        entry_id = prepared.entry_ids.get(me.entry_no)
        if not text or entry_id in unprocessed:
            continue
        items.append(
            QuoteItem(
                entry_no=me.entry_no,
                day=course_mod.day_of(me.record_date, schedule, courses=ctx.courses),
                date=me.record_date,
                text=text,
                by_proxy=me.by_proxy,
            )
        )
    if max_items <= 0:
        return []
    return items[-max_items:]


def _per_symptom(ctx: _Context, result: ConversionResult) -> list[SymptomSummary]:
    if ctx.timeline is None or result.picks is None:
        return []
    return verified_per_symptom(
        result.picks,
        ctx.events,
        schedule=ctx.current.schedule,
        courses=ctx.courses,
        visit_date=ctx.visit_date,
    )


def _grid(
    ctx: _Context,
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
    questions_by_version: Mapping[str, Sequence[Question]],
) -> Grid:
    rows = row_specs(regimen_skill, report_skill)
    marks = (
        event_marks(ctx.events, ctx.current.schedule, ctx.courses, rows)
        if ctx.timeline is not None
        else {}
    )
    return build_grid(
        current=ctx.current,
        previous=ctx.previous if report_skill.show_previous_course else None,
        rows=rows,
        records=ctx.records,
        sets=QuestionSets.build(questions_by_version, regimen_skill),
        marks=marks,
    )


def build_report_data(
    *,
    reception_no: str,
    patient_id: str,
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
    courses: Sequence[Course],
    entries: Sequence[Entry],
    visit_date: date,
    prepared: PreparedInput,
    result: ConversionResult,
    questions_by_version: Mapping[str, Sequence[Question]],
    doctor_masks: Mapping[int, DoctorMask] | None = None,
) -> ReportData:
    """レポートの中身を組み立てる。

    入力が食い違えば ReportBuildError、courses の矛盾は CourseValidationError
    （どちらも ValueError）。doctor_masks は prepare_input に渡した医師の伏せ字
    （entries.id → DoctorMask。無ければ空）。
    """
    ctx = _context(
        patient_id=patient_id,
        regimen_skill=regimen_skill,
        report_skill=report_skill,
        courses=courses,
        entries=entries,
        visit_date=visit_date,
        prepared=prepared,
        result=result,
        questions_by_version=questions_by_version,
        doctor_masks=dict(doctor_masks or {}),
    )
    grid = _grid(ctx, regimen_skill, report_skill, questions_by_version)
    unprocessed = _unprocessed_ids(ctx)
    header = _header(
        ctx,
        reception_no=reception_no,
        patient_id=patient_id,
        regimen_skill=regimen_skill,
    )
    return ReportData(
        header=header,
        attention=_attention(ctx, regimen_skill, report_skill, unprocessed),
        grid=grid,
        per_symptom=_per_symptom(ctx, result),
        quotes=_quotes(ctx, unprocessed, report_skill.quotes_max_items),
        fallback=header.fallback,
        report_skill_version=report_skill.skill_version,
    )
