"""scripts/smoke_agent_sdk.py の、API を呼ばずに確かめられる部分（check 6・7）。

options の組み立て・Hook・判定の関数・会話の記録の数え方だけを試す。query は呼ばない
（main() と check* は動かさない。drain を偽物に替えたときだけ check を回す）。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk._internal.transport.subprocess_cli import (
    SubprocessCLITransport,
)

from tsutae.config import REPO_ROOT, get_settings
from tsutae.masking import detect_identifiers
from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.orchestrator import DISALLOWED_TOOLS
from tsutae.pipeline.tools import (
    EMIT_TIMELINE,
    EMIT_TIMELINE_TOOL,
    SERVER_NAME,
    RunCollector,
    build_tools,
    handle_emit_timeline,
)

SCRIPT = REPO_ROOT / "scripts" / "smoke_agent_sdk.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_agent_sdk", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load()
    monkeypatch.setattr(module, "RESULTS", {})
    return module


def _collector(smoke: ModuleType) -> tuple[RunCollector, MemoryLogger]:
    logger = MemoryLogger()
    return RunCollector.from_prepared(smoke.synthetic_prepared(), logger=logger), logger


def _options(smoke: ModuleType, tmp_path: Path) -> tuple[Any, Any, MemoryLogger]:
    collector, logger = _collector(smoke)
    hook, state = smoke.make_deny_once(EMIT_TIMELINE_TOOL, smoke.CHECK6_DENY_REASON)
    return smoke.check6_options(tmp_path, collector, logger, hook), state, logger


async def _pre_tool_use(options: ClaudeAgentOptions, data: dict) -> list[dict]:
    results = []
    for matcher in options.hooks["PreToolUse"]:  # type: ignore[index]
        if matcher.matcher is not None and data["tool_name"] not in (
            matcher.matcher.split("|")
        ):
            continue
        for hook in matcher.hooks:
            results.append(await hook(data, None, None))
    return results


def _denied(results: list[dict]) -> bool:
    return any(
        r.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        for r in results
    )


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def test_import_does_not_read_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # import 時に .env を読むと、テストのプロセスにキーが入り api のテストが走ってしまう
    calls: list[object] = []
    monkeypatch.setattr(
        "tsutae.config.load_env_file", lambda *a, **k: calls.append(a) or False
    )
    module = _load()
    assert calls == []
    assert module.load_env_file is not None  # main() だけが呼ぶ


# ---------------------------------------------------------------------------
# check 6: 合成の入力・options・Hook
# ---------------------------------------------------------------------------


def test_synthetic_args_pass_real_schema_and_checks(smoke: ModuleType) -> None:
    collector, _ = _collector(smoke)
    [emit_timeline, _] = build_tools(collector)
    assert emit_timeline.name == EMIT_TIMELINE
    jsonschema.validate(instance=smoke.CHECK6_ARGS, schema=emit_timeline.input_schema)
    result = handle_emit_timeline(smoke.CHECK6_ARGS, collector)
    assert not result.get("is_error"), result
    assert collector.timeline is not None and len(collector.timeline.events) == 1


def test_synthetic_quote_is_in_the_free_text(smoke: ModuleType) -> None:
    assert smoke.CHECK6_EVENT["source_quote"] in smoke.CHECK6_TEXT
    prepared = smoke.synthetic_prepared()
    assert prepared.masked_texts == {1: smoke.CHECK6_TEXT}
    assert len(prepared.input.entries) == 1


async def test_check6_prompt_passes_h1(smoke: ModuleType, tmp_path: Path) -> None:
    prompt = smoke.check6_prompt()
    assert detect_identifiers(prompt) == []  # orchestrator の事前の検査と同じ
    options, _, logger = _options(smoke, tmp_path)
    [h1] = options.hooks["UserPromptSubmit"][0].hooks
    assert await h1({"prompt": prompt}, None, None) == {}
    assert logger.find("hook_h1_allow")


def test_check6_options_are_small_and_close_to_build_options(
    smoke: ModuleType, tmp_path: Path
) -> None:
    options, _, _ = _options(smoke, tmp_path)
    assert options.cwd == str(tmp_path)
    assert options.model == get_settings().subagent_model
    assert options.allowed_tools == [EMIT_TIMELINE_TOOL]
    assert options.disallowed_tools == list(DISALLOWED_TOOLS)
    assert options.permission_mode == "dontAsk"
    assert options.extra_args == {"no-session-persistence": None}
    assert list(options.mcp_servers) == [SERVER_NAME]  # type: ignore[arg-type]
    assert options.agents is None and options.skills is None
    assert options.max_turns == smoke.CHECK6_MAX_TURNS <= 8
    assert options.max_budget_usd == smoke.CHECK6_MAX_BUDGET_USD <= 0.5
    assert options.system_prompt == smoke.CHECK6_SYSTEM_PROMPT
    assert set(options.hooks) >= {"UserPromptSubmit", "PreToolUse"}  # type: ignore


def test_check6_cli_command(smoke: ModuleType, tmp_path: Path) -> None:
    options, _, _ = _options(smoke, tmp_path)
    transport = SubprocessCLITransport(prompt="x", options=options)
    transport._cli_path = "claude"  # 起動はしない（引数を組み立てるだけ）
    cmd = transport._build_command()
    assert "--no-session-persistence" in cmd
    assert cmd[cmd.index("--max-turns") + 1] == str(smoke.CHECK6_MAX_TURNS)
    assert "--max-budget-usd" in cmd


async def test_check6_hooks_deny_first_then_allow_real_h2(
    smoke: ModuleType, tmp_path: Path
) -> None:
    options, state, logger = _options(smoke, tmp_path)
    call = {"tool_name": EMIT_TIMELINE_TOOL, "tool_input": smoke.CHECK6_ARGS}
    first = await _pre_tool_use(options, call)
    reasons = [
        r["hookSpecificOutput"]["permissionDecisionReason"]
        for r in first
        if r.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    ]
    assert reasons == [smoke.CHECK6_DENY_REASON]  # 実物の H2・H4 は通す
    second = await _pre_tool_use(options, call)
    assert not _denied(second)
    assert (state.calls, state.denied) == (2, 1)
    assert logger.find("hook_h2_allow") and not logger.find("hook_h2_deny")


async def test_check6_real_h2_still_denies_bad_quote(
    smoke: ModuleType, tmp_path: Path
) -> None:
    options, _, logger = _options(smoke, tmp_path)
    bad = {"events": [{**smoke.CHECK6_EVENT, "source_quote": "吐き気があった"}]}
    call = {"tool_name": EMIT_TIMELINE_TOOL, "tool_input": bad}
    await _pre_tool_use(options, call)
    assert _denied(await _pre_tool_use(options, call))
    assert logger.find("hook_h2_deny")


async def test_deny_once_ignores_other_tools(smoke: ModuleType) -> None:
    hook, state = smoke.make_deny_once(EMIT_TIMELINE_TOOL, "r")
    assert await hook({"tool_name": "Skill"}, None, None) == {}
    assert await hook("not a dict", None, None) == {}
    assert (state.calls, state.denied) == (0, 0)
    denied = await hook({"tool_name": EMIT_TIMELINE_TOOL}, None, None)
    assert denied["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "r",
    }
    assert await hook({"tool_name": EMIT_TIMELINE_TOOL}, None, None) == {}
    assert (state.calls, state.denied) == (2, 1)


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({}, (True, "ok")),
        ({"denied": 0}, (False, "no_deny")),
        ({"denied": 2}, (False, "denied_more_than_once")),
        ({"hook_calls": 1}, (False, "no_retry_after_deny")),
        ({"handler_calls": 0}, (False, "timeline_not_accepted")),
        ({"accepted": False}, (False, "timeline_not_accepted")),
        (
            {"subtype": "error_max_turns"},
            (False, "result_not_success:error_max_turns"),
        ),
        ({"subtype": None}, (False, "result_not_success:None")),
    ],
)
def test_judge_check6(smoke: ModuleType, kw: dict, expected: tuple) -> None:
    base = {
        "denied": 1,
        "hook_calls": 2,
        "handler_calls": 1,
        "accepted": True,
        "subtype": "success",
    }
    assert smoke.judge_check6(**{**base, **kw}) == expected


async def test_check6_records_codes_only(
    smoke: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # drain を偽物に: Hook を2回通し（1回目は deny）、結果は success
    async def fake_drain(prompt: str, options: ClaudeAgentOptions) -> dict:
        call = {"tool_name": EMIT_TIMELINE_TOOL, "tool_input": smoke.CHECK6_ARGS}
        await _pre_tool_use(options, call)
        await _pre_tool_use(options, call)
        return {
            "texts": ["完了 秘密の文"],
            "result": {"subtype": "success", "num_turns": 3, "result": "秘密の文"},
            "error": None,
        }

    monkeypatch.setattr(smoke, "drain", fake_drain)
    await smoke.check6_retry_after_deny(tmp_path)
    [(name, rec)] = smoke.RESULTS.items()
    assert name == "6_retry_after_h2_deny"
    # 偽物はツールの本体を呼ばないので、受け付けは無い
    assert (rec["ok"], rec["reason"]) == (False, "timeline_not_accepted")
    assert (rec["denied"], rec["hook_calls"], rec["handler_calls"]) == (1, 2, 0)
    assert rec["result"] == {"subtype": "success", "num_turns": 3}
    assert "秘密" not in repr(rec)


# ---------------------------------------------------------------------------
# check 7: 会話の記録の数え方
# ---------------------------------------------------------------------------


def test_encode_project_name_matches_existing_dirs(smoke: ModuleType) -> None:
    assert (
        smoke.encode_project_name("/Users/x/Development/tsutae")
        == "-Users-x-Development-tsutae"
    )
    assert smoke.encode_project_name("/tmp/a_b.c") == "-tmp-a-b-c"


def test_projects_root(smoke: ModuleType, tmp_path: Path) -> None:
    assert smoke.projects_root({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == (
        tmp_path / "projects"
    )
    assert smoke.projects_root({}) == Path.home() / ".claude" / "projects"


def _session(root: Path, cwd: Path, name: str, *, encoded: str | None = None) -> Path:
    folder = root / (encoded or smoke_encode(str(cwd)))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", "utf-8")
    return path


def smoke_encode(path: str) -> str:
    """テスト側の独立した符号化（英数字以外を -）。"""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def test_count_session_files(smoke: ModuleType, tmp_path: Path) -> None:
    root = tmp_path / "projects"
    cwd = tmp_path / "work" / "tsutae-smoke7-ab_c1"
    cwd.mkdir(parents=True)
    assert smoke.count_session_files(root, cwd) == 0  # root も無い
    root.mkdir()
    assert smoke.count_session_files(root, cwd) == 0
    _session(root, cwd, "s1.jsonl")
    _session(root, cwd, "s1/subagents/a.jsonl")
    _session(root, cwd, "note.txt")
    # 実パスの前に /private が付くなど、名前の末尾だけ一致するもの
    _session(root, cwd, "s2.jsonl", encoded="-private" + smoke_encode(str(cwd)))
    _session(root, cwd, "x.jsonl", encoded="-Users-other-project")
    assert smoke.count_session_files(root, cwd) == 3
    assert len(smoke.session_dirs(root, cwd)) == 2


def test_session_dirs_follow_symlinked_cwd(smoke: ModuleType, tmp_path: Path) -> None:
    real = tmp_path / "real" / "tsutae-smoke7-xyz"
    real.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real.parent)
    cwd = link / real.name
    root = tmp_path / "projects"
    _session(root, cwd, "a.jsonl", encoded=smoke_encode(str(real.resolve())))
    assert smoke.count_session_files(root, cwd) == 1


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (0, 0, (True, "not_increased")),
        (3, 3, (True, "not_increased")),
        (3, 2, (True, "not_increased")),
        (0, 1, (False, "increased")),
    ],
)
def test_judge_check7(smoke: ModuleType, before, after, expected) -> None:
    assert smoke.judge_check7(before, after) == expected


def test_no_persist_options(smoke: ModuleType, tmp_path: Path) -> None:
    flagged = smoke.no_persist_options(tmp_path, persist=False)
    assert flagged.extra_args == {"no-session-persistence": None}
    assert flagged.max_turns == 1 and flagged.tools == []
    assert flagged.model == get_settings().subagent_model
    control = smoke.no_persist_options(tmp_path, persist=True)
    assert "no-session-persistence" not in control.extra_args


async def test_check7_judges_by_counts(
    smoke: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setattr(smoke, "projects_root", lambda env=None: root)

    # フラグ無しのときだけ記録を書く CLI の偽物
    async def fake_drain(prompt: str, options: ClaudeAgentOptions) -> dict:
        if "no-session-persistence" not in options.extra_args:
            _session(root, Path(str(options.cwd)), "s.jsonl")
        return {
            "texts": ["はい"],
            "result": {"subtype": "success", "result": "はい"},
            "error": None,
        }

    monkeypatch.setattr(smoke, "drain", fake_drain)
    await smoke.check7_no_session_persistence(tmp_path)
    rec = smoke.RESULTS["7_no_session_persistence"]
    assert (rec["ok"], rec["reason"]) == (True, "not_increased")
    assert rec["with_flag"]["before"] == rec["with_flag"]["after"] == 0
    assert rec["control_detected"] is True
    assert rec["control_without_flag"]["dir_found"] is True
    assert rec["with_flag"]["result"] == {"subtype": "success"}


def test_result_summary_and_error_type_drop_text(smoke: ModuleType) -> None:
    out = {"result": {"subtype": "success", "result": "文"}, "error": "ResultError: 文"}
    assert smoke._result_summary(out) == {"subtype": "success"}
    assert smoke._error_type(out) == "ResultError"
    assert smoke._result_summary({"result": None}) is None
    assert smoke._error_type({"error": None}) is None
