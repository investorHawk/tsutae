"""ReportData → A4 一枚の HTML（Jinja2、autoescape）。docs/architecture.md §7b。

- 描画は決定的（時刻などを埋め込まない）。CSS は templates/report.css を <style> に
  埋め込む（印刷時に外部ファイルを読みに行かない）
- 文言はテンプレートと下の定数の決まった文だけ。AI の文は引用・用語名としてだけ出し、
  全てエスケープする
- Grade・重さの判定語を出さない（テストで検査）。用語名（AI が選ぶ欄）に判定語が
  あれば ValueError で描かない（build は ctcae_terms の一覧で既に落としている。
  改ざん・取り違えた ReportData への最後の砦）
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from tsutae.report.labels import (
    TEMPERATURE_ROW_KEY,
    answer_label,
    has_severity_word,
    question_label,
)
from tsutae.schemas import (
    AttentionItem,
    Grid,
    GridCell,
    GridRow,
    Question,
    QuoteItem,
    ReportData,
    ReportHeader,
    SymptomSummary,
)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_NAME = "report.html.j2"
CSS_NAME = "report.css"
SECTIONS: tuple[str, ...] = ("header", "attention", "grid", "per_symptom", "quotes")
DEFAULT_LOW_CONFIDENCE = 0.6  # ReportFormatSkill.low_confidence_threshold の既定と同じ

# 引用欄を2枚目に回すかの見積もり（mm）。A4 から余白 10mm×2 を引いた高さ
_PAGE_MM = 277.0
_LINE_MM = 4.4
_GRID_ROW_MM = 5.0
_SECTION_MM = 8.0
_QUOTE_CHARS_PER_LINE = 50

_OUT_CELL = {
    "cls": "cell out",
    "glyph": "",
    "temp": "",
    "mark": False,
    "recalled": False,
}
# 理由（二次検出・受診前の範囲外など）は紙では断定しない（AttentionItem に理由が無い）
UNPROCESSED_NOTE = "{n}件（AI に送っていない記載。理由と内容は院内画面で確認）"
QUOTES_LIMIT_NOTE = "上限{n}件まで載せた（受診直前の記載を残した。それより前の記載は省いた可能性がある）"

_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=True,  # select_autoescape は .j2 を対象にしないので明示する
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@lru_cache(maxsize=1)
def _css() -> Markup:
    css = (TEMPLATE_DIR / CSS_NAME).read_text(encoding="utf-8")
    if "</" in css:
        raise ValueError("report.css に </ を含めない（<style> が閉じてしまう）")
    return Markup(css)  # 同梱の静的ファイル（データは入らない）だけを素通しする


def _md(d: date | None) -> str:
    return f"{d.month}/{d.day}" if d is not None else ""


def _day(day: int | None) -> str:
    return f"Day{day}" if day is not None else ""


def _sections(sections: Sequence[str] | None) -> list[str]:
    chosen = list(SECTIONS if sections is None else sections)
    unknown = [s for s in chosen if s not in SECTIONS]
    if unknown:
        raise ValueError(f"未知の欄: {unknown}")
    return list(dict.fromkeys(chosen))


def _header_view(h: ReportHeader) -> dict[str, Any]:
    return {
        "reception_no": h.reception_no,
        "patient_id": h.patient_id,
        "regimen": h.regimen,
        "course": f"第{h.course_no}コース",
        "period": f"{h.course_start.isoformat()}〜{h.course_end.isoformat()}",
        "records": f"{h.recorded_days}日/{h.total_days}日",
        "breakdown": f"入力なし{h.no_input_days}・つらくて書けない{h.too_sick_days}",
        "delay_note": h.delay_note,
    }


def _line(kind: str, mark: str, title: str, day: str, detail: str) -> dict[str, str]:
    return {"kind": kind, "mark": mark, "title": title, "day": day, "detail": detail}


def _contradiction_line(
    a: AttentionItem, questions: Sequence[Question]
) -> dict[str, str]:
    label = question_label(a.question_key or "", questions)
    detail = (
        f"{label}: クローズ回答「{answer_label(a.closed_answer)}」"
        f"／自由記載「{a.quote or ''}」"
    )
    return _line("contradiction", "▲", "食い違い", _day(a.day), detail)


def _too_sick_line(items: Sequence[AttentionItem]) -> dict[str, str]:
    days = "・".join(_day(a.day) for a in items)
    same = [_day(a.day) for a in items if a.previous_course_same_day]
    detail = f"（前コースも同じ Day: {'・'.join(same)}）" if same else ""
    return _line("too_sick", "●", "つらくて書けない", days, detail)


def _attention_view(
    items: Sequence[AttentionItem], questions: Sequence[Question]
) -> list[dict[str, str]]:
    """食い違い → 発熱 → つらくて書けない（1行にまとめる）→ 未処理 の順。"""
    lines = [
        _contradiction_line(a, questions) for a in items if a.kind == "contradiction"
    ]
    lines += [
        _line("fever", "▲", "発熱", _day(a.day), f"{a.temperature:.1f}℃")
        for a in items
        if a.kind == "fever" and a.temperature is not None
    ]
    too_sick = [a for a in items if a.kind == "too_sick"]
    if too_sick:
        lines.append(_too_sick_line(too_sick))
    lines += [
        _line(
            "unprocessed",
            "■",
            "未処理の記載あり",
            "",
            UNPROCESSED_NOTE.format(n=a.count or 0),
        )
        for a in items
        if a.kind == "unprocessed"
    ]
    return lines


def _cell_view(
    cell: GridCell | None, day: int, row: GridRow, slashed: bool
) -> dict[str, Any]:
    if cell is None:  # そのコースの範囲外（受診日より後・そのコースに無い Day）
        return {**_OUT_CELL, "day": day}
    is_temp = row.question_key == TEMPERATURE_ROW_KEY
    state = cell.state
    if is_temp and state in ("present", "none"):
        state = "measured" if state == "present" else "not_measured"
    classes = ["cell", f"st-{state}"]
    if slashed or cell.state == "too_sick":
        classes.append("slash")
    glyph = {"none": "−", "not_measured": "−", "not_asked": "−−"}.get(state, "")
    temp = f"{cell.temperature:.1f}" if is_temp and cell.temperature is not None else ""
    return {
        "day": day,
        "cls": " ".join(classes),
        "glyph": glyph,
        "temp": temp,
        "mark": cell.free_text_mark,
        "recalled": cell.recalled_mark,
    }


def _slash_days(grid: Grid, rows: Sequence[GridRow], previous: bool) -> set[int]:
    """そのコースのブロックで列全体に斜線を引く Day。

    今コースは列頭（GridColumn.too_sick）。前コースは列の情報が Grid に無いので、
    そのブロックのどれかのセルが too_sick の Day（回答のある行にも斜線を引く）。
    """
    if not previous:
        return {c.day for c in grid.columns if c.too_sick}
    return {c.day for r in rows for c in r.cells if c.state == "too_sick"}


def _row_view(row: GridRow, grid: Grid, slash_days: set[int]) -> dict[str, Any]:
    by_day = {c.day: c for c in row.cells}
    cells = [
        _cell_view(by_day.get(day), day, row, slashed=day in slash_days)
        for day in grid.days
    ]
    return {
        "id": f"c{row.course_no}-{row.question_key}",
        "label": row.label,
        "previous": row.is_previous_course,
        "cells": cells,
    }


def _block_title(row: GridRow) -> str:
    if row.is_previous_course:
        return f"第{row.course_no}コース（前コース。クローズ回答のみ）"
    return f"第{row.course_no}コース（今回）"


def _grid_view(grid: Grid) -> dict[str, Any]:
    grouped: dict[tuple[int, bool], list[GridRow]] = {}
    for row in grid.rows:
        grouped.setdefault((row.course_no, row.is_previous_course), []).append(row)
    blocks = []
    for key, rows in grouped.items():
        slash = _slash_days(grid, rows, previous=key[1])
        blocks.append(
            {
                "key": key,
                "title": _block_title(rows[0]),
                "rows": [_row_view(row, grid, slash) for row in rows],
            }
        )
    columns = [
        {"day": c.day, "date": _md(c.date), "proxy": c.by_proxy, "slash": c.too_sick}
        for c in grid.columns
    ]
    return {"columns": columns, "blocks": blocks, "span": len(grid.days) + 1}


def _symptom_view(
    items: Sequence[SymptomSummary], threshold: float
) -> list[dict[str, Any]]:
    if any(has_severity_word(s.term) for s in items):
        raise ValueError("症状別の用語名に重さの判定語がある（描かない）")
    return [
        {
            "term": s.term,
            "start": (
                f"{_day(s.start_day)}〜（{_md(s.start_date)}）"
                if s.start_day is not None
                else f"{_md(s.start_date)}〜"
            ),
            "quote": s.representative_quote,
            "low": s.confidence < threshold,
        }
        for s in items
    ]


def _quote_view(items: Sequence[QuoteItem]) -> list[dict[str, Any]]:
    return [
        {"day": _day(q.day), "date": _md(q.date), "proxy": q.by_proxy, "text": q.text}
        for q in items
    ]


def _quotes_limit_note(
    quotes: Sequence[QuoteItem], max_items: int | None
) -> str | None:
    if max_items is None or max_items <= 0 or len(quotes) < max_items:
        return None
    return QUOTES_LIMIT_NOTE.format(n=max_items)


def _quote_lines(quotes: Sequence[QuoteItem]) -> int:
    return sum(max(1, math.ceil(len(q.text) / _QUOTE_CHARS_PER_LINE)) for q in quotes)


def _quotes_need_new_page(data: ReportData, sections: Sequence[str]) -> bool:
    """引用欄まで1枚に収まらない見積もりなら True（引用欄を2枚目に回す）。"""
    if "quotes" not in sections:
        return False
    blocks = len({(r.course_no, r.is_previous_course) for r in data.grid.rows})
    sizes = {
        "header": 14.0,
        "attention": _SECTION_MM + _LINE_MM * max(1, len(data.attention)),
        "grid": _SECTION_MM + 12.0 + _GRID_ROW_MM * (2 + len(data.grid.rows) + blocks),
        "per_symptom": _SECTION_MM + _LINE_MM * (1 + len(data.per_symptom)),
    }
    before = 22.0 + sum(sizes[s] for s in sections if s in sizes)  # 冒頭・欄外を含む
    quotes = _SECTION_MM + _LINE_MM * _quote_lines(data.quotes)
    return before + quotes > _PAGE_MM


def render_report_html(
    data: ReportData,
    *,
    questions: Sequence[Question],
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE,
    sections: Sequence[str] | None = None,
    quotes_max_items: int | None = None,
) -> str:
    """A4 一枚の HTML を返す。

    - questions: 要確認・経過表の表示名に使う質問集（今の regimen Skill）
    - low_confidence_threshold: これ未満の症状別の行に「？」（report Skill の値を渡す）
    - sections: 欄とその順（report Skill の sections）。None なら全て既定の順
    - quotes_max_items: 引用の上限（report Skill の値を渡す）。引用が上限に達していれば
      省いた可能性を書く。None なら書かない（ReportData に省いた件数が無いための暫定）
    """
    chosen = _sections(sections)
    template = _ENV.get_template(TEMPLATE_NAME)
    return template.render(
        css=_css(),
        sections=chosen,
        fallback=data.fallback,
        header=_header_view(data.header),
        attention=_attention_view(data.attention, questions),
        grid=_grid_view(data.grid),
        per_symptom=_symptom_view(data.per_symptom, low_confidence_threshold),
        quotes=_quote_view(data.quotes),
        quotes_limit_note=_quotes_limit_note(data.quotes, quotes_max_items),
        quotes_page_break=_quotes_need_new_page(data, chosen),
        report_skill_version=data.report_skill_version,
    )
