"""予測の保存と読み込み（`docs/eval/runs/<YYYYMMDD-HHMM>/<patient>_c<n>.json`）。

1ファイル = 1患者・1コースの変換。`--cache-only` はここから指標を計り直す。
中身は変換の入力（`PreparedInput`。自由記載は伏せ字後の文だけ）・Timeline・
ConversionResult の stats と error_code・Hook が止めた回数。原文（伏せ字前の文）と
受付番号は入れない。

読み込みでは次を検査し、合わないファイルは拒否する:
- ファイルの中の辻褄（entry_ids・masked_texts・input.entries・unprocessed）
- course_no と visit_date が入力のコース（prepared.input.schedule）と合う
  （CoursePrediction の検証。保存でも読み込みでも効く）
合成データから作り直した入力との照合（辻褄を合わせて記録を消した・患者を入れ替えた
ファイルの拒否）は `eval.verify`（`--cache-only` が呼ぶ）。
format_version 1（Hook の回数なし）は読まない。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from tsutae.eval.hook_counts import HookCounts
from tsutae.schemas import Frozen, PreparedInput, RunStats, Timeline

PATIENT_ID_PATTERN = r"^[A-Za-z0-9-]{1,40}$"  # ファイル名に使うので狭く検査する
EXCEPTION_ERROR_CODE = "eval_exception"  # 評価側で捕まえた想定外の例外
# 想定外の例外で変換できなかったコード（convert の internal_error を含む）。
# 1件でもあれば終了コードを非 0 にし、全コースなら md を書かない
UNEXPECTED_ERROR_CODES = frozenset({EXCEPTION_ERROR_CODE, "internal_error"})
PREDICTION_GLOB = "*_c*.json"
MAX_SUFFIX = 1000


class CoursePrediction(Frozen):
    format_version: Literal[2] = 2
    patient_id: str = Field(pattern=PATIENT_ID_PATTERN)
    course_no: int = Field(ge=1)
    visit_date: date  # 評価の基準日（そのコースの最終日）
    model: str
    subagent_model: str
    prepared: PreparedInput
    timeline: Timeline | None  # None = フォールバック（AI変換なし）
    fallback: bool
    error_code: str | None = None
    stats: RunStats = Field(default_factory=RunStats)
    hooks: HookCounts = Field(default_factory=HookCounts)

    @model_validator(mode="after")
    def _same_course(self) -> CoursePrediction:
        schedule = self.prepared.input.schedule
        if self.course_no != schedule.course_no:
            raise ValueError(
                f"コースが入力と合わない（第{self.course_no}コース、"
                f"入力は第{schedule.course_no}コース）"
            )
        if not schedule.infusion_date <= self.visit_date <= schedule.last_day_date:
            raise ValueError("基準日（visit_date）が入力のコースの期間に無い")
        return self

    @property
    def file_name(self) -> str:
        return f"{self.patient_id}_c{self.course_no}.json"


def sanitize_prepared(prepared: PreparedInput) -> PreparedInput:
    """伏せ字後の文を、入力に入った記録（entry_no）の分だけに絞った新しい入力。"""
    numbers = {e.entry_no for e in prepared.input.entries}
    texts = {no: t for no, t in prepared.masked_texts.items() if no in numbers}
    return prepared.model_copy(update={"masked_texts": texts})


def check_prepared(prepared: PreparedInput) -> None:
    """入力の整合を検査する。合わなければ ValueError（理由は短い文。本文は入れない）。

    - input.entries の entry_no は一意で、entry_ids のキーと同じ集合
    - entry_ids の値（記録 id）は一意で、unprocessed の記録と重ならない
    - masked_texts は input.entries の masked_free_text（空でないもの）と同じ
    """
    entries = prepared.input.entries
    numbers = [e.entry_no for e in entries]
    if len(numbers) != len(set(numbers)):
        raise ValueError("input.entries の entry_no が重複している")
    if set(prepared.entry_ids) != set(numbers):
        raise ValueError("entry_ids と input.entries の entry_no が合わない")
    ids = list(prepared.entry_ids.values())
    if len(ids) != len(set(ids)):
        raise ValueError("entry_ids に同じ記録が2回入っている")
    if {u.entry_id for u in prepared.unprocessed} & set(ids):
        raise ValueError("送信対象外の記録が entry_ids にもある")
    texts = {e.entry_no: e.masked_free_text for e in entries if e.masked_free_text}
    if dict(prepared.masked_texts) != texts:
        raise ValueError("masked_texts が input.entries の伏せ字後の文と合わない")


def new_run_dir(runs_dir: Path, at: datetime) -> Path:
    """`<runs_dir>/<YYYYMMDD-HHMM>` を作って返す。既にあれば `-2`, `-3` … を付ける。"""
    base = at.strftime("%Y%m%d-%H%M")
    runs_dir.mkdir(parents=True, exist_ok=True)
    for n in range(1, MAX_SUFFIX):
        path = runs_dir / (base if n == 1 else f"{base}-{n}")
        try:
            path.mkdir()
        except FileExistsError:
            continue
        return path
    raise ValueError(f"{runs_dir} に {base} の実行が多すぎる")


def save_prediction(run_dir: Path, prediction: CoursePrediction) -> Path:
    """入力外の文を落として保存する。入力が整合しなければ ValueError（書かない）。"""
    clean = prediction.model_copy(
        update={"prepared": sanitize_prepared(prediction.prepared)}
    )
    check_prepared(clean.prepared)
    path = run_dir / clean.file_name
    path.write_text(clean.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _reason(exc: ValidationError) -> str:
    """検証の失敗の要約（msg と場所だけ。入力の値は入れない）。"""
    errors = exc.errors(include_input=False, include_url=False)
    shown = [
        f"{'.'.join(str(x) for x in e['loc']) or '全体'}: {e['msg']}"
        for e in errors[:3]
    ]
    rest = len(errors) - len(shown)
    return "; ".join(shown) + (f" ほか {rest} 件" if rest > 0 else "")


def _load_one(path: Path) -> CoursePrediction:
    try:
        prediction = CoursePrediction.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except ValidationError as exc:
        raise ValueError(
            f"{path.name}: 予測ファイルの形式が違う（{_reason(exc)}）"
        ) from exc
    try:
        check_prepared(prediction.prepared)
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from exc
    return prediction


def _check_unique(predictions: Sequence[CoursePrediction]) -> None:
    keys = [(p.patient_id, p.course_no) for p in predictions]
    if len(keys) != len(set(keys)):
        raise ValueError("同じ患者・コースの予測が2つある")


def load_predictions(run_dir: Path) -> list[CoursePrediction]:
    """run_dir の予測を (患者, コース) 順に読む。無い・壊れていれば ValueError。"""
    if not run_dir.is_dir():
        raise ValueError(f"予測のディレクトリが無い: {run_dir}")
    paths = sorted(run_dir.glob(PREDICTION_GLOB))
    if not paths:
        raise ValueError(f"予測ファイル（{PREDICTION_GLOB}）が無い: {run_dir}")
    predictions = [_load_one(p) for p in paths]
    _check_unique(predictions)
    return sorted(predictions, key=lambda p: (p.patient_id, p.course_no))
