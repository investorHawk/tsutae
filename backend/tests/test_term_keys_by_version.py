"""T95: 用語 → 質問 key の対応を版ごとに（architecture 9c「用語と質問の対応」）。

- `term_keys_for(版の term_keys)` = ctcae_terms.json の全体の対応 ＋ その版の上書き
  （上書きの null も勝つ）。FOLFOX/CAPOX@1 は term_keys が無いので全体の対応のまま
- prepare_input は変換の入力の版（今の版。質問集と同じ版）の term_keys を PreparedInput に
  写す（Claude に送る PipelineInput の JSON には入れない）
- 記録が全て入力の版のとき、checks（OutputContext）・term-mapper の用語の一覧・
  report/validate は同じ対応を使う。その版の質問に無い key は null にそろえる（checks と
  紙の照合を同じにする）。版の混ざる受診（記録ごとの版の対応）は
  test_term_keys_mixed_versions.py
- 紙の照合の入口（gate）は PreparedInput の term_keys が Skill の版と同じかを確かめる
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pytest
from pipeline_fakes import prepare_case, report_skill
from regimen_fixtures import extra_form

from tsutae.config import JST, get_settings
from tsutae.pipeline.agents import TERM_MAPPER, build_agents
from tsutae.pipeline.checks import OutputContext
from tsutae.pipeline.inputs import prepare_input
from tsutae.regimen import render_regimen_skill
from tsutae.report import ReportBuildError
from tsutae.report.validate import usable_events
from tsutae.schemas import (
    ClosedAnswer,
    Course,
    Entry,
    PreparedInput,
    RegimenSkill,
    Timeline,
    TimelineEvent,
)
from tsutae.skills import validate_skill_text
from tsutae.skills.term_keys import global_term_keys, term_keys_for

PID = "P-RAMW0001"
DAY1 = date(2026, 11, 2)
RECORD = date(2026, 11, 9)
TEXT = "今日はだるい。手足のしびれもある。手のひらが赤い"


def _ram() -> RegimenSkill:
    text = render_regimen_skill(extra_form("ram_wptx"), 1)
    skill = validate_skill_text("regimen-ram-wptx", text)
    assert isinstance(skill, RegimenSkill)
    return skill


def _prepared(skill: RegimenSkill) -> tuple[PreparedInput, list[Entry]]:
    entries = [
        Entry(
            id=1,
            patient_id=PID,
            recorded_at=datetime(2026, 11, 9, 20, 0, tzinfo=JST),
            record_date=RECORD,
            kind="mixed",
            by_proxy=False,
            skill_version=skill.skill_version,
            answers=[ClosedAnswer(question_key="fatigue", value="present")],
            free_text=TEXT,
        )
    ]
    prepared = prepare_input(
        courses=[Course(patient_id=PID, course_no=1, infusion_date=DAY1)],
        entries=entries,
        regimen_skill=skill,
        report_skill=report_skill(),
        visit_date=RECORD,
    )
    return prepared, entries


def _event(term: str, key: str | None, quote: str) -> TimelineEvent:
    return TimelineEvent(
        entry_no=1,
        date=RECORD,
        day=8,
        course_no=1,
        term=term,
        question_key=key,
        status="present",
        source_quote=quote,
        confidence=0.9,
    )


def test_term_keys_for_overlays_version_keys() -> None:
    base = global_term_keys()
    assert term_keys_for(None) == base
    assert term_keys_for({}) == base
    got = term_keys_for({"倦怠感": "fatigue", "下痢": None})
    assert got["倦怠感"] == "fatigue"
    assert got["下痢"] is None  # 版の null が全体の対応に勝つ
    assert base["下痢"] == "diarrhea" and base["倦怠感"] is None
    assert {k: v for k, v in got.items() if k not in ("倦怠感", "下痢")} == {
        k: v for k, v in base.items() if k not in ("倦怠感", "下痢")
    }


def test_builtin_prepared_has_no_term_keys() -> None:
    assert prepare_case("demo_patient").term_keys == {}


def test_prepared_carries_version_term_keys_outside_pipeline_input() -> None:
    skill = _ram()
    prepared, _ = _prepared(skill)
    assert prepared.term_keys == skill.term_keys
    assert prepared.term_keys["倦怠感"] == "fatigue"
    assert "term_keys" not in prepared.input.model_dump(mode="json")


def test_output_context_uses_version_mapping() -> None:
    prepared, _ = _prepared(_ram())
    keys = OutputContext.from_prepared(prepared).term_keys
    assert keys["倦怠感"] == "fatigue"
    assert keys["疲労"] == "fatigue"
    assert keys["末梢性感覚ニューロパチー"] == "neuropathy"  # 全体では numbness
    assert keys["鼻出血"] == "bleeding"
    assert keys["手掌・足底発赤知覚不全症候群"] is None  # この版の質問に無い
    assert keys["関節痛"] is None


def test_term_mapper_list_uses_version_mapping() -> None:
    settings = replace(get_settings(), subagent_model="claude-test-sub")
    prepared, _ = _prepared(_ram())
    plain = build_agents(settings, "regimen-ram-wptx")[TERM_MAPPER].prompt
    mapped = build_agents(settings, "regimen-ram-wptx", term_keys=prepared.term_keys)[
        TERM_MAPPER
    ].prompt
    assert "- 倦怠感（question_key: null）" in plain
    assert "- 倦怠感（question_key: fatigue）" in mapped
    assert "- 末梢性感覚ニューロパチー（question_key: neuropathy）" in mapped
    assert mapped.count("question_key: ") == plain.count("question_key: ")


def test_report_keeps_events_of_version_mapping() -> None:
    prepared, entries = _prepared(_ram())
    by_id = {e.id: e for e in entries}
    events = [
        _event("倦怠感", "fatigue", "今日はだるい"),
        _event("末梢性感覚ニューロパチー", "neuropathy", "手足のしびれ"),
        _event("手掌・足底発赤知覚不全症候群", None, "手のひらが赤い"),
    ]
    dropped = [
        _event("倦怠感", None, "今日はだるい"),  # 全体の対応のまま
        _event("末梢性感覚ニューロパチー", "numbness", "手足のしびれ"),
        _event("手掌・足底発赤知覚不全症候群", "hand_foot", "手のひらが赤い"),
    ]
    kept = usable_events(Timeline(events=events + dropped), prepared, by_id)
    assert [(e.term, e.question_key) for e in kept] == [
        (e.term, e.question_key) for e in events
    ]


def test_gate_rejects_term_keys_not_of_the_skill() -> None:
    from tsutae.report.gate import check_inputs

    skill = _ram()
    prepared, entries = _prepared(skill)
    tampered = prepared.model_copy(update={"term_keys": {"倦怠感": None}})
    with pytest.raises(ReportBuildError) as exc:
        check_inputs(
            patient_id=PID,
            regimen_skill=skill,
            report_skill=report_skill(),
            courses=[Course(patient_id=PID, course_no=1, infusion_date=DAY1)],
            entries=entries,
            visit_date=RECORD,
            prepared=tampered,
            questions_by_version={skill.skill_version: list(skill.questions)},
        )
    assert exc.value.code == "skill_mismatch"


def test_folfox_hand_foot_event_kept_with_null_key() -> None:
    """紙の照合は checks と同じ対応（FOLFOX の質問に無い hand_foot は null）。

    T95 より前は紙の照合だけが全体の対応（hand_foot）を使い、checks が通した
    question_key=null の手足症候群の出来事を黙って落としていた。
    """
    from pipeline_fakes import load_case

    from tsutae.dataset import to_entries

    prepared = prepare_case("demo_patient")
    assert "hand_foot" not in [q.key for q in prepared.input.questions]
    patient, _labels = load_case("demo_patient")
    entries = to_entries(patient)
    by_id = {e.id: e for e in entries}
    no, text = next(iter(sorted(prepared.masked_texts.items())))
    entry = by_id[prepared.entry_ids[no]]
    term = "手掌・足底発赤知覚不全症候群"

    def ev(key: str | None) -> TimelineEvent:
        return TimelineEvent(
            entry_no=no,
            date=entry.record_date,
            day=None,
            course_no=prepared.input.schedule.course_no,
            term=term,
            question_key=key,
            status="present",
            source_quote=text[:4],
            confidence=0.9,
        )

    kept = usable_events(Timeline(events=[ev(None), ev("hand_foot")]), prepared, by_id)
    assert [(e.term, e.question_key) for e in kept] == [(term, None)]
    assert OutputContext.from_prepared(prepared).term_keys[term] is None
