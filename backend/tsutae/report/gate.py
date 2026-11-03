"""入口の検査（check_inputs）。docs/architecture.md §7b。

PreparedInput は変換パイプラインが作る。レポートはそれを信じず、渡された記録・
コース・Skill と突き合わせ、合わなければ ReportBuildError にする（紙に出さない）。

- 患者: courses・entries・引数の patient_id が同じ患者
- 日程: 受診日の今コース・レジメン・日程が courses と Skill から作り直したものと同じ
- Skill: regimen / report の版と質問集が、渡された Skill と完全に一致する
- 記録: entry_no ごとに、記録日・Day（記録日から数え直す）・代理・too_sick・回答・
  伏せ字後の文が元の記録と一致する。伏せ字後の文は元の自由記載に伏せ字を掛け直して
  比べる（両方を同じ捏造文に差し替えても通らない）。二次検出に掛かる記録は送れない
- 回答の型: 記録の版の質問集で、3択の質問に none/present/hard、体温の質問に
  measured/not_measured 以外の値があれば answer_mismatch（知らない版・知らない質問は
  ここでは見ない。版が無ければ経過表が unknown_skill_version）
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from tsutae import course as course_mod
from tsutae.masking import check_text, detect_identifiers
from tsutae.report.errors import ReportBuildError
from tsutae.schemas import (
    ClosedAnswer,
    Course,
    CourseSchedule,
    Entry,
    MaskedEntry,
    PreparedInput,
    Question,
    RegimenSkill,
    ReportFormatSkill,
)

_VALUES_BY_TYPE: Mapping[str, frozenset[str]] = {
    "three_level": frozenset({"none", "present", "hard"}),
    "temperature": frozenset({"measured", "not_measured"}),
}


@dataclass(frozen=True)
class CheckedInputs:
    courses: tuple[Course, ...]  # course_no 順
    by_id: Mapping[int, Entry]


def _check_patient(
    patient_id: str, courses: Sequence[Course], entries: Sequence[Entry]
) -> None:
    found = {c.patient_id for c in courses} | {e.patient_id for e in entries}
    if found - {patient_id}:
        raise ReportBuildError(
            "patient_mismatch", "courses・entries に別の患者のものが混ざっている"
        )


def _entries_by_id(entries: Sequence[Entry]) -> dict[int, Entry]:
    by_id = {e.id: e for e in entries}
    if len(by_id) != len(entries):
        raise ReportBuildError("entry_mismatch", "entries の id が重複している")
    return by_id


def _check_schedule(
    prepared: PreparedInput,
    courses: Sequence[Course],
    regimen_skill: RegimenSkill,
    visit_date: date,
) -> None:
    schedule = prepared.input.schedule
    current = course_mod.current_course(courses, visit_date)
    if current is None or current.course_no != schedule.course_no:
        raise ReportBuildError("schedule_mismatch", "受診日の今コースと違う")
    if prepared.input.regimen != regimen_skill.regimen:
        raise ReportBuildError("schedule_mismatch", "レジメンが違う")
    expected = course_mod.build_schedule(
        courses,
        schedule.course_no,
        regimen_skill.cycle_days,
        regimen_skill.pump_removal_day,
    )
    if expected != schedule:
        raise ReportBuildError("schedule_mismatch", "日程が courses と合わない")


def _check_skills(
    prepared: PreparedInput,
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
) -> None:
    pi = prepared.input
    if pi.regimen_skill_version != regimen_skill.skill_version:
        raise ReportBuildError("skill_mismatch", "regimen Skill の版が違う")
    if pi.report_skill_version != report_skill.skill_version:
        raise ReportBuildError("skill_mismatch", "report Skill の版が違う")
    if list(pi.questions) != list(regimen_skill.questions):
        raise ReportBuildError("skill_mismatch", "質問集が regimen Skill と違う")


def mask_free_text(free_text: str | None) -> tuple[str | None, str | None]:
    """元の自由記載に、変換の入力と同じ整形・伏せ字を掛ける。(伏せ字後の文, 外す理由)。

    pipeline.inputs と同じ手順（制御文字を空白に → 一次・二次 → 依頼文の JSON での
    見え方にも二次）。理由があればその記録は送れない。
    """
    # pipeline/__init__ は orchestrator（SDK）を読み込む。将来 service → report の
    # 循環にならないよう、呼ぶときに読み込む（整形の規則は pipeline.inputs が正本）
    from tsutae.pipeline.inputs import flatten_text

    flat = flatten_text(free_text) if free_text else None
    if flat is None:
        return None, None
    check = check_text(flat)
    if check.reason is not None:
        return None, check.reason
    in_prompt = detect_identifiers(json.dumps(check.masked, ensure_ascii=False))
    if in_prompt:
        return None, in_prompt[0].rule
    return check.masked, None


def _same_record(
    me: MaskedEntry, entry: Entry, masked_text: str | None, day: int | None
) -> bool:
    if (me.masked_free_text or None) != masked_text:
        return False
    expected, reason = mask_free_text(entry.free_text)
    if reason is not None or expected != masked_text:
        return False  # 送れない記録・捏造した文・黙って落とした文
    return (
        me.record_date == entry.record_date
        and me.day == day
        and me.by_proxy == entry.by_proxy
        and me.too_sick == (entry.kind == "too_sick")
        and list(me.answers) == list(entry.answers)
    )


def _check_prepared_entries(
    prepared: PreparedInput,
    by_id: Mapping[int, Entry],
    courses: Sequence[Course],
) -> None:
    schedule: CourseSchedule = prepared.input.schedule
    numbers = [me.entry_no for me in prepared.input.entries]
    if len(set(numbers)) != len(numbers) or set(numbers) != set(prepared.entry_ids):
        raise ReportBuildError("entry_mismatch", "entry_no と entry_ids が合わない")
    if not set(prepared.masked_texts) <= set(prepared.entry_ids):
        raise ReportBuildError("entry_mismatch", "masked_texts に未知の entry_no")
    for me in prepared.input.entries:
        entry = by_id.get(prepared.entry_ids[me.entry_no])
        text = prepared.masked_texts.get(me.entry_no)
        day = (
            course_mod.day_of(entry.record_date, schedule, courses=courses)
            if entry is not None
            else None
        )
        if entry is None or not _same_record(me, entry, text, day):
            raise ReportBuildError(
                "entry_mismatch", f"entry_no {me.entry_no} が entries と合わない"
            )
    if any(u.entry_id not in by_id for u in prepared.unprocessed):
        raise ReportBuildError("entry_mismatch", "未処理の記録が entries に無い")


def _answer_fits(answer: ClosedAnswer, questions: Mapping[str, Question]) -> bool:
    question = questions.get(answer.question_key)
    if question is None:
        return True  # 知らない質問は経過表に載らない（体温にも数えない）
    return answer.value in _VALUES_BY_TYPE[question.answer_type]


def _check_answer_types(
    entries: Sequence[Entry],
    regimen_skill: RegimenSkill,
    questions_by_version: Mapping[str, Sequence[Question]],
) -> None:
    by_version = {v: {q.key: q for q in qs} for v, qs in questions_by_version.items()}
    by_version.setdefault(
        regimen_skill.skill_version, {q.key: q for q in regimen_skill.questions}
    )
    for e in entries:
        questions = by_version.get(e.skill_version)
        if questions is None:
            continue
        if not all(_answer_fits(a, questions) for a in e.answers):
            raise ReportBuildError(
                "answer_mismatch", f"記録 {e.id} の回答が質問の型と合わない"
            )


def check_inputs(
    *,
    patient_id: str,
    regimen_skill: RegimenSkill,
    report_skill: ReportFormatSkill,
    courses: Sequence[Course],
    entries: Sequence[Entry],
    visit_date: date,
    prepared: PreparedInput,
    questions_by_version: Mapping[str, Sequence[Question]],
) -> CheckedInputs:
    """入力の対応を確かめる。courses の矛盾は CourseValidationError（course.py）。"""
    _check_patient(patient_id, courses, entries)
    ordered = tuple(course_mod.validate_courses(courses))
    by_id = _entries_by_id(entries)
    _check_schedule(prepared, ordered, regimen_skill, visit_date)
    _check_skills(prepared, regimen_skill, report_skill)
    _check_prepared_entries(prepared, by_id, ordered)
    _check_answer_types(entries, regimen_skill, questions_by_version)
    return CheckedInputs(courses=ordered, by_id=by_id)
