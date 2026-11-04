"""tsutae.eval.report_md: 評価結果の Markdown（症例は全て合成）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from tsutae.eval.hook_counts import HookCounts
from tsutae.eval.metrics import EvalResult, FailureCase, Ratio
from tsutae.eval.report_md import (
    CourseScore,
    EvalSummary,
    format_ratio,
    render_markdown,
    write_markdown,
)
from tsutae.schemas import RunStats


def _score(failures: list[FailureCase] | None = None, **kw) -> CourseScore:
    result = EvalResult(
        patient_id="P-EVAL0001",
        course_no=1,
        label_events=4,
        entries_evaluated=6,
        term=Ratio(numerator=3, denominator=4),
        date=Ratio(numerator=2, denominator=3),
        failures=failures or [],
    )
    base = dict(
        patient_id="P-EVAL0001",
        course_no=1,
        visit_date=date(2026, 9, 14),
        fallback=False,
        error_code=None,
        stats=RunStats(duration_ms=2500, cost_usd=0.5),
        result=result,
    )
    return CourseScore(**{**base, **kw})


def _summary(courses: list[CourseScore], **kw) -> EvalSummary:
    base = dict(
        day=date(2026, 11, 6),
        run_label="runs/20261106-1530",
        cache_only=False,
        models=["claude-opus-5-5"],
        subagent_models=["claude-sonnet-5-5"],
        courses=courses,
        wall_seconds=12.0,
    )
    return EvalSummary(**{**base, **kw})


def test_format_ratio() -> None:
    assert format_ratio(Ratio(numerator=3, denominator=4)) == "75.0%（3/4）"
    assert format_ratio(Ratio()) == "—（0/0）"


def test_render_has_required_notes_and_metrics() -> None:
    md = render_markdown(_summary([_score()]))
    assert md.startswith("# 精度評価 2026-11-06")
    assert "症例は全て合成" in md
    assert "合格ラインは置かず実測値と失敗例を出す" in md
    assert "有害事象共通用語規準 v5.0 日本語訳JCOG版より引用" in md
    assert "claude-opus-5-5" in md and "claude-sonnet-5-5" in md
    assert "75.0%（3/4）" in md and "66.7%（2/3）" in md
    for label in ("日付正規化", "用語", "再現率", "適合率", "absent", "否定", "引用"):
        assert label in md
    assert "$0.5000" in md
    assert "2.5 秒" in md and "12.0 秒" in md


def test_render_escapes_table_cells() -> None:
    failure = FailureCase(
        patient_id="P-EVAL0001",
        course_no=1,
        entry_seq=3,
        metric="quote",
        item="嘔吐",
        expected="伏せ字後の記載に部分一致",
        predicted="a|b\nc",
    )
    md = render_markdown(_summary([_score([failure])]))
    assert "a\\|b c" in md
    assert "失敗例（1件）" in md
    assert "| P-EVAL0001 | 1 | 3 | 引用 | 嘔吐 |" in md


def test_render_escapes_html_in_cells_and_header() -> None:
    # モデルの予測（外からの入力）に HTML が入っても、生の HTML として残さない
    failure = FailureCase(
        patient_id="P-EVAL0001",
        course_no=1,
        entry_seq=3,
        metric="quote",
        item="嘔吐 & 悪心",
        expected="伏せ字後の記載に部分一致",
        predicted="<img src=x onerror=alert(1)>",
    )
    md = render_markdown(_summary([_score([failure])], models=["<script>m</script>"]))
    assert "<img" not in md and "<script>" not in md
    assert "&lt;img src=x onerror=alert(1)&gt;" in md
    assert "嘔吐 &amp; 悪心" in md
    assert "&lt;script&gt;m&lt;/script&gt;" in md


def test_render_counts_unexpected_exceptions_in_header() -> None:
    courses = [
        _score(fallback=True, error_code="eval_exception"),
        _score(course_no=2, fallback=True, error_code="internal_error"),
        _score(course_no=3, fallback=True, error_code="timeout"),
    ]
    md = render_markdown(_summary(courses))
    head = md.split("## 5指標")[0]
    assert "変換で想定外の例外が出たコース 2 件" in head
    assert "変換で想定外の例外" not in render_markdown(_summary([_score()]))


def test_render_shows_hook_counts_and_quote_note() -> None:
    courses = [
        _score(hooks=HookCounts(h1_blocks=1, h2_timeline_denies=2)),
        _score(course_no=2, hooks=HookCounts(h2_timeline_denies=1, h2_report_denies=4)),
    ]
    md = render_markdown(_summary(courses))
    assert "H2 が拒否した引用: emit_timeline 3 回、emit_report 4 回" in md
    assert "H1 が止めた依頼: 1 回" in md
    assert "構造上 100%" in md


def test_render_explains_unprocessed_counts() -> None:
    result = EvalResult(
        patient_id="P-EVAL0001",
        course_no=1,
        held_out_entries=2,
        held_out_label_events=3,
        leaked_unprocessed=1,
    )
    md = render_markdown(_summary([_score(result=result)]))
    head = md.split("## 5指標")[0]
    assert "二次検出で送信対象外にした記録 2 件" in head
    assert "正解ラベルの出来事 3 件は分母に入らない" in head
    assert "送信対象外のはずが入力に入った記録 1 件" in head


def test_render_mild_metric_counts_improving_only() -> None:
    md = render_markdown(_summary([_score()]))
    assert "改善中（improving）" in md
    assert "mild_improving" in md  # 記録のタグを出来事に広げない旨の注記


def test_render_mild_metric_says_mild_is_not_measured() -> None:
    # spec 17.2 ④「軽い・改善中」のうち「軽い」は測っていないと読めるようにする
    md = render_markdown(_summary([_score()]))
    metric_rows = [line for line in md.splitlines() if line.startswith("| 4. 改善中")]
    assert len(metric_rows) == 2
    assert all("改善中のみ（軽いは未計測）" in line for line in metric_rows)
    header = next(
        line for line in md.splitlines() if line.startswith("| 患者 | コース")
    )
    assert "改善中のみ→absent" in header
    assert "軽いは未計測" in md.split("## 注記")[1]


def test_render_header_lines_drop_newlines() -> None:
    # 表の外の行でも、外からの文字（モデル名・予測の場所）の改行で行を作らせない
    md = render_markdown(
        _summary(
            [_score()],
            models=["m\n# 偽の見出し\n<b>x</b>"],
            subagent_models=["s\r\n## 偽2"],
            run_label="runs/x`y\n# 偽3",
        )
    )
    lines = md.splitlines()
    assert [line for line in lines if line.startswith("#")] == [
        "# 精度評価 2026-11-06",
        "## 5指標（全体）",
        "## 患者・コース別",
        "## 失敗例（0件）",
        "## 注記",
    ]
    assert "<b>" not in md
    label_line = next(line for line in lines if line.startswith("- 予測:"))
    assert "``runs/x`y # 偽3``" in label_line  # 中のバッククォートでコードを閉じない


def test_render_shows_label_event_breakdown() -> None:
    result = EvalResult(
        patient_id="P-EVAL0001",
        course_no=1,
        label_events=12,
        held_out_label_events=1,
    )
    md = render_markdown(_summary([_score(result=result)], label_events_total=15))
    head = md.split("## 5指標")[0]
    assert "全 15 件 = 数えた 12 件 + 二次検出で外れた 1 件 + 入力外 2 件" in head
    assert "正解ラベルの出来事 2 件が今回の入力に入っていない" in head


def test_render_breakdown_without_outside_has_no_warning() -> None:
    result = EvalResult(patient_id="P-EVAL0001", course_no=1, label_events=4)
    md = render_markdown(_summary([_score(result=result)], label_events_total=4))
    assert "入力外 0 件" in md
    assert "今回の入力に入っていない" not in md.split("## 5指標")[0]


def test_render_cache_only_and_fallback() -> None:
    md = render_markdown(
        _summary(
            [_score(fallback=True, error_code="max_turns")],
            cache_only=True,
            wall_seconds=None,
        )
    )
    assert "保存済みの予測から再計算" in md
    assert "AI変換なし（max_turns）" in md


def test_write_markdown_numbers_same_day(tmp_path: Path) -> None:
    day = date(2026, 11, 6)
    paths = [write_markdown(f"x{i}", tmp_path / "eval", day) for i in range(3)]
    assert [p.name for p in paths] == [
        "2026-11-06.md",
        "2026-11-06-2.md",
        "2026-11-06-3.md",
    ]
    assert paths[1].read_text(encoding="utf-8") == "x1"
