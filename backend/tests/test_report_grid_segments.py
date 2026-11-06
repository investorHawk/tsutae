"""経過表の段組み（R-1）と凡例のかたまり（R-2）・文字の大きさ（R-3）。

コースが長く伸びても（次コースを登録する前に受診した場合）列がつぶれないよう、
1 段の Day の列を GRID_MAX_COLS までにして段を分ける。全ての日を残す。
症例は全て合成。
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from tsutae.report import build_report_data, render_report_html
from tsutae.report.grid_view import GRID_MAX_COLS, grid_segments
from tsutae.report.sample import SampleInputs, load_demo_inputs


def _html(sample: SampleInputs) -> str:
    data = build_report_data(**sample.build_kwargs())
    return render_report_html(data, questions=list(sample.regimen_skill.questions))


def _segments(html: str) -> list[str]:
    """段（<div class="grid-segment" ...>〜</table>）の HTML を順に返す。"""
    return re.findall(
        r'<div class="grid-segment" data-segment="\d+"[^>]*>(.*?)</table>', html, re.S
    )


def _head_days(segment: str) -> list[int]:
    return [
        int(d)
        for d in re.findall(r'<th class="col-head[^"]*" data-day="(\d+)"', segment)
    ]


def _row_days(segment: str, row: str) -> list[int]:
    return [int(d) for d in re.findall(rf'data-row="{row}" data-day="(\d+)"', segment)]


@pytest.fixture(scope="module")
def html14() -> str:
    return _html(load_demo_inputs())  # デモ C3（FOLFOX 14 日、受診は Day14）


@pytest.fixture(scope="module")
def html21() -> str:
    # 第4コース未登録のまま C3 Day21（11/16）に受診 → 今コースが 21 日に伸びる
    return _html(load_demo_inputs(visit_date=date(2026, 11, 16)))


@pytest.fixture(scope="module")
def html56() -> str:
    # 評価用 P-EVAL0001: 第2コース Day1 9/15、第3コース未登録のまま 11/9 に受診 → 56 日
    return _html(load_demo_inputs(name="eval_patient_a", visit_date=date(2026, 11, 9)))


# ---------------------------------------------------------------------------
# 段の切り方（純関数）
# ---------------------------------------------------------------------------


def test_max_cols_fits_capox_cycle() -> None:
    assert GRID_MAX_COLS == 21  # CAPOX（cycle_days 21）の通常のコースを 1 段に収める


@pytest.mark.parametrize(
    ("n", "sizes"),
    [(1, [1]), (14, [14]), (21, [21]), (22, [21, 1]), (56, [21, 21, 14])],
)
def test_grid_segments_chunks_days_in_order(n: int, sizes: list[int]) -> None:
    days = list(range(1, n + 1))
    chunks = grid_segments(days)
    assert [len(c) for c in chunks] == sizes
    assert [d for c in chunks for d in c] == days  # 捨てない・並べ替えない


def test_grid_segments_rejects_bad_limit() -> None:
    with pytest.raises(ValueError):
        grid_segments([1, 2], max_cols=0)


def test_grid_segments_does_not_mutate_input() -> None:
    days = [1, 2, 3]
    grid_segments(days, max_cols=2)
    assert days == [1, 2, 3]


# ---------------------------------------------------------------------------
# 14・21・56 日のコースの HTML
# ---------------------------------------------------------------------------


def test_14_days_is_one_segment(html14: str) -> None:
    segments = _segments(html14)
    assert len(segments) == 1
    assert _head_days(segments[0]) == list(range(1, 15))
    assert '<table class="grid">' in segments[0]  # 14 列は詰めない
    assert "segment-title" not in segments[0]  # 1 段なら段の見出しを出さない
    assert _row_days(segments[0], "c3-diarrhea") == list(range(1, 15))
    assert _row_days(segments[0], "c2-diarrhea") == list(range(1, 15))


def test_21_days_is_one_dense_segment(html21: str) -> None:
    segments = _segments(html21)
    assert len(segments) == 1
    assert _head_days(segments[0]) == list(range(1, 22))
    assert '<table class="grid dense">' in segments[0]  # 1 列 8mm なので文字を詰める
    assert _row_days(segments[0], "c3-numbness") == list(range(1, 22))
    # 前コース（14 日）の Day15〜21 は範囲外のセル
    assert _row_days(segments[0], "c2-numbness") == list(range(1, 22))
    out = re.findall(
        r'<td class="cell out" data-row="c2-numbness" data-day="(\d+)"', html21
    )
    assert [int(d) for d in out] == list(range(15, 22))


def test_56_days_is_split_into_three_segments(html56: str) -> None:
    segments = _segments(html56)
    assert [len(_head_days(s)) for s in segments] == [21, 21, 14]
    heads = [d for s in segments for d in _head_days(s)]
    assert heads == list(range(1, 57))  # 全ての日が、ちょうど 1 回ずつ
    for row in ("c2-numbness", "c2-diarrhea", "c2-temperature"):
        days = [d for s in segments for d in _row_days(s, row)]
        assert days == list(range(1, 57)), row
    for no, s in enumerate(segments, start=1):
        assert "<thead>" in s  # 段ごとに Day と日付の見出し
        assert f"（{no}/3）" in s
        assert len(_head_days(s)) <= GRID_MAX_COLS
        assert s.count('class="course-sep"') == (2 if no == 1 else 1)
    # 前コース（14 日）は第 1 段だけ。セルの無い段には出さない
    assert _row_days(segments[0], "c1-numbness") == list(range(1, 22))
    assert all(_row_days(s, "c1-numbness") == [] for s in segments[1:])


def test_56_days_segments_keep_column_width(html56: str) -> None:
    tables = re.findall(r"<table class=\"grid dense\"([^>]*)>", html56)
    assert tables == ["", "", ' style="width: 134.0mm"']  # 22 + 14 × 8mm


def test_56_days_dates_in_head(html56: str) -> None:
    segments = _segments(html56)
    head = re.search(
        r'data-day="22"><span class="day">22</span><span class="date">([^<]*)<',
        segments[1],
    )
    assert head and head.group(1) == "10/6"  # 9/15 + 21 日
    last = re.search(
        r'data-day="56"><span class="day">56</span><span class="date">([^<]*)<',
        segments[2],
    )
    assert last and last.group(1) == "11/9"


def test_legend_appears_once_after_segments(html56: str) -> None:
    assert html56.count('<div class="legend">') == 1
    assert html56.rindex("grid-segment") < html56.index('<div class="legend">')


def test_quotes_not_forced_when_grid_nearly_fills_page() -> None:
    # 56 日（3 段）＋症状別 2 行で引用の前の欄が 1 枚目をほぼ埋める → 強制で改ページしない
    # （見積もりが外れて経過表が 2 枚目にまたがっても、引用を 3 枚目に飛ばさない）
    sample = load_demo_inputs(name="eval_patient_a", visit_date=date(2026, 11, 9))
    data = build_report_data(**sample.build_kwargs())
    rows = build_report_data(**load_demo_inputs().build_kwargs()).per_symptom[:2]
    html = render_report_html(
        data.model_copy(update={"per_symptom": rows}),
        questions=list(sample.regimen_skill.questions),
    )
    assert re.search(r'<section class="quotes">', html)


def test_long_grid_does_not_push_quotes_to_a_third_page() -> None:
    # 引用より前の欄だけで 1 枚を超えるなら、引用を強制で改ページしない（3 枚目に
    # 飛ばさず、印刷の流れに任せる）
    sample = load_demo_inputs(name="eval_patient_a", visit_date=date(2026, 11, 9))
    data = build_report_data(**sample.build_kwargs())
    demo = load_demo_inputs()
    many = build_report_data(**demo.build_kwargs()).per_symptom
    assert len(many) == 7
    html = render_report_html(
        data.model_copy(update={"per_symptom": many}),
        questions=list(sample.regimen_skill.questions),
    )
    assert re.search(r'<section class="quotes">', html)


# ---------------------------------------------------------------------------
# R-2 凡例・R-3 文字の大きさ
# ---------------------------------------------------------------------------


def test_legend_items_pair_symbol_and_text(html14: str) -> None:
    legend = re.search(r'<div class="legend">(.*?)</div>', html14, re.S)
    assert legend
    items = re.findall(
        r'<span class="item">((?:(?!<span class="item">).)*)', legend.group(1)
    )
    assert len(items) == 12
    for item in items:
        text = re.sub(r"<[^>]+>", "", item)
        assert text.strip(), item  # 記号だけのかたまりを作らない


def _css(html: str) -> str:
    style = re.search(r"<style>(.*?)</style>", html, re.S)
    assert style
    return style.group(1)


def _rule(css: str, selector: str) -> str:
    """セレクタがちょうど selector の規則の中身（@media の中も探す）。"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for chunk in css.split("}"):
        if "{" not in chunk:
            continue
        head, body = chunk.rsplit("{", 1)
        if " ".join(head.split("{")[-1].split()) == selector:
            return body
    raise AssertionError(selector)


def _pt(rule: str) -> float:
    match = re.search(r"font-size: ([\d.]+)pt", rule)
    assert match, rule
    return float(match.group(1))


def test_legend_item_does_not_break_inside(html14: str) -> None:
    rule = _rule(_css(html14), ".legend .item")
    assert "white-space: nowrap" in rule and "inline-flex" in rule


def test_body_text_is_one_size_larger(html14: str) -> None:
    css = _css(html14)
    assert _pt(_rule(css, "body")) >= 9.5  # 要確認・症状別・引用の本文（旧 8.5pt）
    assert _pt(_rule(css, ".grid td")) >= 9  # 経過表のセル（旧 8pt）


def test_print_breaks_between_segments_not_inside(html14: str) -> None:
    css = _css(html14)
    assert "section.grid" in css and ".grid-segment" in css
    assert "break-inside: auto" in _rule(css, "section.grid")
    assert "break-inside: avoid" in _rule(css, ".grid-segment, .legend, tr")
