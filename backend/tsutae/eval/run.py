"""精度評価の実行: `python -m tsutae.eval.run [--cache-only RUN_DIR] [--patients ...]`。

architecture §7c。症例は全て合成。合格ラインは置かず実測値と失敗例を出す。

- role=eval の患者の各コースについて、visit_date = そのコースの最終日（`cases`）で
  `prepare_input` → `convert`（`predict`）
- 予測は `<runs-dir>/<YYYYMMDD-HHMM>/<patient>_c<n>.json`、結果は
  `<out-dir>/<YYYY-MM-DD>.md`（同じ日付があれば -2, -3 …）
- `--cache-only RUN_DIR` は保存済みの予測から指標と md だけ作り直す（API を呼ばない）。
  保存済みの入力は合成データから作り直した入力と照合し、違えば止める（`verify`）
- md には正解ラベルの出来事の内訳（数えた + 二次検出で外れた + 入力外）を出す。
  コースのファイルが欠けたときなどに、分母から外れた出来事が分かるように
- 本番の変換（convert_fn を差し込まない）は `.env` を `config.load_env_file()` で読み、
  ANTHROPIC_API_KEY が無ければ何も作らずに止める
- 終了コード: 0 = 正常、2 = 入力・設定の誤り（何も変換していないか、途中で止めた）、
  3 = 想定外の例外で変換できなかったコースがある（全コースなら md を書かない）。
  プログラムの誤り（TypeError 等）は捕まえずに外へ出す（`predict`）
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tsutae import config
from tsutae.eval.cache import (
    UNEXPECTED_ERROR_CODES,
    CoursePrediction,
    load_predictions,
    new_run_dir,
    save_prediction,
)
from tsutae.eval.cases import (
    EvalCase,
    course_visit_dates,
    eval_cases,
    select_patients,
)
from tsutae.eval.metrics import evaluate
from tsutae.eval.predict import (
    ConvertFn,
    PrepareFn,
    default_convert_fn,
    default_prepare_fn,
    predict_case,
)
from tsutae.eval.report_md import (
    CourseScore,
    EvalSummary,
    render_markdown,
    write_markdown,
)
from tsutae.eval.verify import verify_predictions
from tsutae.schemas import PatientLabels, Timeline
from tsutae.synthetic import all_patients

__all__ = [
    "ConvertFn",
    "CoursePrediction",
    "EvalCase",
    "PrepareFn",
    "RunOutcome",
    "course_visit_dates",
    "default_convert_fn",
    "eval_cases",
    "load_predictions",
    "main",
    "new_run_dir",
    "predict_case",
    "run_cache_only",
    "run_live",
    "save_prediction",
    "score_predictions",
]

DEFAULT_OUT_DIR = config.REPO_ROOT / "docs" / "eval"
DEFAULT_RUNS_DIR = DEFAULT_OUT_DIR / "runs"
EXIT_OK = 0
EXIT_ERROR = 2
EXIT_UNEXPECTED = 3


@dataclass(frozen=True)
class RunOutcome:
    run_dir: Path
    md_path: Path | None  # None = 全コースが想定外の例外で、md を書いていない
    courses: int
    unexpected: int  # 想定外の例外で変換できなかったコース数


# ---------------------------------------------------------------------------
# 採点と書き出し
# ---------------------------------------------------------------------------


def score_predictions(
    predictions: Sequence[CoursePrediction],
    labels_by_patient: Mapping[str, PatientLabels],
) -> list[CourseScore]:
    """フォールバック（timeline なし）は空の Timeline として数える（全て取りこぼし）。"""
    scores = []
    for p in predictions:
        labels = labels_by_patient.get(p.patient_id)
        if labels is None:
            raise ValueError(f"{p.patient_id} の正解ラベルが無い")
        timeline = p.timeline or Timeline(unprocessed_entries=p.prepared.unprocessed)
        result = evaluate(timeline, p.prepared, labels.labels, patient_id=p.patient_id)
        scores.append(
            CourseScore(
                patient_id=p.patient_id,
                course_no=p.course_no,
                visit_date=p.visit_date,
                fallback=p.fallback,
                error_code=p.error_code,
                stats=p.stats,
                hooks=p.hooks,
                result=result,
            )
        )
    return scores


def _label(run_dir: Path, out_dir: Path) -> str:
    """md に書く予測の場所。out_dir の外ならディレクトリ名だけ（ローカルの絶対パスを
    コミットされうる md に書かない）。"""
    try:
        return run_dir.resolve().relative_to(out_dir.resolve()).as_posix()
    except ValueError:
        return f"{run_dir.name}（--out-dir の外）"


def _label_events_total(
    labels_by_patient: Mapping[str, PatientLabels], patient_ids: set[str]
) -> int:
    """対象の患者の正解ラベルの出来事（expect_unprocessed の記録を除く）。"""
    return sum(
        len(label.events)
        for pid in patient_ids
        if pid in labels_by_patient
        for label in labels_by_patient[pid].labels
        if not label.expect_unprocessed
    )


def _write_summary(
    predictions: Sequence[CoursePrediction],
    *,
    data_dir: Path,
    out_dir: Path,
    run_dir: Path,
    cache_only: bool,
    wall_seconds: float | None,
) -> RunOutcome:
    """md を書く。全コースが想定外の例外なら書かない（0% を結果として残さない）。"""
    unexpected = sum(p.error_code in UNEXPECTED_ERROR_CODES for p in predictions)
    outcome = RunOutcome(
        run_dir=run_dir, md_path=None, courses=len(predictions), unexpected=unexpected
    )
    if predictions and unexpected == len(predictions):
        return outcome
    labels = {p.patient_id: labels for p, labels in all_patients(data_dir)}
    summary = EvalSummary(
        day=config.today(),
        run_label=_label(run_dir, out_dir),
        cache_only=cache_only,
        models=sorted({p.model for p in predictions}),
        subagent_models=sorted({p.subagent_model for p in predictions}),
        courses=score_predictions(predictions, labels),
        wall_seconds=wall_seconds,
        label_events_total=_label_events_total(
            labels, {p.patient_id for p in predictions}
        ),
    )
    path = write_markdown(render_markdown(summary), out_dir, summary.day)
    return RunOutcome(
        run_dir=run_dir,
        md_path=path,
        courses=outcome.courses,
        unexpected=outcome.unexpected,
    )


def run_live(
    *,
    data_dir: Path,
    runs_dir: Path,
    out_dir: Path,
    patients: Sequence[str] | None,
    prepare_fn: PrepareFn,
    convert_fn: ConvertFn,
    settings: config.Settings,
) -> RunOutcome:
    """変換して予測を1コースずつ保存し、md を書く。"""
    started = time.monotonic()
    cases = eval_cases(data_dir, patients)
    run_dir = new_run_dir(runs_dir, config.now())
    predictions = []
    for case in cases:
        print(f"{case.patient.patient_id} 第{case.course_no}コース", file=sys.stderr)
        prediction = predict_case(
            case,
            prepare_fn=prepare_fn,
            convert_fn=convert_fn,
            model=settings.model,
            subagent_model=settings.subagent_model,
            skills_dir=settings.skills_dir,
        )
        save_prediction(run_dir, prediction)
        predictions.append(prediction)
    return _write_summary(
        predictions,
        data_dir=data_dir,
        out_dir=out_dir,
        run_dir=run_dir,
        cache_only=False,
        wall_seconds=time.monotonic() - started,
    )


def run_cache_only(
    run_dir: Path,
    *,
    data_dir: Path,
    out_dir: Path,
    patients: Sequence[str] | None = None,
    prepare_fn: PrepareFn | None = None,
    skills_dir: Path | None = None,
) -> RunOutcome:
    """保存済みの予測から指標と md を作り直す（変換しない）。

    保存済みの入力は合成データから作り直した入力と照合する（prepare_fn の既定は
    実物の prepare_input。純関数で API は呼ばない）。
    """
    predictions = load_predictions(run_dir)
    if patients:
        ids = {p.patient_id for p, _ in select_patients(data_dir, patients)}
        predictions = [p for p in predictions if p.patient_id in ids]
        if not predictions:
            raise ValueError("指定の患者の予測が無い")
    verify_predictions(
        predictions,
        data_dir=data_dir,
        prepare_fn=prepare_fn or default_prepare_fn(),
        skills_dir=skills_dir,
    )
    return _write_summary(
        predictions,
        data_dir=data_dir,
        out_dir=out_dir,
        run_dir=run_dir,
        cache_only=True,
        wall_seconds=None,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tsutae.eval.run",
        description="精度評価（spec 17.2）。症例は全て合成。--cache-only 以外は API を呼ぶ",
    )
    parser.add_argument("--cache-only", type=Path, metavar="RUN_DIR", default=None)
    parser.add_argument("--patients", nargs="+", metavar="PATIENT", default=None)
    parser.add_argument("--data-dir", type=Path, default=config.SYNTHETIC_DIR)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser


def _require_api_key() -> None:
    config.load_env_file()  # サンドボックス内では読めず False
    if not config.has_api_key():
        raise ValueError(
            "ANTHROPIC_API_KEY が無い（.env を読めないか未設定）。本番の評価は API を"
            "呼ぶので止めた（保存済みの予測からは --cache-only）"
        )


def _dispatch(
    args: argparse.Namespace,
    prepare_fn: PrepareFn | None,
    convert_fn: ConvertFn | None,
) -> RunOutcome:
    if args.cache_only is not None:
        return run_cache_only(
            args.cache_only,
            data_dir=args.data_dir,
            out_dir=args.out_dir,
            patients=args.patients,
            prepare_fn=prepare_fn,
            skills_dir=config.get_settings().skills_dir,
        )
    if convert_fn is None:
        _require_api_key()
    settings = config.get_settings()
    return run_live(
        data_dir=args.data_dir,
        runs_dir=args.runs_dir,
        out_dir=args.out_dir,
        patients=args.patients,
        prepare_fn=prepare_fn or default_prepare_fn(),
        convert_fn=convert_fn or default_convert_fn(settings),
        settings=settings,
    )


def _report(outcome: RunOutcome) -> int:
    if outcome.md_path is None:
        print(
            f"エラー: 全{outcome.courses}コースが想定外の例外で変換できなかった。"
            f"md は書かない（予測: {outcome.run_dir}）",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED
    print(outcome.md_path)
    if outcome.unexpected:
        print(
            f"注意: {outcome.courses}コース中 {outcome.unexpected} コースが想定外の"
            "例外で変換できなかった（md の冒頭に件数）",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    prepare_fn: PrepareFn | None = None,
    convert_fn: ConvertFn | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        outcome = _dispatch(args, prepare_fn, convert_fn)
    except ImportError as exc:
        print(f"エラー: 変換パイプラインを読み込めない（{exc.name}）", file=sys.stderr)
        return EXIT_ERROR
    except (ValueError, OSError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return _report(outcome)


if __name__ == "__main__":
    sys.exit(main())
