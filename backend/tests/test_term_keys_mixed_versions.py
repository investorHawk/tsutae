"""T95: 版の混ざった受診で、用語 → 質問 key の対応を記録ごとに（Entry.skill_version）引く。

spec 9.1「変換の検査（出来事の question_key）と紙の検査は、その記録の Skill の版の対応」、
architecture 9c「記録ごとに（Entry.skill_version）その版の対応を使う」。

- 版1（だるさの質問なし）の記録の「だるい」は 倦怠感 → null、版2（だるさを足した）の記録は
  倦怠感 → fatigue。変換の入力の版（今の版）は版2
- prepare_input は記録の版（entry_no → skill_version）と、入力の版と違う版の term_keys・
  質問の key を PreparedInput に写す（Claude に送る PipelineInput の JSON には入れない）
- checks（OutputContext）・report/validate は記録の版の対応で照合する
- 版の材料を引けなかった版（version_skills に無い。skill_versions の全文が今の検査に
  通らない古い版など）の記録は安全側: 空の材料を置き、どの用語も null（○ を付けない。
  出来事は紙に残る）。版の名前と番号だけを警告に残す
- 入口（gate）は送った記録の全てに版があること、他の版の材料が送った版とちょうど同じ
  こと、材料の質問の key が版の質問集と同じ（空の材料は可）ことを確かめる
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import pytest
from pipeline_fakes import report_skill
from regimen_fixtures import extra_form, ram_wptx_data

from tsutae.config import JST
from tsutae.pipeline.checks import OutputContext, timeline_problems
from tsutae.pipeline.inputs import prepare_input
from tsutae.regimen import RegimenForm, render_regimen_skill
from tsutae.report import ReportBuildError
from tsutae.report.gate import check_inputs
from tsutae.report.validate import usable_events
from tsutae.schemas import (
    ClosedAnswer,
    Course,
    Entry,
    PreparedInput,
    RegimenSkill,
    Timeline,
    TimelineEvent,
    VersionTermKeys,
)
from tsutae.skills import validate_skill_text
from tsutae.skills.term_keys import entry_term_keys

PID = "P-RAMW0002"
NAME = "regimen-ram-wptx"
DAY1 = date(2026, 11, 2)
D8 = date(2026, 11, 9)
D9 = date(2026, 11, 10)
V1 = f"{NAME}@1"
V2 = f"{NAME}@2"


def _without_fatigue() -> RegimenForm:
    data = ram_wptx_data()
    data["questions"] = [q for q in data["questions"] if q["key"] != "fatigue"]
    data["side_effects"] = [
        {**s, "question_key": None} if s["question_key"] == "fatigue" else s
        for s in data["side_effects"]
    ]
    return RegimenForm.model_validate(data)


def _skill(form: RegimenForm, version: int) -> RegimenSkill:
    skill = validate_skill_text(NAME, render_regimen_skill(form, version))
    assert isinstance(skill, RegimenSkill)
    return skill


V1_SKILL = _skill(_without_fatigue(), 1)
V2_SKILL = _skill(extra_form("ram_wptx"), 2)
COURSES = [Course(patient_id=PID, course_no=1, infusion_date=DAY1)]


def _entry(entry_id: int, day: date, version: str, text: str) -> Entry:
    answers = [ClosedAnswer(question_key="diarrhea", value="none")]
    if version == V2:
        answers.append(ClosedAnswer(question_key="fatigue", value="present"))
    return Entry(
        id=entry_id,
        patient_id=PID,
        recorded_at=datetime(day.year, day.month, day.day, 20, 0, tzinfo=JST),
        record_date=day,
        kind="mixed",
        by_proxy=False,
        skill_version=version,
        answers=answers,
        free_text=text,
    )


ENTRIES = [
    _entry(1, D8, V1, "今日はだるい"),
    _entry(2, D9, V2, "今日もだるい"),
]


def _prepared(with_versions: bool = True) -> PreparedInput:
    return prepare_input(
        courses=COURSES,
        entries=ENTRIES,
        regimen_skill=V2_SKILL,
        report_skill=report_skill(),
        visit_date=D9,
        version_skills={V1: V1_SKILL, V2: V2_SKILL} if with_versions else None,
    )


def _event(no: int, key: str | None, quote: str) -> TimelineEvent:
    d = D8 if no == 1 else D9
    return TimelineEvent(
        entry_no=no,
        date=d,
        day=(d - DAY1).days + 1,
        course_no=1,
        term="倦怠感",
        question_key=key,
        status="present",
        source_quote=quote,
        confidence=0.9,
    )


def test_fixture_versions_differ_on_fatigue() -> None:
    assert "fatigue" not in [q.key for q in V1_SKILL.questions]
    assert "fatigue" in [q.key for q in V2_SKILL.questions]
    assert (V1_SKILL.term_keys or {}).get("倦怠感") is None
    assert (V2_SKILL.term_keys or {})["倦怠感"] == "fatigue"


def test_prepared_carries_entry_versions_outside_pipeline_input() -> None:
    prepared = _prepared()
    assert prepared.entry_versions == {1: V1, 2: V2}
    assert set(prepared.other_versions) == {V1}
    other = prepared.other_versions[V1]
    assert other.term_keys == dict(V1_SKILL.term_keys or {})
    assert other.question_keys == [q.key for q in V1_SKILL.questions]
    dumped = prepared.input.model_dump(mode="json")
    assert "entry_versions" not in dumped and "other_versions" not in dumped
    assert all("skill_version" not in e for e in dumped["entries"])


def test_entry_term_keys_follow_record_version() -> None:
    prepared = _prepared()
    assert entry_term_keys(prepared, 1)["倦怠感"] is None
    assert entry_term_keys(prepared, 2)["倦怠感"] == "fatigue"
    # 版1 の質問に無い key は null（版1 の対応で上書きした neuropathy は残る）
    assert entry_term_keys(prepared, 1)["末梢性感覚ニューロパチー"] == "neuropathy"


def test_missing_version_material_maps_every_term_to_null(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 版1 の材料を引けない: 版1 の記録は今の版の対応（倦怠感 → fatigue）を当てずに全て null
    caplog.set_level(logging.WARNING, logger="tsutae.pipeline.inputs")
    prepared = _prepared(with_versions=False)
    assert prepared.other_versions == {V1: VersionTermKeys()}
    keys = entry_term_keys(prepared, 1)
    assert keys["倦怠感"] is None and keys["末梢性感覚ニューロパチー"] is None
    assert all(v is None for v in keys.values())
    assert entry_term_keys(prepared, 2)["倦怠感"] == "fatigue"  # 今の版の記録は今の対応
    warned = [r for r in caplog.records if r.name == "tsutae.pipeline.inputs"]
    assert len(warned) == 1 and warned[0].levelno == logging.WARNING
    assert V1 in warned[0].getMessage()
    assert "だるい" not in caplog.text


def test_missing_version_material_checks_and_report_use_null() -> None:
    prepared = _prepared(with_versions=False)
    ctx = OutputContext.from_prepared(prepared)
    assert ctx.term_keys_for(1)["倦怠感"] is None
    ok = [_event(1, None, "今日はだるい"), _event(2, "fatigue", "今日もだるい")]
    assert timeline_problems(ok, [], ctx) == []
    by_id = {e.id: e for e in ENTRIES}
    events = ok + [_event(1, "fatigue", "今日はだるい")]
    kept = usable_events(Timeline(events=events), prepared, by_id)
    assert [(e.entry_no, e.question_key) for e in kept] == [(1, None), (2, "fatigue")]


def test_checks_use_record_version_mapping() -> None:
    ctx = OutputContext.from_prepared(_prepared())
    assert ctx.term_keys_for(1)["倦怠感"] is None
    assert ctx.term_keys_for(2)["倦怠感"] == "fatigue"
    ok = [_event(1, None, "今日はだるい"), _event(2, "fatigue", "今日もだるい")]
    assert timeline_problems(ok, [], ctx) == []
    bad = [_event(1, "fatigue", "今日はだるい"), _event(2, None, "今日もだるい")]
    problems = timeline_problems(bad, [], ctx)
    assert [where for where, _ in problems] == [
        "events.0.question_key",
        "events.1.question_key",
    ]
    assert "null にする" in problems[0][1] and "fatigue にする" in problems[1][1]


def test_report_keeps_events_by_record_version() -> None:
    by_id = {e.id: e for e in ENTRIES}
    kept_events = [
        _event(1, None, "今日はだるい"),
        _event(2, "fatigue", "今日もだるい"),
    ]
    dropped = [_event(1, "fatigue", "今日はだるい"), _event(2, None, "今日もだるい")]
    kept = usable_events(Timeline(events=kept_events + dropped), _prepared(), by_id)
    assert [(e.entry_no, e.question_key) for e in kept] == [(1, None), (2, "fatigue")]


def _check(prepared: PreparedInput) -> None:
    check_inputs(
        patient_id=PID,
        regimen_skill=V2_SKILL,
        report_skill=report_skill(),
        courses=COURSES,
        entries=ENTRIES,
        visit_date=D9,
        prepared=prepared,
        questions_by_version={
            V1: list(V1_SKILL.questions),
            V2: list(V2_SKILL.questions),
        },
    )


def test_gate_accepts_record_versions() -> None:
    _check(_prepared())


def test_gate_accepts_missing_version_material() -> None:
    # 材料を引けなかった版は空の材料（全て null。○ は減る向きにしか効かない）で通す。
    # T95 の直後はここで skill_mismatch になり、フォールバックの紙も出なかった
    _check(_prepared(with_versions=False))


def test_gate_rejects_entries_without_version() -> None:
    prepared = _prepared()
    tampered = prepared.model_copy(update={"entry_versions": {2: V2}})
    with pytest.raises(ReportBuildError) as exc:
        _check(tampered)
    assert exc.value.code == "entry_mismatch"


@pytest.mark.parametrize(
    "update",
    [
        {"entry_versions": {1: V2, 2: V2}},  # 記録の版を差し替えた
        {"entry_versions": {1: V1, 2: V2, 9: V1}},  # 送っていない entry_no
        {"other_versions": {}},  # 版1 の対応を落とした
        {"entry_versions": {1: V1}},  # 送った記録の版が欠けた
        # 送っていない版の材料（空でも）
        {"other_versions": {V1: {}, "regimen-ram-wptx@7": {}}},
        {"other_versions": {V2: {"term_keys": {}, "question_keys": ["fatigue"]}}},
    ],
)
def test_gate_rejects_tampered_record_versions(update: dict) -> None:
    prepared = _prepared()
    tampered = PreparedInput.model_validate({**prepared.model_dump(), **update})
    with pytest.raises(ReportBuildError) as exc:
        _check(tampered)
    assert exc.value.code in ("skill_mismatch", "entry_mismatch")


def test_gate_rejects_question_keys_not_of_the_version() -> None:
    prepared = _prepared()
    other = prepared.other_versions[V1].model_copy(
        update={"question_keys": ["fatigue"]}
    )
    tampered = prepared.model_copy(update={"other_versions": {V1: other}})
    with pytest.raises(ReportBuildError) as exc:
        _check(tampered)
    assert exc.value.code == "skill_mismatch"
