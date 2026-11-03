"""tsutae.report.build_report_data（経過表・要確認・ヘッダ・引用の組み立て）。

入力はデモ患者（合成）を tsutae.dataset で Entry/Course に直し、PreparedInput と
ConversionResult は正解ラベルから組み立てる（tsutae.report.sample。pipeline は使わない）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from tsutae.config import JST
from tsutae.report import build_report_data
from tsutae.report.sample import SampleInputs, load_demo_inputs
from tsutae.schemas import (
    ClosedAnswer,
    ConversionResult,
    Entry,
    GridCell,
    GridRow,
    Question,
    ReportData,
    SymptomSummary,
    Timeline,
    TimelineEvent,
)

C3_DAY1 = date(2026, 10, 27)


def _build(sample: SampleInputs, **overrides: object) -> ReportData:
    kwargs = {**sample.build_kwargs(), **overrides}
    return build_report_data(**kwargs)


def _row(data: ReportData, key: str, *, previous: bool = False) -> GridRow:
    rows = [
        r
        for r in data.grid.rows
        if r.question_key == key and r.is_previous_course == previous
    ]
    assert len(rows) == 1, (key, previous, [r.question_key for r in data.grid.rows])
    return rows[0]


def _cell(data: ReportData, key: str, day: int, *, previous: bool = False) -> GridCell:
    cells = [c for c in _row(data, key, previous=previous).cells if c.day == day]
    assert len(cells) == 1, (key, day, previous)
    return cells[0]


def _as_old_version(entry: Entry, version: str, missing: str = "stomatitis") -> Entry:
    """質問 missing が無かった版で記録したことにする（その回答も無い）。"""
    answers = [a for a in entry.answers if a.question_key != missing]
    return entry.model_copy(update={"skill_version": version, "answers": answers})


@pytest.fixture(scope="module")
def demo() -> SampleInputs:
    return load_demo_inputs()


@pytest.fixture(scope="module")
def demo_data(demo: SampleInputs) -> ReportData:
    return _build(demo)


# ---------------------------------------------------------------------------
# ヘッダ
# ---------------------------------------------------------------------------


def test_header_for_demo_c3(demo_data: ReportData) -> None:
    h = demo_data.header
    assert h.reception_no == "A-023"
    assert h.patient_id == "P-DEMO0001"
    assert h.regimen == "FOLFOX"
    assert h.course_no == 3
    assert h.course_start == C3_DAY1
    assert h.course_end == date(2026, 11, 9)
    # C3 Day1〜14（11/09 まで）: 記録なしは Day9・Day11・Day14、too_sick は Day3〜5
    assert h.total_days == 14
    assert h.recorded_days == 11
    assert h.no_input_days == 3
    assert h.too_sick_days == 3
    assert h.recorded_days + h.no_input_days == h.total_days
    assert h.delay_note is None
    assert h.fallback is False
    assert demo_data.fallback is False
    assert demo_data.report_skill_version == "report-format-default@1"


def test_header_delay_note_for_c2() -> None:
    sample = load_demo_inputs(visit_date=date(2026, 10, 26))
    data = _build(sample)
    assert data.header.course_no == 2
    assert data.header.delay_note == "延期（予定より2日）"
    assert data.header.course_start == date(2026, 10, 13)


# ---------------------------------------------------------------------------
# 要確認
# ---------------------------------------------------------------------------


def test_attention_order_and_content(demo_data: ReportData) -> None:
    kinds = [a.kind for a in demo_data.attention]
    assert kinds == [
        "contradiction",
        "fever",
        "too_sick",
        "too_sick",
        "too_sick",
        "unprocessed",
    ]
    contradiction = demo_data.attention[0]
    assert contradiction.day == 5
    assert contradiction.question_key == "diarrhea"
    assert contradiction.closed_answer == "none"
    assert contradiction.quote == "夕方から下痢が3回あった"
    fever = demo_data.attention[1]
    assert (fever.day, fever.temperature) == (8, 37.9)
    too_sick = demo_data.attention[2:5]
    assert [a.day for a in too_sick] == [3, 4, 5]
    assert all(a.previous_course_same_day for a in too_sick)
    assert demo_data.attention[5].count == 1


def test_attention_previous_course_same_day_false(demo: SampleInputs) -> None:
    # 前コース（C2）の Day5 = 10/17 の too_sick を消す
    entries = [e for e in demo.entries if e.record_date != date(2026, 10, 17)]
    data = _build(demo, entries=entries)
    flags = {
        a.day: a.previous_course_same_day
        for a in data.attention
        if a.kind == "too_sick"
    }
    assert flags == {3: True, 4: True, 5: False}


def test_attention_fever_threshold_from_report_skill(demo: SampleInputs) -> None:
    skill = demo.report_skill.model_copy(update={"fever_attention_celsius": 36.5})
    data = _build(demo, report_skill=skill)
    fevers = [(a.day, a.temperature) for a in data.attention if a.kind == "fever"]
    assert fevers == [(8, 37.9), (10, 36.7)]


# ---------------------------------------------------------------------------
# 経過表: 列
# ---------------------------------------------------------------------------


def test_grid_columns_for_demo_c3(demo_data: ReportData) -> None:
    grid = demo_data.grid
    assert grid.days == list(range(1, 15))
    assert [c.day for c in grid.columns] == grid.days
    assert [c.date for c in grid.columns] == [
        C3_DAY1 + timedelta(days=i) for i in range(14)
    ]
    assert [c.day for c in grid.columns if c.too_sick] == [3, 4, 5]
    assert [c.day for c in grid.columns if c.by_proxy] == [5]


def test_grid_rows_current_then_previous(demo_data: ReportData) -> None:
    keys = [
        (r.course_no, r.question_key, r.is_previous_course) for r in demo_data.grid.rows
    ]
    current = ["numbness", "diarrhea", "stomatitis", "nausea_appetite", "temperature"]
    assert keys == [(3, k, False) for k in current] + [(2, k, True) for k in current]
    labels = [r.label for r in demo_data.grid.rows[:5]]
    assert labels == ["しびれ", "下痢", "口内炎", "吐き気・食欲", "体温"]


def test_grid_toggle_previous_and_temperature(demo: SampleInputs) -> None:
    skill = demo.report_skill.model_copy(
        update={"show_previous_course": False, "show_temperature_row": False}
    )
    data = _build(demo, report_skill=skill)
    assert [r.question_key for r in data.grid.rows] == [
        "numbness",
        "diarrhea",
        "stomatitis",
        "nausea_appetite",
    ]
    assert not any(r.is_previous_course for r in data.grid.rows)


# ---------------------------------------------------------------------------
# 経過表: セル（欠けの4区別 no_input / not_asked / too_sick / none）
# ---------------------------------------------------------------------------


def test_cell_no_input_on_day_without_record(demo_data: ReportData) -> None:
    for key in ("numbness", "diarrhea", "stomatitis", "nausea_appetite", "temperature"):
        for day in (9, 11, 14):
            cell = _cell(demo_data, key, day)
            assert cell.state == "no_input", (key, day)
            assert not cell.free_text_mark


def test_cell_too_sick_only_day(demo_data: ReportData) -> None:
    for day in (3, 4):
        assert _cell(demo_data, "diarrhea", day).state == "too_sick"
        assert _cell(demo_data, "temperature", day).state == "too_sick"
    # 前コース（C2）の Day3〜5 も too_sick だけ
    for day in (3, 4, 5):
        assert _cell(demo_data, "numbness", day, previous=True).state == "too_sick"


def test_cell_none_with_free_text_mark_is_contradiction(demo_data: ReportData) -> None:
    # C3 Day5: too_sick と代理の回答が同じ日。セルは回答（下痢「なし」）＋ ○
    cell = _cell(demo_data, "diarrhea", 5)
    assert cell.state == "none"
    assert cell.free_text_mark is True
    assert cell.recalled_mark is False
    assert _cell(demo_data, "nausea_appetite", 5).state == "hard"


def test_cell_not_asked_uses_skill_version_of_that_day(demo: SampleInputs) -> None:
    old = "regimen-folfox@0"
    old_questions = [q for q in demo.regimen_skill.questions if q.key != "stomatitis"]
    entries = [
        _as_old_version(e, old) if e.record_date == C3_DAY1 else e for e in demo.entries
    ]
    qbv = {**demo.questions_by_version, old: old_questions}
    data = _build(demo.with_entries(entries), questions_by_version=qbv)
    assert _cell(data, "stomatitis", 1).state == "not_asked"
    assert _cell(data, "numbness", 1).state == "present"
    assert _cell(data, "stomatitis", 2).state == "none"  # Day2 は @1
    assert _cell(data, "stomatitis", 9).state == "no_input"  # 記録なしは空白のまま


def test_cell_answers_missing_but_asked_is_no_input(demo: SampleInputs) -> None:
    # Day2（10/28）の回答つきの記録（seq 29、自由記載もある）から回答を外すと、
    # 自由記載だけの日になる
    entries = [
        (e.model_copy(update={"kind": "free_text", "answers": []}) if e.id == 29 else e)
        for e in demo.entries
    ]
    data = _build(demo.with_entries(entries))
    assert _cell(data, "numbness", 2).state == "no_input"
    assert _cell(data, "numbness", 2).free_text_mark is True


def test_cell_takes_heaviest_answer_of_the_day(demo: SampleInputs) -> None:
    extra = Entry(
        id=900,
        patient_id=demo.patient_id,
        recorded_at=datetime(2026, 11, 7, 22, 0, tzinfo=JST),
        record_date=date(2026, 11, 7),
        kind="answers",
        by_proxy=False,
        skill_version="regimen-folfox@1",
        answers=[
            ClosedAnswer(question_key="diarrhea", value="hard"),
            ClosedAnswer(question_key="numbness", value="none"),
            ClosedAnswer(question_key="fever", value="measured", temperature=36.2),
        ],
    )
    data = _build(demo.with_entries([*demo.entries, extra]))
    assert _cell(data, "diarrhea", 12).state == "hard"  # none + hard
    assert _cell(data, "numbness", 12).state == "present"  # present + none
    temp = _cell(data, "temperature", 12)
    assert (temp.state, temp.temperature) == ("present", 36.2)


def test_temperature_row(demo_data: ReportData) -> None:
    day8 = _cell(demo_data, "temperature", 8)
    assert (day8.state, day8.temperature) == ("present", 37.9)
    assert day8.free_text_mark is True  # 「熱をはかったら37.9」
    day1 = _cell(demo_data, "temperature", 1)
    assert (day1.state, day1.temperature) == ("none", None)  # 測っていない


def test_recalled_mark(demo_data: ReportData) -> None:
    # 「おとといの夜から口内炎がいたい」（Day7 の記録）→ Day5 の口内炎に ○回
    cell = _cell(demo_data, "stomatitis", 5)
    assert cell.free_text_mark and cell.recalled_mark
    day2 = _cell(demo_data, "numbness", 2)
    assert day2.free_text_mark and not day2.recalled_mark


def test_absent_event_has_no_mark(demo_data: ReportData) -> None:
    # Day13「吐き気も下痢もなかった」は否定 → ○ にしない
    assert not _cell(demo_data, "diarrhea", 13).free_text_mark
    assert not _cell(demo_data, "nausea_appetite", 13).free_text_mark


def test_previous_course_rows_use_closed_answers_only(demo: SampleInputs) -> None:
    # AI の結果に前コースの日付の出来事が混ざっていても、前コース行には ○ を付けない
    assert demo.result.timeline is not None
    stray = TimelineEvent(
        entry_no=7,
        date=date(2026, 10, 18),
        day=6,
        course_no=2,
        term="下痢",
        question_key="diarrhea",
        status="present",
        source_quote="夕方から下痢が3回あった",
        confidence=0.9,
        recalled=True,
    )
    timeline = demo.result.timeline.model_copy(
        update={"events": [*demo.result.timeline.events, stray]}
    )
    result = demo.result.model_copy(update={"timeline": timeline})
    data = _build(demo, result=result)
    prev_rows = [r for r in data.grid.rows if r.is_previous_course]
    assert prev_rows
    assert not any(
        c.free_text_mark or c.recalled_mark for r in prev_rows for c in r.cells
    )
    assert _cell(data, "diarrhea", 6, previous=True).state == "hard"


def _entry(
    sample: SampleInputs, entry_id: int, when: datetime, **fields: object
) -> Entry:
    base: dict[str, object] = {
        "id": entry_id,
        "patient_id": sample.patient_id,
        "recorded_at": when,
        "record_date": when.date(),
        "kind": "free_text",
        "by_proxy": False,
        "skill_version": "regimen-folfox@1",
    }
    return Entry(**{**base, **fields})


def test_previous_course_too_sick_with_free_text_stays_too_sick(
    demo: SampleInputs,
) -> None:
    # C2 Day5（10/17）は too_sick。同じ日に自由記載だけの記録があっても too_sick のまま
    extra = _entry(
        demo, 901, datetime(2026, 10, 17, 22, 0, tzinfo=JST), free_text="ねむれない"
    )
    data = _build(demo, entries=[*demo.entries, extra])
    for key in ("numbness", "diarrhea", "stomatitis", "nausea_appetite", "temperature"):
        assert _cell(data, key, 5, previous=True).state == "too_sick", key
    flags = {a.day: a.previous_course_same_day for a in data.attention}
    assert flags[5] is True


def test_previous_course_too_sick_with_partial_answers(demo: SampleInputs) -> None:
    # 回答のある質問は回答、回答の無い質問は too_sick（斜線）
    extra = _entry(
        demo,
        902,
        datetime(2026, 10, 17, 22, 0, tzinfo=JST),
        kind="answers",
        by_proxy=True,
        answers=[ClosedAnswer(question_key="diarrhea", value="none")],
    )
    data = _build(demo, entries=[*demo.entries, extra])
    assert _cell(data, "diarrhea", 5, previous=True).state == "none"
    assert _cell(data, "numbness", 5, previous=True).state == "too_sick"
    assert _cell(data, "temperature", 5, previous=True).state == "too_sick"


def test_current_course_too_sick_with_free_text_only(demo: SampleInputs) -> None:
    # C3 Day3（10/29）は too_sick。自由記載だけの記録を足しても too_sick（入力なしにしない）
    extra = _entry(
        demo, 903, datetime(2026, 10, 29, 22, 0, tzinfo=JST), free_text="ねむれない"
    )
    data = _build(demo.with_entries([*demo.entries, extra]))
    assert _cell(data, "diarrhea", 3).state == "too_sick"
    assert [c.day for c in data.grid.columns if c.too_sick] == [3, 4, 5]


def test_visit_after_last_day_counts_same_range() -> None:
    # 次コース未登録で受診日（11/11）が最終日（11/09）より後。Day15・16 も今コース
    sample = load_demo_inputs(visit_date=date(2026, 11, 11))
    extra = _entry(
        sample, 904, datetime(2026, 11, 10, 20, 0, tzinfo=JST), kind="too_sick"
    )
    data = _build(sample, entries=[*sample.entries, extra])
    h = data.header
    assert data.grid.days == list(range(1, 17))
    assert (h.total_days, h.recorded_days, h.no_input_days) == (16, 12, 4)
    assert h.too_sick_days == 4
    assert h.course_end == date(2026, 11, 11)
    too_sick = [a.day for a in data.attention if a.kind == "too_sick"]
    assert too_sick == [3, 4, 5, 15]
    assert [c.day for c in data.grid.columns if c.too_sick] == too_sick
    assert h.too_sick_days == len(too_sick)
    assert _cell(data, "diarrhea", 15).state == "too_sick"
    assert _cell(data, "diarrhea", 16).state == "no_input"


def test_visit_before_last_day_counts_until_visit() -> None:
    sample = load_demo_inputs(visit_date=date(2026, 11, 3))  # C3 Day8
    data = _build(sample)
    h = data.header
    assert (h.total_days, h.course_end) == (8, date(2026, 11, 9))
    assert h.recorded_days + h.no_input_days == 8
    assert data.grid.days == list(range(1, 15))
    cells = [c.day for c in _row(data, "numbness").cells]
    assert cells == list(range(1, 9))


def test_previous_course_cells_cover_its_own_days(demo_data: ReportData) -> None:
    prev = _row(demo_data, "numbness", previous=True)
    assert [c.day for c in prev.cells] == list(range(1, 15))  # C2: 10/13〜10/26
    assert _cell(demo_data, "numbness", 9, previous=True).state == "no_input"  # 10/21


# ---------------------------------------------------------------------------
# 症状別・引用
# ---------------------------------------------------------------------------


def test_per_symptom_from_picks(demo: SampleInputs, demo_data: ReportData) -> None:
    assert demo.result.picks is not None
    assert demo_data.per_symptom
    assert sorted(s.term for s in demo_data.per_symptom) == sorted(
        s.term for s in demo.result.picks.per_symptom
    )
    starts = [s.start_date for s in demo_data.per_symptom]
    assert starts == sorted(starts)


def test_per_symptom_sorted_by_start(demo: SampleInputs) -> None:
    late = SymptomSummary(
        term="悪寒",
        start_day=8,
        start_date=date(2026, 11, 3),
        representative_quote="夕方さむけがして",
        confidence=0.9,
    )
    early = SymptomSummary(
        term="下痢",
        start_day=5,
        start_date=date(2026, 10, 31),
        representative_quote="夕方から下痢が3回あった",
        confidence=0.9,
    )
    assert demo.result.picks is not None
    picks = demo.result.picks.model_copy(update={"per_symptom": [late, early]})
    result = demo.result.model_copy(update={"picks": picks})
    data = _build(demo, result=result)
    assert [s.term for s in data.per_symptom] == ["下痢", "悪寒"]


def test_quotes_masked_in_day_order(demo: SampleInputs, demo_data: ReportData) -> None:
    quotes = demo_data.quotes
    assert [q.entry_no for q in quotes] == sorted(q.entry_no for q in quotes)
    assert [q.date for q in quotes] == sorted(q.date for q in quotes)
    texts = [q.text for q in quotes]
    assert texts == [demo.prepared.masked_texts[q.entry_no] for q in quotes]
    joined = "".join(texts)
    assert "佐藤" not in joined and "○○先生" in joined
    assert "磯鷲" not in joined  # 未処理の記録は載せない
    assert any(q.by_proxy and q.day == 5 for q in quotes)


def test_quotes_max_items_keeps_latest(demo: SampleInputs) -> None:
    # 上限で切るときは受診直前の記載を残す（並びは Day 順のまま）
    skill = demo.report_skill.model_copy(update={"quotes_max_items": 3})
    data = _build(demo, report_skill=skill)
    assert [q.day for q in data.quotes] == [10, 12, 13]
    assert [q.entry_no for q in data.quotes] == [11, 12, 13]


def test_quotes_max_items_zero(demo: SampleInputs) -> None:
    skill = demo.report_skill.model_copy(update={"quotes_max_items": 0})
    assert _build(demo, report_skill=skill).quotes == []


# ---------------------------------------------------------------------------
# フォールバック・決定性
# ---------------------------------------------------------------------------


def test_fallback_has_no_ai_parts(demo: SampleInputs, demo_data: ReportData) -> None:
    fallback = load_demo_inputs(fallback=True)
    data = _build(fallback)
    assert data.fallback is True and data.header.fallback is True
    assert data.per_symptom == []
    assert not any(a.kind == "contradiction" for a in data.attention)
    assert [a.kind for a in data.attention][-1] == "unprocessed"
    assert not any(
        c.free_text_mark or c.recalled_mark for r in data.grid.rows for c in r.cells
    )
    # 経過表のセルの状態と引用はフォールバックでも同じ
    states = [[c.state for c in r.cells] for r in data.grid.rows]
    assert states == [[c.state for c in r.cells] for r in demo_data.grid.rows]
    assert data.quotes == demo_data.quotes


def test_fallback_flag_disables_ai_parts_even_with_timeline(
    demo: SampleInputs, demo_data: ReportData
) -> None:
    # timeline・picks に中身があっても、fallback=True なら AI の部分は全て空
    assert demo.result.timeline is not None and demo.result.timeline.events
    assert demo.result.timeline.contradictions
    assert demo.result.picks is not None and demo.result.picks.per_symptom
    assert any(a.kind == "contradiction" for a in demo_data.attention)
    result = demo.result.model_copy(update={"fallback": True, "error_code": "timeout"})
    data = _build(demo, result=result)
    assert data.fallback is True and data.header.fallback is True
    assert data.per_symptom == []
    assert not any(a.kind == "contradiction" for a in data.attention)
    assert not any(
        c.free_text_mark or c.recalled_mark for r in data.grid.rows for c in r.cells
    )
    assert data.quotes == demo_data.quotes


def test_empty_timeline_without_fallback_flag(demo: SampleInputs) -> None:
    # AI が呼ばれずに成功した（記録0件など）場合は fallback ではない
    result = ConversionResult(timeline=Timeline(), picks=None, fallback=False)
    data = _build(demo, result=result)
    assert data.fallback is False
    assert data.per_symptom == []
    assert not any(a.kind == "contradiction" for a in data.attention)


def test_deterministic_and_order_independent(demo: SampleInputs) -> None:
    first = _build(demo)
    second = _build(demo)
    assert first.model_dump() == second.model_dump()
    shuffled = _build(
        demo,
        entries=list(reversed(demo.entries)),
        courses=list(reversed(demo.courses)),
    )
    assert shuffled.model_dump() == first.model_dump()


def test_does_not_mutate_inputs(demo: SampleInputs) -> None:
    entries = list(demo.entries)
    qbv = {k: list(v) for k, v in demo.questions_by_version.items()}
    before = ([e.model_dump() for e in entries], {k: len(v) for k, v in qbv.items()})
    _build(demo, entries=entries, questions_by_version=qbv)
    after = ([e.model_dump() for e in entries], {k: len(v) for k, v in qbv.items()})
    assert before == after


def test_current_skill_version_needs_no_snapshot(demo: SampleInputs) -> None:
    # 今の regimen Skill と同じ版は、questions_by_version に無くてもその質問集で判断する
    # （別の版が無いときは ReportBuildError。test_report_validate.py）
    data = _build(demo, questions_by_version={})
    assert _cell(data, "stomatitis", 1).state == "none"
    assert data.model_dump() == _build(demo).model_dump()


def test_question_label_falls_back_to_text() -> None:
    from tsutae.report import question_label

    questions = [
        Question(
            key="meal_intake", text="食事はとれましたか", answer_type="three_level"
        )
    ]
    assert question_label("meal_intake", questions) == "食事はとれましたか"
    assert question_label("diarrhea", questions) == "下痢"
    assert question_label("temperature", questions) == "体温"
    assert question_label("unknown_key", questions) == "unknown_key"
