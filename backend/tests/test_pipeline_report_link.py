"""pipeline が受け付けた Timeline / ReportPicks が report の組み立てで落ちないこと。

convert（偽の runner・正解ラベルの台本）の結果を `build_report_data` に渡し、食い違い・
症状別の行・経過表の○が紙向けデータに全部残るかを、全症例の全コースで確かめる。
pipeline の検査（checks）と report の検査（verify）の規則がずれたら、ここで気づく。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
from pipeline_fakes import (
    CASE_NAMES,
    FakeRunner,
    course_last_days,
    label_payloads,
    load_case,
    prepare_case,
    regimen_skill,
    report_skill,
    standard_steps,
)

from tsutae.config import get_settings
from tsutae.dataset import to_courses, to_entries
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.orchestrator import convert
from tsutae.report.build import build_report_data
from tsutae.report.grid import row_specs
from tsutae.schemas import ConversionResult, PreparedInput, ReportData

SETTINGS = replace(get_settings(), pipeline_timeout_s=5.0)
CASES = [(name, d) for name in CASE_NAMES for d in course_last_days(name)]


async def _convert(
    name: str, visit_date: date
) -> tuple[PreparedInput, ConversionResult]:
    prepared = prepare_case(name, visit_date)
    timeline, report = label_payloads(name, prepared)
    runner = FakeRunner(standard_steps(timeline, report))
    result = await convert(
        prepared, runner=runner, logger=MemoryLogger(), settings=SETTINGS
    )
    assert result.fallback is False, (name, visit_date, result.error_code)
    return prepared, result


def _build(
    name: str, visit_date: date, prepared: PreparedInput, result: ConversionResult
) -> ReportData:
    patient, _labels = load_case(name)
    skill = regimen_skill(patient.regimen)
    return build_report_data(
        reception_no="A-001",
        patient_id=patient.patient_id,
        regimen_skill=skill,
        report_skill=report_skill(),
        courses=to_courses(patient),
        entries=to_entries(patient),
        visit_date=visit_date,
        prepared=prepared,
        result=result,
        questions_by_version={skill.skill_version: list(skill.questions)},
    )


@pytest.mark.parametrize(("name", "visit_date"), CASES)
async def test_contradictions_reach_the_report(name: str, visit_date: date) -> None:
    prepared, result = await _convert(name, visit_date)
    data = _build(name, visit_date, prepared, result)
    assert result.timeline is not None
    got = [
        (a.day, a.question_key, a.closed_answer, a.quote)
        for a in data.attention
        if a.kind == "contradiction"
    ]
    expected = [
        (c.day, c.question_key, c.closed_answer, c.free_text_quote)
        for c in result.timeline.contradictions
    ]
    assert sorted(got, key=repr) == sorted(expected, key=repr)


@pytest.mark.parametrize(("name", "visit_date"), CASES)
async def test_per_symptom_rows_reach_the_report(name: str, visit_date: date) -> None:
    prepared, result = await _convert(name, visit_date)
    data = _build(name, visit_date, prepared, result)
    assert result.picks is not None
    assert data.per_symptom == result.picks.per_symptom


@pytest.mark.parametrize(("name", "visit_date"), CASES)
async def test_events_mark_the_current_course_grid(name: str, visit_date: date) -> None:
    # 体温の質問（fever）の出来事は体温行に畳まれる（report.grid の行の対応をそのまま使う）
    prepared, result = await _convert(name, visit_date)
    data = _build(name, visit_date, prepared, result)
    assert result.timeline is not None
    patient, _labels = load_case(name)
    row_of = {
        spec.question.key: spec.key
        for spec in row_specs(regimen_skill(patient.regimen), report_skill())
    }
    expected = {
        (row_of[e.question_key], e.day)
        for e in result.timeline.events
        if e.status in ("present", "improving")
        and e.question_key in row_of
        and e.day is not None
    }
    marked = {
        (row.question_key, cell.day)
        for row in data.grid.rows
        if not row.is_previous_course
        for cell in row.cells
        if cell.free_text_mark
    }
    assert marked == expected


def test_cases_include_contradictions_and_symptom_rows() -> None:
    # 上のテストが空振りしていないこと（食い違いと症状別の行がある症例を含む）
    prepared = prepare_case("demo_patient")
    timeline, report = label_payloads("demo_patient", prepared)
    assert timeline["contradictions"] and report["per_symptom"]
