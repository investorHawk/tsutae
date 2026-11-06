"""AI の出力と入力の照合（tsutae.report.build_report_data の入口と AI 由来の欄）。

- 症状別の時系列: 用語名は ctcae_terms.json の一覧だけ。代表引用はその用語の出来事の
  source_quote。開始日・Day・確からしさは出来事から決め直す（AI は選び方だけ）
- 要確認の食い違い: entry_no の記録の実際のクローズ回答と照合し、合わないものは落とす
- 入口: 患者・日程・記録の対応が合わなければ ReportBuildError
症例は全て合成。
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from tsutae.config import JST
from tsutae.report import ReportBuildError, build_report_data, render_report_html
from tsutae.report.labels import SEVERITY_WORDS
from tsutae.report.sample import SampleInputs, load_demo_inputs
from tsutae.schemas import (
    ClosedAnswer,
    Contradiction,
    Course,
    Entry,
    GridCell,
    PreparedInput,
    ReportData,
    ReportPicks,
    SymptomSummary,
    TimelineEvent,
    UnprocessedEntry,
)
from tsutae.synthetic import load_terms

C3_DAY5 = date(2026, 10, 31)


@pytest.fixture(scope="module")
def demo() -> SampleInputs:
    return load_demo_inputs()


def _build(sample: SampleInputs, **overrides: object) -> ReportData:
    return build_report_data(**{**sample.build_kwargs(), **overrides})


def _html(sample: SampleInputs, data: ReportData) -> str:
    return render_report_html(data, questions=list(sample.regimen_skill.questions))


def _section(html: str, cls: str) -> str:
    match = re.search(rf'<section class="{cls}[^"]*">(.*?)</section>', html, re.S)
    assert match, cls
    return match.group(1)


def _summary(
    term: str,
    quote: str,
    *,
    start_day: int | None = 5,
    start_date: date = C3_DAY5,
    confidence: float = 0.9,
    question_key: str | None = None,
) -> SymptomSummary:
    return SymptomSummary(
        term=term,
        question_key=question_key,
        start_day=start_day,
        start_date=start_date,
        representative_quote=quote,
        confidence=confidence,
    )


def _with_picks(sample: SampleInputs, items: list[SymptomSummary]) -> ReportData:
    result = sample.result.model_copy(update={"picks": ReportPicks(per_symptom=items)})
    return _build(sample, result=result)


def _with_contradictions(
    sample: SampleInputs, items: list[Contradiction]
) -> ReportData:
    assert sample.result.timeline is not None
    timeline = sample.result.timeline.model_copy(update={"contradictions": items})
    return _build(
        sample, result=sample.result.model_copy(update={"timeline": timeline})
    )


def _demo_contradiction(sample: SampleInputs, **update: object) -> Contradiction:
    assert sample.result.timeline is not None
    return sample.result.timeline.contradictions[0].model_copy(update=update)


def _contradictions(data: ReportData) -> list[tuple[object, ...]]:
    return [
        (a.day, a.question_key, a.closed_answer, a.quote)
        for a in data.attention
        if a.kind == "contradiction"
    ]


# ---------------------------------------------------------------------------
# 症状別の時系列: 用語名
# ---------------------------------------------------------------------------


def test_ctcae_terms_have_no_severity_words() -> None:
    for item in load_terms():
        for word in SEVERITY_WORDS:
            assert word.lower() not in item["term"].lower(), (item["term"], word)


@pytest.mark.parametrize(
    "term",
    [
        "下痢 Grade 2（重症）",
        "Grade 3",
        "重症の下痢",
        "下痢（軽症）",
        "受診してください",
        "下痢 ",
        "diarrhea",
    ],
)
def test_term_outside_ctcae_list_is_dropped(demo: SampleInputs, term: str) -> None:
    data = _with_picks(demo, [_summary(term, "夕方から下痢が3回あった")])
    assert data.per_symptom == []
    section = _section(_html(demo, data), "per-symptom")
    assert term.strip() not in section
    for word in SEVERITY_WORDS:
        assert word not in section, word
    assert "grade" not in section.lower()


def test_adversarial_term_mixed_with_valid_ones(demo: SampleInputs) -> None:
    items = [
        _summary("下痢 Grade 2（重症）", "夕方から下痢が3回あった"),
        _summary("下痢", "夕方から下痢が3回あった", question_key="diarrhea"),
    ]
    data = _with_picks(demo, items)
    assert [s.term for s in data.per_symptom] == ["下痢"]
    html = _html(demo, data)
    for word in SEVERITY_WORDS:
        assert word not in html, word


def test_patient_quote_may_contain_severity_words(demo: SampleInputs) -> None:
    # 患者の原文には「重症」と書く自由がある。引用には禁止語の検査を掛けない
    extra = Entry(
        id=950,
        patient_id=demo.patient_id,
        recorded_at=datetime(2026, 11, 6, 21, 0, tzinfo=JST),
        record_date=date(2026, 11, 6),
        kind="free_text",
        by_proxy=False,
        skill_version="regimen-folfox@1",
        free_text="重症かと思うほど下痢がつらかった",
    )
    data = _build(demo.with_entries([*demo.entries, extra]))
    assert any("重症" in q.text for q in data.quotes)
    assert "重症かと思うほど" in _section(_html(demo, data), "quotes")


# ---------------------------------------------------------------------------
# 症状別の時系列: 出来事との照合
# ---------------------------------------------------------------------------


def test_quote_must_be_source_quote_of_same_term(demo: SampleInputs) -> None:
    items = [
        _summary("下痢", "しゃっくりがとまらない"),  # 別の用語の出来事の引用
        _summary("下痢", "夕方から下痢が3回"),  # 出来事の引用の一部だけ
        _summary("倦怠感", "だるい"),  # 出来事に無い用語
    ]
    assert _with_picks(demo, items).per_symptom == []


def test_absent_only_term_is_dropped(demo: SampleInputs) -> None:
    # Day13「吐き気も下痢もなかった」の悪心は absent だけ
    data = _with_picks(demo, [_summary("悪心", "吐き気も下痢もなかった")])
    assert data.per_symptom == []


def test_start_and_confidence_come_from_events(demo: SampleInputs) -> None:
    # AI の開始日・Day・確からしさは使わない。出来事から決め直す
    item = _summary(
        "下痢",
        "下痢は2回。きのうよりはまし",
        start_day=1,
        start_date=date(2026, 11, 7),
        confidence=0.99,
    )
    data = _with_picks(demo, [item])
    [s] = data.per_symptom
    assert (s.start_date, s.start_day) == (C3_DAY5, 5)  # present の最初の日
    assert s.representative_quote == "下痢は2回。きのうよりはまし"
    assert s.confidence == 0.9  # 代表引用に選んだ出来事（Day6 improving）の値
    assert s.question_key == "diarrhea"


def test_recalled_event_confidence_is_used(demo: SampleInputs) -> None:
    item = _summary("口内炎", "おとといの夜から口内炎がいたい", confidence=0.95)
    [s] = _with_picks(demo, [item]).per_symptom
    assert s.confidence == 0.5  # 回想の出来事の値（「？」が付く）
    assert (s.start_date, s.start_day) == (C3_DAY5, 5)


def test_sorted_by_start_day_even_if_ai_day_disagrees(demo: SampleInputs) -> None:
    # AI の start_day と start_date が食い違っていても、出来事から数え直した Day 順
    items = [
        _summary("発熱", "熱をはかったら37.9", start_day=1),
        _summary("下痢", "夕方から下痢が3回あった", start_day=12),
        _summary("しゃっくり", "しゃっくりがとまらない", start_day=None),
    ]
    data = _with_picks(demo, items)
    assert [(s.term, s.start_day) for s in data.per_symptom] == [
        ("しゃっくり", 2),
        ("下痢", 5),
        ("発熱", 8),
    ]


def test_duplicate_term_is_kept_once(demo: SampleInputs) -> None:
    items = [
        _summary("下痢", "夕方から下痢が3回あった"),
        _summary("下痢", "下痢は2回。きのうよりはまし"),
    ]
    data = _with_picks(demo, items)
    assert [s.representative_quote for s in data.per_symptom] == [
        "夕方から下痢が3回あった"
    ]


def test_demo_picks_survive_validation(demo: SampleInputs) -> None:
    assert demo.result.picks is not None
    data = _build(demo)
    assert [s.term for s in data.per_symptom] == [
        s.term
        for s in sorted(
            demo.result.picks.per_symptom, key=lambda s: (s.start_date, s.term)
        )
    ]


# ---------------------------------------------------------------------------
# 要確認の食い違い: 実際のクローズ回答との照合
# ---------------------------------------------------------------------------


def test_contradiction_with_real_answer_is_kept(demo: SampleInputs) -> None:
    data = _with_contradictions(demo, [_demo_contradiction(demo)])
    assert _contradictions(data) == [(5, "diarrhea", "none", "夕方から下痢が3回あった")]


@pytest.mark.parametrize(
    "update",
    [
        {"closed_answer": "hard"},  # 記録は「なし」
        {"closed_answer": "present"},
        {"question_key": "hand_foot"},  # その記録に回答が無い質問
        {"question_key": "stomatitis", "closed_answer": "none"},  # 記録は「ある」
        {"entry_no": 99},  # 未知の記録
        {"entry_no": 6},  # too_sick の記録（回答も自由記載も無い）
        {"date": date(2026, 10, 20), "day": 99},  # 記録日と違う（前コースの日付）
        {"free_text_quote": "下痢が5回あった"},  # 自由記載に無い引用
    ],
)
def test_contradiction_not_matching_record_is_dropped(
    demo: SampleInputs, update: dict[str, object]
) -> None:
    data = _with_contradictions(demo, [_demo_contradiction(demo, **update)])
    assert _contradictions(data) == []
    section = _section(_html(demo, data), "attention")
    assert "食い違い" not in section


def test_contradiction_day_comes_from_record_not_ai(demo: SampleInputs) -> None:
    data = _with_contradictions(demo, [_demo_contradiction(demo, day=99)])
    assert _contradictions(data) == [(5, "diarrhea", "none", "夕方から下痢が3回あった")]


def test_contradiction_with_tampered_answer_not_printed(demo: SampleInputs) -> None:
    bad = _demo_contradiction(demo, closed_answer="hard")
    good = _demo_contradiction(demo)
    data = _with_contradictions(demo, [bad, good])
    section = _section(_html(demo, data), "attention")
    assert "クローズ回答「なし」" in section
    assert "クローズ回答「つらい」" not in section


# ---------------------------------------------------------------------------
# 入口の検査（患者・日程・記録の対応）
# ---------------------------------------------------------------------------


def _other_patient_entry(sample: SampleInputs) -> Entry:
    return Entry(
        id=960,
        patient_id="P-OTHER001",
        recorded_at=datetime(2026, 11, 7, 21, 0, tzinfo=JST),
        record_date=date(2026, 11, 7),
        kind="answers",
        by_proxy=False,
        skill_version="regimen-folfox@1",
        answers=[{"question_key": "diarrhea", "value": "hard"}],
    )


def test_entry_of_other_patient_is_rejected(demo: SampleInputs) -> None:
    entries = [*demo.entries, _other_patient_entry(demo)]
    with pytest.raises(ReportBuildError) as err:
        _build(demo, entries=entries)
    assert err.value.code == "patient_mismatch"


def test_course_of_other_patient_is_rejected(demo: SampleInputs) -> None:
    courses = [
        c.model_copy(update={"patient_id": "P-OTHER001"}) if c.course_no == 1 else c
        for c in demo.courses
    ]
    with pytest.raises(ReportBuildError) as err:
        _build(demo, courses=courses)
    assert err.value.code == "patient_mismatch"


def test_patient_id_argument_must_match_records(demo: SampleInputs) -> None:
    with pytest.raises(ReportBuildError) as err:
        _build(demo, patient_id="P-OTHER001")
    assert err.value.code == "patient_mismatch"


def test_prepared_for_other_course_is_rejected(demo: SampleInputs) -> None:
    c2 = load_demo_inputs(visit_date=date(2026, 10, 26))
    with pytest.raises(ReportBuildError) as err:
        _build(demo, prepared=c2.prepared)
    assert err.value.code == "schedule_mismatch"


def test_prepared_schedule_must_match_courses(demo: SampleInputs) -> None:
    courses: list[Course] = [
        c.model_copy(update={"next_visit": date(2026, 11, 9)}) for c in demo.courses
    ]
    _build(demo, courses=courses)  # 日程に関わらない項目の違いは通す
    schedule = demo.prepared.input.schedule.model_copy(update={"delay_days": 5})
    prepared = demo.prepared.model_copy(
        update={"input": demo.prepared.input.model_copy(update={"schedule": schedule})}
    )
    with pytest.raises(ReportBuildError) as err:
        _build(demo, prepared=prepared)
    assert err.value.code == "schedule_mismatch"


def test_prepared_entry_id_must_exist(demo: SampleInputs) -> None:
    entry_ids = {**demo.prepared.entry_ids, 7: 9999}
    prepared = demo.prepared.model_copy(update={"entry_ids": entry_ids})
    with pytest.raises(ReportBuildError) as err:
        _build(demo, prepared=prepared)
    assert err.value.code == "entry_mismatch"


def test_prepared_entry_must_match_record(demo: SampleInputs) -> None:
    # entry_no 7（C3 Day5 の代理入力）の回答を書き換えた入力
    masked = [
        (me.model_copy(update={"answers": []}) if me.entry_no == 7 else me)
        for me in demo.prepared.input.entries
    ]
    prepared = demo.prepared.model_copy(
        update={"input": demo.prepared.input.model_copy(update={"entries": masked})}
    )
    with pytest.raises(ReportBuildError) as err:
        _build(demo, prepared=prepared)
    assert err.value.code == "entry_mismatch"


def test_duplicate_entry_ids_are_rejected(demo: SampleInputs) -> None:
    dup = demo.entries[0].model_copy(
        update={"recorded_at": demo.entries[0].recorded_at}
    )
    with pytest.raises(ReportBuildError) as err:
        _build(demo, entries=[*demo.entries, dup])
    assert err.value.code == "entry_mismatch"


def test_report_build_error_is_value_error() -> None:
    err = ReportBuildError("patient_mismatch")
    assert isinstance(err, ValueError) and err.code == "patient_mismatch"


# ---------------------------------------------------------------------------
# 版ごとの質問集（未設問の判断）
# ---------------------------------------------------------------------------


def test_unknown_old_skill_version_is_rejected(demo: SampleInputs) -> None:
    # 版のスナップショットが無いと「未設問」と「入力なし」を区別できない。補わずに失敗させる
    old = "regimen-folfox@0"
    entries = [
        (
            e.model_copy(
                update={
                    "skill_version": old,
                    "answers": [a for a in e.answers if a.question_key != "stomatitis"],
                }
            )
            if e.record_date == date(2026, 10, 27)
            else e
        )
        for e in demo.entries
    ]
    with pytest.raises(ReportBuildError) as err:
        _build(demo.with_entries(entries))
    assert err.value.code == "unknown_skill_version"


@pytest.mark.parametrize(
    "visit",
    [date(2026, 11, 9), date(2026, 10, 26), date(2026, 11, 3), date(2026, 11, 12)],
)
def test_pipeline_prepare_input_passes_checks(visit: date) -> None:
    # 本番の経路（pipeline.inputs.prepare_input）の出力が入口の検査を通ること
    from tsutae.pipeline.inputs import prepare_input
    from tsutae.report.sample import result_from_labels

    sample = load_demo_inputs(visit_date=visit)
    prepared = prepare_input(
        courses=sample.courses,
        entries=sample.entries,
        regimen_skill=sample.regimen_skill,
        report_skill=sample.report_skill,
        visit_date=visit,
    )
    result = result_from_labels(prepared, sample.labels)
    data = _build(sample, prepared=prepared, result=result)
    assert data.model_dump() == _build(sample).model_dump()


# ---------------------------------------------------------------------------
# 出来事の照合: AI の出力をわざと崩した入力（○・「回」・代表引用）
# ---------------------------------------------------------------------------


def _with_result(
    sample: SampleInputs,
    *,
    events: list[TimelineEvent] | None = None,
    picks: list[SymptomSummary] | None = None,
    unprocessed: list[UnprocessedEntry] | None = None,
) -> ReportData:
    assert sample.result.timeline is not None
    update: dict[str, object] = {}
    if events is not None:
        update["events"] = events
    if unprocessed is not None:
        update["unprocessed_entries"] = unprocessed
    result = sample.result.model_copy(
        update={"timeline": sample.result.timeline.model_copy(update=update)}
    )
    if picks is not None:
        result = result.model_copy(update={"picks": ReportPicks(per_symptom=picks)})
    return _build(sample, result=result)


def _events_with(
    sample: SampleInputs, entry_no: int, term: str, /, **update: object
) -> list[TimelineEvent]:
    """entry_no・term の出来事（1つ）だけを書き換えた出来事の一覧。"""
    assert sample.result.timeline is not None
    events = list(sample.result.timeline.events)
    [i] = [
        i for i, ev in enumerate(events) if ev.entry_no == entry_no and ev.term == term
    ]
    events[i] = events[i].model_copy(update=update)
    return events


def _cell_of(data: ReportData, key: str, day: int) -> GridCell:
    [row] = [
        r for r in data.grid.rows if r.question_key == key and not r.is_previous_course
    ]
    [cell] = [c for c in row.cells if c.day == day]
    return cell


def test_event_dated_after_its_record_is_dropped(demo: SampleInputs) -> None:
    # entry 3（10/28 Day2）の記録に、記録日より後（11/06 Day11）の出来事は書けない
    quote = "きょうも水道の水でピリピリ"
    events = _events_with(
        demo,
        3,
        "末梢神経障害",
        date=date(2026, 11, 6),
        day=11,
        term="下痢",
        question_key="diarrhea",
    )
    data = _with_result(demo, events=events, picks=[_summary("下痢", quote)])
    cell = _cell_of(data, "diarrhea", 11)
    assert cell.state == "no_input"  # 空白の日は空白のまま
    assert not cell.free_text_mark and not cell.recalled_mark
    assert data.per_symptom == []  # 下痢と関係のない引用を代表にしない


def test_recalled_mark_comes_from_dates_not_ai(demo: SampleInputs) -> None:
    # entry 9（11/02）の口内炎は 10/31 の出来事＝回想。AI が recalled=False でも「回」
    events = _events_with(demo, 9, "口内炎", recalled=False)
    # entry 7（10/31）の下痢は記録日と同じ日。AI が recalled=True でも「回」は付けない
    events = [
        (
            ev.model_copy(update={"recalled": True})
            if (ev.entry_no, ev.term) == (7, "下痢")
            else ev
        )
        for ev in events
    ]
    data = _with_result(demo, events=events)
    stomatitis = _cell_of(data, "stomatitis", 5)
    assert stomatitis.free_text_mark and stomatitis.recalled_mark
    diarrhea = _cell_of(data, "diarrhea", 5)
    assert diarrhea.state == "none"  # 食い違いの日
    assert diarrhea.free_text_mark and not diarrhea.recalled_mark


def test_recalled_used_for_per_symptom_is_from_dates(demo: SampleInputs) -> None:
    events = _events_with(demo, 9, "口内炎", recalled=False)
    data = _with_result(demo, events=events)
    [s] = [s for s in data.per_symptom if s.term == "口内炎"]
    assert (s.start_date, s.start_day) == (C3_DAY5, 5)


@pytest.mark.parametrize(
    ("entry_no", "term", "update", "row", "day"),
    [
        (7, "下痢", {"question_key": "stomatitis"}, "diarrhea", 5),
        (7, "下痢", {"term": "おなかの不調"}, "diarrhea", 5),  # 一覧に無い用語
        (7, "下痢", {"question_key": None}, "diarrhea", 5),
        (10, "発熱", {"question_key": "diarrhea"}, "temperature", 8),
    ],
)
def test_event_term_and_question_key_must_match_list(
    demo: SampleInputs,
    entry_no: int,
    term: str,
    update: dict[str, object],
    row: str,
    day: int,
) -> None:
    data = _with_result(demo, events=_events_with(demo, entry_no, term, **update))
    assert not _cell_of(data, row, day).free_text_mark
    if update.get("question_key") == "stomatitis":
        # 口内炎 Day5 の ○ は entry 9 の回想だけが支える（entry 7 は混ざらない）
        cell = _cell_of(data, "stomatitis", 5)
        assert cell.free_text_mark and cell.recalled_mark
    if update.get("question_key") == "diarrhea":
        assert not _cell_of(data, "diarrhea", 8).free_text_mark


def test_mismatched_event_is_not_representative_quote(demo: SampleInputs) -> None:
    events = _events_with(demo, 7, "下痢", question_key="stomatitis")
    data = _with_result(
        demo, events=events, picks=[_summary("下痢", "夕方から下痢が3回あった")]
    )
    assert data.per_symptom == []


def test_processed_entry_in_timeline_unprocessed_is_ignored(
    demo: SampleInputs,
) -> None:
    # 未処理は prepared.unprocessed（コードの選別）だけで決める。AI 側の値は使わない
    assert demo.result.timeline is not None
    unprocessed = [
        *demo.result.timeline.unprocessed_entries,
        UnprocessedEntry(entry_id=demo.prepared.entry_ids[13], reason="x"),
    ]
    data = _with_result(demo, unprocessed=unprocessed)
    assert 13 in [q.entry_no for q in data.quotes]
    [item] = [a for a in data.attention if a.kind == "unprocessed"]
    assert item.count == 1


# ---------------------------------------------------------------------------
# 入口の検査: Skill の版・Day・伏せ字・回答の型
# ---------------------------------------------------------------------------


def _prepared_with(sample: SampleInputs, **input_update: object) -> PreparedInput:
    return sample.prepared.model_copy(
        update={"input": sample.prepared.input.model_copy(update=input_update)}
    )


def _with_masked_entry(
    sample: SampleInputs, entry_no: int, **update: object
) -> PreparedInput:
    masked = [
        me.model_copy(update=update) if me.entry_no == entry_no else me
        for me in sample.prepared.input.entries
    ]
    return _prepared_with(sample, entries=masked)


@pytest.mark.parametrize(
    "update",
    [
        {"regimen_skill_version": "regimen-folfox@0"},
        {"report_skill_version": "report-format-default@9"},
        {"questions": "drop_last"},
        {"questions": "reversed"},
    ],
)
def test_prepared_skill_versions_and_questions_must_match(
    demo: SampleInputs, update: dict[str, object]
) -> None:
    questions = list(demo.prepared.input.questions)
    if update.get("questions") == "drop_last":
        update = {"questions": questions[:-1]}
    elif update.get("questions") == "reversed":
        update = {"questions": questions[::-1]}
    with pytest.raises(ReportBuildError) as err:
        _build(demo, prepared=_prepared_with(demo, **update))
    assert err.value.code == "skill_mismatch"


def test_report_skill_must_match_prepared(demo: SampleInputs) -> None:
    newer = demo.report_skill.model_copy(update={"version": 2})
    with pytest.raises(ReportBuildError) as err:
        _build(demo, report_skill=newer)
    assert err.value.code == "skill_mismatch"


def test_prepared_entry_day_must_match_record_date(demo: SampleInputs) -> None:
    with pytest.raises(ReportBuildError) as err:
        _build(demo, prepared=_with_masked_entry(demo, 7, day=99))
    assert err.value.code == "entry_mismatch"


def test_quote_day_is_computed_from_record_date(demo: SampleInputs) -> None:
    data = _build(demo)
    days = {q.entry_no: q.day for q in data.quotes}
    assert days[7] == 5 and days[13] == 13


def test_fabricated_masked_text_is_rejected(demo: SampleInputs) -> None:
    # masked_texts と MaskedEntry の両方を同じ捏造文にしても、元の記録の伏せ字と合わない
    fake = "夕方から下痢が10回あった"
    prepared = _with_masked_entry(demo, 13, masked_free_text=fake)
    prepared = prepared.model_copy(
        update={"masked_texts": {**prepared.masked_texts, 13: fake}}
    )
    with pytest.raises(ReportBuildError) as err:
        _build(demo, prepared=prepared)
    assert err.value.code == "entry_mismatch"


def test_text_added_to_record_without_free_text_is_rejected(
    demo: SampleInputs,
) -> None:
    # entry 1 は回答だけの記録。そこへ文を足した入力は通さない
    fake = "下痢がひどい"
    prepared = _with_masked_entry(demo, 1, masked_free_text=fake)
    prepared = prepared.model_copy(
        update={"masked_texts": {**prepared.masked_texts, 1: fake}}
    )
    with pytest.raises(ReportBuildError) as err:
        _build(demo, prepared=prepared)
    assert err.value.code == "entry_mismatch"


def _answers_entry(
    sample: SampleInputs, entry_id: int, answers: list[ClosedAnswer]
) -> Entry:
    when = datetime(2026, 11, 4, 21, 0, tzinfo=JST)  # C3 Day9（記録の無い日）
    return Entry(
        id=entry_id,
        patient_id=sample.patient_id,
        recorded_at=when,
        record_date=when.date(),
        kind="answers",
        by_proxy=False,
        skill_version="regimen-folfox@1",
        answers=answers,
    )


@pytest.mark.parametrize(
    "answer",
    [
        ClosedAnswer(question_key="diarrhea", value="measured", temperature=39.0),
        ClosedAnswer(question_key="diarrhea", value="not_measured"),
        ClosedAnswer(question_key="fever", value="hard"),
    ],
)
def test_answer_value_must_fit_question_type(
    demo: SampleInputs, answer: ClosedAnswer
) -> None:
    extra = _answers_entry(demo, 970, [answer])
    with pytest.raises(ReportBuildError) as err:
        _build(demo.with_entries([*demo.entries, extra]))
    assert err.value.code == "answer_mismatch"


def test_fever_only_from_temperature_questions(demo: SampleInputs) -> None:
    # 質問集に無い key の「測った」は体温として扱わない（発熱にしない）
    extra = _answers_entry(
        demo,
        971,
        [ClosedAnswer(question_key="body_temp", value="measured", temperature=39.0)],
    )
    data = _build(demo.with_entries([*demo.entries, extra]))
    fevers = [(a.day, a.temperature) for a in data.attention if a.kind == "fever"]
    assert fevers == [(8, 37.9)]
