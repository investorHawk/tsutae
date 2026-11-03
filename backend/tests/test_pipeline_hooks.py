"""tsutae.pipeline.hooks（H1〜H4・trace・build_hooks）を偽のイベントで発火させる。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tsutae.masking import RULE_AT_MARK, RULE_UNKNOWN_BEFORE_HONORIFIC
from tsutae.pipeline.hooks import (
    H2_MATCHER,
    H3_MATCHER,
    build_hooks,
    make_h1,
    make_h2,
    make_h3,
    make_h4,
    make_trace_hooks,
)
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.tools import EMIT_REPORT_TOOL, EMIT_TIMELINE_TOOL

CTX: dict[str, Any] = {"signal": None}
MASKED = {
    1: "夕方から下痢が3回あった。ほとんど食べてない",
    2: "あしたは受診日。○○先生にきくことをメモした。きょうは吐き気も下痢もなかった",
}
ALLOWED_TOOLS = (
    "Task",
    "Agent",
    "Skill",
    EMIT_TIMELINE_TOOL,
    EMIT_REPORT_TOOL,
)
ALLOWED_AGENTS = ("date-normalizer", "term-mapper", "contradiction-finder")


def _prompt(text: str) -> dict[str, Any]:
    return {
        "hook_event_name": "UserPromptSubmit",
        "prompt": text,
        "session_id": "s",
        "transcript_path": "",
        "cwd": "/",
    }


def _pre(tool_name: str, tool_input: Any, agent_type: str | None = None) -> dict:
    inp = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "toolu_1",
        "session_id": "s",
        "transcript_path": "",
        "cwd": "/",
    }
    if agent_type:
        inp.update(agent_id="a1", agent_type=agent_type)
    return inp


def _denied(result: dict[str, Any]) -> bool:
    out = result.get("hookSpecificOutput") or {}
    return out.get("hookEventName") == "PreToolUse" and (
        out.get("permissionDecision") == "deny"
    )


def _reason(result: dict[str, Any]) -> str:
    return result["hookSpecificOutput"]["permissionDecisionReason"]


# --- H1 -------------------------------------------------------------------


async def test_h1_blocks_prompt_with_identifier_by_rule_name() -> None:
    logger = MemoryLogger()
    h1 = make_h1(logger)
    result = await h1(_prompt("担当者さんに聞いた"), None, CTX)
    assert result == {
        "decision": "block",
        "reason": RULE_UNKNOWN_BEFORE_HONORIFIC,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "suppressOriginalPrompt": True,
        },
    }
    assert logger.find("hook_h1_block") == [
        {
            "event": "hook_h1_block",
            "hook_name": "H1",
            "decision": f"block:{RULE_UNKNOWN_BEFORE_HONORIFIC}",
        }
    ]


async def test_h1_uses_first_detection() -> None:
    result = await make_h1(MemoryLogger())(_prompt("連絡は x@y まで"), None, CTX)
    assert result["reason"] == RULE_AT_MARK


async def test_h1_passes_clean_prompt_and_logs_that_it_ran() -> None:
    logger = MemoryLogger()
    assert await make_h1(logger)(_prompt("下痢が3回あった"), None, CTX) == {}
    assert logger.records == [
        {"event": "hook_h1_allow", "hook_name": "H1", "decision": "allow"}
    ]


async def test_h1_blocks_non_text_prompt() -> None:
    result = await make_h1(MemoryLogger())({"prompt": None}, None, CTX)
    assert result["decision"] == "block"


# --- H2 -------------------------------------------------------------------


def _timeline_input(**over: Any) -> dict[str, Any]:
    base = {
        "events": [
            {"entry_no": 1, "source_quote": "夕方から下痢が3回あった"},
            {"entry_no": 2, "source_quote": "吐き気も下痢もなかった"},
        ],
        "contradictions": [{"entry_no": 1, "free_text_quote": "下痢が3回"}],
    }
    return {**base, **over}


async def test_h2_allows_exact_substrings_and_logs_that_it_ran() -> None:
    logger = MemoryLogger()
    h2 = make_h2(MASKED, logger)
    assert await h2(_pre(EMIT_TIMELINE_TOOL, _timeline_input()), None, CTX) == {}
    ok = {"per_symptom": [{"representative_quote": "下痢が3回"}]}
    assert await h2(_pre(EMIT_REPORT_TOOL, ok), None, CTX) == {}
    assert logger.records == [
        {
            "event": "hook_h2_allow",
            "hook_name": "H2",
            "tool_name": EMIT_TIMELINE_TOOL,
            "decision": "allow",
        },
        {
            "event": "hook_h2_allow",
            "hook_name": "H2",
            "tool_name": EMIT_REPORT_TOOL,
            "decision": "allow",
        },
    ]


async def test_h2_denies_fabricated_quote_without_echoing_text() -> None:
    logger = MemoryLogger()
    h2 = make_h2(MASKED, logger)
    bad = _timeline_input(
        events=[
            {"entry_no": 1, "source_quote": "夕方から下痢が3回あった"},
            {"entry_no": 1, "source_quote": "腹痛がひどかった"},
        ]
    )
    result = await h2(_pre(EMIT_TIMELINE_TOOL, bad, agent_type=None), None, CTX)
    assert _denied(result)
    reason = _reason(result)
    assert "events.1.source_quote" in reason and "entry_no=1" in reason
    assert "腹痛" not in reason and "下痢" not in reason
    assert logger.find("hook_h2_deny") == [
        {
            "event": "hook_h2_deny",
            "hook_name": "H2",
            "tool_name": EMIT_TIMELINE_TOOL,
            "decision": "deny:events.1.source_quote",
        }
    ]


async def test_h2_denies_paraphrase_and_whitespace_change() -> None:
    h2 = make_h2(MASKED, MemoryLogger())
    for quote in ("夕方から下痢が３回あった", "夕方から 下痢が3回あった", " ", ""):
        payload = _timeline_input(events=[{"entry_no": 1, "source_quote": quote}])
        assert _denied(await h2(_pre(EMIT_TIMELINE_TOOL, payload), None, CTX)), quote


async def test_h2_matches_quotes_across_kept_line_breaks() -> None:
    # masked_texts は改行を含みうる（§7 W2b）。改行ごと写した引用は通し、改行を空白や
    # 無しに変えた引用は通さない
    h2 = make_h2({1: "朝から下痢。\nセンターで点滴した"}, MemoryLogger())

    def payload_of(quote: str) -> dict[str, Any]:
        return {"events": [{"entry_no": 1, "source_quote": quote}]}

    ok = payload_of("下痢。\nセンター")
    assert not _denied(await h2(_pre(EMIT_TIMELINE_TOOL, ok), None, CTX))
    for quote in ("下痢。 センター", "下痢。センター", "下痢。\\nセンター"):
        payload = payload_of(quote)
        assert _denied(await h2(_pre(EMIT_TIMELINE_TOOL, payload), None, CTX)), quote


async def test_h2_denies_quote_from_another_entry() -> None:
    h2 = make_h2(MASKED, MemoryLogger())
    payload = _timeline_input(
        events=[{"entry_no": 1, "source_quote": "吐き気も下痢もなかった"}]
    )
    assert _denied(await h2(_pre(EMIT_TIMELINE_TOOL, payload), None, CTX))


async def test_h2_denies_unknown_entry_no() -> None:
    h2 = make_h2(MASKED, MemoryLogger())
    for no in (3, 0, True, "1", None):
        payload = _timeline_input(events=[{"entry_no": no, "source_quote": "下痢"}])
        result = await h2(_pre(EMIT_TIMELINE_TOOL, payload), None, CTX)
        assert _denied(result), no
        assert "events.0" in _reason(result)


async def test_h2_checks_contradiction_quotes() -> None:
    h2 = make_h2(MASKED, MemoryLogger())
    payload = _timeline_input(
        contradictions=[{"entry_no": 2, "free_text_quote": "下痢が3回"}]
    )
    result = await h2(_pre(EMIT_TIMELINE_TOOL, payload), None, CTX)
    assert _denied(result)
    assert "contradictions.0.free_text_quote" in _reason(result)


async def test_h2_checks_report_representative_quote_against_any_text() -> None:
    h2 = make_h2(MASKED, MemoryLogger())
    ok = {"per_symptom": [{"representative_quote": "吐き気も下痢もなかった"}]}
    assert await h2(_pre(EMIT_REPORT_TOOL, ok), None, CTX) == {}
    bad = {"per_symptom": [ok["per_symptom"][0], {"representative_quote": "熱が出た"}]}
    result = await h2(_pre(EMIT_REPORT_TOOL, bad), None, CTX)
    assert _denied(result)
    assert "per_symptom.1.representative_quote" in _reason(result)


async def test_h2_reason_says_how_to_fix_and_to_resend_everything() -> None:
    h2 = make_h2(MASKED, MemoryLogger())
    bad = _timeline_input(
        events=[{"entry_no": 1, "source_quote": "夕方から、下痢が3回あった"}]
    )
    reason = _reason(await h2(_pre(EMIT_TIMELINE_TOOL, bad), None, CTX))
    assert "受け付けていない" in reason and "全体" in reason
    for word in ("句読点", "空白", "改行", "全角半角"):
        assert word in reason, word
    no_text = _timeline_input(events=[{"entry_no": 9, "source_quote": "下痢"}])
    reason = _reason(await h2(_pre(EMIT_TIMELINE_TOOL, no_text), None, CTX))
    assert "masked_free_text" in reason and "null" in reason


async def test_h2_report_reason_points_at_accepted_source_quotes() -> None:
    h2 = make_h2(MASKED, MemoryLogger())
    bad = {"per_symptom": [{"representative_quote": "熱が出た"}]}
    reason = _reason(await h2(_pre(EMIT_REPORT_TOOL, bad), None, CTX))
    assert "source_quote" in reason


async def test_h2_lists_up_to_twenty_problems() -> None:
    h2 = make_h2(MASKED, MemoryLogger())
    events = [{"entry_no": 1, "source_quote": "腹痛"} for _ in range(25)]
    reason = _reason(await h2(_pre(EMIT_TIMELINE_TOOL, {"events": events}), None, CTX))
    assert "events.19.source_quote" in reason
    assert "events.20.source_quote" not in reason
    assert "ほか 5 件" in reason


async def test_h2_denies_malformed_input_without_raising() -> None:
    h2 = make_h2(MASKED, MemoryLogger())
    for payload in (None, [], {"events": "x"}, {"events": [1]}, {"per_symptom": 3}):
        tool = EMIT_REPORT_TOOL if payload == {"per_symptom": 3} else EMIT_TIMELINE_TOOL
        assert _denied(await h2(_pre(tool, payload), None, CTX)), payload


async def test_h2_ignores_other_tools() -> None:
    logger = MemoryLogger()
    h2 = make_h2(MASKED, logger)
    assert await h2(_pre("Skill", {"skill": "regimen-folfox"}), None, CTX) == {}
    assert logger.records == []  # 自分の受け持ちでないツールは記録しない


async def test_h2_records_subagent_type_when_present() -> None:
    logger = MemoryLogger()
    h2 = make_h2(MASKED, logger)
    payload = _timeline_input(events=[{"entry_no": 1, "source_quote": "x"}])
    await h2(_pre(EMIT_TIMELINE_TOOL, payload, agent_type="term-mapper"), None, CTX)
    assert logger.find("hook_h2_deny")[0]["agent_type"] == "term-mapper"


async def test_h2_does_not_keep_reference_to_caller_dict() -> None:
    texts = dict(MASKED)
    h2 = make_h2(texts, MemoryLogger())
    texts[1] = "書き換え"
    payload = _timeline_input()
    assert await h2(_pre(EMIT_TIMELINE_TOOL, payload), None, CTX) == {}


# --- H3 -------------------------------------------------------------------


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    (root / ".claude" / "skills" / "regimen-folfox").mkdir(parents=True)
    (root / ".claude" / "skills" / "report-format-default").mkdir(parents=True)
    return root


def _write(path: str | Path, tool: str = "Write") -> dict[str, Any]:
    return _pre(tool, {"file_path": str(path), "content": "x"})


async def test_h3_allows_skill_md_under_skills(skills_root: Path) -> None:
    logger = MemoryLogger()
    h3 = make_h3(skills_root, logger)
    skills = skills_root / ".claude" / "skills"
    for tool in ("Write", "Edit", "MultiEdit"):
        assert (
            await h3(_write(skills / "regimen-folfox" / "SKILL.md", tool), None, CTX)
            == {}
        )
    new = skills / "regimen-capox" / "SKILL.md"  # まだ無い Skill の新規作成も同じ規則
    assert await h3(_write(new), None, CTX) == {}
    assert [r["tool_name"] for r in logger.find("hook_h3_allow")] == [
        "Write",
        "Edit",
        "MultiEdit",
        "Write",
    ]
    assert {r["decision"] for r in logger.records} == {"allow"}


async def test_h3_denies_paths_outside_or_wrong_shape(skills_root: Path) -> None:
    logger = MemoryLogger()
    h3 = make_h3(skills_root, logger)
    skills = skills_root / ".claude" / "skills"
    bad = [
        skills_root / "app.py",
        skills / "regimen-folfox" / "README.md",
        skills / "evil" / "SKILL.md",
        skills / "regimen-folfox" / "sub" / "SKILL.md",
        skills / "regimen-folfox" / ".." / ".." / ".." / "SKILL.md",
        skills / "SKILL.md",
        Path("/etc/passwd"),
        Path(".claude/skills/regimen-folfox/SKILL.md"),  # 相対パス
    ]
    for path in bad:
        assert _denied(await h3(_write(path), None, CTX)), path
    assert len(logger.find("hook_h3_deny")) == len(bad)


async def test_h3_denies_symlink_escape(skills_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("x", encoding="utf-8")
    skills = skills_root / ".claude" / "skills"
    os.symlink(outside, skills / "regimen-link")
    os.symlink(outside / "SKILL.md", skills / "report-format-default" / "SKILL.md")
    h3 = make_h3(skills_root, MemoryLogger())
    assert _denied(await h3(_write(skills / "regimen-link" / "SKILL.md"), None, CTX))
    target = skills / "report-format-default" / "SKILL.md"
    assert _denied(await h3(_write(target), None, CTX))


async def test_h3_denies_missing_file_path(skills_root: Path) -> None:
    h3 = make_h3(skills_root, MemoryLogger())
    assert _denied(await h3(_pre("Write", {"content": "x"}), None, CTX))
    assert _denied(await h3(_pre("Edit", None), None, CTX))


async def test_h3_ignores_other_tools(skills_root: Path) -> None:
    logger = MemoryLogger()
    h3 = make_h3(skills_root, logger)
    assert await h3(_pre("Skill", {"skill": "x"}), None, CTX) == {}
    assert logger.records == []


def test_h3_matcher_covers_write_tools() -> None:
    assert set(H3_MATCHER.split("|")) == {"Write", "Edit", "MultiEdit"}


# --- H4 -------------------------------------------------------------------


async def test_h4_allows_listed_tools_and_subagents() -> None:
    logger = MemoryLogger()
    h4 = make_h4(ALLOWED_TOOLS, ALLOWED_AGENTS, logger)
    assert await h4(_pre("Skill", {"skill": "regimen-folfox"}), None, CTX) == {}
    assert await h4(_pre(EMIT_TIMELINE_TOOL, {}), None, CTX) == {}
    for tool in ("Agent", "Task"):
        call = _pre(tool, {"subagent_type": "date-normalizer", "prompt": "x"})
        assert await h4(call, None, CTX) == {}
    assert [r["tool_name"] for r in logger.find("hook_h4_allow")] == [
        "Skill",
        EMIT_TIMELINE_TOOL,
        "Agent",
        "Task",
    ]
    assert all(r["hook_name"] == "H4" for r in logger.records)


async def test_h4_allow_log_has_agent_type_inside_subagents() -> None:
    logger = MemoryLogger()
    h4 = make_h4(ALLOWED_TOOLS, ALLOWED_AGENTS, logger)
    await h4(_pre("Skill", {"skill": "x"}, agent_type="term-mapper"), None, CTX)
    assert logger.records == [
        {
            "event": "hook_h4_allow",
            "hook_name": "H4",
            "agent_type": "term-mapper",
            "tool_name": "Skill",
            "decision": "allow",
        }
    ]


async def test_h4_denies_tools_outside_the_list() -> None:
    logger = MemoryLogger()
    h4 = make_h4(ALLOWED_TOOLS, ALLOWED_AGENTS, logger)
    for tool in ("Bash", "Write", "Read", "WebFetch", "mcp__other__x"):
        result = await h4(_pre(tool, {}), None, CTX)
        assert _denied(result), tool
    assert [r["tool_name"] for r in logger.find("hook_h4_deny")] == [
        "Bash",
        "Write",
        "Read",
        "WebFetch",
        "mcp__other__x",
    ]
    assert logger.find("hook_h4_deny")[0]["decision"] == "deny:tool_not_allowed"


async def test_h4_denies_builtin_or_unknown_subagents() -> None:
    logger = MemoryLogger()
    h4 = make_h4(ALLOWED_TOOLS, ALLOWED_AGENTS, logger)
    for tool_input in (
        {"subagent_type": "general-purpose"},
        {"subagent_type": "Explore"},
        {},
        None,
    ):
        assert _denied(await h4(_pre("Agent", tool_input), None, CTX)), tool_input
    assert logger.find("hook_h4_deny")[0]["decision"] == "deny:subagent_not_allowed"


async def test_h4_applies_inside_subagents() -> None:
    logger = MemoryLogger()
    h4 = make_h4(ALLOWED_TOOLS, ALLOWED_AGENTS, logger)
    result = await h4(
        _pre("Bash", {"command": "ls"}, agent_type="term-mapper"), None, CTX
    )
    assert _denied(result)
    assert logger.find("hook_h4_deny")[0]["agent_type"] == "term-mapper"


# --- trace / build_hooks ----------------------------------------------------


async def test_trace_hooks_only_record() -> None:
    logger = MemoryLogger()
    trace = make_trace_hooks(logger)
    assert set(trace) == {"SubagentStart", "SubagentStop", "PostToolUse"}
    start = {
        "hook_event_name": "SubagentStart",
        "agent_id": "a",
        "agent_type": "term-mapper",
    }
    assert await trace["SubagentStart"](start, None, CTX) == {}
    stop = {**start, "hook_event_name": "SubagentStop", "stop_hook_active": False}
    assert await trace["SubagentStop"](stop, None, CTX) == {}
    post = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Skill",
        "tool_input": {},
        "tool_response": "本文",
        "duration_ms": 12,
    }
    assert await trace["PostToolUse"](post, "toolu_1", CTX) == {}
    assert logger.records == [
        {"event": "subagent_start", "agent_type": "term-mapper"},
        {"event": "subagent_stop", "agent_type": "term-mapper"},
        {"event": "tool_use", "tool_name": "Skill", "duration_ms": 12},
    ]


async def test_build_hooks_wires_everything_with_block_on_failure() -> None:
    logger = MemoryLogger()
    hooks = build_hooks(
        masked_texts=MASKED,
        logger=logger,
        allowed_tools=ALLOWED_TOOLS,
        allowed_subagents=ALLOWED_AGENTS,
    )
    assert set(hooks) == {
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "SubagentStart",
        "SubagentStop",
    }
    for matchers in hooks.values():
        for m in matchers:
            assert m.on_failure == "block"
            assert m.hooks
    pre = hooks["PreToolUse"]
    assert [m.matcher for m in pre] == [None, H2_MATCHER]
    assert f"{EMIT_TIMELINE_TOOL}|{EMIT_REPORT_TOOL}" == H2_MATCHER
    h4, h2 = pre[0].hooks[0], pre[1].hooks[0]
    assert _denied(await h4(_pre("Bash", {}), None, CTX))
    bad = _timeline_input(events=[{"entry_no": 1, "source_quote": "x"}])
    assert _denied(await h2(_pre(EMIT_TIMELINE_TOOL, bad), None, CTX))
    h1 = hooks["UserPromptSubmit"][0].hooks[0]
    assert (await h1(_prompt("担当者さん"), None, CTX))["decision"] == "block"
