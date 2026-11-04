"""パイプラインのテスト用の偽物と症例ヘルパー（API を呼ばない）。

- 症例: 合成データ（data/synthetic）を読み、`prepare_input` に掛ける
- FakeRunner: 台本どおりに options.hooks（UserPromptSubmit → PreToolUse）を実際に呼び、
  deny されなかった emit_* だけ handle_emit_* を呼ぶ。RaisingRunner・SlowRunner も置く
- label_payloads / standard_steps: 正解ラベルから台本を作る
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from tsutae.config import SKILLS_DIR, SYNTHETIC_DIR
from tsutae.course import build_schedule
from tsutae.dataset import to_courses, to_entries
from tsutae.pipeline.inputs import prepare_input
from tsutae.pipeline.tools import (
    EMIT_REPORT_TOOL,
    EMIT_TIMELINE_TOOL,
    RunCollector,
    handle_emit_report,
    handle_emit_timeline,
)
from tsutae.schemas import (
    PatientLabels,
    PreparedInput,
    RegimenSkill,
    ReportFormatSkill,
    RunStats,
    SyntheticPatient,
)
from tsutae.skills import load_regimen_skill, load_report_skill
from tsutae.synthetic import DATASET_NAMES, load_labels, load_patient

CASE_NAMES = DATASET_NAMES


def load_case(name: str) -> tuple[SyntheticPatient, PatientLabels]:
    return (
        load_patient(SYNTHETIC_DIR / f"{name}.json"),
        load_labels(SYNTHETIC_DIR / f"labels_{name}.json"),
    )


def regimen_skill(regimen: str = "FOLFOX") -> RegimenSkill:
    return load_regimen_skill(regimen, SKILLS_DIR)  # type: ignore[arg-type]


def report_skill() -> ReportFormatSkill:
    return load_report_skill(skills_dir=SKILLS_DIR)


def prepare_case(name: str, visit_date: date | None = None) -> PreparedInput:
    patient, _labels = load_case(name)
    return prepare_input(
        courses=to_courses(patient),
        entries=to_entries(patient),
        regimen_skill=regimen_skill(patient.regimen),
        report_skill=report_skill(),
        visit_date=visit_date or patient.visit_date,
    )


def course_last_days(name: str) -> list[date]:
    """各コースの最終日（評価と同じく、その日を受診日とみなす）。"""
    patient, _labels = load_case(name)
    courses = to_courses(patient)
    skill = regimen_skill(patient.regimen)
    return [
        build_schedule(
            courses, c.course_no, skill.cycle_days, skill.pump_removal_day
        ).last_day_date
        for c in courses
    ]


# ---------------------------------------------------------------------------
# 偽の runner（options.hooks を実際に呼ぶ。API は呼ばない）
# ---------------------------------------------------------------------------

SUBAGENT_TOOLS = ("Agent", "Task")
_CTX: dict[str, Any] = {"signal": None}


@dataclass(frozen=True)
class Step:
    """台本の1手（主エージェントか、agent_type のサブエージェントのツール呼び出し）。"""

    tool_name: str
    tool_input: Mapping[str, Any] = field(default_factory=dict)
    agent_type: str | None = None


@dataclass(frozen=True)
class Outcome:
    tool_name: str
    decision: str  # "allow" / "deny"
    reason: str | None = None
    result: dict[str, Any] | None = None  # emit_* の handler の戻り値


def _matches(matcher: str | None, tool_name: str) -> bool:
    if matcher in (None, "", "*"):
        return True
    return re.fullmatch(f"(?:{matcher})", tool_name) is not None


def _hooks(options: ClaudeAgentOptions, event: str, tool_name: str = "") -> list:
    matchers = (options.hooks or {}).get(event, [])  # type: ignore[call-overload]
    return [h for m in matchers if _matches(m.matcher, tool_name) for h in m.hooks]


async def _call(hook: Any, data: dict[str, Any], tool_use_id: str | None) -> dict:
    """on_failure="block" と同じく、例外・None は「止める」扱いにする。"""
    try:
        result = await hook(data, tool_use_id, _CTX)
    except Exception:  # noqa: BLE001 — Hook の失敗そのものを再現したい
        return {"decision": "block", "reason": "hook_failed"}
    return result if isinstance(result, dict) else {"decision": "block"}


def _deny_reason(result: dict[str, Any]) -> str | None:
    out = result.get("hookSpecificOutput") or {}
    if out.get("permissionDecision") == "deny":
        return str(out.get("permissionDecisionReason", ""))
    if result.get("decision") == "block":
        return str(result.get("reason", ""))
    return None


def _base(options: ClaudeAgentOptions, event: str) -> dict[str, Any]:
    return {
        "hook_event_name": event,
        "session_id": "fake-session",
        "transcript_path": "",
        "cwd": str(options.cwd or ""),
    }


class FakeRunner:
    """台本どおりに動く runner。

    1. options.hooks の UserPromptSubmit を呼ぶ（止められたら num_turns=0 で終わる）
    2. 各手で PreToolUse（matcher の合うもの全部。H4・H2）を通し、deny が無ければ
       emit_* は handle_emit_* を呼ぶ。Agent/Task は SubagentStart/Stop を、
       最後に PostToolUse を呼ぶ
    3. raise_after があれば台本の後にその例外を出す
    """

    def __init__(
        self,
        steps: Sequence[Step] = (),
        *,
        stats: RunStats | None = None,
        raise_after: BaseException | None = None,
    ) -> None:
        self.steps = tuple(steps)
        self.stats = stats or RunStats(duration_ms=1000, num_turns=len(self.steps))
        self.raise_after = raise_after
        self.calls = 0
        self.prompts: list[str] = []
        self.options: ClaudeAgentOptions | None = None
        self.blocked = False
        self.outcomes: list[Outcome] = []

    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats:
        self.calls += 1
        self.prompts.append(prompt)
        self.options = options
        if await self._prompt_blocked(prompt, options):
            self.blocked = True
            return RunStats()
        for i, step in enumerate(self.steps):
            await self._run_step(i, step, options, collector)
        if self.raise_after is not None:
            raise self.raise_after
        return self.stats

    def denied(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.decision == "deny"]

    async def _prompt_blocked(self, prompt: str, options: ClaudeAgentOptions) -> bool:
        data = {**_base(options, "UserPromptSubmit"), "prompt": prompt}
        for hook in _hooks(options, "UserPromptSubmit"):
            if (await _call(hook, data, None)).get("decision") == "block":
                return True
        return False

    async def _run_step(
        self, i: int, step: Step, options: ClaudeAgentOptions, collector: RunCollector
    ) -> None:
        tool_use_id = f"toolu_{i:03d}"
        data = {
            **_base(options, "PreToolUse"),
            "tool_name": step.tool_name,
            "tool_input": dict(step.tool_input),
            "tool_use_id": tool_use_id,
        }
        if step.agent_type:
            data.update(agent_id=f"agent-{i}", agent_type=step.agent_type)
        for hook in _hooks(options, "PreToolUse", step.tool_name):
            reason = _deny_reason(await _call(hook, data, tool_use_id))
            if reason is not None:
                self.outcomes.append(Outcome(step.tool_name, "deny", reason))
                return
        result = await self._execute(i, step, options, collector)
        post = {**data, "hook_event_name": "PostToolUse", "tool_response": result}
        for hook in _hooks(options, "PostToolUse", step.tool_name):
            await _call(hook, post, tool_use_id)
        self.outcomes.append(Outcome(step.tool_name, "allow", result=result))

    async def _execute(
        self, i: int, step: Step, options: ClaudeAgentOptions, collector: RunCollector
    ) -> dict[str, Any] | None:
        args = dict(step.tool_input)
        if step.tool_name == EMIT_TIMELINE_TOOL:
            return handle_emit_timeline(args, collector)
        if step.tool_name == EMIT_REPORT_TOOL:
            return handle_emit_report(args, collector)
        if step.tool_name in SUBAGENT_TOOLS:
            sub = {"agent_id": f"agent-{i}", "agent_type": args.get("subagent_type")}
            for event in ("SubagentStart", "SubagentStop"):
                for hook in _hooks(options, event, str(sub["agent_type"])):
                    await _call(hook, {**_base(options, event), **sub}, None)
        return None


class RaisingRunner:
    """run で例外を出すだけ（ResultError・CLIConnectionError などを試す）。"""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.calls = 0

    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats:
        self.calls += 1
        raise self.exc


class SlowRunner:
    """seconds 待ってから終わる（タイムアウトを試す）。"""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.calls = 0
        self.cancelled = False

    async def run(
        self, prompt: str, options: ClaudeAgentOptions, collector: RunCollector
    ) -> RunStats:
        self.calls += 1
        try:
            await asyncio.sleep(self.seconds)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return RunStats()


# ---------------------------------------------------------------------------
# 正解ラベルから作る台本
# ---------------------------------------------------------------------------


def label_payloads(
    name: str, prepared: PreparedInput, confidence: float = 0.9
) -> tuple[dict[str, Any], dict[str, Any]]:
    """正解ラベルから emit_timeline / emit_report の入力を作る（今回の入力の記録だけ）。"""
    _patient, labels = load_case(name)
    seq_to_no = {seq: no for no, seq in prepared.entry_ids.items()}
    by_no = {e.entry_no: e for e in prepared.input.entries}
    events: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    for label in labels.labels:
        no = seq_to_no.get(label.entry_seq)
        if no is None:
            continue
        entry = by_no[no]
        for ev in label.events:
            events.append(
                {
                    "entry_no": no,
                    **ev.model_dump(mode="json"),
                    "confidence": confidence,
                    "by_proxy": entry.by_proxy,
                }
            )
        for c in label.contradictions:
            contradictions.append(
                {
                    "entry_no": no,
                    "date": entry.record_date.isoformat(),
                    "day": entry.day,
                    **c.model_dump(mode="json"),
                }
            )
    timeline = {"events": events, "contradictions": contradictions}
    return timeline, {"per_symptom": _per_symptom(events)}


def _per_symptom(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """term ごとに最初の出来事から1行。開始日の早い順、同じなら term 名順（§7 W2b）。"""
    first: dict[str, dict[str, Any]] = {}
    for ev in sorted(events, key=lambda e: e["date"]):
        if ev["status"] != "absent" and ev["term"] not in first:
            first[ev["term"]] = ev
    ordered = sorted(first.values(), key=lambda e: (e["date"], e["term"]))
    return [
        {
            "term": ev["term"],
            "question_key": ev["question_key"],
            "start_day": ev["day"],
            "start_date": ev["date"],
            "representative_quote": ev["source_quote"],
            "confidence": ev["confidence"],
        }
        for ev in ordered
    ]


def agent_step(subagent_type: str, tool_name: str = "Agent") -> Step:
    return Step(
        tool_name,
        {"subagent_type": subagent_type, "description": "変換", "prompt": "入力 JSON"},
    )


def standard_steps(
    timeline: Mapping[str, Any],
    report: Mapping[str, Any],
    regimen_skill_name: str = "regimen-folfox",
) -> list[Step]:
    """主エージェントの標準の手順: Skill → 3役 → emit_timeline → emit_report。"""
    return [
        Step("Skill", {"skill": regimen_skill_name}),
        Step("Skill", {"skill": "report-format-default"}),
        agent_step("date-normalizer"),
        agent_step("contradiction-finder"),
        agent_step("term-mapper"),
        Step(EMIT_TIMELINE_TOOL, timeline),
        Step(EMIT_REPORT_TOOL, report),
    ]
