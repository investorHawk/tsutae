"""tsutae.skillchange.editor（SdkSkillEditor の組み立て。API は呼ばない）。"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultError, ResultMessage

from tsutae.config import get_settings
from tsutae.masking import detect_identifiers
from tsutae.pipeline.hooks import H3_MATCHER
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.orchestrator import sdk_error_code
from tsutae.pipeline.runner import RunFailedError
from tsutae.schemas import RunStats
from tsutae.skillchange.editor import (
    EDITOR_ALLOWED_TOOLS,
    EDITOR_MAX_TURNS,
    EDITOR_SYSTEM_PROMPT,
    SdkSkillEditor,
    SkillEditor,
    build_options,
    build_prompt,
    current_logger,
    logging_to,
)
from tsutae.skillchange.workcopy import work_copy_path

NAME = "regimen-folfox"


@pytest.fixture
def work_root(tmp_path: Path) -> Path:
    root = (tmp_path / "work").resolve()
    work_copy_path(root, NAME).parent.mkdir(parents=True)
    work_copy_path(root, NAME).write_text("x", "utf-8")
    return root


def _options(work_root: Path, logger: MemoryLogger | None = None) -> Any:
    return build_options(
        work_root, get_settings(), logger or MemoryLogger(), skill_name=NAME
    )


async def _call(options: ClaudeAgentOptions, event: str, data: dict) -> list[dict]:
    """event の HookMatcher のうち、matcher が tool_name に合うものを順に呼ぶ。"""
    results = []
    for m in options.hooks[event]:  # type: ignore[index]
        tool = data.get("tool_name")
        if m.matcher is not None and tool not in m.matcher.split("|"):
            continue
        for hook in m.hooks:
            results.append(await hook(data, None, None))
    return results


def _denied(results: list[dict]) -> bool:
    return any(
        r.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        for r in results
    )


# ---------------------------------------------------------------------------
# build_options
# ---------------------------------------------------------------------------


def test_build_options_fields(work_root: Path) -> None:
    settings = dataclasses.replace(get_settings(), model="claude-test-model")
    options = build_options(work_root, settings, MemoryLogger(), skill_name=NAME)
    assert options.cwd == str(work_root)
    # Skill もファイルの設定も読まない（[] は SDK の分離モード。None は全部読む）
    assert options.setting_sources == []
    assert options.allowed_tools == ["Read", "Edit", "Write"]
    assert list(EDITOR_ALLOWED_TOOLS) == ["Read", "Edit", "Write"]
    for tool in ("Bash", "WebFetch", "WebSearch", "Task", "Agent", "Skill"):
        assert tool in options.disallowed_tools
    assert not set(options.allowed_tools) & set(options.disallowed_tools)
    assert options.permission_mode == "acceptEdits"
    # 読む1・書く1〜2・Hook の理由で直す数回（読み直しを含む）・締め1
    assert options.max_turns == EDITOR_MAX_TURNS == 16
    assert options.model == "claude-test-model"
    assert options.max_budget_usd == settings.pipeline_max_budget_usd
    assert options.agents in (None, {})
    assert not options.mcp_servers


def test_build_options_hooks_shape(work_root: Path) -> None:
    hooks = _options(work_root).hooks
    assert set(hooks) == {"UserPromptSubmit", "PreToolUse", "PostToolUse"}
    assert [m.matcher for m in hooks["PostToolUse"]] == [H3_MATCHER]
    matchers = [m.matcher for m in hooks["PreToolUse"]]
    assert None in matchers  # H4（全ツール）
    assert H3_MATCHER in matchers
    assert "Read" in matchers
    for group in hooks.values():
        for m in group:
            assert m.on_failure == "block"
            assert len(m.hooks) == 1


async def test_h1_blocks_prompt_with_name(work_root: Path) -> None:
    logger = MemoryLogger()
    options = _options(work_root, logger)
    blocked = await _call(
        options, "UserPromptSubmit", {"prompt": build_prompt(NAME, "磯鷲さんの件")}
    )
    assert blocked[0]["decision"] == "block"
    ok = await _call(
        options, "UserPromptSubmit", {"prompt": build_prompt(NAME, "下痢の質問を短く")}
    )
    assert ok == [{}]
    assert logger.names() == ["hook_h1_block", "hook_h1_allow"]


@pytest.mark.parametrize(
    "tool, tool_input",
    [
        ("Bash", {"command": "ls"}),
        ("Agent", {"subagent_type": "general-purpose"}),
        ("Task", {"subagent_type": "general-purpose"}),
        ("WebFetch", {"url": "https://example.com"}),
        ("MultiEdit", {"file_path": "/x"}),
        ("Skill", {"skill": NAME}),
    ],
)
async def test_h4_denies_other_tools(
    work_root: Path, tool: str, tool_input: dict
) -> None:
    results = await _call(
        _options(work_root),
        "PreToolUse",
        {"tool_name": tool, "tool_input": tool_input},
    )
    assert _denied(results)


async def test_h3_allows_only_skill_file_in_work_root(work_root: Path) -> None:
    options = _options(work_root)
    target = work_copy_path(work_root, NAME)
    assert "/.claude/" not in str(target)  # CLI が acceptEdits でも保護する場所
    for tool in ("Edit", "Write"):
        ok = await _call(
            options,
            "PreToolUse",
            {"tool_name": tool, "tool_input": {"file_path": str(target)}},
        )
        assert not _denied(ok)
    for bad in (
        work_root / "other.md",
        work_root / ".claude" / "skills" / NAME / "SKILL.md",  # 旧い配置
        work_root / "skills" / "regimen-capox" / "SKILL.md",  # 別の Skill
        work_root / "skills" / NAME / ".." / ".." / "settings.json",
        work_root / "skills" / NAME / ".." / ".." / ".." / "skills" / NAME / "SKILL.md",
        work_root.parent / "skills_home" / ".claude" / "skills" / NAME / "SKILL.md",
        Path("skills") / NAME / "SKILL.md",
    ):
        results = await _call(
            options,
            "PreToolUse",
            {"tool_name": "Write", "tool_input": {"file_path": str(bad)}},
        )
        assert _denied(results), bad


async def test_read_is_confined_to_work_root(work_root: Path, tmp_path: Path) -> None:
    options = _options(work_root)
    inside = work_copy_path(work_root, NAME)
    ok = await _call(
        options,
        "PreToolUse",
        {"tool_name": "Read", "tool_input": {"file_path": str(inside)}},
    )
    assert not _denied(ok)
    outside = tmp_path / "secret.db"
    outside.write_text("x", "utf-8")
    link = work_root / "link.db"
    link.symlink_to(outside)
    for bad in (
        str(outside),
        str(link),
        str(work_root / ".." / "secret.db"),
        "rel.md",
        None,
    ):
        results = await _call(
            options,
            "PreToolUse",
            {"tool_name": "Read", "tool_input": {"file_path": bad}},
        )
        assert _denied(results), bad


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


def test_prompt_contains_request_and_relative_path() -> None:
    prompt = build_prompt(NAME, "下痢の質問の文をやさしくして")
    assert "下痢の質問の文をやさしくして" in prompt
    assert f"skills/{NAME}/SKILL.md" in prompt
    assert ".claude" not in prompt
    assert "version" in prompt


@pytest.mark.parametrize("name", [NAME, "regimen-capox", "report-format-default"])
def test_prompt_itself_passes_h1(name: str) -> None:
    assert detect_identifiers(build_prompt(name, "質問を1つ足して")) == []


FOLFOX_KEYS = ("numbness", "diarrhea", "stomatitis", "nausea_appetite", "fever")


def test_prompt_lists_current_keys_and_regimen_rules() -> None:
    prompt = build_prompt(
        NAME, "口内炎は、食事がとれたかも次から聞いて", question_keys=FOLFOX_KEYS
    )
    assert "numbness, diarrhea, stomatitis, nausea_appetite, fever" in prompt
    assert "重ならない" in prompt
    for word in (
        "three_level",
        "temperature",
        "35.0〜42.0",
        "pump_removal_day",
        "fixed_rules",
        "question_key",
    ):
        assert word in prompt, word
    # 依頼文は最後（<<< >>> の中）
    assert prompt.rstrip().endswith(">>>")


def test_report_prompt_has_report_rules_and_no_question_rules() -> None:
    prompt = build_prompt("report-format-default", "引用を20件までにして")
    assert "sections" in prompt and "quotes_max_items" in prompt
    assert "answer_type" not in prompt


def test_system_prompt_has_common_rules() -> None:
    for word in ("PRO-CTCAE", "本文", "name と version", "理由"):
        assert word in EDITOR_SYSTEM_PROMPT, word


@pytest.mark.parametrize(
    "request_text",
    ["口内炎は、食事がとれたかも次から聞いて", "質問を1つ足して", "下痢の質問を短く"],
)
def test_prompt_with_keys_passes_h1(request_text: str) -> None:
    for name, keys in (
        (NAME, FOLFOX_KEYS),
        ("regimen-capox", (*FOLFOX_KEYS, "hand_foot")),
        ("report-format-default", ()),
    ):
        prompt = build_prompt(name, request_text, question_keys=keys)
        assert detect_identifiers(prompt) == [], name


async def test_h1_hook_passes_demo_prompt_and_blocks_name(work_root: Path) -> None:
    logger = MemoryLogger()
    options = _options(work_root, logger)
    demo = build_prompt(
        NAME, "口内炎は、食事がとれたかも次から聞いて", question_keys=FOLFOX_KEYS
    )
    assert await _call(options, "UserPromptSubmit", {"prompt": demo}) == [{}]
    bad = build_prompt(NAME, "磯鷲さんの口内炎の質問", question_keys=FOLFOX_KEYS)
    [blocked] = await _call(options, "UserPromptSubmit", {"prompt": bad})
    assert blocked["decision"] == "block"


def test_prompt_rejects_bad_name() -> None:
    with pytest.raises(ValueError):
        build_prompt("../etc", "x")


# ---------------------------------------------------------------------------
# SdkSkillEditor（偽の query）
# ---------------------------------------------------------------------------


def _result() -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=900,
        duration_api_ms=800,
        is_error=False,
        num_turns=4,
        session_id="s",
        total_cost_usd=0.12,
        usage={"input_tokens": 30, "output_tokens": 7},
    )


class FakeQuery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ClaudeAgentOptions]] = []

    def __call__(self, *, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator:
        self.calls.append((prompt, options))

        async def gen() -> AsyncIterator[Any]:
            yield object()
            yield _result()

        return gen()


async def test_sdk_editor_runs_query_with_options(work_root: Path) -> None:
    fake = FakeQuery()
    editor = SdkSkillEditor(get_settings(), query_fn=fake)
    assert isinstance(editor, SkillEditor)
    logger = MemoryLogger()
    with logging_to(logger):
        stats = await editor.edit(work_root, NAME, "下痢の質問を短く")
    assert stats == RunStats(
        duration_ms=900, num_turns=4, tokens_in=30, tokens_out=7, cost_usd=0.12
    )
    prompt, options = fake.calls[0]
    assert prompt == build_prompt(NAME, "下痢の質問を短く")
    assert options.cwd == str(work_root)
    # Hook の記録は logging_to で渡したロガーに入る
    await _call(options, "PreToolUse", {"tool_name": "Bash", "tool_input": {}})
    assert "hook_h4_deny" in logger.names()


async def test_sdk_editor_without_logger_uses_memory_logger(work_root: Path) -> None:
    fake = FakeQuery()
    await SdkSkillEditor(query_fn=fake).edit(work_root, NAME, "下痢の質問を短く")
    assert len(fake.calls) == 1


def test_logging_to_restores_previous_logger() -> None:
    outer, inner = MemoryLogger(), MemoryLogger()
    with logging_to(outer):
        with logging_to(inner):
            assert current_logger() is inner
        assert current_logger() is outer
    assert current_logger() is not outer


def test_cli_command_disables_session_persistence(work_root: Path) -> None:
    # 依頼文・Skill の本文を ~/.claude/projects/ に残さない（pipeline と同じ）
    from claude_agent_sdk._internal.transport.subprocess_cli import (
        SubprocessCLITransport,
    )

    options = build_options(work_root, get_settings(), MemoryLogger(), skill_name=NAME)
    transport = SubprocessCLITransport(prompt="x", options=options)
    transport._cli_path = "claude"  # 起動はしない（引数を組み立てるだけ）
    command = transport._build_command()
    assert "--no-session-persistence" in command
    # ファイルの設定（~/.claude/settings.json・.claude/settings.json）を読まない
    assert "--setting-sources=" in command


async def test_editor_h3_logs_as_h3(work_root: Path) -> None:
    logger = MemoryLogger()
    options = _options(work_root, logger)
    target = work_copy_path(work_root, NAME)
    for path in (target, work_root / ".claude" / "skills" / NAME / "SKILL.md"):
        await _call(
            options,
            "PreToolUse",
            {"tool_name": "Edit", "tool_input": {"file_path": str(path)}},
        )
    assert [r["decision"] for r in logger.find("hook_h3_allow")] == ["allow"]
    [deny] = logger.find("hook_h3_deny")
    assert deny["hook_name"] == "H3"
    assert deny["decision"] == "deny:outside_work_copy"


# ---------------------------------------------------------------------------
# SDK の失敗（ResultError など）でも費用・トークン数を残して投げ直す
# ---------------------------------------------------------------------------


def _error_result(subtype: str) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=4000,
        duration_api_ms=3500,
        is_error=True,
        num_turns=12,
        session_id="s",
        total_cost_usd=0.61,
        usage={"input_tokens": 9000, "output_tokens": 800},
    )


def _failing_query(result: ResultMessage | None, exc: Exception):
    async def fake_query(*, prompt: str, options: ClaudeAgentOptions):
        if result is not None:
            yield result
        raise exc

    return fake_query


@pytest.mark.parametrize(
    ("subtype", "code"),
    [("error_max_budget_usd", "max_budget"), ("error_max_turns", "max_turns")],
)
async def test_sdk_editor_failure_keeps_stats_and_reraises(
    work_root: Path, subtype: str, code: str
) -> None:
    exc = ResultError(
        "Claude Code returned an error result: 秘密", {"subtype": subtype}
    )
    editor = SdkSkillEditor(
        get_settings(), query_fn=_failing_query(_error_result(subtype), exc)
    )
    logger = MemoryLogger()
    with logging_to(logger), pytest.raises(RunFailedError) as info:
        await editor.edit(work_root, NAME, "下痢の質問を短く")
    assert info.value.cause is exc
    assert info.value.stats == RunStats(
        duration_ms=4000, num_turns=12, tokens_in=9000, tokens_out=800, cost_usd=0.61
    )
    assert sdk_error_code(info.value) == code
    [failed] = logger.find("editor_failed")
    assert failed["decision"] == code
    assert (failed["duration_ms"], failed["tokens_in"], failed["tokens_out"]) == (
        4000,
        9000,
        800,
    )
    assert failed["cost_usd"] == pytest.approx(0.61)
    assert "秘密" not in repr(logger.records)


async def test_sdk_editor_failure_without_result_logs_zero_stats(
    work_root: Path,
) -> None:
    from claude_agent_sdk import CLIConnectionError

    exc = CLIConnectionError("cannot connect")
    editor = SdkSkillEditor(get_settings(), query_fn=_failing_query(None, exc))
    logger = MemoryLogger()
    with logging_to(logger), pytest.raises(RunFailedError) as info:
        await editor.edit(work_root, NAME, "下痢の質問を短く")
    assert info.value.stats == RunStats()
    [failed] = logger.find("editor_failed")
    assert failed["decision"] == "sdk_error" and failed["cost_usd"] == 0.0


async def test_sdk_editor_does_not_wrap_other_exceptions(work_root: Path) -> None:
    editor = SdkSkillEditor(
        get_settings(), query_fn=_failing_query(None, RuntimeError("bug"))
    )
    with pytest.raises(RuntimeError):
        await editor.edit(work_root, NAME, "下痢の質問を短く")


async def test_sdk_editor_removes_session_files(
    work_root: Path, tmp_path: Path
) -> None:
    """書き換えの後に ~/.claude/projects/<cwd>/<session>/ を消す（spec 13.3）。"""
    sid = "0b6f2a4e-3c1d-4e5f-9a7b-8c9d0e1f2a3b"
    projects = tmp_path / "projects"
    session = projects / "-tmp-work" / sid / "subagents"
    session.mkdir(parents=True)

    async def fake_query(*, prompt: str, options: ClaudeAgentOptions):
        yield dataclasses.replace(_result(), session_id=sid)

    editor = SdkSkillEditor(get_settings(), query_fn=fake_query, projects_root=projects)
    await editor.edit(work_root, NAME, "下痢の質問を短く")
    assert not session.parent.exists()
