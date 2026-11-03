"""精度評価（spec 17.2、architecture §7c）。症例は全て合成。

- `metrics`: 5指標を計る純関数（`evaluate`）。出来事の指標は `event_metrics`、
  型と合算は `results`（`aggregate`）
- `matching`: ラベルの出来事と予測の出来事の1対1の対応づけ
- `hook_counts`: 変換1回で H1・H2 が止めた回数（幻覚引用の量は H2 の拒否回数で見る）
- `cache`: 予測の保存・読み込みと整合の検査（`docs/eval/runs/<日時>/<patient>_c<n>.json`）
- `verify`: 保存済みの予測の入力を、合成データから作り直した入力と照合する（`--cache-only`）
- `cases` / `predict`: 評価の対象（患者・コース・基準日）と1コース分の変換
- `report_md` / `md_format`: 結果の Markdown（`docs/eval/<日付>.md`）
- `run`: `python -m tsutae.eval.run`（`--cache-only` 以外は API を呼ぶ）
"""

from tsutae.eval.metrics import evaluate
from tsutae.eval.results import EvalResult, FailureCase, Ratio, aggregate

__all__ = ["EvalResult", "FailureCase", "Ratio", "aggregate", "evaluate"]
