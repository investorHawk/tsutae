"""届いていない日（plan-device-records §5.6）。今コースの印のうち、記録が無い日。

デモ患者の C3 は Day1 = 10/27。記録が無いのは Day9（11/04）・Day11（11/06）・Day14（11/09）。
"""

from __future__ import annotations

import inspect
import re
from datetime import date

import pytest

from tsutae.pipeline import inputs as inputs_module
from tsutae.pipeline.inputs import prepare_input
from tsutae.report import ReportBuildError, build_report_data, render_report_html
from tsutae.report.sample import SampleInputs, load_demo_inputs
from tsutae.schemas import (
    AttentionItem,
    PipelineInput,
    PreparedInput,
    QuoteItem,
    RecordMark,
    ReportData,
    Timeline,
    TimelineEvent,
)

DAY9 = date(2026, 11, 4)
DAY11 = date(2026, 11, 6)
DAY14 = date(2026, 11, 9)
DAY3_TOO_SICK = date(2026, 10, 29)


def _marks(sample: SampleInputs, *dates: date) -> list[RecordMark]:
    return [RecordMark(patient_id=sample.patient_id, record_date=d) for d in dates]


def _build(sample: SampleInputs, *dates: date, **overrides: object) -> ReportData:
    kwargs = {
        **sample.build_kwargs(),
        "record_marks": _marks(sample, *dates),
        **overrides,
    }
    return build_report_data(**kwargs)


def _html(sample: SampleInputs, data: ReportData, **kwargs: object) -> str:
    return render_report_html(
        data, questions=list(sample.regimen_skill.questions), **kwargs
    )


def _attention_section(html: str) -> str:
    match = re.search(r'<section class="attention">(.*?)</section>', html, re.S)
    assert match
    return match.group(1)


def _days(data: ReportData) -> list[int | None]:
    return [a.day for a in data.attention if a.kind == "not_received"]


def _cell_state(data: ReportData, day: int) -> str:
    row = next(
        r
        for r in data.grid.rows
        if r.question_key == "diarrhea" and not r.is_previous_course
    )
    return next(c.state for c in row.cells if c.day == day)


@pytest.fixture(scope="module")
def demo() -> SampleInputs:
    return load_demo_inputs()


@pytest.fixture(scope="module")
def fallback() -> SampleInputs:
    return load_demo_inputs(fallback=True)


# ---------------------------------------------------------------------------
# 組み立て
# ---------------------------------------------------------------------------


def test_marked_days_without_records_are_not_received(demo: SampleInputs) -> None:
    data = _build(demo, DAY9, DAY11)
    h = data.header
    assert h.not_received_days == 2
    assert _days(data) == [9, 11]
    # 入力なしには数えない。合計は記録・入力なし・届いていないで揃う
    assert (h.total_days, h.recorded_days, h.no_input_days) == (14, 11, 1)
    assert h.recorded_days + h.no_input_days + h.not_received_days == h.total_days


def test_grid_stays_blank_on_not_received_days(demo: SampleInputs) -> None:
    data = _build(demo, DAY9, DAY11)
    assert _cell_state(data, 9) == "no_input"
    assert _cell_state(data, 11) == "no_input"
    assert data.grid == _build(demo).grid


def test_without_marks_nothing_changes(demo: SampleInputs) -> None:
    data = _build(demo)
    assert data == build_report_data(**demo.build_kwargs())
    assert data.header.not_received_days == 0
    assert _days(data) == []


def test_a_day_with_any_record_counts_as_received(demo: SampleInputs) -> None:
    # 記録のある日（つらくて書けないも）。別の端末の記録があれば届いた扱い（§5.6）
    data = _build(demo, date(2026, 10, 27), DAY3_TOO_SICK)
    assert data.header.not_received_days == 0
    assert _days(data) == []
    assert data.header.no_input_days == 3


def test_marks_outside_the_current_range_are_ignored(demo: SampleInputs) -> None:
    previous_course = date(2026, 10, 20)  # 前コース
    after_visit = date(2026, 11, 10)  # 受診日より後
    data = _build(demo, previous_course, after_visit)
    assert data.header.not_received_days == 0
    assert _days(data) == []


def test_range_stops_at_the_visit_day() -> None:
    sample = load_demo_inputs(visit_date=date(2026, 11, 3))  # C3 Day8
    assert _build(sample, DAY9).header.not_received_days == 0


def test_range_extends_past_the_last_day() -> None:
    # 次コース未登録で受診日が最終日より後。Day15・16 も今コース
    sample = load_demo_inputs(visit_date=date(2026, 11, 11))
    data = _build(sample, date(2026, 11, 10))
    assert _days(data) == [15]
    h = data.header
    assert (h.total_days, h.no_input_days, h.not_received_days) == (16, 4, 1)


def test_marks_are_order_independent_and_not_mutated(demo: SampleInputs) -> None:
    marks = _marks(demo, DAY11, DAY9, DAY9)
    data = build_report_data(**demo.build_kwargs(), record_marks=marks)
    assert _days(data) == [9, 11]
    assert [m.record_date for m in marks] == [DAY11, DAY9, DAY9]


def test_attention_keeps_unprocessed_last(demo: SampleInputs) -> None:
    kinds = [a.kind for a in _build(demo, DAY9).attention]
    assert kinds == [
        "contradiction",
        "fever",
        "too_sick",
        "too_sick",
        "too_sick",
        "not_received",
        "unprocessed",
    ]


def test_fallback_report_shows_not_received_days(fallback: SampleInputs) -> None:
    data = _build(fallback, DAY9, DAY11)
    assert data.fallback is True
    assert _days(data) == [9, 11]
    assert data.header.not_received_days == 2


def test_ai_output_does_not_make_a_day_received(demo: SampleInputs) -> None:
    """後の日の記述から回想で ○回 が付いても、記録が届いたことにはしない。"""
    assert demo.result.timeline is not None
    source = next(e for e in demo.result.timeline.events if e.date > DAY9)
    recalled: TimelineEvent = source.model_copy(update={"date": DAY9})
    timeline: Timeline = demo.result.timeline.model_copy(
        update={"events": [*demo.result.timeline.events, recalled]}
    )
    result = demo.result.model_copy(update={"timeline": timeline})
    data = _build(demo, DAY9, result=result)
    assert _days(data) == [9]
    assert _cell_state(data, 9) == "no_input"


# ---------------------------------------------------------------------------
# 入口の検査
# ---------------------------------------------------------------------------


def test_gate_refuses_marks_of_another_patient(demo: SampleInputs) -> None:
    other = [RecordMark(patient_id="P-OTHER0001", record_date=DAY9)]
    with pytest.raises(ReportBuildError) as err:
        build_report_data(**demo.build_kwargs(), record_marks=other)
    assert err.value.code == "patient_mismatch"


# ---------------------------------------------------------------------------
# 描画
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["demo", "fallback"])
def test_paper_shows_line_and_breakdown(
    which: str, demo: SampleInputs, fallback: SampleInputs
) -> None:
    sample = demo if which == "demo" else fallback
    html = _html(sample, _build(sample, DAY9, DAY11))
    section = _attention_section(html)
    assert "記録が届いていない日: Day9, Day11" in section
    assert "入力なし1・つらくて書けない3・届いていない2" in html


def test_paper_without_marks_has_no_mention(demo: SampleInputs) -> None:
    html = _html(demo, _build(demo))
    assert "届いていない" not in html
    assert "入力なし3・つらくて書けない3" in html


def test_not_received_line_sits_before_unprocessed(demo: SampleInputs) -> None:
    section = _attention_section(_html(demo, _build(demo, DAY14)))
    too_sick = section.index("つらくて書けない")
    assert too_sick < section.index("記録が届いていない日: Day14")
    assert section.index("記録が届いていない日") < section.index("未処理の記載あり")


def test_paper_cells_stay_blank(demo: SampleInputs) -> None:
    html = _html(demo, _build(demo, DAY9))
    cell = re.search(r'<td class="([^"]*)" data-row="c3-diarrhea" data-day="9">', html)
    assert cell
    assert "st-no_input" in cell.group(1)


def test_css_lets_the_long_line_wrap() -> None:
    sample = load_demo_inputs()
    html = _html(sample, _build(sample, DAY9))
    rule = re.search(r"\.att-not_received \.att-title \{(.*?)\}", html, re.S)
    assert rule
    assert "display: inline" in rule.group(1)


def test_a_few_days_keep_the_paper_on_one_page(demo: SampleInputs) -> None:
    html = _html(demo, _build(demo, DAY9, DAY11, DAY14))
    assert re.search(r'<section class="quotes"', html)


def _page_breaks(sample: SampleInputs, data: ReportData) -> bool:
    html = _html(sample, data)
    return re.search(r'<section class="quotes page-break"', html) is not None


def test_long_list_counts_its_wrapped_lines(demo: SampleInputs) -> None:
    """折り返す分も見積もりに入れる。1行と数えると引用が溢れても改ページしない。"""
    data = _build(demo)
    long_list = [AttentionItem(kind="not_received", day=d) for d in range(1, 41)]
    wide = data.model_copy(update={"attention": long_list})
    narrow = data.model_copy(update={"attention": long_list[:1]})
    differs = []
    for n in range(0, 60):
        quotes = [
            QuoteItem(entry_no=i + 1, day=1, date=date(2026, 10, 27), text="あ")
            for i in range(n)
        ]
        with_quotes = {"quotes": quotes}
        differs.append(
            _page_breaks(demo, wide.model_copy(update=with_quotes))
            and not _page_breaks(demo, narrow.model_copy(update=with_quotes))
        )
    assert any(differs)


# ---------------------------------------------------------------------------
# Claude に送らない
# ---------------------------------------------------------------------------


def test_marks_are_not_an_input_of_the_conversion() -> None:
    """変換の入力には印を渡す口が無い（§5.6。Claude には送らない）。"""
    words = ("mark", "received")
    names = [
        *inspect.signature(prepare_input).parameters,
        *PipelineInput.model_fields,
        *PreparedInput.model_fields,
    ]
    assert not [n for n in names if any(w in n for w in words)]
    source = inspect.getsource(inputs_module)
    assert "record_marks" not in source
    assert "not_received" not in source
