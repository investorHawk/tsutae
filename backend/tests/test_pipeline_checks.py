"""tsutae.pipeline.checks（emit_* の中身を入力と用語の一覧に照らす純関数）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from pipeline_fakes import label_payloads, load_case, prepare_case

from tsutae.course import day_of
from tsutae.dataset import to_courses
from tsutae.pipeline.checks import OutputContext, report_problems, timeline_problems
from tsutae.schemas import Contradiction, SymptomSummary, Timeline, TimelineEvent

PREPARED = prepare_case("demo_patient")
CTX = OutputContext.from_prepared(PREPARED)
LAST_NO = max(PREPARED.masked_texts)  # 11/08（Day13）の記録。今コースの最終日は 11/09


def _event(**over: Any) -> TimelineEvent:
    base: dict[str, Any] = {
        "entry_no": LAST_NO,
        "date": date(2026, 11, 8),
        "day": 13,
        "course_no": 3,
        "term": "下痢",
        "question_key": "diarrhea",
        "status": "absent",
        "source_quote": "吐き気も下痢もなかった",
        "confidence": 0.9,
    }
    return TimelineEvent(**{**base, **over})


def test_context_copies_schedule_and_entries() -> None:
    schedule = PREPARED.input.schedule
    assert CTX.course_no == schedule.course_no == 3
    assert CTX.day1_date == schedule.day1_date
    assert CTX.last_day_date == schedule.last_day_date
    assert set(CTX.entries) == set(PREPARED.entry_ids) == CTX.entry_nos
    with pytest.raises(TypeError):
        CTX.entries[999] = CTX.entries[1]  # type: ignore[index]


def test_term_keys_drop_questions_not_asked_this_time() -> None:
    terms = [
        {"term": "下痢", "question_key": "diarrhea"},
        {"term": "手足症候群", "question_key": "hand_foot"},
        {"term": "疲労", "question_key": None},
    ]
    ctx = OutputContext.from_prepared(PREPARED, terms=terms)
    assert dict(ctx.term_keys) == {
        "下痢": "diarrhea",
        "手足症候群": None,  # FOLFOX には手足症候群の質問が無い
        "疲労": None,
    }


def test_default_terms_come_from_ctcae_list() -> None:
    assert CTX.term_keys["下痢"] == "diarrhea"
    assert CTX.term_keys["しゃっくり"] is None
    assert "Grade" not in "".join(CTX.term_keys)


def test_label_timeline_has_no_problems() -> None:
    timeline, _ = label_payloads("demo_patient", PREPARED)
    events = [TimelineEvent.model_validate(e) for e in timeline["events"]]
    contradictions = [
        Contradiction.model_validate(c) for c in timeline["contradictions"]
    ]
    assert timeline_problems(events, contradictions, CTX) == []


def test_event_after_its_record_date_is_rejected() -> None:
    # report は記録日より後の出来事を使わない（§7 W2b）。受け付けると紙から黙って消える
    event = _event(date=date(2026, 11, 9), day=14)
    problems = timeline_problems([event], [], CTX)
    assert [where for where, _ in problems] == ["events.0.date"]


@pytest.mark.parametrize("day", [None, 15])
def test_event_after_last_day_is_rejected(day: int | None) -> None:
    event = _event(date=date(2026, 11, 10), day=day)
    wheres = [where for where, _ in timeline_problems([event], [], CTX)]
    assert "events.0.date" in wheres


def test_day_agrees_with_course_day_of_for_every_allowed_date() -> None:
    # 受け付ける date は記録日以前（≦ 最終日）なので、day_of の答えは一意に決まる
    patient, _ = load_case("demo_patient")
    courses = to_courses(patient)
    schedule = PREPARED.input.schedule
    record_date = CTX.entries[LAST_NO].record_date
    d = schedule.day1_date - timedelta(days=20)
    while d <= record_date:
        expected = day_of(d, schedule, courses=courses)
        ok = _event(date=d, day=expected, recalled=d < record_date)
        assert timeline_problems([ok], [], CTX) == [], d
        wrong = (expected or 0) + 1 if expected is not None else 1
        bad = _event(date=d, day=wrong, recalled=d < record_date)
        assert [w for w, _ in timeline_problems([bad], [], CTX)] == ["events.0.day"]
        d += timedelta(days=1)


def test_duplicate_events_are_rejected_by_position() -> None:
    first = _event()
    again = _event(confidence=0.5)  # 同じ (entry_no, term, date, status, source_quote)
    other_status = _event(status="present")
    problems = timeline_problems([first, other_status, again], [], CTX)
    assert problems == [("events.2", "同じ出来事が前にある（重ねて出さない）")]


def _contradiction(**over: Any) -> Contradiction:
    timeline, _ = label_payloads("demo_patient", PREPARED)
    base = timeline["contradictions"][0]
    return Contradiction.model_validate({**base, **over})


def test_duplicate_contradictions_are_rejected_by_position() -> None:
    c = _contradiction()
    problems = timeline_problems([], [c, c, c], CTX)
    assert [where for where, _ in problems] == [
        "contradictions.1",
        "contradictions.2",
    ]


def test_problems_are_positions_and_fixed_messages() -> None:
    event = _event(term="重症の下痢", course_no=9, by_proxy=True, day=1)
    problems = timeline_problems([event], [], CTX)
    assert [where for where, _ in problems] == [
        "events.0.term",
        "events.0.course_no",
        "events.0.by_proxy",
        "events.0.day",
    ]
    assert all("重症" not in why for _, why in problems)


def test_unknown_entry_no_stops_further_checks_of_that_item() -> None:
    event = _event(entry_no=999, term="x")
    assert [w for w, _ in timeline_problems([event], [], CTX)] == ["events.0.entry_no"]


def test_report_needs_timeline() -> None:
    summary = SymptomSummary(
        term="下痢",
        start_day=5,
        start_date=date(2026, 10, 31),
        representative_quote="夕方から下痢が3回あった",
        confidence=0.9,
    )
    assert [w for w, _ in report_problems([summary], None)] == ["(root)"]
    assert report_problems([], Timeline()) == []


def _label_timeline_and_rows() -> tuple[Timeline, list[SymptomSummary]]:
    timeline, report = label_payloads("demo_patient", PREPARED)
    parsed = Timeline(
        events=[TimelineEvent.model_validate(e) for e in timeline["events"]],
        contradictions=[
            Contradiction.model_validate(c) for c in timeline["contradictions"]
        ],
    )
    rows = [SymptomSummary.model_validate(r) for r in report["per_symptom"]]
    return parsed, rows


def test_label_rows_cover_every_present_term_in_order() -> None:
    timeline, rows = _label_timeline_and_rows()
    terms = {e.term for e in timeline.events if e.status != "absent"}
    assert len(rows) == len(terms) >= 2
    assert report_problems(rows, timeline) == []


def test_empty_report_is_rejected_when_events_have_symptoms() -> None:
    timeline, _ = _label_timeline_and_rows()
    problems = report_problems([], timeline)
    assert problems and all(where.startswith("events.") for where, _ in problems)
    assert all(why == "この出来事の term の行が無い" for _, why in problems)


def test_missing_row_points_at_the_first_event_of_that_term() -> None:
    timeline, rows = _label_timeline_and_rows()
    dropped = rows[1]
    first_index = next(
        i
        for i, e in enumerate(timeline.events)
        if e.term == dropped.term and e.status != "absent"
    )
    problems = report_problems([r for r in rows if r != dropped], timeline)
    assert problems == [(f"events.{first_index}.term", "この出来事の term の行が無い")]


def test_rows_out_of_order_are_accepted() -> None:
    # term 名順（文字コード順）はモデルが再現しにくく、report も必ず並べ直すので拒否しない
    # （受け付けた後に tools.RunCollector が並べ直す）。欠け・余分・重複は拒否のまま
    timeline, rows = _label_timeline_and_rows()
    assert report_problems([rows[1], rows[0], *rows[2:]], timeline) == []
    assert report_problems(rows[::-1], timeline) == []


def test_same_start_date_in_any_term_order_is_accepted() -> None:
    base = _event(status="present", source_quote="下痢", term="下痢")
    other = _event(
        status="present",
        source_quote="下痢",
        term="口内炎",
        question_key="stomatitis",
    )
    timeline = Timeline(events=[base, other])
    rows = [
        SymptomSummary(
            term=e.term,
            question_key=e.question_key,
            start_day=e.day,
            start_date=e.date,
            representative_quote=e.source_quote,
            confidence=e.confidence,
        )
        for e in sorted([base, other], key=lambda e: e.term)
    ]
    assert report_problems(rows, timeline) == []
    assert report_problems(rows[::-1], timeline) == []


def test_missing_and_extra_rows_are_still_rejected_in_any_order() -> None:
    timeline, rows = _label_timeline_and_rows()
    reordered = rows[::-1]
    assert [w for w, _ in report_problems(reordered[1:], timeline)]
    assert [w for w, _ in report_problems([*reordered, reordered[0]], timeline)] == [
        f"per_symptom.{len(rows)}.term"
    ]


# --- 理由に期待される値を入れる（原文・用語名は入れない） ----------------------


def _why(problems: list[tuple[str, str]], where: str) -> str:
    return dict(problems)[where]


def test_day_reason_names_the_expected_day() -> None:
    problems = timeline_problems([_event(day=12)], [], CTX)
    assert "Day13" in _why(problems, "events.0.day")
    assert "対応表" in _why(problems, "events.0.day")
    before = _event(date=date(2026, 10, 20), day=1, recalled=True)
    assert "null" in _why(timeline_problems([before], [], CTX), "events.0.day")


def test_copy_reasons_name_the_expected_values() -> None:
    event = _event(
        course_no=9, by_proxy=True, recalled=True, question_key="nausea_appetite"
    )
    problems = timeline_problems([event], [], CTX)
    assert "3 にする" in _why(problems, "events.0.course_no")
    assert "false にする" in _why(problems, "events.0.by_proxy")
    assert "false にする" in _why(problems, "events.0.recalled")
    assert "diarrhea にする" in _why(problems, "events.0.question_key")
    late = _event(date=date(2026, 11, 9), day=14)
    assert "2026-11-08" in _why(timeline_problems([late], [], CTX), "events.0.date")


def test_contradiction_reasons_name_the_expected_values() -> None:
    good = _contradiction()
    entry = CTX.entries[good.entry_no]
    wrong_answer = "hard" if good.closed_answer != "hard" else "none"
    bad = _contradiction(
        date="2026-10-01", day=(entry.day or 0) + 1, closed_answer=wrong_answer
    )
    problems = timeline_problems([], [bad], CTX)
    assert entry.record_date.isoformat() in _why(problems, "contradictions.0.date")
    assert f"{entry.day}" in _why(problems, "contradictions.0.day")
    assert good.closed_answer in _why(problems, "contradictions.0.closed_answer")


def test_summary_reasons_name_the_expected_values() -> None:
    timeline, rows = _label_timeline_and_rows()
    row = rows[0]
    wrong_date = row.model_copy(update={"start_date": date(2026, 10, 1)})
    problems = report_problems([wrong_date, *rows[1:]], timeline)
    assert row.start_date.isoformat() in _why(problems, "per_symptom.0.start_date")
    wrong_day = row.model_copy(update={"start_day": 99})
    problems = report_problems([wrong_day, *rows[1:]], timeline)
    assert f"{row.start_day}" in _why(problems, "per_symptom.0.start_day")
    wrong_conf = row.model_copy(update={"confidence": 0.11})
    problems = report_problems([wrong_conf, *rows[1:]], timeline)
    assert f"{row.confidence}" in _why(problems, "per_symptom.0.confidence")


def test_representative_quote_reason_says_whole_source_quote() -> None:
    timeline, rows = _label_timeline_and_rows()
    cut = rows[0].model_copy(
        update={"representative_quote": rows[0].representative_quote[:-1]}
    )
    why = _why(
        report_problems([cut, *rows[1:]], timeline),
        "per_symptom.0.representative_quote",
    )
    assert "source_quote" in why and "そのまま" in why


def test_problems_never_contain_record_text() -> None:
    timeline, rows = _label_timeline_and_rows()
    quotes = {e.source_quote for e in timeline.events}
    terms = {e.term for e in timeline.events}
    shifted = [r.model_copy(update={"start_day": 99, "confidence": 0.01}) for r in rows]
    for candidate in ([], rows[::-1], rows[1:], shifted):
        for where, why in report_problems(candidate, timeline):
            assert not any(q in where or q in why for q in quotes | terms)
    wrong = [
        e.model_copy(update={"day": 99, "course_no": 9, "by_proxy": True})
        for e in timeline.events
    ]
    for where, why in timeline_problems(wrong, timeline.contradictions, CTX):
        assert not any(q in where or q in why for q in quotes | terms)
