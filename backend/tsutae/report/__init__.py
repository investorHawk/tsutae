"""レポート（A4 一枚・モノクロ印刷）。docs/architecture.md §7b、docs/spec.md 10節。

- `build_report_data`: 記録・コース・変換結果から ReportData を決定的に組み立てる。
  入力の対応が崩れていれば `ReportBuildError`（ValueError、`code` 付き）
- `render_report_html`: ReportData を Jinja2（autoescape）で HTML にする。AI は HTML を書かない
"""

from tsutae.report.build import build_report_data
from tsutae.report.errors import ReportBuildError
from tsutae.report.labels import question_label
from tsutae.report.render import render_report_html

__all__ = [
    "ReportBuildError",
    "build_report_data",
    "question_label",
    "render_report_html",
]
