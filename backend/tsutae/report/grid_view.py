"""経過表（Grid）→ テンプレートに渡す表示用の値。決定的な純関数。

- 1 段の Day の列は GRID_MAX_COLS まで。超えたら段を分けて折り返す（次コースを
  登録する前に受診してコースが長く伸びた場合）。全ての日を残し、並べ替えない
- 段ごとに Day と日付の見出しを付ける。列の幅は全段で同じ（最後の段が短ければ表も
  短くする）ので、Day1 の真下に Day22 が来る
- そのコースのセルが 1 つも無い段には、そのコースの行を出さない（全て範囲外の行は
  情報が無く紙を使うだけ）
- 1 列が細い（GRID_DENSE_FROM 列以上の）段は、列頭とセルの文字を詰める
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from tsutae.report.labels import TEMPERATURE_ROW_KEY
from tsutae.schemas import Grid, GridCell, GridColumn, GridRow

GRID_MAX_COLS = 21  # CAPOX（cycle_days 21）の通常のコースを 1 段に収める
GRID_DENSE_FROM = 17  # 1 列が 10mm を切る列数（168mm ÷ 17 ≒ 9.9mm）
_LABEL_COL_MM = 22.0  # report.css の .grid col.label-col と同じ
_DAYS_MM = 168.0  # 本文の幅 190mm − 行名の列 22mm

_OUT_CELL = {
    "cls": "cell out",
    "glyph": "",
    "temp": "",
    "mark": False,
    "recalled": False,
}

BlockKey = tuple[int, bool]  # (course_no, is_previous_course)


def grid_segments(
    days: Sequence[int], max_cols: int = GRID_MAX_COLS
) -> list[list[int]]:
    """Day を先頭から max_cols ずつの段に分ける。Day が無ければ空の段を 1 つ。"""
    if max_cols < 1:
        raise ValueError(f"1 段の列数は 1 以上: {max_cols}")
    if not days:
        return [[]]
    return [list(days[i : i + max_cols]) for i in range(0, len(days), max_cols)]


def _md(d: date | None) -> str:
    return f"{d.month}/{d.day}" if d is not None else ""


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


def _row_view(
    row: GridRow, days: Sequence[int], slash_days: set[int]
) -> dict[str, Any]:
    by_day = {c.day: c for c in row.cells}
    cells = [
        _cell_view(by_day.get(day), day, row, slashed=day in slash_days) for day in days
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


def _column_view(day: int, column: GridColumn | None) -> dict[str, Any]:
    if column is None:  # 列の情報が無い Day も、セルとずれないよう空の列頭を置く
        return {"day": day, "date": "", "proxy": False, "slash": False}
    return {
        "day": day,
        "date": _md(column.date),
        "proxy": column.by_proxy,
        "slash": column.too_sick,
    }


def _segment_view(
    no: int,
    total: int,
    days: Sequence[int],
    *,
    grouped: Mapping[BlockKey, Sequence[GridRow]],
    slash: Mapping[BlockKey, set[int]],
    columns: Mapping[int, GridColumn],
    full_cols: int,
) -> dict[str, Any]:
    day_set = set(days)
    blocks = [
        {
            "key": key,
            "title": _block_title(rows[0]),
            "rows": [_row_view(row, days, slash[key]) for row in rows],
        }
        for key, rows in grouped.items()
        if any(c.day in day_set for r in rows for c in r.cells)
    ]
    width = None
    if len(days) < full_cols:  # 最後の短い段: 列の幅を他の段にそろえる
        width = f"{_LABEL_COL_MM + _DAYS_MM / full_cols * len(days):.1f}mm"
    title = None
    if total > 1 and days:
        title = f"（{no}/{total}）Day{days[0]}〜Day{days[-1]}"
    return {
        "no": no,
        "title": title,
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "columns": [_column_view(d, columns.get(d)) for d in days],
        "blocks": blocks,
        "span": len(days) + 1,
        "width": width,
    }


def grid_view(grid: Grid, max_cols: int = GRID_MAX_COLS) -> dict[str, Any]:
    """段（segments）に分けた経過表。凡例はテンプレートで最後の段の後に 1 回だけ。"""
    grouped: dict[BlockKey, list[GridRow]] = {}
    for row in grid.rows:
        grouped.setdefault((row.course_no, row.is_previous_course), []).append(row)
    slash = {
        key: _slash_days(grid, rows, previous=key[1]) for key, rows in grouped.items()
    }
    chunks = grid_segments(grid.days, max_cols)
    full_cols = max(1, len(chunks[0]))
    columns = {c.day: c for c in grid.columns}
    segments = [
        _segment_view(
            no,
            len(chunks),
            days,
            grouped=grouped,
            slash=slash,
            columns=columns,
            full_cols=full_cols,
        )
        for no, days in enumerate(chunks, start=1)
    ]
    return {"segments": segments, "dense": full_cols >= GRID_DENSE_FROM}
