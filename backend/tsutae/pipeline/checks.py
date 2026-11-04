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
  - 並び順は検査しない。受け付けた後に tools.RunCollector が (start_date, term) で
    並べ直す。「同じ日なら term 名順」は Python の文字列順（コードポイント順）で、
    日本語の用語名ではモデルが再現できず、順序違いの拒否は直しのターンを使うだけ。
    report.validate.verified_per_symptom も必ず並べ直す
  - term・question_key はその用語の出来事のもの
  - start_date・start_day はその用語の最初の出来事のもの
  - representative_quote・confidence は、その用語のどれか1つの出来事の source_quote・
    confidence そのまま（開始日の出来事でなくてよい）
- 理由は (項目の位置, 短い説明)。入力から写す項目・数えられる項目は、説明に期待される
  値（日付・Day・真偽値・番号・key・回答の値・confidence）を入れ、1回で直せるようにする。
  自由記載の文面（引用）と用語名は返さない
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

__all__ = [
    "OutputContext",
    "Problem",
    "report_problems",
    "sort_per_symptom",
    "timeline_problems",
]

Problem = tuple[str, str]  # (項目の位置, 理由)
UNKNOWN_ENTRY = "入力に無い entry_no"
DUPLICATE_EVENT = "同じ出来事が前にある（重ねて出さない）"
DUPLICATE_CONTRADICTION = "同じ食い違いが前にある（重ねて出さない）"
MISSING_ROW = "この出来事の term の行が無い"
FIRST_EVENT = "その term の present か improving の出来事で date が最も早いもの"


def _json(value: object) -> str:
    """期待される値の書き方（JSON と同じ: null・true・false・数値・ISO 日付・key）。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _expect(value: object) -> str:
    return f"{_json(value)} にする"


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

    def expected_day(self, d: date) -> int | None:
        """date ≦ last_day_date の範囲で course.day_of と同じ Day（Day1 より前は None）。"""
        if d < self.day1_date:
            return None
        return (d - self.day1_date).days + 1

    def day_ok(self, d: date, day: int | None) -> bool:
        """date ≦ last_day_date の範囲で course.day_of と同じ判定（範囲外は False）。"""
        if d > self.last_day_date:
            return False
        return day == self.expected_day(d)


def _day_reason(expected: int | None) -> str:
    shown = "Day1 より前なので null" if expected is None else f"Day{expected}"
    return (
        f"date の Day と違う（この date は {shown}。依頼文の日付と Day の対応表で引く）"
    )


# ---------------------------------------------------------------------------
# emit_timeline
# ---------------------------------------------------------------------------


def _term_problems(where: str, ev: TimelineEvent, ctx: OutputContext) -> list[Problem]:
    if ev.term not in ctx.term_keys:
        return [(f"{where}.term", "用語の一覧に無い（一覧の用語名をそのまま使う）")]
    expected = ctx.term_keys[ev.term]
    if ev.question_key != expected:
        return [
            (
                f"{where}.question_key",
                f"term に対応する質問の key と違う（{_expect(expected)}。"
                "今回の質問に無い key なら null）",
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
        found.append(
            (
                f"{where}.course_no",
                f"schedule.course_no と違う（{_expect(ctx.course_no)}）",
            )
        )
    if ev.by_proxy != entry.by_proxy:
        found.append(
            (
                f"{where}.by_proxy",
                f"その記録の by_proxy と違う（{_expect(entry.by_proxy)}）",
            )
        )
    if ev.date > entry.record_date:
        found.append(
            (
                f"{where}.date",
                f"その記録の record_date（{_json(entry.record_date)}）より後にしない",
            )
        )
    elif not ctx.day_ok(ev.date, ev.day):
        found.append((f"{where}.day", _day_reason(ctx.expected_day(ev.date))))
    recalled = ev.date < entry.record_date
    if ev.recalled != recalled:
        found.append(
            (
                f"{where}.recalled",
                f"date が record_date より前なら true、ほかは false（{_expect(recalled)}）",
            )
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
        found.append(
            (
                f"{where}.question_key",
                "その記録にこの質問の回答が無い（その記録の answers にある key だけ）",
            )
        )
    elif c.closed_answer != answers[c.question_key]:
        found.append(
            (
                f"{where}.closed_answer",
                f"その記録の回答と違う（{_expect(answers[c.question_key])}。"
                "クローズ回答は書き換えない）",
            )
        )
    if c.date != entry.record_date:
        found.append(
            (
                f"{where}.date",
                f"その記録の record_date と違う（{_expect(entry.record_date)}）",
            )
        )
    if c.day != entry.day:
        found.append((f"{where}.day", f"その記録の day と違う（{_expect(entry.day)}）"))
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
            (
                f"{where}.question_key",
                f"その term の出来事の question_key と違う（{_expect(first.question_key)}）",
            )
        )
    if s.start_date != first.date:
        found.append(
            (
                f"{where}.start_date",
                f"{FIRST_EVENT}の date と違う（{_expect(first.date)}）",
            )
        )
    elif s.start_day != first.day:
        found.append(
            (
                f"{where}.start_day",
                f"{FIRST_EVENT}の day と違う（{_expect(first.day)}）",
            )
        )
    found += _pick_problems(where, s, events)
    return found


def _pick_problems(
    where: str, s: SymptomSummary, events: list[TimelineEvent]
) -> list[Problem]:
    picked = [e for e in events if e.source_quote == s.representative_quote]
    if not picked:
        return [
            (
                f"{where}.representative_quote",
                "その term の present か improving の出来事の source_quote の"
                "どれとも一致しない（どれか1つの source_quote を丸ごとそのまま写す）",
            )
        ]
    if all(e.confidence != s.confidence for e in picked):
        shown = " か ".join(sorted({_json(e.confidence) for e in picked}))
        return [
            (
                f"{where}.confidence",
                f"代表引用に選んだ出来事の confidence と違う（{shown} にする）",
            )
        ]
    return []


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


def sort_per_symptom(per_symptom: Sequence[SymptomSummary]) -> list[SymptomSummary]:
    """開始日の早い順、同じなら term 名順（Python の文字列順）に並べた新しいリスト。"""
    return sorted(per_symptom, key=lambda s: (s.start_date, s.term))


def report_problems(
    per_symptom: Sequence[SymptomSummary], timeline: Timeline | None
) -> list[Problem]:
    if timeline is None:
        return [("(root)", "先に emit_timeline を受け付けさせてから呼ぶ")]
    by_term = _symptom_events(timeline)
    return _row_problems(per_symptom, by_term) + _missing_rows(per_symptom, by_term)
