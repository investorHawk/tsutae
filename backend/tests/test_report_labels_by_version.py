"""T95: 紙の短い名前と、ヘッダの表示名。

- 経過表の行・要確認の質問の名前: 既知の6問は今の SHORT_LABELS、それ以外は版の form の
  短い名前（label）、それも無ければ質問文（旧 D4 で足した版など）、最後に key
- ヘッダのレジメンは表示名（display_name。無ければ識別名。FOLFOX/CAPOX は今と同じ）
"""

from __future__ import annotations

from datetime import date, datetime

from pipeline_fakes import report_skill
from regimen_fixtures import extra_form

from tsutae.config import JST
from tsutae.pipeline.inputs import prepare_input
from tsutae.regimen import render_regimen_skill
from tsutae.regimen.labels import question_labels_of
from tsutae.report import build_report_data, render_report_html
from tsutae.report.labels import question_label
from tsutae.schemas import (
    ClosedAnswer,
    Contradiction,
    ConversionResult,
    Course,
    Entry,
    Question,
    RegimenSkill,
    ReportPicks,
    Timeline,
)
from tsutae.skills import load_regimen_skill, validate_skill_text

PID = "P-RAMW0001"
DAY1 = date(2026, 11, 2)
RECORD = date(2026, 11, 9)
TEXT = "だるさは無かった"
QUESTIONS = [
    Question(key="diarrhea", text="下痢はありましたか", answer_type="three_level"),
    Question(key="fatigue", text="だるさや疲れやすさは", answer_type="three_level"),
    Question(key="odd", text="変わった質問", answer_type="three_level"),
]


def _ram() -> RegimenSkill:
    skill = validate_skill_text(
        "regimen-ram-wptx", render_regimen_skill(extra_form("ram_wptx"), 1)
    )
    assert isinstance(skill, RegimenSkill)
    return skill


def test_question_label_order() -> None:
    labels = {"fatigue": "だるさ", "diarrhea": "お腹"}
    assert question_label("diarrhea", QUESTIONS, labels) == "下痢"  # 既知は今のまま
    assert question_label("fatigue", QUESTIONS, labels) == "だるさ"
    assert question_label("odd", QUESTIONS, labels) == "変わった質問"
    assert question_label("none_such", QUESTIONS, labels) == "none_such"
    assert question_label("fatigue", QUESTIONS) == "だるさや疲れやすさは"


def test_question_labels_of_form() -> None:
    labels = question_labels_of(extra_form("ram_wptx"))
    assert labels["fatigue"] == "だるさ"
    assert labels["bleeding"] == "出血"
    assert labels["neuropathy"] == "しびれ"
    assert question_labels_of(None) == {}


def _report(skill: RegimenSkill, labels: dict[str, str] | None) -> tuple[str, str]:
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
    courses = [Course(patient_id=PID, course_no=1, infusion_date=DAY1)]
    rskill = report_skill()
    prepared = prepare_input(
        courses=courses,
        entries=entries,
        regimen_skill=skill,
        report_skill=rskill,
        visit_date=RECORD,
    )
    contradiction = Contradiction(
        entry_no=1,
        date=RECORD,
        day=8,
        question_key="fatigue",
        closed_answer="present",
        free_text_quote=TEXT,
    )
    result = ConversionResult(
        timeline=Timeline(contradictions=[contradiction]),
        picks=ReportPicks(),
        fallback=False,
    )
    data = build_report_data(
        reception_no="B-101",
        patient_id=PID,
        regimen_skill=skill,
        report_skill=rskill,
        courses=courses,
        entries=entries,
        visit_date=RECORD,
        prepared=prepared,
        result=result,
        questions_by_version={skill.skill_version: list(skill.questions)},
        question_labels=labels,
    )
    html = render_report_html(
        data, questions=list(skill.questions), question_labels=labels
    )
    rows = {r.question_key: r.label for r in data.grid.rows}
    return html, rows["fatigue"]


def test_paper_uses_form_labels_and_display_name() -> None:
    skill = _ram()
    labels = question_labels_of(extra_form("ram_wptx"))
    html, fatigue = _report(skill, labels)
    assert fatigue == "だるさ"
    assert "<td>RAM＋wPTX</td>" in html
    assert "だるさ: クローズ回答「ある」" in html


def test_without_labels_falls_back_to_question_text() -> None:
    skill = _ram()
    html, fatigue = _report(skill, None)
    assert fatigue == "だるさや疲れやすさはありましたか"


def test_builtin_header_is_the_code() -> None:
    skill = load_regimen_skill("FOLFOX")
    assert skill.display_name is None
    html, _ = _report_folfox(skill)
    assert "<td>FOLFOX</td>" in html


def _report_folfox(skill: RegimenSkill) -> tuple[str, None]:
    from tsutae.report.sample import load_demo_inputs

    sample = load_demo_inputs()
    data = build_report_data(**sample.build_kwargs())
    assert data.header.regimen_label is None
    return render_report_html(data, questions=list(skill.questions)), None
