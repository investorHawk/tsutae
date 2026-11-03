"""評価結果の型と合算（純関数）。症例は全て合成。

- `Ratio`: 分子・分母（率だけにしない。分母0の率は None）
- `FailureCase`: 失敗例（記録 seq・項目・期待・予測）
- `EvalResult`: 1患者・1コース（または合算）の5指標と参考の指標
- `aggregate`: 分子・分母を足して合算する（率の平均はとらない）
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import Field, model_validator

from tsutae.schemas import Frozen

MetricName = Literal[
    "match",
    "date",
    "term",
    "contradiction_missed",
    "contradiction_spurious",
    "mild_as_absent",
    "mild_missed",
    "negation_as_present",
    "quote",
    "contradiction_quote",
]
RATIO_FIELDS: tuple[str, ...] = (
    "matched",
    "date",
    "date_paired",
    "term",
    "contradiction_recall",
    "contradiction_precision",
    "mild_as_absent",
    "mild_missed",
    "negation_as_present",
    "quote",
    "contradiction_quote",
)
COUNT_FIELDS: tuple[str, ...] = (
    "entries_evaluated",
    "label_events",
    "held_out_entries",
    "held_out_label_events",
    "leaked_unprocessed",
)


class Ratio(Frozen):
    numerator: int = Field(default=0, ge=0)
    denominator: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _not_above(self) -> Ratio:
        if self.numerator > self.denominator:
            raise ValueError("分子が分母を超えている")
        return self

    @property
    def rate(self) -> float | None:
        """分母が0なら None（0% とも 100% とも言わない）。"""
        return self.numerator / self.denominator if self.denominator else None

    def __add__(self, other: Ratio) -> Ratio:
        return Ratio(
            numerator=self.numerator + other.numerator,
            denominator=self.denominator + other.denominator,
        )


def ratio(numerator: int, denominator: int) -> Ratio:
    return Ratio(numerator=numerator, denominator=denominator)


class FailureCase(Frozen):
    """失敗例（記録 seq・項目・期待・予測）。文は伏せ字後の引用だけを入れる。"""

    patient_id: str | None = None
    course_no: int | None = None
    entry_seq: int | None  # 入力に無い entry_no を予測が指したときは None
    metric: MetricName
    item: str
    expected: str
    predicted: str


class EvalResult(Frozen):
    """件数の意味:

    - entries_evaluated: 数えた記録（入力に入った記録。expect_unprocessed を除く）
    - label_events: 分母にした正解ラベルの出来事
    - held_out_entries: 二次検出で送信対象外にした記録（`prepared.unprocessed`）
    - held_out_label_events: そのうち expect_unprocessed でない記録の出来事
      （検出しすぎで外れ、分母に入らなかった正解ラベル）
    - leaked_unprocessed: expect_unprocessed のラベルなのに入力に入った記録
      （二次検出の漏れ。指標には数えない。0 が正常）
    """

    patient_id: str | None = None
    course_no: int | None = None
    entries_evaluated: int = 0
    label_events: int = 0
    held_out_entries: int = 0
    held_out_label_events: int = 0
    leaked_unprocessed: int = 0
    matched: Ratio = Field(default_factory=Ratio)
    date: Ratio = Field(default_factory=Ratio)
    date_paired: Ratio = Field(default_factory=Ratio)
    term: Ratio = Field(default_factory=Ratio)
    contradiction_recall: Ratio = Field(default_factory=Ratio)
    contradiction_precision: Ratio = Field(default_factory=Ratio)
    mild_as_absent: Ratio = Field(default_factory=Ratio)
    mild_missed: Ratio = Field(default_factory=Ratio)
    negation_as_present: Ratio = Field(default_factory=Ratio)
    quote: Ratio = Field(default_factory=Ratio)
    contradiction_quote: Ratio = Field(default_factory=Ratio)
    failures: list[FailureCase] = Field(default_factory=list)


def _common[T](values: Iterable[T | None]) -> T | None:
    unique = set(values)
    return unique.pop() if len(unique) == 1 else None


def aggregate(results: Sequence[EvalResult]) -> EvalResult:
    """複数コース・複数患者を合算する（分子・分母を足す。率の平均はとらない）。

    patient_id は全件で同じときだけ残す（違えば None）。course_no は患者が1人で、
    コースも全件で同じときだけ残す。
    """
    patient_id = _common(r.patient_id for r in results)
    course_no = (
        _common(r.course_no for r in results) if patient_id is not None else None
    )
    ratios = {
        name: sum((getattr(r, name) for r in results), Ratio()) for name in RATIO_FIELDS
    }
    counts = {name: sum(getattr(r, name) for r in results) for name in COUNT_FIELDS}
    return EvalResult(
        patient_id=patient_id,
        course_no=course_no,
        failures=[f for r in results for f in r.failures],
        **ratios,
        **counts,
    )
