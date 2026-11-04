"""出来事の指標（1 日付・2 用語・4 改善中と否定）。純関数。症例は全て合成。

- 1 日付（date）: ラベルの出来事ごとに、対応づけた予測の date と day が両方一致した
  割合（分母はラベルの出来事。対応づけできない出来事は不一致）。参考に、対応づけ
  できた出来事だけを分母にした率（date_paired）も出す
- 2 用語（term）: ラベルの出来事のうち、同じ記録に同じ term の予測がある割合
- 4 改善中（status が improving の出来事。出来事ごと）を absent と誤った件数
  （mild_as_absent）・対応する予測が無い件数（mild_missed）。「軽い」の印は正解
  ラベルに無い（mild_improving は記録のタグ）ので、present の出来事は数えない
- 4 否定（status が absent）を present / improving とした件数（negation_as_present）。
  対応づけた予測に加え、同じ記録で他のラベルに対応づかなかった同じ用語の予測
  （同じ用語の予測が1件も無ければ同じ question_key の予測）も見る
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as Date

from tsutae.eval.matching import match_events
from tsutae.eval.results import FailureCase, MetricName, Ratio, ratio
from tsutae.schemas import EntryLabel, LabelEvent, TimelineEvent

NO_PREDICTION = "予測なし"


@dataclass(frozen=True)
class Outcome:
    seq: int
    label: LabelEvent
    pred: TimelineEvent | None
    term_hit: bool
    negation_offenders: tuple[TimelineEvent, ...]  # 否定を症状ありとした予測
    others: tuple[str, ...]  # 同じ記録の予測の用語（失敗例の説明用）

    @property
    def mild_target(self) -> bool:
        return self.label.status == "improving"

    @property
    def negation_target(self) -> bool:
        return self.label.status == "absent"


def _negation_offenders(
    label: LabelEvent,
    pred: TimelineEvent | None,
    preds: Sequence[TimelineEvent],
    assigned: set[int],
) -> tuple[TimelineEvent, ...]:
    if label.status != "absent":
        return ()
    free = [p for i, p in enumerate(preds) if i not in assigned]
    related = [p for p in free if p.term == label.term]
    if label.question_key is not None and not any(p.term == label.term for p in preds):
        related += [p for p in free if p.question_key == label.question_key]
    candidates = ([pred] if pred is not None else []) + related
    return tuple(p for p in candidates if p.status != "absent")


def entry_outcomes(
    seq: int, label: EntryLabel, preds: Sequence[TimelineEvent]
) -> list[Outcome]:
    pairs = match_events(label.events, preds)
    assigned = set(pairs.values())
    terms = {p.term for p in preds}
    others = tuple(dict.fromkeys(p.term for p in preds))
    outcomes = []
    for i, event in enumerate(label.events):
        pred = preds[pairs[i]] if i in pairs else None
        outcomes.append(
            Outcome(
                seq=seq,
                label=event,
                pred=pred,
                term_hit=event.term in terms,
                negation_offenders=_negation_offenders(event, pred, preds, assigned),
                others=others,
            )
        )
    return outcomes


def _same_when(o: Outcome) -> bool:
    return o.pred is not None and (o.pred.date, o.pred.day) == (
        o.label.date,
        o.label.day,
    )


def event_ratios(outcomes: Sequence[Outcome]) -> dict[str, Ratio]:
    paired = [o for o in outcomes if o.pred is not None]
    mild = [o for o in outcomes if o.mild_target]
    negation = [o for o in outcomes if o.negation_target]
    same_when = sum(_same_when(o) for o in paired)
    return {
        "matched": ratio(len(paired), len(outcomes)),
        "date": ratio(same_when, len(outcomes)),
        "date_paired": ratio(same_when, len(paired)),
        "term": ratio(sum(o.term_hit for o in outcomes), len(outcomes)),
        "mild_as_absent": ratio(
            sum(o.pred is not None and o.pred.status == "absent" for o in mild),
            len(mild),
        ),
        "mild_missed": ratio(sum(o.pred is None for o in mild), len(mild)),
        "negation_as_present": ratio(
            sum(bool(o.negation_offenders) for o in negation), len(negation)
        ),
    }


# ---------------------------------------------------------------------------
# 失敗例
# ---------------------------------------------------------------------------


def _when(d: Date, day: int | None) -> str:
    return (
        f"{d.isoformat()} Day{day}" if day is not None else f"{d.isoformat()} Dayなし"
    )


def _item(event: LabelEvent) -> str:
    return f"{event.term}（{event.question_key}）" if event.question_key else event.term


def _term_predicted(o: Outcome) -> str:
    if o.pred is not None:
        return f"{o.pred.term}（question_key で対応）"
    if o.others:
        return f"{NO_PREDICTION}（同じ記録の予測: {'、'.join(o.others)}）"
    return NO_PREDICTION


def _offenders_text(o: Outcome) -> str:
    return "、".join(
        p.status if p is o.pred else f"{p.status}（対応づけ外の予測 {p.term}）"
        for p in o.negation_offenders
    )


def _event_failures(o: Outcome) -> list[tuple[MetricName, str, str]]:
    found: list[tuple[MetricName, str, str]] = []
    when = _when(o.label.date, o.label.day)
    if not o.term_hit:
        found.append(("term", o.label.term, _term_predicted(o)))
    if o.pred is None and o.term_hit:
        found.append(
            ("match", when, "対応なし（同じ用語の予測は別の出来事に対応済み）")
        )
    if o.pred is not None and not _same_when(o):
        found.append(("date", when, _when(o.pred.date, o.pred.day)))
    if o.mild_target and o.pred is None:
        found.append(("mild_missed", o.label.status, NO_PREDICTION))
    if o.mild_target and o.pred is not None and o.pred.status == "absent":
        found.append(("mild_as_absent", o.label.status, "absent"))
    if o.negation_offenders:
        found.append(("negation_as_present", "absent", _offenders_text(o)))
    return found


def outcome_failures(outcomes: Sequence[Outcome]) -> list[FailureCase]:
    return [
        FailureCase(
            entry_seq=o.seq,
            metric=metric,
            item=_item(o.label),
            expected=expected,
            predicted=predicted,
        )
        for o in outcomes
        for metric, expected, predicted in _event_failures(o)
    ]
