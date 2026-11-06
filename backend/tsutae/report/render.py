"""ReportData → A4 の HTML（Jinja2、autoescape）。docs/architecture.md §7b。

- 通常のコースは A4 1 枚。コースが長く伸びて経過表の段が増えたときは 2 枚目に流れる
  （段組みは grid_view.py）

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
from collections.abc import Mapping, Sequence
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from tsutae.report.grid_view import grid_view
from tsutae.report.labels import answer_label, has_severity_word, question_label
from tsutae.schemas import (
    AttentionItem,
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

# 引用欄を2枚目に回すかの見積もり（mm）。A4 から余白 10mm×2 を引いた高さ。
# 1 行の高さ・1 行の字数は report.css の本文（9.5pt）と経過表の寸法に合わせる
_PAGE_MM = 277.0
_LINE_MM = 5.0
_GRID_ROW_MM = 5.0
_GRID_HEAD_MM = 11.0
_SEGMENT_TITLE_MM = 4.5
_LEGEND_MM = 13.0
_SECTION_MM = 8.0
_QUOTE_CHARS_PER_LINE = 46
_NOT_RECEIVED_CHARS_PER_LINE = 46  # 英数字が多いので実際はもっと入る。少なめに見積もる
# 引用より前の欄で 1 枚目の残りがこれ未満なら強制で改ページしない（見積もりが外れて
# 前の欄が 2 枚目にまたがったとき、引用が 3 枚目に飛ぶのを防ぐ）
_NEAR_FULL_MM = 15.0

# 理由（二次検出・受診前の範囲外など）は紙では断定しない（AttentionItem に理由が無い）
UNPROCESSED_NOTE = "{n}件（AI に送っていない記載。理由と内容は院内画面で確認）"
NOT_RECEIVED_LINE = "記録が届いていない日: {days}"
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


def _breakdown(h: ReportHeader) -> str:
    text = f"入力なし{h.no_input_days}・つらくて書けない{h.too_sick_days}"
    if h.not_received_days:
        return f"{text}・届いていない{h.not_received_days}"
    return text


def _header_view(h: ReportHeader) -> dict[str, Any]:
    return {
        "reception_no": h.reception_no,
        "patient_id": h.patient_id,
        "regimen": h.regimen_label or h.regimen,
        "course": f"第{h.course_no}コース",
        "period": f"{h.course_start.isoformat()}〜{h.course_end.isoformat()}",
        "records": f"{h.recorded_days}日/{h.total_days}日",
        "breakdown": _breakdown(h),
        "delay_note": h.delay_note,
    }


def _line(kind: str, mark: str, title: str, day: str, detail: str) -> dict[str, str]:
    return {"kind": kind, "mark": mark, "title": title, "day": day, "detail": detail}


def _contradiction_line(
    a: AttentionItem,
    questions: Sequence[Question],
    labels: Mapping[str, str] | None,
) -> dict[str, str]:
    label = question_label(a.question_key or "", questions, labels)
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


def _not_received_line(items: Sequence[AttentionItem]) -> dict[str, str]:
    days = ", ".join(_day(a.day) for a in items)
    return _line("not_received", "□", NOT_RECEIVED_LINE.format(days=days), "", "")


def _attention_view(
    items: Sequence[AttentionItem],
    questions: Sequence[Question],
    labels: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """食い違い → 発熱 → つらくて書けない・届いていない（各1行）→ 未処理 の順。"""
    lines = [
        _contradiction_line(a, questions, labels)
        for a in items
        if a.kind == "contradiction"
    ]
    lines += [
        _line("fever", "▲", "発熱", _day(a.day), f"{a.temperature:.1f}℃")
        for a in items
        if a.kind == "fever" and a.temperature is not None
    ]
    too_sick = [a for a in items if a.kind == "too_sick"]
    if too_sick:
        lines.append(_too_sick_line(too_sick))
    not_received = [a for a in items if a.kind == "not_received"]
    if not_received:
        lines.append(_not_received_line(not_received))
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


def _attention_lines(lines: Sequence[Mapping[str, str]]) -> int:
    """要確認の行数。届いていない日の行は日が並ぶと折り返すので、その分も数える。"""
    return sum(
        (
            math.ceil(len(line["title"]) / _NOT_RECEIVED_CHARS_PER_LINE)
            if line["kind"] == "not_received"
            else 1
        )
        for line in lines
    )


def _quote_lines(quotes: Sequence[QuoteItem]) -> int:
    return sum(max(1, math.ceil(len(q.text) / _QUOTE_CHARS_PER_LINE)) for q in quotes)


def _grid_mm(grid: dict[str, Any]) -> float:
    """経過表の欄の高さ。段ごとに列頭＋（コースの区切り行＋行）、最後に凡例。"""
    total = _SECTION_MM + _LEGEND_MM
    for seg in grid["segments"]:
        rows = sum(1 + len(block["rows"]) for block in seg["blocks"])
        title = _SEGMENT_TITLE_MM if seg["title"] else 0.0
        total += title + _GRID_HEAD_MM + _GRID_ROW_MM * rows
    return total


def _quotes_need_new_page(
    data: ReportData,
    sections: Sequence[str],
    *,
    attention_lines: int,
    grid: dict[str, Any],
) -> bool:
    """引用欄まで1枚に収まらない見積もりなら True（引用欄を2枚目に回す）。

    引用より前の欄だけで1枚目がほぼ埋まる（経過表が長く伸びた）なら False。強制で
    改ページすると、見積もりが外れたときに引用が3枚目に飛ぶ。印刷の流れ（欄の途中で
    切らない）に任せても、引用は2枚目の頭から始まる。
    """
    if "quotes" not in sections:
        return False
    sizes = {
        "header": 14.0,
        "attention": _SECTION_MM + _LINE_MM * max(1, attention_lines),
        "grid": _grid_mm(grid),
        "per_symptom": _SECTION_MM + _LINE_MM * (1 + len(data.per_symptom)),
    }
    before = 22.0 + sum(sizes[s] for s in sections if s in sizes)  # 冒頭・欄外を含む
    if before > _PAGE_MM - _NEAR_FULL_MM:
        return False
    quotes = _SECTION_MM + _LINE_MM * _quote_lines(data.quotes)
    return before + quotes > _PAGE_MM


def render_report_html(
    data: ReportData,
    *,
    questions: Sequence[Question],
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE,
    sections: Sequence[str] | None = None,
    quotes_max_items: int | None = None,
    question_labels: Mapping[str, str] | None = None,
) -> str:
    """A4 の HTML を返す（通常は 1 枚）。

    - questions: 要確認・経過表の表示名に使う質問集（今の regimen Skill）
    - question_labels: 今の版の form の質問の短い名前（要確認の質問名。既知の6問は
      SHORT_LABELS が先。無ければ質問文。v1.1）
    - low_confidence_threshold: これ未満の症状別の行に「？」（report Skill の値を渡す）
    - sections: 欄とその順（report Skill の sections）。None なら全て既定の順
    - quotes_max_items: 引用の上限（report Skill の値を渡す）。引用が上限に達していれば
      省いた可能性を書く。None なら書かない（ReportData に省いた件数が無いための暫定）
    """
    chosen = _sections(sections)
    attention = _attention_view(data.attention, questions, question_labels)
    grid = grid_view(data.grid)
    template = _ENV.get_template(TEMPLATE_NAME)
    return template.render(
        css=_css(),
        sections=chosen,
        fallback=data.fallback,
        header=_header_view(data.header),
        attention=attention,
        grid=grid,
        per_symptom=_symptom_view(data.per_symptom, low_confidence_threshold),
        quotes=_quote_view(data.quotes),
        quotes_limit_note=_quotes_limit_note(data.quotes, quotes_max_items),
        quotes_page_break=_quotes_need_new_page(
            data, chosen, attention_lines=_attention_lines(attention), grid=grid
        ),
        report_skill_version=data.report_skill_version,
    )
