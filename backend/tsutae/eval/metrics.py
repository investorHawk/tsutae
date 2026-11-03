"""精度評価の5指標（spec 17.2、architecture §7c）。純関数。症例は全て合成。

合格ラインは置かない。指標ごとに分子・分母を持ち、失敗例を一覧にする。

対象の記録:
- 今回の入力に入った記録（`prepared.entry_ids`。合成データでは entries.id = seq）
- ただし正解ラベルが `expect_unprocessed` の記録は、ラベルも予測も数えない
  （入力に入っていれば二次検出の漏れとして leaked_unprocessed に数える）
- 入力に入っていない記録のラベルは数えない。二次検出で外した記録
  （`prepared.unprocessed`）の件数と、そこで外れた正解ラベルの出来事の数は残す
- ラベルの無い入力の記録（回答だけ等）は「出来事も食い違いも無い」記録として
  予測を数える

指標:
1・2・4 は `event_metrics`（日付・用語・改善中と否定）
3. 食い違い: (記録, question_key) で対応。再現率（ラベル基準）・適合率（予測基準）
5. 引用（quote）: 出来事の source_quote のうち、その entry_no の伏せ字後の文に部分
   一致する割合（未知の entry_no は不一致）。食い違いの free_text_quote は spec の
   指標5の対象外なので、参考（contradiction_quote）として別に数える
   本番の変換では H2 が同じ条件で emit_timeline を拒否するので、最終の Timeline の
   一致率は構造上 100% になる（幻覚引用の量は H2 の拒否回数で見る。`eval.hook_counts`）
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from tsutae.eval.event_metrics import (
    Outcome,
    entry_outcomes,
    event_ratios,
    outcome_failures,
)
from tsutae.eval.results import (
    COUNT_FIELDS,
    RATIO_FIELDS,
    EvalResult,
    FailureCase,
    MetricName,
    Ratio,
    aggregate,
)
from tsutae.eval.results import ratio as _ratio
from tsutae.schemas import (
    Contradiction,
    EntryLabel,
    PreparedInput,
    Timeline,
    TimelineEvent,
)

__all__ = [
    "COUNT_FIELDS",
    "RATIO_FIELDS",
    "EvalResult",
    "FailureCase",
    "MetricName",
    "Ratio",
    "aggregate",
    "evaluate",
]


# ---------------------------------------------------------------------------
# 対象の記録
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Scope:
    seq_of: Mapping[int, int]  # entry_no -> seq（対象の記録だけ）
    labels: Mapping[int, EntryLabel]  # seq -> ラベル（対象の記録だけ）
    excluded_nos: frozenset[int]  # expect_unprocessed の記録の entry_no
    held_out_entries: int  # prepared.unprocessed の記録数
    held_out_label_events: int  # そこで外れた（expect_unprocessed でない）出来事


def _labels_by_seq(labels: Sequence[EntryLabel]) -> dict[int, EntryLabel]:
    by_seq: dict[int, EntryLabel] = {}
    for label in labels:
        if label.entry_seq in by_seq:
            raise ValueError(f"記録 seq={label.entry_seq} のラベルが重複している")
        by_seq[label.entry_seq] = label
    return by_seq


def _held_out_events(
    prepared: PreparedInput, by_seq: Mapping[int, EntryLabel]
) -> tuple[int, int]:
    held = {u.entry_id for u in prepared.unprocessed}
    events = sum(
        len(by_seq[seq].events)
        for seq in held
        if seq in by_seq and not by_seq[seq].expect_unprocessed
    )
    return len(held), events


def _scope(prepared: PreparedInput, labels: Sequence[EntryLabel]) -> _Scope:
    ids = dict(prepared.entry_ids)
    if len(set(ids.values())) != len(ids):
        raise ValueError("entry_ids に同じ記録が2回入っている")
    by_seq = _labels_by_seq(labels)
    excluded = frozenset(
        no
        for no, seq in ids.items()
        if seq in by_seq and by_seq[seq].expect_unprocessed
    )
    seq_of = {no: seq for no, seq in ids.items() if no not in excluded}
    in_scope = {seq: by_seq[seq] for seq in seq_of.values() if seq in by_seq}
    held_entries, held_events = _held_out_events(prepared, by_seq)
    return _Scope(
        seq_of=seq_of,
        labels=in_scope,
        excluded_nos=excluded,
        held_out_entries=held_entries,
        held_out_label_events=held_events,
    )


def _group_events(
    events: Iterable[TimelineEvent], scope: _Scope
) -> dict[int, list[TimelineEvent]]:
    grouped: dict[int, list[TimelineEvent]] = {}
    for event in events:
        seq = scope.seq_of.get(event.entry_no)
        if seq is not None:
            grouped.setdefault(seq, []).append(event)
    return grouped


def _outcomes(scope: _Scope, timeline: Timeline) -> list[Outcome]:
    grouped = _group_events(timeline.events, scope)
    return [
        outcome
        for seq in sorted(scope.labels)
        for outcome in entry_outcomes(seq, scope.labels[seq], grouped.get(seq, []))
    ]


# ---------------------------------------------------------------------------
# 食い違い（指標 3）
# ---------------------------------------------------------------------------


def _label_contradiction_keys(scope: _Scope) -> dict[tuple[int, str], str]:
    """(seq, question_key) → クローズ回答。"""
    return {
        (seq, c.question_key): c.closed_answer
        for seq, label in scope.labels.items()
        for c in label.contradictions
    }


def _predicted_contradictions(
    timeline: Timeline, scope: _Scope
) -> dict[tuple[int, str], Contradiction]:
    """(entry_no, question_key) → 予測（重複は最初の1件）。対象外の記録は除く。"""
    found: dict[tuple[int, str], Contradiction] = {}
    for c in timeline.contradictions:
        if c.entry_no not in scope.excluded_nos:
            found.setdefault((c.entry_no, c.question_key), c)
    return found


def _unknown_item(entry_no: int, detail: str) -> str:
    return f"entry_no={entry_no}（入力に無い記録）: {detail}"


def _contradiction_scores(
    timeline: Timeline, scope: _Scope
) -> tuple[dict[str, Ratio], list[FailureCase]]:
    expected = _label_contradiction_keys(scope)
    predicted = _predicted_contradictions(timeline, scope)
    hits = {
        (scope.seq_of[no], qk)
        for no, qk in predicted
        if no in scope.seq_of and (scope.seq_of[no], qk) in expected
    }
    failures = [
        FailureCase(
            entry_seq=seq,
            metric="contradiction_missed",
            item=qk,
            expected=f"食い違い（クローズ {value}）",
            predicted="検出なし",
        )
        for (seq, qk), value in sorted(expected.items())
        if (seq, qk) not in hits
    ]
    for (no, qk), c in sorted(predicted.items()):
        seq = scope.seq_of.get(no)
        if seq is not None and (seq, qk) in hits:
            continue
        failures.append(
            FailureCase(
                entry_seq=seq,
                metric="contradiction_spurious",
                item=qk if seq is not None else _unknown_item(no, qk),
                expected="食い違いなし",
                predicted=f"食い違い（クローズ {c.closed_answer}）",
            )
        )
    ratios = {
        "contradiction_recall": _ratio(len(hits), len(expected)),
        "contradiction_precision": _ratio(len(hits), len(predicted)),
    }
    return ratios, failures


# ---------------------------------------------------------------------------
# 引用（指標 5 と参考）
# ---------------------------------------------------------------------------

Quote = tuple[int, str, str]  # (entry_no, 項目, 引用)


def _quote_scores(
    quotes: Sequence[Quote],
    metric: MetricName,
    prepared: PreparedInput,
    scope: _Scope,
) -> tuple[Ratio, list[FailureCase]]:
    targets = [q for q in quotes if q[0] not in scope.excluded_nos]
    failures: list[FailureCase] = []
    for no, item, quote in targets:
        seq = scope.seq_of.get(no)
        if seq is not None and quote in prepared.masked_texts.get(no, ""):
            continue
        failures.append(
            FailureCase(
                entry_seq=seq,
                metric=metric,
                item=item if seq is not None else _unknown_item(no, item),
                expected="伏せ字後の記載に部分一致",
                predicted=quote,
            )
        )
    return _ratio(len(targets) - len(failures), len(targets)), failures


def _all_quote_scores(
    timeline: Timeline, prepared: PreparedInput, scope: _Scope
) -> tuple[dict[str, Ratio], list[FailureCase]]:
    events = [(e.entry_no, e.term, e.source_quote) for e in timeline.events]
    contradictions = [
        (c.entry_no, f"食い違い {c.question_key}", c.free_text_quote)
        for c in timeline.contradictions
    ]
    quote, quote_failures = _quote_scores(events, "quote", prepared, scope)
    con, con_failures = _quote_scores(
        contradictions, "contradiction_quote", prepared, scope
    )
    return {"quote": quote, "contradiction_quote": con}, quote_failures + con_failures


# ---------------------------------------------------------------------------
# 公開関数
# ---------------------------------------------------------------------------


def evaluate(
    predicted: Timeline,
    prepared: PreparedInput,
    labels: Sequence[EntryLabel],
    *,
    patient_id: str | None = None,
) -> EvalResult:
    """1回の変換（1患者・1コース）を正解ラベルと比べる。引数は書き換えない。"""
    scope = _scope(prepared, labels)
    outcomes = _outcomes(scope, predicted)
    contradiction_ratios, contradiction_failures = _contradiction_scores(
        predicted, scope
    )
    quote_ratios, quote_failures = _all_quote_scores(predicted, prepared, scope)
    course_no = prepared.input.schedule.course_no
    failures = [
        f.model_copy(update={"patient_id": patient_id, "course_no": course_no})
        for f in outcome_failures(outcomes) + contradiction_failures + quote_failures
    ]
    return EvalResult(
        patient_id=patient_id,
        course_no=course_no,
        entries_evaluated=len(scope.seq_of),
        label_events=len(outcomes),
        held_out_entries=scope.held_out_entries,
        held_out_label_events=scope.held_out_label_events,
        leaked_unprocessed=len(scope.excluded_nos),
        failures=failures,
        **event_ratios(outcomes),
        **contradiction_ratios,
        **quote_ratios,
    )
