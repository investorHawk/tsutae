"""AI の出力の照合。docs/architecture.md §7b、docs/spec.md 10・12節。

入口の検査（入力どうしの対応）は gate.py。ここは AI の出力を記録と突き合わせる。

- 出来事（usable_events）: その entry_no の記録日より後の日付、用語と question_key の
  対応（ctcae_terms.json ＋ その記録の版の term_keys。その版の質問に無い key は null。
  checks.OutputContext と同じ。v1.1。spec 9.1）に合わないもの、引用が伏せ字後の文に
  無いものを落とす。
  「回」（recalled）は AI の値ではなく「出来事の日付が記録日より前」で決め直す
- 食い違い（verified_contradictions）: entry_no の記録の実際のクローズ回答と照合する。
  記録日・質問・回答・引用のどれかが合わないものは載せない。表示する回答は記録の値、
  Day は AI の day ではなく記録日から数える（今コース外なら載せない）
- 症状別の時系列（verified_per_symptom）: AI が選ぶのは「どの用語を、どの出来事の
  引用で載せるか」だけ。用語名は ctcae_terms.json の一覧に限り、重さの判定語を
  含むものも落とす。開始日は present/improving の最初の日、Day は開始日から数え直し、
  確からしさは代表引用に選んだ出来事の値（同じ引用が複数あれば低い方）
- 出来事・引用は H2 と同じ照合（その記録の伏せ字後の文に部分一致）をもう一度掛ける
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from functools import lru_cache
from types import MappingProxyType

from tsutae import course as course_mod
from tsutae.report.labels import has_severity_word
from tsutae.schemas import (
    AttentionItem,
    ClosedAnswer,
    Contradiction,
    Course,
    CourseSchedule,
    Entry,
    PreparedInput,
    ReportPicks,
    SymptomSummary,
    Timeline,
    TimelineEvent,
)
from tsutae.skills.term_keys import entry_term_keys
from tsutae.synthetic import load_terms

_MARKED_STATUSES = frozenset({"present", "improving"})


@lru_cache(maxsize=1)
def ctcae_term_keys() -> Mapping[str, str | None]:
    """紙に載せてよい用語名 → 対応するクローズ質問（ctcae_terms.json）。

    重さの判定語を含む語は除く。question_key が null の用語は経過表に ○ を付けない。
    """
    return MappingProxyType(
        {
            item["term"]: item.get("question_key")
            for item in load_terms()
            if not has_severity_word(item["term"])
        }
    )


def ctcae_terms() -> frozenset[str]:
    """紙に載せてよい用語名（ctcae_terms.json）。"""
    return frozenset(ctcae_term_keys())


# ---------------------------------------------------------------------------
# AI の出力の照合
# ---------------------------------------------------------------------------


def quote_matches(prepared: PreparedInput, entry_no: int, quote: str) -> bool:
    """引用がその記録の伏せ字後の自由記載に部分一致するか（H2 と同じ照合）。"""
    text = prepared.masked_texts.get(entry_no)
    return bool(text) and bool(quote) and quote in text


def _source_entry(
    entry_no: int, prepared: PreparedInput, by_id: Mapping[int, Entry]
) -> Entry | None:
    entry_id = prepared.entry_ids.get(entry_no)
    return by_id.get(entry_id) if entry_id is not None else None


def prepared_term_keys(
    prepared: PreparedInput, entry_no: int
) -> Mapping[str, str | None]:
    """紙に載せてよい用語名 → その記録の版の質問 key（v1.1。checks と同じ対応）。

    全体の対応（ctcae_terms.json）＋ その記録の版の term_keys。その版の質問に無い key は
    null。重さの判定語を含む語は除く（ctcae_term_keys と同じ）。
    """
    return {
        term: key
        for term, key in entry_term_keys(prepared, entry_no).items()
        if term in ctcae_term_keys()
    }


def _event_fits(
    ev: TimelineEvent,
    entry: Entry,
    prepared: PreparedInput,
    keys: Mapping[str, str | None],
) -> bool:
    return (
        ev.date <= entry.record_date  # 記録した日より後の出来事は書けない
        and ev.term in keys
        and keys[ev.term] == ev.question_key  # 用語と行（質問）の対応は版の対応のとおり
        and quote_matches(prepared, ev.entry_no, ev.source_quote)
    )


def usable_events(
    timeline: Timeline, prepared: PreparedInput, by_id: Mapping[int, Entry]
) -> list[TimelineEvent]:
    """記録と照合できた出来事だけ。「回」（recalled）は記録日と出来事の日付から決め直す。

    落とすもの: 未知の entry_no、記録日より後の日付、一覧に無い用語、用語と
    question_key の組み合わせがその記録の版の対応（prepared_term_keys）と違うもの、
    引用が伏せ字後の文に無いもの。
    """
    keys: dict[int, Mapping[str, str | None]] = {}
    usable = []
    for ev in timeline.events:
        entry = _source_entry(ev.entry_no, prepared, by_id)
        if entry is None:
            continue
        if ev.entry_no not in keys:
            keys[ev.entry_no] = prepared_term_keys(prepared, ev.entry_no)
        if not _event_fits(ev, entry, prepared, keys[ev.entry_no]):
            continue
        usable.append(ev.model_copy(update={"recalled": ev.date < entry.record_date}))
    return usable


def _matched_answer(
    c: Contradiction, prepared: PreparedInput, by_id: Mapping[int, Entry]
) -> tuple[Entry, ClosedAnswer] | None:
    entry = _source_entry(c.entry_no, prepared, by_id)
    if entry is None or entry.record_date != c.date:
        return None
    if not quote_matches(prepared, c.entry_no, c.free_text_quote):
        return None
    answer = next((a for a in entry.answers if a.question_key == c.question_key), None)
    if answer is None or answer.value != c.closed_answer:
        return None
    return entry, answer


def verified_contradictions(
    timeline: Timeline,
    prepared: PreparedInput,
    by_id: Mapping[int, Entry],
    *,
    schedule: CourseSchedule,
    courses: Sequence[Course],
) -> list[AttentionItem]:
    """記録と照合できた食い違いだけを、記録日・entry_no 順に（重複は1つ）。"""
    items: list[AttentionItem] = []
    seen: set[tuple[int, str, str]] = set()
    ordered = sorted(
        timeline.contradictions,
        key=lambda c: (c.date, c.entry_no, c.question_key, c.free_text_quote),
    )
    for c in ordered:
        matched = _matched_answer(c, prepared, by_id)
        key = (c.entry_no, c.question_key, c.free_text_quote)
        if matched is None or key in seen:
            continue
        entry, answer = matched
        day = course_mod.day_of(entry.record_date, schedule, courses=courses)
        if day is None:
            continue
        seen.add(key)
        items.append(
            AttentionItem(
                kind="contradiction",
                day=day,
                question_key=answer.question_key,
                closed_answer=answer.value,
                quote=c.free_text_quote,
            )
        )
    return items


def _rebuilt_summary(
    pick: SymptomSummary,
    events: Sequence[TimelineEvent],
    *,
    schedule: CourseSchedule,
    courses: Sequence[Course],
    visit_date: date,
) -> SymptomSummary | None:
    same_term = [
        ev
        for ev in events
        if ev.term == pick.term
        and ev.status in _MARKED_STATUSES
        and ev.date <= visit_date
    ]
    chosen = [ev for ev in same_term if ev.source_quote == pick.representative_quote]
    if not chosen:
        return None
    rep = min(chosen, key=lambda ev: (ev.confidence, ev.date, ev.entry_no))
    start = min(ev.date for ev in same_term)
    return SymptomSummary(
        term=pick.term,
        question_key=rep.question_key,
        start_day=course_mod.day_of(start, schedule, courses=courses),
        start_date=start,
        representative_quote=rep.source_quote,
        confidence=rep.confidence,
    )


def _start_order(s: SymptomSummary) -> tuple[bool, int, date, str]:
    # 開始 Day の早い順。Day が None（Day1 より前への回想）は先頭。同じ Day は日付・用語名
    return (s.start_day is not None, s.start_day or 0, s.start_date, s.term)


def verified_per_symptom(
    picks: ReportPicks,
    events: Sequence[TimelineEvent],
    *,
    schedule: CourseSchedule,
    courses: Sequence[Course],
    visit_date: date,
) -> list[SymptomSummary]:
    """AI の選んだ症状を出来事と照合して組み直す。用語ごとに1行（最初の有効なもの）。"""
    allowed = ctcae_terms()
    rows: dict[str, SymptomSummary] = {}
    for pick in picks.per_symptom:
        if pick.term in rows or pick.term not in allowed:
            continue
        rebuilt = _rebuilt_summary(
            pick, events, schedule=schedule, courses=courses, visit_date=visit_date
        )
        if rebuilt is not None:
            rows[pick.term] = rebuilt
    return sorted(rows.values(), key=_start_order)
