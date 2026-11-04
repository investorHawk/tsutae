"""tsutae.pipeline.orchestrator（build_options・convert）を偽の runner で通す。"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKError,
    CLIConnectionError,
    ResultError,
    ResultMessage,
)
from claude_agent_sdk._internal.transport.subprocess_cli import (
    SubprocessCLITransport,
)
from pipeline_fakes import (
    FakeRunner,
    RaisingRunner,
    SlowRunner,
    Step,
    agent_step,
    label_payloads,
    load_case,
    prepare_case,
    regimen_skill,
    report_skill,
    standard_steps,
)

from tsutae.config import SKILLS_DIR, SKILLS_HOME, get_settings
from tsutae.dataset import to_courses, to_entries
from tsutae.pipeline.agents import AGENT_NAMES
from tsutae.pipeline.inputs import prepare_input
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.orchestrator import (
    ALLOWED_TOOLS,
    DISALLOWED_TOOLS,
    build_options,
    convert,
    sdk_error_code,
)
from tsutae.pipeline.prompt import SYSTEM_PROMPT, build_prompt
from tsutae.pipeline.runner import RunFailedError, SdkRunner
from tsutae.pipeline.tools import EMIT_REPORT_TOOL, EMIT_TIMELINE_TOOL, RunCollector
from tsutae.schemas import (
    Contradiction,
    MaskedEntry,
    PreparedInput,
    ReportPicks,
    RunStats,
    SymptomSummary,
    Timeline,
    TimelineEvent,
    UnprocessedEntry,
)

SETTINGS = replace(
    get_settings(),
    model="claude-test-main",
    subagent_model="claude-test-sub",
    pipeline_timeout_s=5.0,
    pipeline_max_turns=12,
    pipeline_max_budget_usd=1.5,
)
DEMO = "demo_patient"
MAX_TURNS_MESSAGE = (
    "Claude Code returned an error result: Reached maximum number of turns (2)"
)
BUDGET_MESSAGE = "Claude Code returned an error result: Reached maximum budget ($1.5)"


def _demo() -> tuple[PreparedInput, dict[str, Any], dict[str, Any]]:
    prepared = prepare_case(DEMO)
    timeline, report = label_payloads(DEMO, prepared)
    return prepared, timeline, report


async def _convert(prepared: PreparedInput, runner: Any, **over: Any):
    logger = MemoryLogger()
    settings = replace(SETTINGS, **over)
    result = await convert(prepared, runner=runner, logger=logger, settings=settings)
    return result, logger


def _with_text(prepared: PreparedInput, text: str) -> PreparedInput:
    """伏せ字の検査を通さずに作った入力（H1 を試す）。"""
    entry = MaskedEntry(
        entry_no=1,
        record_date=prepared.input.schedule.day1_date,
        day=1,
        by_proxy=False,
        too_sick=False,
        masked_free_text=text,
    )
    return PreparedInput(
        input=prepared.input.model_copy(update={"entries": [entry]}),
        entry_ids={1: 1},
        masked_texts={1: text},
    )


# --- build_options ------------------------------------------------------------


def test_build_options_values(tmp_path: Path) -> None:
    prepared = prepare_case(DEMO)
    collector = RunCollector.from_prepared(prepared)
    options = build_options(prepared, collector, MemoryLogger(), SETTINGS, tmp_path)
    assert options.cwd == str(tmp_path)
    assert options.setting_sources == ["project"]
    assert options.skills == ["regimen-folfox", "report-format-default"]
    assert options.model == "claude-test-main"
    assert options.allowed_tools == [
        "Task",
        "Agent",
        "Skill",
        "mcp__tsutae__emit_timeline",
        "mcp__tsutae__emit_report",
    ]
    assert options.allowed_tools == list(ALLOWED_TOOLS)
    assert options.disallowed_tools == [
        "Bash",
        "Write",
        "Edit",
        "MultiEdit",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
        "Workflow",
        "Read",
        "Glob",
        "Grep",
        # 遅延読み込みを切り、emit_* が常に直接見えるようにする（同梱 CLI の分岐）
        "ToolSearch",
        # T03 の init に出た、使わない組み込みツール（説明文とターンを使わせない）
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "EnterWorktree",
        "ExitWorktree",
        "ListAgents",
        "Monitor",
        "PushNotification",
        "ReportFindings",
        "ScheduleWakeup",
        "SendMessage",
        "TaskStop",
    ]
    assert options.disallowed_tools == list(DISALLOWED_TOOLS)
    assert not set(ALLOWED_TOOLS) & set(DISALLOWED_TOOLS)
    # 会話の記録（伏せ字後の自由記載・変換結果）を ~/.claude/projects に残さない
    assert options.extra_args == {"no-session-persistence": None}
    # 開発用の CLAUDE.md（リポジトリ直下など cwd の祖先）を変換の文脈に入れない
    assert options.env == {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}
    assert options.permission_mode == "dontAsk"
    assert options.max_turns == 12
    assert options.max_budget_usd == 1.5
    assert options.system_prompt == SYSTEM_PROMPT
    assert set(options.agents or {}) == set(AGENT_NAMES)
    assert all(a.model == "claude-test-sub" for a in (options.agents or {}).values())
    assert set(options.mcp_servers) == {"tsutae"}  # type: ignore[arg-type]
    assert set(options.hooks or {}) == {
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "SubagentStart",
        "SubagentStop",
    }


def test_cli_command_disables_session_persistence(tmp_path: Path) -> None:
    """SDK が組み立てる CLI の引数に --no-session-persistence が入る（SDK は既定で付けない）。"""
    prepared = prepare_case(DEMO)
    collector = RunCollector.from_prepared(prepared)
    options = build_options(prepared, collector, MemoryLogger(), SETTINGS, tmp_path)
    transport = SubprocessCLITransport(prompt="x", options=options)
    transport._cli_path = "claude"  # 起動はしない（引数を組み立てるだけ）
    cmd = transport._build_command()
    assert "--no-session-persistence" in cmd
    disallowed = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert "ToolSearch" in disallowed


async def test_build_options_server_and_hooks_use_given_collector(
    tmp_path: Path,
) -> None:
    prepared, timeline, report = _demo()
    collector = RunCollector.from_prepared(prepared)
    options = build_options(prepared, collector, MemoryLogger(), SETTINGS, tmp_path)
    runner = FakeRunner(
        [Step("Bash", {"command": "ls"}), *standard_steps(timeline, report)]
    )
    await runner.run(build_prompt(prepared), options, collector)
    assert [o.tool_name for o in runner.denied()] == ["Bash"]
    assert collector.timeline is not None and collector.picks is not None


def _copy_skills(home: Path) -> Path:
    """本物の Skill を `<home>/.claude/skills` に写して、その skills_dir を返す。"""
    skills_dir = home / ".claude" / "skills"
    shutil.copytree(SKILLS_DIR, skills_dir)
    return skills_dir


async def test_convert_takes_skills_home_from_settings(tmp_path: Path) -> None:
    prepared, timeline, report = _demo()
    runner = FakeRunner(standard_steps(timeline, report))
    skills_dir = _copy_skills(tmp_path)
    await _convert(prepared, runner, skills_dir=skills_dir)
    assert runner.options is not None and runner.options.cwd == str(tmp_path)
    runner2 = FakeRunner(standard_steps(timeline, report))
    await _convert(prepared, runner2)
    assert runner2.options is not None and runner2.options.cwd == str(SKILLS_HOME)


# --- 正常 -------------------------------------------------------------------


async def test_convert_demo_course3_from_label_script() -> None:
    prepared, timeline, report = _demo()
    runner = FakeRunner(standard_steps(timeline, report))
    result, logger = await _convert(prepared, runner)
    assert result.fallback is False and result.error_code is None
    assert result.timeline is not None
    assert result.timeline.events == [
        TimelineEvent.model_validate(e) for e in timeline["events"]
    ]
    assert result.timeline.contradictions == [
        Contradiction.model_validate(c) for c in timeline["contradictions"]
    ]
    assert result.timeline.unprocessed_entries == [
        UnprocessedEntry(entry_id=38, reason="unknown_before_honorific")
    ]
    assert result.picks == ReportPicks(
        per_symptom=[SymptomSummary.model_validate(s) for s in report["per_symptom"]]
    )
    assert result.stats == runner.stats
    assert runner.calls == 1 and runner.denied() == []
    assert runner.prompts == [build_prompt(prepared)]


async def test_convert_demo_course3_has_the_diarrhea_contradiction() -> None:
    prepared, timeline, report = _demo()
    result, _ = await _convert(prepared, FakeRunner(standard_steps(timeline, report)))
    assert result.timeline is not None
    [contra] = result.timeline.contradictions
    assert prepared.entry_ids[contra.entry_no] == 33
    assert (contra.question_key, contra.closed_answer, contra.day) == (
        "diarrhea",
        "none",
        5,
    )


async def test_convert_logs_without_text() -> None:
    prepared, timeline, report = _demo()
    _, logger = await _convert(prepared, FakeRunner(standard_steps(timeline, report)))
    names = logger.names()
    assert names[0] == "run_start" and names[-1] == "run_end"
    for name in (
        "hook_h1_allow",
        "hook_h4_allow",
        "hook_h2_allow",
        "subagent_start",
        "subagent_stop",
        "tool_use",
        "emit_timeline",
        "emit_report",
    ):
        assert name in names, name
    # 正常に通った Hook も、どの Hook が走ったかをツールごとに残す（spec §8）
    assert [r["tool_name"] for r in logger.find("hook_h2_allow")] == [
        EMIT_TIMELINE_TOOL,
        EMIT_REPORT_TOOL,
    ]
    assert len(logger.find("hook_h4_allow")) == len(standard_steps(timeline, report))
    assert [r["agent_type"] for r in logger.find("subagent_start")] == [
        "date-normalizer",
        "contradiction-finder",
        "term-mapper",
    ]
    end = logger.find("run_end")[0]
    assert end["decision"] == "ok" and end["duration_ms"] == 1000
    for record in logger.records:
        for value in record.values():
            assert not isinstance(value, str) or value.isascii()


async def test_convert_accepts_task_as_subagent_tool_name() -> None:
    prepared, timeline, report = _demo()
    steps = [
        agent_step("date-normalizer", tool_name="Task"),
        *standard_steps(timeline, report),
    ]
    runner = FakeRunner(steps)
    result, _ = await _convert(prepared, runner)
    assert result.fallback is False and runner.denied() == []


# --- H1 ---------------------------------------------------------------------


async def test_h1_code_stage_stops_before_claude() -> None:
    bad = _with_text(prepare_case(DEMO), "担当者さんに聞いた")
    runner = FakeRunner()
    result, logger = await _convert(bad, runner)
    assert runner.calls == 0
    assert result.fallback is True and result.error_code == "h1_blocked"
    assert result.timeline is None and result.picks is None
    assert (
        logger.find("hook_h1_block")[0]["decision"] == "block:unknown_before_honorific"
    )
    assert logger.find("fallback")[0]["decision"] == "h1_blocked"


async def test_h1_hook_stage_blocks_prompt_in_sdk(tmp_path: Path) -> None:
    bad = _with_text(prepare_case(DEMO), "連絡先は x@y")
    collector = RunCollector.from_prepared(bad)
    logger = MemoryLogger()
    options = build_options(bad, collector, logger, SETTINGS, tmp_path)
    prepared, timeline, report = _demo()
    runner = FakeRunner(standard_steps(timeline, report))
    stats = await runner.run(build_prompt(bad), options, collector)
    assert runner.blocked is True and runner.outcomes == []
    assert stats.num_turns == 0 and collector.timeline is None
    assert logger.find("hook_h1_block")[0]["decision"] == "block:at_mark"


async def test_h1_in_sdk_does_not_block_prompts_written_for_subagents(
    tmp_path: Path,
) -> None:
    # build_options の H1 はアプリの依頼文だけを止める。主エージェントがサブエージェントに
    # 書いた依頼文（ここでは敬称を含む文）は通して記録だけ残す
    prepared, _timeline, _report = _demo()
    collector = RunCollector.from_prepared(prepared)
    logger = MemoryLogger()
    options = build_options(prepared, collector, logger, SETTINGS, tmp_path)
    (matcher,) = options.hooks["UserPromptSubmit"]
    (h1,) = matcher.hooks
    sub = {"hook_event_name": "UserPromptSubmit", "prompt": "担当者さんの記録を直して"}
    assert await h1(sub, None, {"signal": None}) == {}
    assert logger.find("hook_h1_subagent_flag")
    ours = {"hook_event_name": "UserPromptSubmit", "prompt": build_prompt(prepared)}
    assert await h1(ours, None, {"signal": None}) == {}  # 依頼文はきれい


# --- H2 ---------------------------------------------------------------------


def _fabricated(timeline: dict[str, Any]) -> dict[str, Any]:
    events = [dict(e) for e in timeline["events"]]
    events[0] = {**events[0], "source_quote": events[0]["source_quote"] + "がひどい"}
    return {**timeline, "events": events}


async def test_h2_denies_fabricated_quote_then_correct_emit_is_used() -> None:
    prepared, timeline, report = _demo()
    bad_report = {
        "per_symptom": [
            {**report["per_symptom"][0], "representative_quote": "書かれていない文"}
        ]
    }
    steps = [
        *standard_steps(timeline, report)[:5],
        Step(EMIT_TIMELINE_TOOL, _fabricated(timeline)),
        Step(EMIT_TIMELINE_TOOL, timeline),
        Step(EMIT_REPORT_TOOL, bad_report),
        Step(EMIT_REPORT_TOOL, report),
    ]
    runner = FakeRunner(steps)
    result, logger = await _convert(prepared, runner)
    assert [o.tool_name for o in runner.denied()] == [
        EMIT_TIMELINE_TOOL,
        EMIT_REPORT_TOOL,
    ]
    assert "events.0.source_quote" in (runner.denied()[0].reason or "")
    assert result.fallback is False and result.timeline is not None
    assert result.timeline.events == [
        TimelineEvent.model_validate(e) for e in timeline["events"]
    ]
    assert result.picks is not None
    assert result.picks.per_symptom[0].representative_quote == (
        report["per_symptom"][0]["representative_quote"]
    )
    assert len(logger.find("hook_h2_deny")) == 2
    assert [r["decision"] for r in logger.find("emit_timeline")] == ["accept"]


async def test_h2_deny_leaves_no_timeline_if_never_corrected() -> None:
    prepared, timeline, report = _demo()
    steps = [
        Step(EMIT_TIMELINE_TOOL, _fabricated(timeline)),
        Step(EMIT_REPORT_TOOL, report),
    ]
    result, _ = await _convert(prepared, FakeRunner(steps))
    assert result.fallback is True and result.error_code == "no_timeline"


# --- H4 ---------------------------------------------------------------------


async def test_h4_denies_bash_builtin_agents_and_tools_inside_subagents() -> None:
    prepared, timeline, report = _demo()
    steps = [
        Step("Bash", {"command": "cat /etc/hosts"}),
        agent_step("general-purpose"),
        agent_step("Explore", tool_name="Task"),
        Step("Read", {"file_path": "/etc/hosts"}, agent_type="term-mapper"),
        Step("Write", {"file_path": "/tmp/x", "content": "x"}),
        *standard_steps(timeline, report),
    ]
    runner = FakeRunner(steps)
    result, logger = await _convert(prepared, runner)
    assert [o.tool_name for o in runner.denied()] == [
        "Bash",
        "Agent",
        "Task",
        "Read",
        "Write",
    ]
    assert len(logger.find("hook_h4_deny")) == 5
    assert result.fallback is False
    starts = [r["agent_type"] for r in logger.find("subagent_start")]
    assert "general-purpose" not in starts and "Explore" not in starts


# --- 失敗とフォールバック ------------------------------------------------------


async def test_timeout_falls_back() -> None:
    prepared, _, _ = _demo()
    runner = SlowRunner(5)
    result, logger = await _convert(prepared, runner, pipeline_timeout_s=0.05)
    assert result.fallback is True and result.error_code == "timeout"
    assert result.timeline is None and result.picks is None
    assert runner.cancelled is True
    assert logger.find("fallback")[0]["decision"] == "timeout"
    assert logger.find("run_end")[0]["decision"] == "timeout"


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (
            ResultError(
                MAX_TURNS_MESSAGE,
                {"subtype": "error_max_turns", "terminal_reason": "max_turns"},
            ),
            "max_turns",
        ),
        (ResultError(MAX_TURNS_MESSAGE), "max_turns"),
        (ClaudeSDKError("max turns reached"), "max_turns"),
        (ResultError("failed", {"subtype": "error_during_execution"}), "sdk_error"),
        (
            ResultError(BUDGET_MESSAGE, {"subtype": "error_max_budget_usd"}),
            "max_budget",
        ),
        (ResultError(BUDGET_MESSAGE), "max_budget"),
        (ClaudeSDKError("max budget exceeded"), "max_budget"),
        (CLIConnectionError("cannot connect"), "sdk_error"),
        (RuntimeError("bug"), "internal_error"),
    ],
)
async def test_errors_fall_back_with_code(exc: BaseException, code: str) -> None:
    prepared, _, _ = _demo()
    runner = RaisingRunner(exc)
    result, logger = await _convert(prepared, runner)
    assert runner.calls == 1
    assert result.fallback is True and result.error_code == code
    assert result.timeline is None and result.picks is None
    assert logger.find("fallback")[0]["decision"] == code


async def test_max_turns_after_emit_still_falls_back() -> None:
    prepared, timeline, report = _demo()
    exc = ResultError(MAX_TURNS_MESSAGE, {"subtype": "error_max_turns"})
    runner = FakeRunner(standard_steps(timeline, report), raise_after=exc)
    result, _ = await _convert(prepared, runner)
    assert result.fallback is True and result.error_code == "max_turns"
    assert result.stats.duration_ms >= 0 and result.stats.cost_usd == 0.0


async def test_failed_run_keeps_cost_and_tokens_in_run_end() -> None:
    # r3: is_error の ResultMessage の後に ResultError。費用・トークン数をログに残す
    async def fake_query(*, prompt: str, options: ClaudeAgentOptions):
        yield ResultMessage(
            subtype="error_max_turns",
            duration_ms=90000,
            duration_api_ms=80000,
            is_error=True,
            num_turns=30,
            session_id="s",
            total_cost_usd=0.83,
            usage={"input_tokens": 120000, "output_tokens": 9000},
        )
        raise ResultError(
            MAX_TURNS_MESSAGE,
            {"subtype": "error_max_turns", "terminal_reason": "max_turns"},
        )

    prepared, _, _ = _demo()
    result, logger = await _convert(prepared, SdkRunner(query_fn=fake_query))
    assert result.fallback is True and result.error_code == "max_turns"
    assert result.stats.num_turns == 30 and result.stats.cost_usd == 0.83
    [end] = logger.find("run_end")
    assert end["decision"] == "max_turns"
    assert (end["tokens_in"], end["tokens_out"], end["cost_usd"]) == (
        120000,
        9000,
        0.83,
    )
    assert end["duration_ms"] == 90000


async def test_max_budget_run_keeps_cost_in_run_end() -> None:
    # max_budget_usd 超過は is_error の ResultMessage（error_max_budget_usd）の後に
    # ResultError。max_turns と区別し、費用を残す
    async def fake_query(*, prompt: str, options: ClaudeAgentOptions):
        yield ResultMessage(
            subtype="error_max_budget_usd",
            duration_ms=50000,
            duration_api_ms=40000,
            is_error=True,
            num_turns=9,
            session_id="s",
            total_cost_usd=1.52,
            usage={"input_tokens": 80000, "output_tokens": 5000},
        )
        raise ResultError(BUDGET_MESSAGE, {"subtype": "error_max_budget_usd"})

    prepared, _, _ = _demo()
    result, logger = await _convert(prepared, SdkRunner(query_fn=fake_query))
    assert result.fallback is True and result.error_code == "max_budget"
    [end] = logger.find("run_end")
    assert end["decision"] == "max_budget"
    assert (end["tokens_in"], end["tokens_out"], end["cost_usd"]) == (
        80000,
        5000,
        1.52,
    )


def test_sdk_error_code_is_shared_and_unwraps_run_failed() -> None:
    err = ResultError("x", {"subtype": "error_max_budget_usd"})
    assert sdk_error_code(err) == "max_budget"
    assert sdk_error_code(RunFailedError(err, RunStats())) == "max_budget"
    turns = ResultError("x", {"subtype": "error_max_turns"})
    assert sdk_error_code(RunFailedError(turns, RunStats())) == "max_turns"
    assert sdk_error_code(CLIConnectionError("cannot connect")) == "sdk_error"


async def test_failed_run_without_result_uses_elapsed_time() -> None:
    async def fake_query(*, prompt: str, options: ClaudeAgentOptions):
        raise CLIConnectionError("cannot connect")
        yield  # pragma: no cover

    prepared, _, _ = _demo()
    result, _ = await _convert(prepared, SdkRunner(query_fn=fake_query))
    assert result.error_code == "sdk_error"
    assert result.stats.cost_usd == 0.0 and result.stats.tokens_in == 0


async def test_exception_text_is_not_logged() -> None:
    prepared, _, _ = _demo()
    runner = RaisingRunner(ClaudeSDKError("secret 下痢が3回"))
    _, logger = await _convert(prepared, runner)
    for record in logger.records:
        assert all("secret" not in str(v) for v in record.values())


async def test_no_emit_timeline_falls_back_and_keeps_stats() -> None:
    prepared, _, report = _demo()
    runner = FakeRunner([Step(EMIT_REPORT_TOOL, report)])
    result, _ = await _convert(prepared, runner)
    assert result.fallback is True and result.error_code == "no_timeline"
    assert result.timeline is None and result.picks is None
    assert result.stats == runner.stats


async def test_missing_emit_report_falls_back() -> None:
    # 統合役は timeline と report の両方を出す（spec §7.1）。片方だけは成功にしない
    prepared, timeline, _ = _demo()
    runner = FakeRunner([Step(EMIT_TIMELINE_TOOL, timeline)])
    result, logger = await _convert(prepared, runner)
    assert result.fallback is True and result.error_code == "no_report"
    assert result.timeline is None and result.picks is None
    assert result.stats == runner.stats
    assert logger.find("run_end")[0]["decision"] == "no_report"


async def test_report_before_timeline_is_rejected_and_falls_back() -> None:
    prepared, timeline, report = _demo()
    runner = FakeRunner(
        [Step(EMIT_REPORT_TOOL, report), Step(EMIT_TIMELINE_TOOL, timeline)]
    )
    result, logger = await _convert(prepared, runner)
    assert result.fallback is True and result.error_code == "no_report"
    assert logger.find("emit_report")[0]["decision"].startswith("reject:")


# --- 出力の検査（入力から写す項目・用語・per_symptom の結び付き）--------------------


def _tampered(timeline: dict[str, Any], report: dict[str, Any], prepared):
    """クローズ回答・用語・コピー項目を書き換えた台本（r2 の再現）。"""
    [contra] = timeline["contradictions"]
    no_answers = next(
        e for e in prepared.input.entries if e.masked_free_text and not e.answers
    )
    contradictions = [
        {**contra, "closed_answer": "hard"},
        {
            "entry_no": no_answers.entry_no,
            "date": "2026-12-31",
            "day": 99,
            "question_key": "fever",
            "closed_answer": "measured",
            "free_text_quote": prepared.masked_texts[no_answers.entry_no][:3],
        },
    ]
    first = {
        **timeline["events"][0],
        "term": "重症の下痢（Grade 3）",
        "course_no": 7,
        "day": 99,
        "date": "2027-01-01",
    }
    bad_timeline = {
        "events": [first, *timeline["events"][1:]],
        "contradictions": contradictions,
    }
    summary = {**report["per_symptom"][0], "term": "重篤な発熱。すぐ受診を"}
    return bad_timeline, {"per_symptom": [summary, *report["per_symptom"][1:]]}


async def test_tampered_output_is_rejected_then_corrected_output_is_used() -> None:
    prepared, timeline, report = _demo()
    bad_timeline, bad_report = _tampered(timeline, report, prepared)
    steps = [
        *standard_steps(timeline, report)[:5],
        Step(EMIT_TIMELINE_TOOL, bad_timeline),
        Step(EMIT_TIMELINE_TOOL, timeline),
        Step(EMIT_REPORT_TOOL, bad_report),
        Step(EMIT_REPORT_TOOL, report),
    ]
    runner = FakeRunner(steps)
    result, logger = await _convert(prepared, runner)
    rejected = [
        o.result for o in runner.outcomes if o.result and o.result.get("is_error")
    ]
    assert len(rejected) == 2
    text = rejected[0]["content"][0]["text"]
    for where in (
        "events.0.term",
        "events.0.course_no",
        "contradictions.0.closed_answer",
        "contradictions.1.question_key",
    ):
        assert where in text, where
    assert "重症" not in text and "重篤" not in rejected[1]["content"][0]["text"]
    assert result.fallback is False and result.timeline is not None
    [contra] = result.timeline.contradictions
    assert (contra.closed_answer, contra.day) == ("none", 5)
    assert result.picks is not None
    assert [s.term for s in result.picks.per_symptom] == [
        s["term"] for s in report["per_symptom"]
    ]
    decisions = [r["decision"] for r in logger.find("emit_timeline")]
    assert decisions[0].startswith("reject:") and decisions[1] == "accept"


async def test_tampered_output_never_corrected_falls_back() -> None:
    prepared, timeline, report = _demo()
    bad_timeline, _ = _tampered(timeline, report, prepared)
    runner = FakeRunner(standard_steps(bad_timeline, report))
    result, _ = await _convert(prepared, runner)
    assert result.fallback is True and result.error_code == "no_timeline"


async def test_line_break_before_facility_word_does_not_stop_the_whole_run() -> None:
    # r1: 「…\nセンター…」は依頼文の JSON では「n＋センター」になる。記録1件で全体を止めない
    patient, _ = load_case(DEMO)
    entries = to_entries(patient)
    changed = entries[-1].model_copy(
        update={"free_text": "朝から下痢。\nセンターで点滴した"}
    )
    prepared = prepare_input(
        courses=to_courses(patient),
        entries=[*entries[:-1], changed],
        regimen_skill=regimen_skill(),
        report_skill=report_skill(),
        visit_date=patient.visit_date,
    )
    changed_no = next(n for n, i in prepared.entry_ids.items() if i == changed.id)
    assert prepared.masked_texts[changed_no] == "朝から下痢。\nセンターで点滴した"
    timeline, report = label_payloads(DEMO, prepared)
    kept = [e for e in timeline["events"] if e["entry_no"] != changed_no]
    runner = FakeRunner(standard_steps({**timeline, "events": kept}, report))
    result, _ = await _convert(prepared, runner)
    assert runner.calls == 1 and runner.blocked is False and runner.denied() == []
    assert result.fallback is False and result.error_code is None


async def test_empty_input_does_not_call_claude() -> None:
    patient, _ = load_case(DEMO)
    flagged_only = [e for e in to_entries(patient) if e.id == 38]
    prepared = prepare_input(
        courses=to_courses(patient),
        entries=flagged_only,
        regimen_skill=regimen_skill(),
        report_skill=report_skill(),
        visit_date=date(2026, 11, 9),
    )
    assert prepared.input.entries == []
    runner = FakeRunner()
    result, logger = await _convert(prepared, runner)
    assert runner.calls == 0
    assert result.fallback is False and result.error_code is None
    assert result.timeline == Timeline(
        unprocessed_entries=[
            UnprocessedEntry(entry_id=38, reason="unknown_before_honorific")
        ]
    )
    assert result.picks == ReportPicks()
    assert logger.names() == ["run_start", "run_end"]


async def test_input_without_free_text_does_not_call_claude() -> None:
    # 回答だけ・つらくて書けないだけの記録では、H2 が引用を全て拒否するので出せる結果は
    # 空だけ。Claude を呼ばずに空の Timeline（unprocessed だけ）で成功（§7 W2b）
    patient, _ = load_case(DEMO)
    entries = [
        (
            e.model_copy(update={"free_text": None, "kind": "answers"})
            if e.kind in ("free_text", "mixed") and e.answers
            else e
        )
        for e in to_entries(patient)
        if e.kind != "free_text" or e.id == 38
    ]
    prepared = prepare_input(
        courses=to_courses(patient),
        entries=entries,
        regimen_skill=regimen_skill(),
        report_skill=report_skill(),
        visit_date=date(2026, 11, 9),
    )
    assert prepared.input.entries and prepared.masked_texts == {}
    runner = FakeRunner()
    result, logger = await _convert(prepared, runner)
    assert runner.calls == 0
    assert result.fallback is False and result.error_code is None
    assert result.timeline == Timeline(unprocessed_entries=list(prepared.unprocessed))
    assert result.picks == ReportPicks()
    assert logger.names() == ["run_start", "run_end"]


async def test_cancellation_is_not_swallowed() -> None:
    prepared, _, _ = _demo()
    task = asyncio.create_task(_convert(prepared, SlowRunner(5)))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_unusual_skills_dir_falls_back_without_calling_claude(
    tmp_path: Path,
) -> None:
    # <home>/.claude/skills の形でない skills_dir は SDK が読めない。黙って既定の
    # SKILLS_HOME に替えると、prepare_input・report の Skill と SDK の Skill が別物になる
    prepared, timeline, report = _demo()
    runner = FakeRunner(standard_steps(timeline, report))
    result, logger = await _convert(prepared, runner, skills_dir=tmp_path / "custom")
    assert runner.calls == 0
    assert result.fallback is True and result.error_code == "config_error"
    assert logger.find("config_error")[0]["decision"] == "skills_dir_shape"


async def test_failure_while_building_options_is_internal_error() -> None:
    prepared = prepare_case(DEMO)
    broken = prepared.model_copy(
        update={
            "input": prepared.input.model_copy(
                update={"regimen_skill_version": "report-format-default@1"}
            )
        }
    )
    runner = FakeRunner()
    result, logger = await _convert(broken, runner)
    assert runner.calls == 0
    assert result.fallback is True and result.error_code == "internal_error"
    # 例外の型名だけを残す（本文は残さない）
    assert logger.find("internal_error") == [
        {"event": "internal_error", "decision": "error_type:ValueError"}
    ]


async def test_internal_error_logs_only_the_exception_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prepared, _, _ = _demo()
    runner = RaisingRunner(KeyError("secret 下痢が3回"))
    with caplog.at_level("WARNING", logger="tsutae.pipeline.orchestrator"):
        result, logger = await _convert(prepared, runner)
    assert result.error_code == "internal_error"
    assert logger.find("internal_error")[0]["decision"] == "error_type:KeyError"
    assert "KeyError" in caplog.text and "secret" not in caplog.text
    for record in logger.records:
        assert all("secret" not in str(v) for v in record.values())


# --- 実行直前の Skill の版の照合（入力準備後に Skill が更新された競合）----------------


@pytest.mark.parametrize("skill_name", ["regimen-folfox", "report-format-default"])
async def test_skill_updated_after_prepare_falls_back_without_calling_claude(
    tmp_path: Path, skill_name: str
) -> None:
    prepared, timeline, report = _demo()
    skills_dir = _copy_skills(tmp_path)
    skill_md = skills_dir / skill_name / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "\nversion: 1\n" in text
    skill_md.write_text(text.replace("\nversion: 1\n", "\nversion: 2\n"), "utf-8")
    runner = FakeRunner(standard_steps(timeline, report))
    result, logger = await _convert(prepared, runner, skills_dir=skills_dir)
    assert runner.calls == 0
    assert result.fallback is True and result.error_code == "skill_version_mismatch"
    assert result.timeline is None and result.picks is None
    assert logger.find("skill_check") == [
        {"event": "skill_check", "decision": f"mismatch:{skill_name}"}
    ]
    assert logger.find("run_end")[0]["decision"] == "skill_version_mismatch"


async def test_skill_check_uses_the_given_skills_home(tmp_path: Path) -> None:
    prepared, timeline, report = _demo()
    skills_dir = _copy_skills(tmp_path)
    skill_md = skills_dir / "regimen-folfox" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    skill_md.write_text(text.replace("\nversion: 1\n", "\nversion: 3\n"), "utf-8")
    runner = FakeRunner(standard_steps(timeline, report))
    logger = MemoryLogger()
    result = await convert(
        prepared, runner=runner, logger=logger, settings=SETTINGS, skills_home=tmp_path
    )
    assert runner.calls == 0 and result.error_code == "skill_version_mismatch"


async def test_missing_skill_falls_back_without_calling_claude(tmp_path: Path) -> None:
    prepared, timeline, report = _demo()
    skills_dir = _copy_skills(tmp_path)
    shutil.rmtree(skills_dir / "report-format-default")
    runner = FakeRunner(standard_steps(timeline, report))
    result, logger = await _convert(prepared, runner, skills_dir=skills_dir)
    assert runner.calls == 0
    assert result.fallback is True and result.error_code == "skill_load_error"
    assert logger.find("skill_check") == [
        {"event": "skill_check", "decision": "load_error:report-format-default"}
    ]


async def test_broken_skill_falls_back_without_calling_claude(tmp_path: Path) -> None:
    prepared, timeline, report = _demo()
    skills_dir = _copy_skills(tmp_path)
    (skills_dir / "regimen-folfox" / "SKILL.md").write_text("壊れた", "utf-8")
    runner = FakeRunner(standard_steps(timeline, report))
    result, _logger = await _convert(prepared, runner, skills_dir=skills_dir)
    assert runner.calls == 0 and result.error_code == "skill_load_error"


async def test_matching_skills_are_checked_and_run(tmp_path: Path) -> None:
    prepared, timeline, report = _demo()
    runner = FakeRunner(standard_steps(timeline, report))
    result, logger = await _convert(prepared, runner, skills_dir=_copy_skills(tmp_path))
    assert runner.calls == 1 and result.fallback is False
    assert logger.find("skill_check") == [{"event": "skill_check", "decision": "ok"}]
