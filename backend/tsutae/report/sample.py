"""目で確かめる用・テスト用: 合成データと正解ラベルから build_report_data の入力を作る。

- 変換パイプライン（prepare_input / convert）の代わり。API を呼ばない
- 正解ラベルを AI の出力の代わりにする。ラベルには確からしさが無いので、回想は
  SAMPLE_RECALLED_CONFIDENCE（「？」の見た目を確かめるため低め）、それ以外は
  SAMPLE_CONFIDENCE と置く
- 伏せ字は report.gate.mask_free_text（変換の入力と同じ整形・一次・二次）。二次検出に
  掛かった記録は記録ごと外して未処理にする
- 記録の版（entry_versions）と他の版の材料も変換の入力と同じ形で埋める（他の版の材料は
  引かないので空。その版の記録の出来事は質問につながらない）
- 症例は全て合成
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from tsutae import course as course_mod
from tsutae import dataset
from tsutae.config import SYNTHETIC_DIR
from tsutae.report.gate import mask_free_text
from tsutae.schemas import (
    Contradiction,
    ConversionResult,
    Course,
    CourseSchedule,
    Entry,
    EntryLabel,
    MaskedEntry,
    PatientLabels,
    PipelineInput,
    PreparedInput,
    Question,
    RegimenSkill,
    ReportFormatSkill,
    ReportPicks,
    SymptomSummary,
    Timeline,
    TimelineEvent,
    UnprocessedEntry,
    VersionTermKeys,
)
from tsutae.skills import load_regimen_skill, load_report_skill
from tsutae.synthetic import load_labels, load_patient

SAMPLE_CONFIDENCE = 0.9
SAMPLE_RECALLED_CONFIDENCE = 0.5
SAMPLE_FALLBACK_CODE = "sample_fallback"


@dataclass(frozen=True)
class SampleInputs:
    reception_no: str
    patient_id: str
    regimen_skill: RegimenSkill
    report_skill: ReportFormatSkill
    courses: list[Course]
    entries: list[Entry]
    visit_date: date
    prepared: PreparedInput
    result: ConversionResult
    questions_by_version: dict[str, list[Question]]
    labels: PatientLabels

    def with_entries(self, entries: Sequence[Entry]) -> SampleInputs:
        """記録を差し替え、prepared と（ラベル由来の）変換結果も作り直した新しい入力。"""
        prepared = prepare_sample_input(
            courses=self.courses,
            entries=entries,
            regimen_skill=self.regimen_skill,
            report_skill=self.report_skill,
            visit_date=self.visit_date,
        )
        result = result_from_labels(
            prepared, self.labels, fallback=self.result.fallback
        )
        return replace(self, entries=list(entries), prepared=prepared, result=result)

    def build_kwargs(self) -> dict[str, Any]:
        """build_report_data にそのまま渡せるキーワード引数。"""
        return {
            "reception_no": self.reception_no,
            "patient_id": self.patient_id,
            "regimen_skill": self.regimen_skill,
            "report_skill": self.report_skill,
            "courses": list(self.courses),
            "entries": list(self.entries),
            "visit_date": self.visit_date,
            "prepared": self.prepared,
            "result": self.result,
            "questions_by_version": dict(self.questions_by_version),
        }


@dataclass(frozen=True)
class _Masked:
    entries: list[MaskedEntry]
    entry_ids: dict[int, int]
    texts: dict[int, str]
    unprocessed: list[UnprocessedEntry]


def _mask_entries(
    picked: Sequence[Entry], schedule: CourseSchedule, courses: Sequence[Course]
) -> _Masked:
    """記録日時順に entry_no を振る。二次検出に掛かった記録は記録ごと外す。"""
    out = _Masked(entries=[], entry_ids={}, texts={}, unprocessed=[])
    for e in picked:
        masked, reason = mask_free_text(e.free_text)
        if reason is not None:
            out.unprocessed.append(UnprocessedEntry(entry_id=e.id, reason=reason))
            continue
        no = len(out.entries) + 1
        out.entries.append(
            MaskedEntry(
                entry_no=no,
                record_date=e.record_date,
                day=course_mod.day_of(e.record_date, schedule, courses=courses),
                by_proxy=e.by_proxy,
                too_sick=e.kind == "too_sick",
                answers=list(e.answers),
                masked_free_text=masked,
            )
        )
        out.entry_ids[no] = e.id
        if masked is not None:
            out.texts[no] = masked
    return out


def prepare_sample_input(
    *,
    courses: Sequence[Course],
    entries: Sequence[Entry],
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
    visit_date: date,
) -> PreparedInput:
    """今コースの Day1〜min(最終日, 受診日) の記録を伏せ字にして番号を振る。"""
    current = course_mod.current_course(courses, visit_date)
    if current is None:
        raise ValueError("受診日にコースが無い")
    schedule = course_mod.build_schedule(
        courses,
        current.course_no,
        regimen_skill.cycle_days,
        regimen_skill.pump_removal_day,
    )
    end = min(schedule.last_day_date, visit_date)
    picked = sorted(
        (e for e in entries if schedule.day1_date <= e.record_date <= end),
        key=lambda e: (e.recorded_at, e.id),
    )
    masked = _mask_entries(picked, schedule, courses)
    versions = {e.id: e.skill_version for e in picked}
    entry_versions = {no: versions[eid] for no, eid in masked.entry_ids.items()}
    return PreparedInput(
        input=PipelineInput(
            regimen=regimen_skill.regimen,
            regimen_skill_version=regimen_skill.skill_version,
            report_skill_version=report_skill.skill_version,
            schedule=schedule,
            questions=list(regimen_skill.questions),
            entries=masked.entries,
        ),
        entry_ids=masked.entry_ids,
        masked_texts=masked.texts,
        unprocessed=masked.unprocessed,
        term_keys=dict(regimen_skill.term_keys or {}),
        entry_versions=entry_versions,
        other_versions=_version_materials(entry_versions, regimen_skill),
    )


def _version_materials(
    entry_versions: dict[int, str], regimen_skill: RegimenSkill
) -> dict[str, VersionTermKeys]:
    """他の版の材料は持たない（変換の入力と同じく、その版の記録は質問につなげない）。"""
    # pipeline/__init__ は orchestrator（SDK）を読み込むので、呼ぶときに読み込む
    from tsutae.pipeline.inputs import version_materials

    return version_materials(entry_versions, regimen_skill, None)


def _events(no: int, me: MaskedEntry, label: EntryLabel) -> list[TimelineEvent]:
    return [
        TimelineEvent(
            entry_no=no,
            date=ev.date,
            day=ev.day,
            course_no=ev.course_no,
            term=ev.term,
            question_key=ev.question_key,
            status=ev.status,
            source_quote=ev.source_quote,
            confidence=SAMPLE_RECALLED_CONFIDENCE if ev.recalled else SAMPLE_CONFIDENCE,
            recalled=ev.recalled,
            by_proxy=me.by_proxy,
        )
        for ev in label.events
    ]


def _contradictions(no: int, me: MaskedEntry, label: EntryLabel) -> list[Contradiction]:
    return [
        Contradiction(
            entry_no=no,
            date=me.record_date,
            day=me.day,
            question_key=c.question_key,
            closed_answer=c.closed_answer,
            free_text_quote=c.free_text_quote,
        )
        for c in label.contradictions
    ]


def _picks(events: Sequence[TimelineEvent]) -> ReportPicks:
    """症状（用語名）ごとに、present/improving で最初に出た出来事を代表にする。"""
    first: dict[str, TimelineEvent] = {}
    for ev in sorted(events, key=lambda e: (e.date, e.entry_no)):
        if ev.status != "absent" and ev.term not in first:
            first[ev.term] = ev
    return ReportPicks(
        per_symptom=[
            SymptomSummary(
                term=ev.term,
                question_key=ev.question_key,
                start_day=ev.day,
                start_date=ev.date,
                representative_quote=ev.source_quote,
                confidence=ev.confidence,
            )
            for ev in first.values()
        ]
    )


def result_from_labels(
    prepared: PreparedInput, labels: PatientLabels, *, fallback: bool = False
) -> ConversionResult:
    """正解ラベルを変換結果の代わりにする。fallback なら AI変換なし（timeline=None）。"""
    if fallback:
        return ConversionResult(
            timeline=None, picks=None, fallback=True, error_code=SAMPLE_FALLBACK_CODE
        )
    by_seq = {label.entry_seq: label for label in labels.labels}
    events: list[TimelineEvent] = []
    contradictions: list[Contradiction] = []
    for me in prepared.input.entries:
        label = by_seq.get(prepared.entry_ids[me.entry_no])
        if label is None or label.expect_unprocessed:
            continue
        events += _events(me.entry_no, me, label)
        contradictions += _contradictions(me.entry_no, me, label)
    timeline = Timeline(
        events=events,
        contradictions=contradictions,
        unprocessed_entries=list(prepared.unprocessed),
    )
    return ConversionResult(timeline=timeline, picks=_picks(events), fallback=False)


def load_demo_inputs(
    *,
    visit_date: date | None = None,
    fallback: bool = False,
    name: str = "demo_patient",
) -> SampleInputs:
    """合成データ（既定はデモ患者）を読み、レポートの入力一式を作る。"""
    patient = load_patient(SYNTHETIC_DIR / f"{name}.json")
    labels = load_labels(SYNTHETIC_DIR / f"labels_{name}.json")
    regimen_skill = load_regimen_skill(patient.regimen)
    report_skill = load_report_skill()
    courses = dataset.to_courses(patient)
    entries = dataset.to_entries(patient)
    day = visit_date or patient.visit_date
    prepared = prepare_sample_input(
        courses=courses,
        entries=entries,
        regimen_skill=regimen_skill,
        report_skill=report_skill,
        visit_date=day,
    )
    return SampleInputs(
        reception_no=patient.reception_no,
        patient_id=patient.patient_id,
        regimen_skill=regimen_skill,
        report_skill=report_skill,
        courses=courses,
        entries=entries,
        visit_date=day,
        prepared=prepared,
        result=result_from_labels(prepared, labels, fallback=fallback),
        questions_by_version={
            regimen_skill.skill_version: list(regimen_skill.questions)
        },
        labels=labels,
    )
