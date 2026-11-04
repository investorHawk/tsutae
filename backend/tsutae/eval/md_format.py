"""評価結果の Markdown の書式（エスケープ・表・指標の見出し）。症例は全て合成。

- 文字は `html.escape` で `&` `<` `>` を実体参照にする（予測は外からの入力。
  Markdown のレンダラーが生の HTML を通しても効かないように）
- 表のセルと表の外の行（`inline`）は改行を空白にする（外からの文字で見出し等の行を
  作らせない）。表のセルはさらに `|` を `\\|` にする
- コード（`code_span`）は中のバッククォートより長い区切りで囲む
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence

from tsutae.eval.results import Ratio

# (EvalResult の項目, 表の見出し, 数え方)
METRIC_ROWS: tuple[tuple[str, str, str], ...] = (
    (
        "date",
        "1. 日付正規化の一致率（暦日と Day）",
        "正解ラベルの出来事のうち、対応づけた予測の date と day が両方一致"
        "（対応づけできない出来事は不一致）",
    ),
    (
        "date_paired",
        "（参考）対応づけできた出来事に限った日付の一致率",
        "分母は対応づけできた出来事だけ",
    ),
    (
        "matched",
        "（参考）出来事の対応づけ",
        "同じ記録に同じ用語、無ければ同じ question_key の予測がある（1対1。"
        "日付が近く status が同じ組を先にする）",
    ),
    ("term", "2. 用語当てはめの一致率", "同じ記録に同じ用語の予測がある"),
    (
        "contradiction_recall",
        "3. 食い違い検出の再現率",
        "正解の食い違い（記録, question_key）のうち検出できた",
    ),
    (
        "contradiction_precision",
        "3. 食い違い検出の適合率",
        "検出した食い違いのうち正解にある",
    ),
    (
        "mild_as_absent",
        "4. 改善中のみ（軽いは未計測）: 改善中（improving）を absent と誤った件数",
        "分母は status が improving の出来事（出来事ごと。mild_improving の記録タグは"
        "使わない）。spec の「軽い」は正解ラベルに出来事ごとの印が無く数えていない",
    ),
    (
        "mild_missed",
        "4. 改善中のみ（軽いは未計測）: 改善中（improving）を取りこぼした件数",
        "分母は同上。対応する予測が無い",
    ),
    (
        "negation_as_present",
        "4. 否定を present / improving とした件数",
        "分母は否定（absent）の出来事。対応づけた予測か、同じ記録で他の出来事に"
        "対応づかなかった同じ用語の予測が present / improving なら誤り",
    ),
    (
        "quote",
        "5. 引用一致率",
        "出来事の source_quote が伏せ字後の記載に部分一致。最終の Timeline は H2 を"
        "通ったものなので、AI変換のコースでは構造上 100%",
    ),
    (
        "contradiction_quote",
        "（参考）食い違いの引用の一致率",
        "食い違いの free_text_quote が伏せ字後の記載に部分一致（指標5の対象外）",
    ),
)
COUNT_METRICS = frozenset({"mild_as_absent", "mild_missed", "negation_as_present"})
FAILURE_LABELS: dict[str, str] = {
    "match": "対応づけ",
    "date": "日付",
    "term": "用語",
    "contradiction_missed": "食い違いの取りこぼし",
    "contradiction_spurious": "食い違いの誤検出",
    "mild_as_absent": "改善中を absent",
    "mild_missed": "改善中の取りこぼし",
    "negation_as_present": "否定を症状あり",
    "quote": "引用",
    "contradiction_quote": "食い違いの引用",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def format_ratio(r: Ratio) -> str:
    rate = r.rate
    shown = f"{rate * 100:.1f}%" if rate is not None else "—"
    return f"{shown}（{r.numerator}/{r.denominator}）"


def format_count(r: Ratio) -> str:
    return f"{r.numerator}件（{r.denominator}件中）"


def seconds(ms: int) -> str:
    return f"{ms / 1000:.1f} 秒"


def inline(value: object) -> str:
    """表の外の1行に入れる文字（エスケープして改行を空白に）。"""
    return esc(value).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def code_span(value: object) -> str:
    """`inline` の文字をコードにする。中のバッククォートで閉じないよう区切りを長くする。"""
    text = inline(value)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _cell(value: object) -> str:
    return inline(value).replace("|", "\\|")


def _row(values: Sequence[object]) -> str:
    return "| " + " | ".join(_cell(v) for v in values) + " |"


def table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    return [_row(header), _row(["---"] * len(header)), *(_row(r) for r in rows)]
