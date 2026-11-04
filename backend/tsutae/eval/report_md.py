"""評価結果の Markdown（`docs/eval/<YYYY-MM-DD>.md`）。症例は全て合成。

合格ラインは置かず、5指標の実測値（分子・分母つき）と失敗例を出す。
「## 5指標」より後ろは予測だけで決まる（`--cache-only` で同じ表になる）。
文字は全て HTML エスケープしてから書く（予測は外からの入力。`md_format`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from itertools import groupby
from pathlib import Path

from pydantic import Field

from tsutae.eval.cache import UNEXPECTED_ERROR_CODES
from tsutae.eval.hook_counts import HookCounts
from tsutae.eval.md_format import (
    COUNT_METRICS,
    FAILURE_LABELS,
    METRIC_ROWS,
    code_span,
    esc,
    format_count,
    format_ratio,
    inline,
    seconds,
    table,
)
from tsutae.eval.metrics import EvalResult, FailureCase, Ratio, aggregate
from tsutae.schemas import Frozen, RunStats

__all__ = [
    "CourseScore",
    "EvalSummary",
    "format_ratio",
    "render_markdown",
    "write_markdown",
]

MAX_SUFFIX = 1000
CTCAE_NOTE = "用語は「有害事象共通用語規準 v5.0 日本語訳JCOG版より引用」"


class CourseScore(Frozen):
    patient_id: str
    course_no: int
    visit_date: date
    fallback: bool
    error_code: str | None = None
    stats: RunStats = Field(default_factory=RunStats)
    hooks: HookCounts = Field(default_factory=HookCounts)
    result: EvalResult


class EvalSummary(Frozen):
    day: date
    run_label: str
    cache_only: bool
    models: list[str]
    subagent_models: list[str]
    courses: list[CourseScore]
    wall_seconds: float | None = None
    # 対象の患者の正解ラベルの出来事（expect_unprocessed を除く）。None = 内訳を出さない
    label_events_total: int | None = None


def _total_stats(courses: Sequence[CourseScore]) -> RunStats:
    return RunStats(
        duration_ms=sum(c.stats.duration_ms for c in courses),
        num_turns=sum(c.stats.num_turns for c in courses),
        tokens_in=sum(c.stats.tokens_in for c in courses),
        tokens_out=sum(c.stats.tokens_out for c in courses),
        cost_usd=sum(c.stats.cost_usd for c in courses),
    )


def _total_hooks(courses: Sequence[CourseScore]) -> HookCounts:
    return sum((c.hooks for c in courses), HookCounts())


# ---------------------------------------------------------------------------
# 節
# ---------------------------------------------------------------------------


def _outside(summary: EvalSummary, total: EvalResult) -> int | None:
    """正解ラベルの出来事のうち、どのコースの入力にも入らなかった数。"""
    if summary.label_events_total is None:
        return None
    counted = total.label_events + total.held_out_label_events
    return summary.label_events_total - counted


def _exception_warning(summary: EvalSummary) -> list[str]:
    bad = [c for c in summary.courses if c.error_code in UNEXPECTED_ERROR_CODES]
    if not bad:
        return []
    return [
        f"- **注意: 変換で想定外の例外が出たコース {len(bad)} 件**"
        f"（{len(summary.courses)} コース中。"
        f"{esc(', '.join(sorted(UNEXPECTED_ERROR_CODES)))}）。"
        "このコースの出来事は全て取りこぼしとして数えている。"
        "評価の手順か変換の呼び方の誤りを先に直す",
    ]


def _outside_warning(summary: EvalSummary, total: EvalResult) -> list[str]:
    outside = _outside(summary, total)
    if not outside:
        return []
    return [
        f"- **注意: 正解ラベルの出来事 {outside} 件が今回の入力に入っていない**"
        "（分母に入らない。コースの予測ファイルが欠けているか、入力の作り方が"
        "変わった）",
    ]


def _breakdown(summary: EvalSummary, total: EvalResult) -> list[str]:
    outside = _outside(summary, total)
    if outside is None:
        return []
    return [
        "- 正解ラベルの出来事の内訳（expect_unprocessed を除く）: "
        f"全 {summary.label_events_total} 件 = 数えた {total.label_events} 件 + "
        f"二次検出で外れた {total.held_out_label_events} 件 + 入力外 {outside} 件",
    ]


def _scope_lines(summary: EvalSummary, total: EvalResult) -> list[str]:
    return [
        f"- 記録 {total.entries_evaluated} 件、"
        f"正解ラベルの出来事 {total.label_events} 件（分母）",
        *_breakdown(summary, total),
        f"- 二次検出で送信対象外にした記録 {total.held_out_entries} 件"
        f"（そのうち正解ラベルの出来事 {total.held_out_label_events} 件は分母に入らない。"
        "検出しすぎならここが増える）",
        f"- 送信対象外のはずが入力に入った記録 {total.leaked_unprocessed} 件"
        "（正解ラベルが expect_unprocessed。二次検出の漏れ。0 が正常。指標には数えない）",
    ]


def _header(summary: EvalSummary, total: EvalResult) -> list[str]:
    stats = _total_stats(summary.courses)
    patients = {c.patient_id for c in summary.courses}
    source = (
        "保存済みの予測から再計算（API は呼んでいない）"
        if summary.cache_only
        else "この実行で変換した予測"
    )
    lines = [
        f"# 精度評価 {summary.day.isoformat()}",
        "",
        *_exception_warning(summary),
        *_outside_warning(summary, total),
        "- **症例は全て合成**（data/synthetic の評価用患者。デモ患者は含めない）",
        "- 合格ラインは置かず実測値と失敗例を出す（spec 17.2）",
        f"- 予測: {code_span(summary.run_label)}（{source}）",
        f"- モデル: {inline(', '.join(summary.models)) or '不明'}"
        f"（サブエージェント: {inline(', '.join(summary.subagent_models)) or '不明'}）",
        f"- 対象: {len(patients)}人・{len(summary.courses)}コース",
        *_scope_lines(summary, total),
        f"- 変換の所要時間（合計）: {seconds(stats.duration_ms)}",
    ]
    if summary.wall_seconds is not None:
        lines.append(f"- 評価全体の実時間: {summary.wall_seconds:.1f} 秒")
    lines += [
        f"- 費用（合計）: ${stats.cost_usd:.4f}、ターン数 {stats.num_turns}、"
        f"トークン 入力 {stats.tokens_in} / 出力 {stats.tokens_out}",
        "- 基準日（visit_date）は各コースの最終日（次コース実投与日の前日。"
        "最後のコースは受診予定日）",
        "",
    ]
    return lines


def _hook_lines(hooks: HookCounts) -> list[str]:
    return [
        f"- H2 が拒否した引用: emit_timeline {hooks.h2_timeline_denies} 回、"
        f"emit_report {hooks.h2_report_denies} 回（引用が伏せ字後の記載の部分文字列で"
        "なかった呼び出し。モデルは直して呼び直す）",
        f"- H1 が止めた依頼: {hooks.h1_blocks} 回",
        "- 指標5は最終の Timeline（H2 を通ったもの）で数えるので、AI変換のコースでは"
        "部分一致率は構造上 100%。幻覚引用の量は上の H2 の拒否回数で見る",
    ]


def _metric_section(total: EvalResult, hooks: HookCounts) -> list[str]:
    rows = []
    for name, label, how in METRIC_ROWS:
        r: Ratio = getattr(total, name)
        shown = format_count(r) if name in COUNT_METRICS else format_ratio(r)
        rows.append([label, shown, r.numerator, r.denominator, how])
    header = ["指標", "実測値", "分子", "分母", "数え方"]
    return ["## 5指標（全体）", "", *table(header, rows), "", *_hook_lines(hooks), ""]


COURSE_HEADER = [
    "患者",
    "コース",
    "基準日",
    "変換",
    "日付",
    "用語",
    "食い違い 再現率",
    "食い違い 適合率",
    "改善中のみ→absent",
    "改善中のみ 取りこぼし",
    "否定→あり",
    "引用",
    "H2 拒否",
    "所要時間",
    "費用",
]


def _metric_cells(r: EvalResult) -> list[str]:
    return [
        format_ratio(r.date),
        format_ratio(r.term),
        format_ratio(r.contradiction_recall),
        format_ratio(r.contradiction_precision),
        format_count(r.mild_as_absent),
        format_count(r.mild_missed),
        format_count(r.negation_as_present),
        format_ratio(r.quote),
    ]


def _conversion(c: CourseScore) -> str:
    if not c.fallback and c.error_code is None:
        return "AI変換"
    return f"AI変換なし（{c.error_code or 'fallback'}）"


def _tail(courses: Sequence[CourseScore]) -> list[object]:
    stats = _total_stats(courses)
    hooks = _total_hooks(courses)
    return [hooks.h2_denies, seconds(stats.duration_ms), f"${stats.cost_usd:.4f}"]


def _course_rows(courses: Sequence[CourseScore]) -> list[list[object]]:
    rows: list[list[object]] = []
    ordered = sorted(courses, key=lambda c: (c.patient_id, c.course_no))
    for pid, group in groupby(ordered, key=lambda c: c.patient_id):
        items = list(group)
        for c in items:
            head = [pid, c.course_no, c.visit_date.isoformat(), _conversion(c)]
            rows.append([*head, *_metric_cells(c.result), *_tail([c])])
        subtotal = aggregate([c.result for c in items])
        rows.append([pid, "計", "—", "—", *_metric_cells(subtotal), *_tail(items)])
    return rows


def _course_section(courses: Sequence[CourseScore]) -> list[str]:
    return ["## 患者・コース別", "", *table(COURSE_HEADER, _course_rows(courses)), ""]


def _failure_row(f: FailureCase) -> list[object]:
    seq = f.entry_seq if f.entry_seq is not None else "—"
    course = f.course_no if f.course_no is not None else "—"
    label = FAILURE_LABELS.get(f.metric, f.metric)
    return [f.patient_id or "—", course, seq, label, f.item, f.expected, f.predicted]


def _failure_section(failures: Sequence[FailureCase]) -> list[str]:
    lines = [f"## 失敗例（{len(failures)}件）", ""]
    if not failures:
        return [*lines, "なし", ""]
    header = ["患者", "コース", "記録 seq", "指標", "項目", "期待", "予測"]
    return [*lines, *table(header, [_failure_row(f) for f in failures]), ""]


def _notes() -> list[str]:
    return [
        "## 注記",
        "",
        f"- {CTCAE_NOTE}",
        "- 引用・期待の文は伏せ字後の記載（原文は載せない）。"
        "予測の引用が記載に無いものは「引用」の失敗例に出す",
        "- 指標4の「改善中」は正解ラベルの status が improving の出来事だけを数える。"
        "mild_improving は記録単位のタグなので、その記録の present の出来事"
        "（「つらかった」等も含む）には広げない。spec 17.2 ④の「軽い」は、"
        "出来事ごとの印が正解ラベルに無いので未計測（軽いは未計測）",
        "- 正解ラベルが送信対象外（expect_unprocessed）の記録と、"
        "今回の入力に入っていない記録は数えない",
        "",
    ]


def render_markdown(summary: EvalSummary) -> str:
    total = aggregate([c.result for c in summary.courses])
    failures = [f for c in summary.courses for f in c.result.failures]
    lines = [
        *_header(summary, total),
        *_metric_section(total, _total_hooks(summary.courses)),
        *_course_section(summary.courses),
        *_failure_section(failures),
        *_notes(),
    ]
    return "\n".join(lines)


def write_markdown(text: str, out_dir: Path, day: date) -> Path:
    """`<out_dir>/<YYYY-MM-DD>.md` に書く。同じ日付があれば `-2`, `-3` … を付ける。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    for n in range(1, MAX_SUFFIX):
        name = f"{day.isoformat()}.md" if n == 1 else f"{day.isoformat()}-{n}.md"
        path = out_dir / name
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write(text)
        except FileExistsError:
            continue
        return path
    raise ValueError(f"{out_dir} に {day.isoformat()} の結果が多すぎる")
