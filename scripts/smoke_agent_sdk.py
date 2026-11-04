"""T03: Agent SDK の前提を実際の API で確かめる（症例は使わない。ダミー文のみ）。

実行（先生が Claude Code のプロンプトで）:
    ! .venv/bin/python scripts/smoke_agent_sdk.py

確かめる7点（結果は docs/eval/smoke-<日付>.json に書く。文面は残さない）:
  1. UserPromptSubmit が query() の最初のプロンプトで発火し、送信を止められるか（H1 の前提）
  2. サブエージェントが呼んだカスタムツールにも PreToolUse が掛かるか（H2 の前提）
  3. setting_sources=["project"] + skills で cwd 配下の .claude/skills/<name>/SKILL.md が読まれるか
  4. max_turns とタイムアウトで止まり、例外を捕まえられるか（フォールバックの前提）
  5. サブエージェント起動ツールの名前（"Agent" か "Task" か）と、init が報告するツール一覧
  6. H2 の deny（PreToolUse の permissionDecision: "deny" と理由）の後に呼び直しが来て、
     実物の emit_timeline（build_server・EMIT_TIMELINE_SCHEMA・検査）が受け付け、
     ResultMessage.subtype が success で終わるか（小さな合成の入力。自由記載1件）
  7. extra_args={"no-session-persistence": None} の query で、~/.claude/projects/<cwd の
     符号化名>/ の *.jsonl が増えないか（フラグ無しの対照で符号化名の推定も確かめる）

6・7 の結果には件数・コード・subtype だけを書く（モデルの文・例外の本文は書かない）。
import しても API は呼ばない（.env も読まない。main() だけが読む）。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import sys
import tempfile
import textwrap
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from claude_agent_sdk import (  # noqa: E402
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from tsutae.config import (  # noqa: E402
    REPO_ROOT,
    SKILLS_HOME,
    Settings,
    get_settings,
    has_api_key,
    load_env_file,
)
from tsutae.pipeline.hooks import build_hooks  # noqa: E402
from tsutae.pipeline.logs import MemoryLogger  # noqa: E402
from tsutae.pipeline.orchestrator import (  # noqa: E402
    NO_SESSION_PERSISTENCE,
    build_options,
)
from tsutae.pipeline.tools import EMIT_TIMELINE_TOOL, RunCollector  # noqa: E402
from tsutae.schemas import (  # noqa: E402
    CourseSchedule,
    MaskedEntry,
    PipelineInput,
    PreparedInput,
)

HookFn = Callable[[Any, str | None, Any], Awaitable[dict[str, Any]]]
CODEWORD = "HAMAGURI-42"
RESULTS: dict[str, Any] = {}


def _settings() -> Settings:
    """main() が .env を読んだ後の設定（import の時点では読まない）。"""
    return get_settings()


def record(name: str, ok: bool, **detail: Any) -> None:
    RESULTS[name] = {"ok": ok, **detail}
    mark = "OK " if ok else "NG "
    print(f"[{mark}] {name}: {json.dumps(detail, ensure_ascii=False, default=str)}")


async def drain(prompt: str, options: ClaudeAgentOptions) -> dict[str, Any]:
    """メッセージを全部読み、要点だけ返す。"""
    out: dict[str, Any] = {
        "texts": [],
        "result": None,
        "init_tools": None,
        "error": None,
    }
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, SystemMessage) and msg.subtype == "init":
                out["init_tools"] = msg.data.get("tools")
                out["init_skills"] = msg.data.get("skills")
                out["init_agents"] = msg.data.get("agents")
            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        out["texts"].append(block.text)
            elif isinstance(msg, ResultMessage):
                out["result"] = {
                    "subtype": msg.subtype,
                    "is_error": msg.is_error,
                    "num_turns": msg.num_turns,
                    "terminal_reason": msg.terminal_reason,
                    "cost_usd": msg.total_cost_usd,
                    "result": (msg.result or "")[:200],
                }
    except Exception as exc:  # noqa: BLE001 — 失敗の形そのものを記録したい
        out["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return out


def base_options(cwd: Path, **kw: Any) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=str(cwd),
        setting_sources=["project"],
        model=_settings().subagent_model,
        permission_mode="dontAsk",
        max_turns=kw.pop("max_turns", 8),
        max_budget_usd=0.5,
        **kw,
    )


async def check1_user_prompt_submit(cwd: Path) -> None:
    fired: list[str] = []

    async def h1(inp: dict[str, Any], _tid: str | None, _ctx: Any) -> dict[str, Any]:
        fired.append(inp.get("hook_event_name", "?"))
        if "BLOCK-ME" in inp.get("prompt", ""):
            return {
                "decision": "block",
                "reason": "smoke: blocked by UserPromptSubmit",
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "suppressOriginalPrompt": True,
                },
            }
        return {}

    hooks = {"UserPromptSubmit": [HookMatcher(hooks=[h1], on_failure="block")]}
    blocked = await drain(
        "BLOCK-ME 次の単語を繰り返して: りんご",
        base_options(cwd, hooks=hooks, tools=[]),
    )
    n_blocked = len(fired)
    passed = await drain(
        "「りんご」とだけ答えて", base_options(cwd, hooks=hooks, tools=[])
    )
    model_answered_blocked = any("りんご" in t for t in blocked["texts"])
    record(
        "1_user_prompt_submit",
        n_blocked >= 1 and not model_answered_blocked and len(fired) > n_blocked,
        fired_on_blocked=n_blocked,
        fired_total=len(fired),
        model_answered_blocked_prompt=model_answered_blocked,
        blocked_result=blocked["result"],
        blocked_error=blocked["error"],
        passed_texts=[t[:40] for t in passed["texts"]],
    )


async def check2_and_5_subagent_tool(cwd: Path) -> None:
    seen: list[dict[str, Any]] = []
    calls: list[str] = []

    @tool("ping", "smoke 用。必ず呼ぶこと。", {"word": str})
    async def ping(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args.get("word", ""))
        return {"content": [{"type": "text", "text": "pong"}]}

    server = create_sdk_mcp_server("smoke", tools=[ping])

    async def pre(inp: dict[str, Any], _tid: str | None, _ctx: Any) -> dict[str, Any]:
        seen.append(
            {
                "tool": inp.get("tool_name"),
                "agent_id": bool(inp.get("agent_id")),
                "agent_type": inp.get("agent_type"),
            }
        )
        return {}

    agents = {
        "pinger": AgentDefinition(
            description="ping ツールを呼ぶだけの係",
            prompt="mcp__smoke__ping を word='hello' で1回呼び、結果を一言で返す。",
            tools=["mcp__smoke__ping"],
            model=_settings().subagent_model,
        )
    }
    opts = base_options(
        cwd,
        mcp_servers={"smoke": server},
        agents=agents,
        allowed_tools=["Agent", "Task", "mcp__smoke__ping"],
        hooks={"PreToolUse": [HookMatcher(hooks=[pre], on_failure="block")]},
    )
    out = await drain(
        "サブエージェント pinger を起動して ping を呼ばせ、その結果を報告して。"
        "あなた自身は ping を呼ばないこと。",
        opts,
    )
    sub_ping = [s for s in seen if s["tool"] == "mcp__smoke__ping" and s["agent_id"]]
    record(
        "2_pretooluse_on_subagent_tool",
        bool(sub_ping),
        pretooluse_seen=seen,
        ping_calls=len(calls),
        result=out["result"],
        error=out["error"],
    )
    tools = out.get("init_tools") or []
    spawn = [t for t in tools if t in ("Agent", "Task")]
    record(
        "5_subagent_tool_name",
        bool(spawn) or any(s["tool"] in ("Agent", "Task") for s in seen),
        spawn_tools_in_init=spawn,
        spawn_tools_in_hooks=sorted(
            {s["tool"] for s in seen if s["tool"] in ("Agent", "Task")}
        ),
        init_tools=tools,
        init_agents=out.get("init_agents"),
    )


async def check3_skills(cwd: Path) -> None:
    skill_dir = cwd / ".claude" / "skills" / "smoke-probe"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(f"""\
            ---
            name: smoke-probe
            description: smoke 用。合言葉を聞かれたらこの Skill を使う。
            version: 1
            ---
            合言葉は {CODEWORD} です。聞かれたらそのまま答える。
            """),
        encoding="utf-8",
    )
    out = await drain(
        "smoke-probe Skill を使って、合言葉だけを答えて。",
        base_options(cwd, skills=["smoke-probe"]),
    )
    found = any(CODEWORD in t for t in out["texts"]) or CODEWORD in str(out["result"])
    record(
        "3_skill_loaded_from_cwd",
        found,
        init_skills=out.get("init_skills"),
        result=out["result"],
        error=out["error"],
    )


async def check4_limits(cwd: Path) -> None:
    @tool("step", "smoke 用。呼ぶたびに次を呼べと言われる。", {"n": int})
    async def step(args: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": [
                {"type": "text", "text": f"次は n={args.get('n', 0) + 1} で呼ぶ"}
            ]
        }

    server = create_sdk_mcp_server("limits", tools=[step])
    out = await drain(
        "mcp__limits__step を n=0 から、言われるとおり10回続けて呼んで。",
        base_options(
            cwd,
            mcp_servers={"limits": server},
            allowed_tools=["mcp__limits__step"],
            max_turns=2,
        ),
    )
    max_turns_ok = bool(out["result"]) and (
        out["result"]["subtype"] != "success"
        or out["result"]["terminal_reason"] == "max_turns"
    )
    timed_out = False
    try:
        await asyncio.wait_for(
            drain("1から100まで数を書いて", base_options(cwd, tools=[])), timeout=0.5
        )
    except TimeoutError:
        timed_out = True
    record(
        "4_max_turns_and_timeout",
        max_turns_ok and timed_out,
        max_turns_result=out["result"],
        max_turns_error=out["error"],
        timeout_caught=timed_out,
    )


# ---------------------------------------------------------------------------
# 6. H2 の deny の後の呼び直しと、実物の emit_timeline の schema
# ---------------------------------------------------------------------------

# 症例は架空（自由記載1件）。日付は検査（day・record_date 以前）に合わせる
CHECK6_TEXT = "今日はお腹がゆるく、下痢が2回あった。"
CHECK6_EVENT: dict[str, Any] = {
    "entry_no": 1,
    "date": "2026-11-03",
    "day": 3,
    "course_no": 1,
    "term": "下痢",
    "question_key": None,
    "status": "present",
    "source_quote": "下痢が2回あった",
    "confidence": 0.9,
    "recalled": False,
    "by_proxy": False,
}
CHECK6_ARGS: dict[str, Any] = {"events": [CHECK6_EVENT], "contradictions": []}
CHECK6_MAX_TURNS = 6
CHECK6_MAX_BUDGET_USD = 0.3
CHECK6_DENY_REASON = (
    "smoke: 1回目の emit_timeline は検査で拒否した。"
    "引数を確かめて、同じ引数でもう一度呼び直す"
)
CHECK6_SYSTEM_PROMPT = (
    "あなたは smoke テストの係。指示されたツールを指示どおりの引数で呼ぶ。"
    "拒否やエラーが返ったら理由を読んで呼び直す。それ以外のことはしない。"
)


def synthetic_prepared() -> PreparedInput:
    """check 6 の入力（架空の1コース・1記録。質問は無し＝question_key は null）。"""
    schedule = CourseSchedule(
        course_no=1,
        infusion_date=date(2026, 11, 1),
        day1_date=date(2026, 11, 1),
        last_day_date=date(2026, 11, 14),
        pump_removal_date=date(2026, 11, 3),
        previous_infusion_date=None,
        delay_days=None,
    )
    entry = MaskedEntry(
        entry_no=1,
        record_date=date(2026, 11, 3),
        day=3,
        by_proxy=False,
        too_sick=False,
        masked_free_text=CHECK6_TEXT,
    )
    pipeline_input = PipelineInput(
        regimen="FOLFOX",
        regimen_skill_version="regimen-folfox@1",
        report_skill_version="report-format-default@1",
        schedule=schedule,
        questions=[],
        entries=[entry],
    )
    return PreparedInput(
        input=pipeline_input, entry_ids={1: 1}, masked_texts={1: CHECK6_TEXT}
    )


def check6_prompt() -> str:
    return (
        f"テスト用。{EMIT_TIMELINE_TOOL} を次の JSON の引数で呼ぶ。"
        "拒否やエラーが返ったら、理由を読んで呼び直す。"
        "受け付けられたら「完了」とだけ答えて終える。\n"
        + json.dumps(CHECK6_ARGS, ensure_ascii=False)
    )


class DenyOnceState:
    """deny-once の Hook が見た呼び出しの数（calls）と拒否した数（denied）。

    dataclass にしない（importlib で sys.modules に入れずに読むテストでも動くように）。
    """

    def __init__(self) -> None:
        self.calls = 0
        self.denied = 0


def make_deny_once(tool_name: str, reason: str) -> tuple[HookFn, DenyOnceState]:
    """tool_name の1回目だけを PreToolUse で deny する Hook（H2 の deny の代わり）。"""
    state = DenyOnceState()

    async def deny_once(inp: Any, _tid: str | None, _ctx: Any) -> dict[str, Any]:
        if not isinstance(inp, Mapping) or inp.get("tool_name") != tool_name:
            return {}
        state.calls += 1
        if state.denied:
            return {}
        state.denied += 1
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return deny_once, state


def check6_options(
    cwd: Path, collector: RunCollector, logger: MemoryLogger, deny_hook: HookFn
) -> ClaudeAgentOptions:
    """orchestrator.build_options を元に、小さく安くしたもの。

    実物の build_server・DISALLOWED_TOOLS・permission_mode・no-session-persistence と、
    実物の Hook（H1・H4・H2・trace）を保つ。deny_hook を PreToolUse の先頭に足す。
    サブエージェント・Skill は使わない（主エージェントが emit_timeline を直接呼ぶ）。
    """
    settings = _settings()
    prepared = synthetic_prepared()
    base = build_options(prepared, collector, logger, settings, SKILLS_HOME)
    hooks = build_hooks(
        masked_texts=prepared.masked_texts,
        logger=logger,
        allowed_tools=(EMIT_TIMELINE_TOOL,),
        allowed_subagents=(),
    )
    deny_matcher = HookMatcher(hooks=[deny_hook], on_failure="block")
    return dataclasses.replace(
        base,
        cwd=str(cwd),
        skills=None,
        agents=None,
        model=settings.subagent_model,
        allowed_tools=[EMIT_TIMELINE_TOOL],
        hooks={**hooks, "PreToolUse": [deny_matcher, *hooks["PreToolUse"]]},
        max_turns=CHECK6_MAX_TURNS,
        max_budget_usd=CHECK6_MAX_BUDGET_USD,
        system_prompt=CHECK6_SYSTEM_PROMPT,
    )


def judge_check6(
    *,
    denied: int,
    hook_calls: int,
    handler_calls: int,
    accepted: bool,
    subtype: str | None,
) -> tuple[bool, str]:
    """OK/NG と短い理由。deny は1回、呼び直しが来て、実物が受け付け、success で終わる。"""
    if denied != 1:
        return False, "no_deny" if denied == 0 else "denied_more_than_once"
    if hook_calls < 2:
        return False, "no_retry_after_deny"
    if handler_calls < 1 or not accepted:
        return False, "timeline_not_accepted"
    if subtype != "success":
        return False, f"result_not_success:{subtype}"
    return True, "ok"


def _result_summary(out: dict[str, Any]) -> dict[str, Any] | None:
    """drain の result から文（result）を除いたもの。"""
    result = out.get("result")
    if not result:
        return None
    return {k: v for k, v in result.items() if k != "result"}


def _error_type(out: dict[str, Any]) -> str | None:
    """drain の error（"型名: 本文"）の型名だけ。"""
    error = out.get("error")
    return error.split(":", 1)[0] if error else None


async def check6_retry_after_deny(_cwd: Path) -> None:
    # 別の一時ディレクトリ（check 3 が置いた .claude/skills を読ませない。費用を小さく）
    logger = MemoryLogger()
    collector = RunCollector.from_prepared(synthetic_prepared(), logger=logger)
    deny_hook, state = make_deny_once(EMIT_TIMELINE_TOOL, CHECK6_DENY_REASON)
    with tempfile.TemporaryDirectory(prefix="tsutae-smoke6-") as work:
        options = check6_options(Path(work), collector, logger, deny_hook)
        out = await drain(check6_prompt(), options)
    summary = _result_summary(out)
    ok, reason = judge_check6(
        denied=state.denied,
        hook_calls=state.calls,
        handler_calls=collector.timeline_calls,
        accepted=collector.timeline is not None,
        subtype=summary["subtype"] if summary else None,
    )
    record(
        "6_retry_after_h2_deny",
        ok,
        reason=reason,
        denied=state.denied,
        hook_calls=state.calls,
        handler_calls=collector.timeline_calls,
        timeline_accepted=collector.timeline is not None,
        hook_decisions=[
            f"{r['event']}:{r.get('decision')}"
            for r in logger.records
            if r["event"].startswith(("hook_h", "emit_"))
        ],
        result=summary,
        error_type=_error_type(out),
    )


# ---------------------------------------------------------------------------
# 7. 会話の記録（~/.claude/projects/<符号化した cwd>/*.jsonl）が残らないか
# ---------------------------------------------------------------------------


def encode_project_name(path: str) -> str:
    """CLI が ~/.claude/projects/ の下に作るディレクトリ名の推定（英数字以外を - に）。

    既存のディレクトリ名（/Users/x/Development/tsutae → -Users-x-Development-tsutae）
    から推定した規則。
    """
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def projects_root(env: Mapping[str, str] | None = None) -> Path:
    """会話の記録の置き場所（CLAUDE_CONFIG_DIR があればその下）。"""
    environ = os.environ if env is None else env
    config_dir = environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".claude"
    return base / "projects"


def session_dirs(root: Path, cwd: Path) -> list[Path]:
    """cwd の会話の記録のディレクトリの候補（cwd・実パスの符号化名か、cwd の名前で終わる）。"""
    if not root.is_dir():
        return []
    names = {encode_project_name(str(cwd)), encode_project_name(str(cwd.resolve()))}
    tail = encode_project_name(cwd.name)
    return sorted(
        p
        for p in root.iterdir()
        if p.is_dir() and (p.name in names or p.name.endswith(tail))
    )


def count_session_files(root: Path, cwd: Path) -> int:
    """cwd の会話の記録（*.jsonl。サブエージェントの分も含む）の数。無ければ 0。"""
    return sum(len(list(d.rglob("*.jsonl"))) for d in session_dirs(root, cwd))


def judge_check7(before: int, after: int) -> tuple[bool, str]:
    """増えていなければ OK（ディレクトリが見つからなくても「増えていない」とする）。"""
    return (True, "not_increased") if after <= before else (False, "increased")


def no_persist_options(cwd: Path, *, persist: bool) -> ClaudeAgentOptions:
    """最小の query の options。persist=False なら pipeline と同じフラグを付ける。"""
    extra = {} if persist else dict(NO_SESSION_PERSISTENCE)
    return base_options(cwd, tools=[], max_turns=1, extra_args=extra)


async def _count_around_query(cwd: Path, *, persist: bool) -> dict[str, Any]:
    root = projects_root()
    before = count_session_files(root, cwd)
    out = await drain("「はい」とだけ答えて", no_persist_options(cwd, persist=persist))
    return {
        "before": before,
        "after": count_session_files(root, cwd),
        "dir_found": bool(session_dirs(root, cwd)),
        "result": _result_summary(out),
        "error_type": _error_type(out),
    }


async def check7_no_session_persistence(_cwd: Path) -> None:
    # 1〜5 はフラグ無しで共有の cwd に記録を書くので、新しい一時ディレクトリを使う
    with (
        tempfile.TemporaryDirectory(prefix="tsutae-smoke7-") as target,
        tempfile.TemporaryDirectory(prefix="tsutae-smoke7c-") as control,
    ):
        flagged = await _count_around_query(Path(target), persist=False)
        # 対照（フラグ無し）。増えれば符号化名の推定が合っている（判定には使わない）
        unflagged = await _count_around_query(Path(control), persist=True)
    ok, reason = judge_check7(flagged["before"], flagged["after"])
    record(
        "7_no_session_persistence",
        ok,
        reason=reason,
        with_flag=flagged,
        control_without_flag=unflagged,
        control_detected=unflagged["after"] > unflagged["before"],
        projects_root_exists=projects_root().is_dir(),
    )


async def main() -> int:
    load_env_file()
    if not has_api_key():
        print("ANTHROPIC_API_KEY がありません。.env を確認してください。")
        return 2
    with tempfile.TemporaryDirectory(prefix="tsutae-smoke-") as tmp:
        cwd = Path(tmp)
        for check in (
            check1_user_prompt_submit,
            check2_and_5_subagent_tool,
            check3_skills,
            check4_limits,
            check6_retry_after_deny,
            check7_no_session_persistence,
        ):
            try:
                await check(cwd)
            except Exception as exc:  # noqa: BLE001
                record(
                    check.__name__, False, crashed=f"{type(exc).__name__}: {exc}"[:300]
                )
    out_dir = REPO_ROOT / "docs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    path = out_dir / f"smoke-{stamp}.json"
    path.write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    ok = all(r["ok"] for r in RESULTS.values())
    print(f"\n結果: {'全て OK' if ok else '一部 NG'} → {path.relative_to(REPO_ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
