"""T03: Agent SDK の前提を実際の API で確かめる（症例は使わない。ダミー文のみ）。

実行（先生が Claude Code のプロンプトで）:
    ! .venv/bin/python scripts/smoke_agent_sdk.py

確かめる5点（結果は docs/eval/smoke-<日付>.json に書く。文面は残さない）:
  1. UserPromptSubmit が query() の最初のプロンプトで発火し、送信を止められるか（H1 の前提）
  2. サブエージェントが呼んだカスタムツールにも PreToolUse が掛かるか（H2 の前提）
  3. setting_sources=["project"] + skills で cwd 配下の .claude/skills/<name>/SKILL.md が読まれるか
  4. max_turns とタイムアウトで止まり、例外を捕まえられるか（フォールバックの前提）
  5. サブエージェント起動ツールの名前（"Agent" か "Task" か）と、init が報告するツール一覧
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from tsutae.config import (
    REPO_ROOT,
    get_settings,
    has_api_key,
    load_env_file,
)  # noqa: E402

load_env_file()

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

SETTINGS = get_settings()
CODEWORD = "HAMAGURI-42"
RESULTS: dict[str, Any] = {}


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
        model=SETTINGS.subagent_model,
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
            model=SETTINGS.subagent_model,
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


async def main() -> int:
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
