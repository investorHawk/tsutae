"""tsutae.regimen.chat_sdk: SdkRegimenChat の組み立て（偽の query。API は呼ばない）。

- 許可ツール・拒否ツール・H4 の許可一覧を値で固定する（decisions.md「T94」に記録）
- cwd は空の一時ディレクトリ・setting_sources=[]・--no-session-persistence・
  NO_CLAUDE_MD_ENV・max_turns・max_budget_usd・model
- Hook は H1（依頼文）と H4（3つのツールだけ。サブエージェント無し）
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultError
from regimen_chat_fakes import ToolQuery, result_message

from tsutae.config import get_settings
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.orchestrator import sdk_error_code
from tsutae.pipeline.runner import RunFailedError
from tsutae.regimen.chat_args import SERVER_NAME
from tsutae.regimen.chat_prompt import SYSTEM_PROMPT, build_turn_prompt
from tsutae.regimen.chat_sdk import (
    REGIMEN_ALLOWED_TOOLS,
    REGIMEN_DISALLOWED_TOOLS,
    SdkRegimenChat,
    build_options,
    logging_to,
)
from tsutae.regimen.chat_session import ChatSession
from tsutae.regimen.chat_types import RegimenChat, TurnInput
from tsutae.regimen.form import FieldSources
from tsutae.regimen.source import new_draft_form
from tsutae.schemas import RunStats
from tsutae.skillchange.editor import EDITOR_DISALLOWED_TOOLS

EXPECTED_ALLOWED = [
    "mcp__tsutae_regimen__set_fields",
    "mcp__tsutae_regimen__ask",
    "mcp__tsutae_regimen__propose_questions",
]
EXPECTED_DISALLOWED = [
    # 9b（skillchange の書き換え係）と同じ
    "Bash",
    "WebFetch",
    "WebSearch",
    "Task",
    "Agent",
    "Skill",
    "MultiEdit",
    "NotebookEdit",
    "Workflow",
    "Glob",
    "Grep",
    # 9c で足したもの（ファイルを読まない・書かない）
    "Read",
    "Edit",
    "Write",
    # MCP ツールを遅延読み込みの向こうに隠さない（pipeline と同じ）
    "ToolSearch",
    # 使わない組み込みツール（pipeline と同じ）
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
TEXT = "FOLFIRI＋BV を作りたい"


def _draft() -> TurnInput:
    return TurnInput(draft_id=1, form=new_draft_form(), sources=FieldSources({}))


def _options(tmp_path: Path, logger: MemoryLogger | None = None, **kw: Any) -> Any:
    settings = dataclasses.replace(get_settings(), **kw)
    session = ChatSession(_draft(), logger)
    return build_options(tmp_path, settings, logger or MemoryLogger(), session)


async def _hooks(options: ClaudeAgentOptions, event: str, data: dict) -> list[dict]:
    results = []
    for m in options.hooks[event]:  # type: ignore[index]
        for hook in m.hooks:
            results.append(await hook(data, None, None))
    return results


def _denied(results: list[dict]) -> bool:
    return any(
        r.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        for r in results
    )


# ---------------------------------------------------------------------------
# 値の固定
# ---------------------------------------------------------------------------


def test_allowed_and_disallowed_tools_are_pinned(tmp_path: Path) -> None:
    assert list(REGIMEN_ALLOWED_TOOLS) == EXPECTED_ALLOWED
    assert list(REGIMEN_DISALLOWED_TOOLS) == EXPECTED_DISALLOWED
    assert set(EDITOR_DISALLOWED_TOOLS) <= set(REGIMEN_DISALLOWED_TOOLS)
    options = _options(tmp_path)
    assert options.allowed_tools == EXPECTED_ALLOWED
    assert options.disallowed_tools == EXPECTED_DISALLOWED
    assert not set(options.allowed_tools) & set(options.disallowed_tools)


def test_build_options_fields(tmp_path: Path) -> None:
    options = _options(
        tmp_path,
        model="claude-test-model",
        regimen_max_turns=7,
        regimen_max_budget_usd=0.25,
    )
    assert options.cwd == str(tmp_path)
    assert options.setting_sources == []
    assert options.model == "claude-test-model"
    assert options.max_turns == 7
    assert options.max_budget_usd == 0.25
    assert options.permission_mode == "dontAsk"
    assert options.env == {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}
    assert options.extra_args == {"no-session-persistence": None}
    assert options.system_prompt == SYSTEM_PROMPT
    assert options.agents in (None, {})
    assert list(options.mcp_servers) == [SERVER_NAME]
    assert options.mcp_servers[SERVER_NAME]["type"] == "sdk"


def test_hooks_are_h1_and_h4_only(tmp_path: Path) -> None:
    hooks = _options(tmp_path).hooks
    assert set(hooks) == {"UserPromptSubmit", "PreToolUse"}
    assert [m.matcher for m in hooks["PreToolUse"]] == [None]
    for group in hooks.values():
        for m in group:
            assert m.on_failure == "block"
            assert len(m.hooks) == 1


async def test_h4_allows_only_three_tools(tmp_path: Path) -> None:
    logger = MemoryLogger()
    options = _options(tmp_path, logger)
    for name in EXPECTED_ALLOWED:
        results = await _hooks(options, "PreToolUse", {"tool_name": name})
        assert not _denied(results), name
    for name in [
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Skill",
        "ToolSearch",
        "mcp__tsutae__emit_timeline",
    ]:
        results = await _hooks(options, "PreToolUse", {"tool_name": name})
        assert _denied(results), name
    for name in ("Agent", "Task"):
        data = {"tool_name": name, "tool_input": {"subagent_type": "general-purpose"}}
        assert _denied(await _hooks(options, "PreToolUse", data))
    assert len(logger.find("hook_h4_allow")) == 3
    assert len(logger.find("hook_h4_deny")) == 9


async def test_h1_blocks_prompt_with_identifier(tmp_path: Path) -> None:
    logger = MemoryLogger()
    options = _options(tmp_path, logger)
    ok = await _hooks(
        options, "UserPromptSubmit", {"prompt": build_turn_prompt(_draft(), TEXT)}
    )
    assert ok == [{}]
    blocked = await _hooks(
        options,
        "UserPromptSubmit",
        {"prompt": build_turn_prompt(_draft(), "受付 A-023 の件")},
    )
    assert blocked[0]["decision"] == "block"
    assert logger.names() == ["hook_h1_allow", "hook_h1_block"]


def test_cli_command_disables_session_persistence(tmp_path: Path) -> None:
    from claude_agent_sdk._internal.transport.subprocess_cli import (
        SubprocessCLITransport,
    )

    transport = SubprocessCLITransport(prompt="x", options=_options(tmp_path))
    transport._cli_path = "claude"  # 起動はしない（引数を組み立てるだけ）
    command = transport._build_command()
    assert "--no-session-persistence" in command
    assert "--setting-sources=" in command


# ---------------------------------------------------------------------------
# 偽の query
# ---------------------------------------------------------------------------


async def test_sdk_chat_runs_tools_and_returns_result() -> None:
    query = ToolQuery(
        [
            (
                "set_fields",
                {
                    "changes": [
                        {
                            "field": "basic.cycle_days",
                            "value": 14,
                            "source": "doctor_text",
                        }
                    ]
                },
            ),
            ("set_fields", {"changes": [{"field": "basic.cycle_days"}]}),  # schema 違い
        ]
    )
    chat = SdkRegimenChat(get_settings(), query_fn=query)
    assert isinstance(chat, RegimenChat)
    logger = MemoryLogger()
    with logging_to(logger):
        result = await chat.turn(_draft(), TEXT)
    prompt, options = query.seen[0]
    assert prompt == build_turn_prompt(_draft(), TEXT)
    assert not Path(options.cwd).exists()  # type: ignore[arg-type]  後始末
    assert result.form.basic.cycle_days == 14
    assert result.changed == ("basic.cycle_days",)
    assert result.reply == "1コースを14日にした"
    assert result.stats == RunStats(
        duration_ms=1200, num_turns=3, tokens_in=50, tokens_out=9, cost_usd=0.05
    )
    assert result.tool_calls == 1  # schema 違いは SDK が handler の前に止める
    assert query.outputs[1].is_error
    assert [r["decision"] for r in logger.find("regimen_tool")] == ["accept"]


async def test_sdk_chat_reply_falls_back_to_last_text() -> None:
    query = ToolQuery([], result=result_message(None))
    result = await SdkRegimenChat(get_settings(), query_fn=query).turn(_draft(), TEXT)
    assert result.reply == "途中の文"


async def test_sdk_chat_failure_keeps_stats(tmp_path: Path) -> None:
    async def failing(*, prompt: str, options: ClaudeAgentOptions):
        yield result_message()
        raise ResultError("秘密", {"subtype": "error_max_turns"})

    chat = SdkRegimenChat(get_settings(), query_fn=failing)
    with pytest.raises(RunFailedError) as info:
        await chat.turn(_draft(), TEXT)
    assert sdk_error_code(info.value) == "max_turns"
    assert info.value.stats.cost_usd == 0.05


async def test_sdk_chat_removes_session_files(tmp_path: Path) -> None:
    """会話の後に ~/.claude/projects/<cwd>/<session>/ を消す（spec 13.3）。"""
    sid = "0b6f2a4e-3c1d-4e5f-9a7b-8c9d0e1f2a3b"
    session = tmp_path / "-tmp-tsutae-regimen" / sid / "subagents"
    session.mkdir(parents=True)
    query = ToolQuery([], result=dataclasses.replace(result_message(), session_id=sid))
    chat = SdkRegimenChat(get_settings(), query_fn=query, projects_root=tmp_path)
    await chat.turn(_draft(), TEXT)
    assert not session.parent.exists()
