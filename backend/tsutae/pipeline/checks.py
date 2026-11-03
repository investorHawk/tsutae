"""emit_timeline / emit_report の中身を、入力（PreparedInput）と用語の一覧に照らす検査。

H2 は引用の一致だけを見る。ここでは「入力から写すだけの項目」と「一覧から選ぶ項目」を
機械で検査する（spec 12.1 重さを判定しない・12.5 食い違いを解決しない・12.7 助言しない、
architecture §7 / §7b の「Grade・重症などの語を出さない」をプロンプトだけに任せない）:

- events
  - term は CTCAE 用語の一覧（ctcae_terms.json。term-mapper に渡すものと同じ）の名前そのもの
  - question_key はその用語に対応する質問の key（今回の質問に無ければ null）
  - course_no は schedule.course_no、by_proxy はその記録のもの
  - date はその記録の record_date 以前（report は記録日より後の出来事を使わない。§7 W2b）
  - day は `course.day_of(date, schedule, courses=…)` と同じ値。受け付ける date は
    record_date ≦ min(最終日, visit_date) 以前なので、次コースが登録済みでもその実投与日
    より前になり、day_of の答えは「day1_date より前は null、ほかは day1_date から数えた
    Day」に一意に決まる（courses を持たずに同じ判定ができる）
  - recalled は date が record_date より前かどうか
  - 同じ (entry_no, term, date, status, source_quote) の出来事を重ねない
- contradictions: その記録に question_key の回答があり、closed_answer がその値、
  date・day がその記録の record_date・day（クローズ回答を書き換えさせない）。同じ
  (entry_no, question_key, free_text_quote) を重ねない（report の重複の鍵と同じ）
- per_symptom（report-format の Skill「症状別の時系列」§4）: 受け付けた timeline の、
  status が present か improving の出来事に結び付ける
  - その term ごとに行がちょうど1つ（欠け・余分・重複は拒否。空は出来事が無い時だけ）
  - 開始 Day の早い順、同じなら term 名順（Day1 前の回想は start_day が null になる
    ので、start_date で比べる。Day の順と同じ）
  - term・question_key はその用語の出来事のもの
  - start_date・start_day はその用語の最初の出来事のもの
  - representative_quote・confidence は、その用語のどれか1つの出来事の source_quote・
    confidence そのまま（開始日の出来事でなくてよい）
- 理由は (項目の位置, 決まった短い説明)。入力の文面は返さない（用語名も返さない）
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any

from tsutae.schemas import (
    Contradiction,
    MaskedEntry,
    PreparedInput,
    SymptomSummary,
    Timeline,
    TimelineEvent,
)
from tsutae.synthetic import load_terms, term_question_keys

__all__ = ["OutputContext", "Problem", "report_problems", "timeline_problems"]

Problem = tuple[str, str]  # (項目の位置, 理由)
UNKNOWN_ENTRY = "入力に無い entry_no"
DUPLICATE_EVENT = "同じ出来事が前にある（重ねて出さない）"
DUPLICATE_CONTRADICTION = "同じ食い違いが前にある（重ねて出さない）"
MISSING_ROW = "この出来事の term の行が無い"
WRONG_ORDER = "開始 Day の早い順（同じ日なら term 名順）に並べる"


@dataclass(frozen=True)
class OutputContext:
    """検査に使う入力側の事実（PreparedInput と用語の一覧から作る。読み取り専用）。"""

    course_no: int
    day1_date: date
    last_day_date: date
    entries: Mapping[int, MaskedEntry]  # entry_no -> 送った記録
    term_keys: Mapping[str, str | None]  # 用語名 -> 今回の質問の key（無ければ None）

    @classmethod
    def from_prepared(
        cls,
        prepared: PreparedInput,
        terms: Iterable[Mapping[str, Any]] | None = None,
    ) -> OutputContext:
        asked = {q.key for q in prepared.input.questions}
        mapping = term_question_keys(load_terms() if terms is None else terms)
        schedule = prepared.input.schedule
        return cls(
            course_no=schedule.course_no,
            day1_date=schedule.day1_date,
            last_day_date=schedule.last_day_date,
            entries=MappingProxyType({e.entry_no: e for e in prepared.input.entries}),
            term_keys=MappingProxyType(
                {t: (k if k in asked else None) for t, k in mapping.items()}
            ),
        )

    @property
    def entry_nos(self) -> frozenset[int]:
        return frozenset(self.entries)

    def day_ok(self, d: date, day: int | None) -> bool:
        """date ≦ last_day_date の範囲で course.day_of と同じ判定（範囲外は False）。"""
        if d < self.day1_date:
            return day is None
        if d > self.last_day_date:
            return False
        return day == (d - self.day1_date).days + 1


# ---------------------------------------------------------------------------
# emit_timeline
# ---------------------------------------------------------------------------


def _term_problems(where: str, ev: TimelineEvent, ctx: OutputContext) -> list[Problem]:
    if ev.term not in ctx.term_keys:
        return [(f"{where}.term", "用語の一覧に無い（一覧の用語名をそのまま使う）")]
    if ev.question_key != ctx.term_keys[ev.term]:
        return [
            (
                f"{where}.question_key",
                "term に対応する質問の key と違う（今回の質問に無い key なら null）",
            )
        ]
    return []


def _event_problems(i: int, ev: TimelineEvent, ctx: OutputContext) -> list[Problem]:
    where = f"events.{i}"
    entry = ctx.entries.get(ev.entry_no)
    if entry is None:
        return [(f"{where}.entry_no", UNKNOWN_ENTRY)]
    found = _term_problems(where, ev, ctx)
    if ev.course_no != ctx.course_no:
        found.append((f"{where}.course_no", "schedule.course_no と違う"))
    if ev.by_proxy != entry.by_proxy:
        found.append((f"{where}.by_proxy", "その記録の by_proxy と違う"))
    if ev.date > entry.record_date:
        found.append((f"{where}.date", "その記録の record_date より後にしない"))
    elif not ctx.day_ok(ev.date, ev.day):
        found.append(
            (
                f"{where}.day",
                "date から数えた Day と違う（day1_date が Day1、前は null）",
            )
        )
    if ev.recalled != (ev.date < entry.record_date):
        found.append(
            (f"{where}.recalled", "date が record_date より前なら true、ほかは false")
        )
    return found


def _contradiction_problems(
    i: int, c: Contradiction, ctx: OutputContext
) -> list[Problem]:
    where = f"contradictions.{i}"
    entry = ctx.entries.get(c.entry_no)
    if entry is None:
        return [(f"{where}.entry_no", UNKNOWN_ENTRY)]
    answers = {a.question_key: a.value for a in entry.answers}
    found: list[Problem] = []
    if c.question_key not in answers:
        found.append((f"{where}.question_key", "その記録にこの質問の回答が無い"))
    elif c.closed_answer != answers[c.question_key]:
        found.append(
            (
                f"{where}.closed_answer",
                "その記録の回答と違う（クローズ回答は書き換えない）",
            )
        )
    if c.date != entry.record_date:
        found.append((f"{where}.date", "その記録の record_date と違う"))
    if c.day != entry.day:
        found.append((f"{where}.day", "その記録の day と違う"))
    return found


def _event_key(ev: TimelineEvent) -> tuple[object, ...]:
    return (ev.entry_no, ev.term, ev.date, ev.status, ev.source_quote)


def _contradiction_key(c: Contradiction) -> tuple[object, ...]:
    return (c.entry_no, c.question_key, c.free_text_quote)


def _duplicates(prefix: str, keys: Iterable[object], why: str) -> list[Problem]:
    seen: set[object] = set()
    found: list[Problem] = []
    for i, key in enumerate(keys):
        if key in seen:
            found.append((f"{prefix}.{i}", why))
        seen.add(key)
    return found


def timeline_problems(
    events: Sequence[TimelineEvent],
    contradictions: Sequence[Contradiction],
    ctx: OutputContext,
) -> list[Problem]:
    found: list[Problem] = []
    for i, ev in enumerate(events):
        found += _event_problems(i, ev, ctx)
    for i, c in enumerate(contradictions):
        found += _contradiction_problems(i, c, ctx)
    found += _duplicates("events", map(_event_key, events), DUPLICATE_EVENT)
    found += _duplicates(
        "contradictions",
        map(_contradiction_key, contradictions),
        DUPLICATE_CONTRADICTION,
    )
    return found


# ---------------------------------------------------------------------------
# emit_report
# ---------------------------------------------------------------------------


def _summary_problems(
    where: str, s: SymptomSummary, events: list[TimelineEvent]
) -> list[Problem]:
    first = min(events, key=lambda e: e.date)
    found: list[Problem] = []
    if s.question_key != first.question_key:
        found.append(
            (f"{where}.question_key", "その term の出来事の question_key と違う")
        )
    if s.start_date != first.date:
        found.append((f"{where}.start_date", "その term の最初の出来事の date と違う"))
    elif s.start_day != first.day:
        found.append((f"{where}.start_day", "その term の最初の出来事の day と違う"))
    picked = [e for e in events if e.source_quote == s.representative_quote]
    if not picked:
        found.append(
            (
                f"{where}.representative_quote",
                "その term の出来事の source_quote のどれとも一致しない",
            )
        )
    elif all(e.confidence != s.confidence for e in picked):
        found.append(
            (f"{where}.confidence", "代表引用に選んだ出来事の confidence と違う")
        )
    return found


def _symptom_events(timeline: Timeline) -> dict[str, list[tuple[int, TimelineEvent]]]:
    """term -> その term の present / improving の出来事（events の位置つき）。"""
    by_term: dict[str, list[tuple[int, TimelineEvent]]] = {}
    for i, ev in enumerate(timeline.events):
        if ev.status != "absent":
            by_term.setdefault(ev.term, []).append((i, ev))
    return by_term


def _row_problems(
    per_symptom: Sequence[SymptomSummary],
    by_term: Mapping[str, list[tuple[int, TimelineEvent]]],
) -> list[Problem]:
    found: list[Problem] = []
    seen: set[str] = set()
    for i, s in enumerate(per_symptom):
        where = f"per_symptom.{i}"
        if s.term not in by_term:
            found.append(
                (
                    f"{where}.term",
                    "受け付けた events に present か improving で無い term",
                )
            )
        elif s.term in seen:
            found.append((f"{where}.term", "同じ term は1行だけ"))
        else:
            found += _summary_problems(where, s, [ev for _, ev in by_term[s.term]])
        seen.add(s.term)
    return found


def _missing_rows(
    per_symptom: Sequence[SymptomSummary],
    by_term: Mapping[str, list[tuple[int, TimelineEvent]]],
) -> list[Problem]:
    listed = {s.term for s in per_symptom}
    firsts = sorted(items[0][0] for t, items in by_term.items() if t not in listed)
    return [(f"events.{i}.term", MISSING_ROW) for i in firsts]


def _order_problems(per_symptom: Sequence[SymptomSummary]) -> list[Problem]:
    keys = [(s.start_date, s.term) for s in per_symptom]
    for i in range(1, len(keys)):
        if keys[i] < keys[i - 1]:
            return [(f"per_symptom.{i}", WRONG_ORDER)]
    return []


def report_problems(
    per_symptom: Sequence[SymptomSummary], timeline: Timeline | None
) -> list[Problem]:
    if timeline is None:
        return [("(root)", "先に emit_timeline を受け付けさせてから呼ぶ")]
    by_term = _symptom_events(timeline)
    found = _row_problems(per_symptom, by_term) + _missing_rows(per_symptom, by_term)
    return found or _order_problems(per_symptom)
