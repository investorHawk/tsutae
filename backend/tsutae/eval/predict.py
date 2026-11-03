"""1コース分の変換（prepare_input → convert）。症例は全て合成。

- `tsutae.pipeline` は関数の中で遅延 import する。`--cache-only` も入力の照合に
  `tsutae.pipeline.inputs.prepare_input`（純関数）を使うので pipeline を読むが、
  変換（convert・SdkRunner）は呼ばない。API は呼ばない
- 変換関数（ConvertFn）は `(prepared, logger)` を受ける。logger は `HookCounter`
  （H1・H2 が止めた回数を数える。文面は持たない）。既定の変換は実物の
  `convert(prepared, runner=SdkRunner(), logger=..., settings=...)`（API を呼ぶ）
- 例外の扱い:
  - プログラムの誤り（TypeError・AttributeError・NameError・ImportError）は捕まえない。
    convert の呼び方や SdkRunner の作り方が契約とずれたまま 0% の結果を残さない
  - それ以外の例外は1コースのフォールバック（error_code="eval_exception"）にして
    評価を続ける。stderr には型名とコードだけを出す（本文には入力の文が混ざりうる）
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

from tsutae import config
from tsutae.dataset import to_courses, to_entries
from tsutae.eval.cache import EXCEPTION_ERROR_CODE, CoursePrediction
from tsutae.eval.cases import EvalCase
from tsutae.eval.hook_counts import HookCounter, HookCounts
from tsutae.schemas import ConversionResult, PreparedInput
from tsutae.skills import load_regimen_skill, load_report_skill

# prepare_input(*, courses, entries, regimen_skill, report_skill, visit_date)
PrepareFn = Callable[..., PreparedInput]
ConvertFn = Callable[[PreparedInput, HookCounter], ConversionResult]

PROGRAM_ERRORS: tuple[type[Exception], ...] = (
    TypeError,
    AttributeError,
    NameError,
    ImportError,
)


def default_prepare_fn() -> PrepareFn:
    from tsutae.pipeline.inputs import prepare_input

    return prepare_input


def default_convert_fn(settings: config.Settings) -> ConvertFn:
    """`convert(SdkRunner)` を1コースずつ同期で回す関数（Anthropic API を呼ぶ）。

    import は作る時に済ませる（pipeline が無ければ変換を始める前に ImportError）。
    SdkRunner は呼ぶたびにモジュールから引く（テストで差し替えられるように）。
    """
    from tsutae.pipeline import runner as runner_module
    from tsutae.pipeline.orchestrator import convert

    if not callable(runner_module.SdkRunner):  # 無ければここで AttributeError
        raise TypeError("tsutae.pipeline.runner.SdkRunner が呼べない")

    def _convert(prepared: PreparedInput, logger: HookCounter) -> ConversionResult:
        return asyncio.run(
            convert(
                prepared,
                runner=runner_module.SdkRunner(),
                logger=logger,
                settings=settings,
            )
        )

    return _convert


def _fallback() -> ConversionResult:
    return ConversionResult(
        timeline=None, picks=None, fallback=True, error_code=EXCEPTION_ERROR_CODE
    )


def safe_convert(
    convert_fn: ConvertFn, prepared: PreparedInput
) -> tuple[ConversionResult, HookCounts]:
    counter = HookCounter()
    try:
        result = convert_fn(prepared, counter)
    except PROGRAM_ERRORS:
        raise
    except Exception as exc:  # noqa: BLE001  1コースの失敗で評価全体を止めない
        print(
            f"  変換で例外 {type(exc).__name__} → error_code={EXCEPTION_ERROR_CODE}",
            file=sys.stderr,
        )
        result = _fallback()
    if not isinstance(result, ConversionResult):
        raise TypeError(f"変換関数の戻り値が ConversionResult でない: {type(result)}")
    return result, counter.counts()


def build_prepared(
    case: EvalCase, *, prepare_fn: PrepareFn, skills_dir: Path | None = None
) -> PreparedInput:
    """合成データから1コース分の入力を作る（API は呼ばない）。"""
    patient = case.patient
    return prepare_fn(
        courses=to_courses(patient),
        entries=to_entries(patient),
        regimen_skill=load_regimen_skill(patient.regimen, skills_dir),
        report_skill=load_report_skill(skills_dir=skills_dir),
        visit_date=case.visit_date,
    )


def predict_case(
    case: EvalCase,
    *,
    prepare_fn: PrepareFn,
    convert_fn: ConvertFn,
    model: str,
    subagent_model: str,
    skills_dir: Path | None = None,
) -> CoursePrediction:
    patient = case.patient
    prepared = build_prepared(case, prepare_fn=prepare_fn, skills_dir=skills_dir)
    got = prepared.input.schedule.course_no
    if got != case.course_no:
        raise ValueError(
            f"{patient.patient_id}: 第{case.course_no}コースのはずが第{got}コースの入力"
        )
    result, hooks = safe_convert(convert_fn, prepared)
    return CoursePrediction(
        patient_id=patient.patient_id,
        course_no=case.course_no,
        visit_date=case.visit_date,
        model=model,
        subagent_model=subagent_model,
        prepared=prepared,
        timeline=result.timeline,
        fallback=result.fallback,
        error_code=result.error_code,
        stats=result.stats,
        hooks=hooks,
    )
