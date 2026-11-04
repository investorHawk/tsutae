"""拒否の理由だけを読んで直す偽のモデルで、少ない呼び出しで convert が通ることを確かめる。

本物のモデル（API）は呼ばない。FakeRunner を継いだ ReactiveRunner が「主エージェント」を
演じる: 1回目に典型的な誤り（Day のずれ・引用の句読点違い・per_symptom の順序違いと
start_day のずれ）を出し、H2 の deny と emit_* の is_error の理由に挙がった**位置だけ**を
直して全体を渡し直す。理由が項目を取りこぼしていれば、何度呼んでも通らない。

- Day は理由の文の「この date は DayN」（期待される値）から直す（正解を見ない）
- 引用は理由に原文が無いので、その位置だけ入力（正解の台本）から写し直す
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions
from pipeline_fakes import FakeRunner, Outcome, Step, label_payloads, prepare_case

from tsutae.config import SKILLS_HOME, get_settings
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.orchestrator import build_options, convert
from tsutae.pipeline.tools import EMIT_REPORT_TOOL, EMIT_TIMELINE_TOOL, RunCollector
from tsutae.schemas import ReportPicks, RunStats, Timeline

DEMO = "demo_patient"
MAX_TRIES = 5
_LOC = re.compile(r"\b(events|contradictions|per_symptom)\.(\d+)\.([a-z_]+)")
_DAY = re.compile(
    r"\b(events)\.(\d+)\.day: date の Day と違う（この date は "
    r"(?:Day(\d+)|Day1 より前なので null)"
)
_START_DAY = re.compile(r"\bper_symptom\.(\d+)\.start_day: [^;]*?（(\d+|null) にする）")

Payload = dict[str, Any]
QUOTE_FIELDS = frozenset({"source_quote", "free_text_quote", "representative_quote"})


def _reason(outcome: Outcome) -> str | None:
    """H2 の deny の理由、または emit_* の is_error の本文。受け付けたら None。"""
    if outcome.decision == "deny":
        return outcome.reason or ""
    result = outcome.result or {}
    if result.get("is_error"):
        return "".join(c.get("text", "") for c in result.get("content", []))
    return None


def _repair(payload: Payload, reason: str, correct: Mapping[str, Any]) -> Payload:
    """理由に挙がった位置だけを直した新しい payload（引数は書き換えない）。"""
    fixed = copy.deepcopy(payload)
    by_value = {(k, int(i), "day"): d for k, i, d in _DAY.findall(reason)}
    by_value |= {
        ("per_symptom", int(i), "start_day"): v for i, v in _START_DAY.findall(reason)
    }
    for key, index, field in _LOC.findall(reason):
        loc = (key, int(index), field)
        if loc in by_value:
            raw = by_value[loc]
            fixed[key][loc[1]][field] = None if raw in ("", "null") else int(raw)
        elif field in QUOTE_FIELDS:  # 理由に原文は無い。入力（正解）から写し直す
            fixed[key][loc[1]][field] = correct[key][loc[1]][field]
        # ほかの項目は理由から読めなければ直せない（そのまま。何度でも拒否される）
    return fixed


class ReactiveRunner(FakeRunner):
    """前置きの手（Skill・3役）の後、emit_* を理由に従って直しながら呼ぶ。"""

    def __init__(
        self,
        prelude: list[Step],
        first: tuple[Payload, Payload],
        correct: tuple[Payload, Payload],
        repair: Callable[[Payload, str, Mapping[str, Any]], Payload] = _repair,
    ) -> None:
        super().__init__(prelude)
        self.first = first
        self.correct = correct
        self.repair = repair
        self.reasons: list[str] = []

    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats:
        self.calls += 1
        self.prompts.append(prompt)
        self.options = options
        if await self._prompt_blocked(prompt, options):
            self.blocked = True
            return RunStats()
        for step in self.steps:
            await self._run_step(len(self.outcomes), step, options, collector)
        pairs = zip(
            (EMIT_TIMELINE_TOOL, EMIT_REPORT_TOOL),
            self.first,
            self.correct,
            strict=True,
        )
        for tool, payload, correct in pairs:
            await self._emit_until_accepted(tool, payload, correct, options, collector)
        return RunStats(duration_ms=1000, num_turns=len(self.outcomes))

    async def _emit_until_accepted(
        self,
        tool: str,
        payload: Payload,
        correct: Mapping[str, Any],
        options: ClaudeAgentOptions,
        collector: RunCollector,
    ) -> None:
        for _ in range(MAX_TRIES):
            await self._run_step(
                len(self.outcomes), Step(tool, payload), options, collector
            )
            reason = _reason(self.outcomes[-1])
            if reason is None:
                return
            self.reasons.append(reason)
            payload = self.repair(payload, reason, correct)


def _prelude() -> list[Step]:
    agent = {"description": "変換", "prompt": "入力 JSON"}
    return [
        Step("Skill", {"skill": "regimen-folfox"}),
        Step("Skill", {"skill": "report-format-default"}),
        Step("Agent", {**agent, "subagent_type": "date-normalizer"}),
        Step("Agent", {**agent, "subagent_type": "contradiction-finder"}),
        Step("Agent", {**agent, "subagent_type": "term-mapper"}),
    ]


def _typical_mistakes(
    timeline: Payload, report: Payload, texts: Mapping[int, str]
) -> tuple[Payload, Payload, list[int]]:
    """Day を1日ずらす（2件）・引用に読点を足す（1件）・per_symptom を逆順にし
    start_day を1日ずらす（1件）。ずらした出来事の位置も返す。"""
    bad_tl = copy.deepcopy(timeline)
    with_day = [i for i, e in enumerate(bad_tl["events"]) if e["day"] is not None]
    shifted = with_day[:2]
    for i in shifted:
        bad_tl["events"][i]["day"] += 1
    quoted = with_day[-1]
    ev = bad_tl["events"][quoted]
    ev["source_quote"] = ev["source_quote"][:2] + "、" + ev["source_quote"][2:]
    assert ev["source_quote"] not in texts[ev["entry_no"]]
    bad_rep = copy.deepcopy(report)
    bad_rep["per_symptom"].reverse()
    row = next(r for r in bad_rep["per_symptom"] if r["start_day"] is not None)
    row["start_day"] += 1
    return bad_tl, bad_rep, [*shifted, quoted]


async def _convert_with_mistakes() -> tuple[Any, ReactiveRunner, Payload, Payload]:
    prepared = prepare_case(DEMO)
    timeline, report = label_payloads(DEMO, prepared)
    bad_tl, bad_rep, _ = _typical_mistakes(timeline, report, prepared.masked_texts)
    assert len(report["per_symptom"]) >= 3
    runner = ReactiveRunner(_prelude(), (bad_tl, bad_rep), (timeline, report))
    settings = replace(get_settings(), pipeline_timeout_s=5.0)
    result = await convert(
        prepared, runner=runner, logger=MemoryLogger(), settings=settings
    )
    return result, runner, timeline, report


async def test_typical_mistakes_are_fixed_from_the_reasons_alone() -> None:
    result, runner, timeline, report = await _convert_with_mistakes()
    assert result.fallback is False, result.error_code
    assert result.timeline == Timeline.model_validate(
        {**timeline, "unprocessed_entries": result.timeline.unprocessed_entries}
    )
    # 逆順に渡した per_symptom は拒否されず、並べ直して受け付けられる
    assert result.picks == ReportPicks.model_validate(report)


async def test_retries_fit_in_half_of_max_turns() -> None:
    _result, runner, _tl, _rep = await _convert_with_mistakes()
    tools = [o.tool_name for o in runner.outcomes]
    # 引用（H2）→ Day（checks）→ 受け付け、の3回。report は start_day → 受け付けの2回
    assert tools.count(EMIT_TIMELINE_TOOL) == 3
    assert tools.count(EMIT_REPORT_TOOL) == 2
    assert len(runner.outcomes) <= get_settings().pipeline_max_turns // 2


async def test_each_rejection_names_positions_and_never_the_record_text() -> None:
    _result, runner, timeline, _rep = await _convert_with_mistakes()
    assert len(runner.reasons) == 3
    h2, day, start_day = runner.reasons
    assert ".source_quote" in h2 and "句読点" in h2
    assert "events." in day and ".day" in day and "対応表" in day
    assert "per_symptom." in start_day and ".start_day" in start_day
    quotes = {e["source_quote"] for e in timeline["events"]}
    terms = {e["term"] for e in timeline["events"]}
    for reason in runner.reasons:
        assert not any(q in reason for q in quotes | terms)


async def test_day_reason_carries_the_expected_day_of_each_shifted_event() -> None:
    # 偽のモデルは理由の「この date は DayN」だけで Day を直す（理由の形を固定する）
    prepared = prepare_case(DEMO)
    timeline, report = label_payloads(DEMO, prepared)
    bad_tl, _bad_rep, shifted = _typical_mistakes(
        timeline, report, prepared.masked_texts
    )
    runner = ReactiveRunner(_prelude(), (bad_tl, report), (timeline, report))
    collector = RunCollector.from_prepared(prepared)
    settings = replace(get_settings(), pipeline_timeout_s=5.0)
    options = build_options(prepared, collector, MemoryLogger(), settings, SKILLS_HOME)
    await runner.run("依頼", options, collector)
    day_reason = next(r for r in runner.reasons if ".day:" in r)
    for i in shifted[:2]:
        expected = timeline["events"][i]["day"]
        assert f"events.{i}.day: date の Day と違う（この date は Day{expected}" in (
            day_reason
        )
