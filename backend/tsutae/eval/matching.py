"""ラベルの出来事と予測の出来事を、同じ記録の中で1対1に対応づける（純関数）。

- まず同じ term どうしを対応づけ、残ったラベルだけ同じ question_key（ラベル側が
  None なら対応づけない）の予測に対応づける
- 1つの予測は1つのラベルにしか使わない。同じ用語が1記録に2回ある（回想と当日）
  ときは、日付の近い組から先に決める（貪欲法）。日付と Day が同じなら status の
  同じ組を先にする
- 同点はラベルの中身（term・引用）で決め、ラベルの並び順に左右されないようにする
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from tsutae.schemas import LabelEvent, TimelineEvent

Same = Callable[[LabelEvent, TimelineEvent], bool]
Cost = tuple[int, int, int]


def _cost(label: LabelEvent, pred: TimelineEvent) -> Cost:
    return (
        abs((pred.date - label.date).days),
        int(pred.day != label.day),
        int(pred.status != label.status),
    )


def _same_term(label: LabelEvent, pred: TimelineEvent) -> bool:
    return label.term == pred.term


def _same_question_key(label: LabelEvent, pred: TimelineEvent) -> bool:
    return label.question_key is not None and label.question_key == pred.question_key


def _assign(
    labels: Sequence[LabelEvent],
    preds: Sequence[TimelineEvent],
    fixed: Mapping[int, int],
    same: Same,
) -> dict[int, int]:
    used = set(fixed.values())
    candidates = sorted(
        (_cost(label, pred), label.term, label.source_quote, li, pi)
        for li, label in enumerate(labels)
        if li not in fixed
        for pi, pred in enumerate(preds)
        if pi not in used and same(label, pred)
    )
    result = dict(fixed)
    for *_, li, pi in candidates:
        if li in result or pi in used:
            continue
        result[li] = pi
        used.add(pi)
    return result


def match_events(
    labels: Sequence[LabelEvent], preds: Sequence[TimelineEvent]
) -> dict[int, int]:
    """ラベルの添字 → 予測の添字。対応のないラベルは含めない。"""
    by_term = _assign(labels, preds, {}, _same_term)
    return _assign(labels, preds, by_term, _same_question_key)
