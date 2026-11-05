"""D4 レジメンの1往復（T94）のテスト用の偽物。Anthropic API は呼ばない。

- `ScriptChat`: RegimenChat の偽物。ツールの本体（chat_tools の handle_*）を順に呼び、
  ChatSession の結果を返す（Claude の代わり。API・dump_api_fixtures で使う）
- `ToolQuery`: `claude_agent_sdk.query` の偽物。CLI の代わりに options の Hook を呼び
  （依頼文に UserPromptSubmit＝H1、ツールごとに PreToolUse＝H4。H4 が拒めば呼ばない）、
  SDK MCP サーバー経由でツールを呼んでから ResultMessage を返す（SdkRegimenChat の
  組み立て・jsonschema・Hook のログの書き先ごと確かめる）。3つのツール以外の名前
  （"Bash" など）はそのままの名前で H4 に掛ける
- `call_tool`: SDK MCP サーバーのツールを呼ぶ。SDK の内部（`_request_handlers`）に頼るので
  テストだけで使う
- `ready_form`: 基本・投与スケジュール・注意する症状がそろい、質問は体温だけのフォーム
  （propose_questions の source=standard が受け付けられる形）
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
)
from mcp_types._types import CallToolRequestParams

from tsutae.regimen.chat_args import SERVER_NAME
from tsutae.regimen.chat_session import ChatSession
from tsutae.regimen.chat_tools import (
    handle_ask,
    handle_propose_questions,
    handle_set_fields,
)
from tsutae.regimen.chat_types import TurnInput, TurnResult
from tsutae.regimen.form import RegimenForm
from tsutae.schemas import RunStats

__all__ = [
    "DENIED",
    "FailingChat",
    "ScriptChat",
    "SlowChat",
    "ToolQuery",
    "call_tool",
    "change",
    "denied",
    "ready_form",
    "result_message",
    "run_hooks",
]

_HANDLERS = {
    "set_fields": handle_set_fields,
    "ask": handle_ask,
    "propose_questions": handle_propose_questions,
}


def change(
    field_ref: str, value: Any, source: str = "doctor_text"
) -> tuple[str, dict[str, Any]]:
    """set_fields の1つの欄の呼び出し（`("set_fields", {...})`）。"""
    return (
        "set_fields",
        {"changes": [{"field": field_ref, "value": value, "source": source}]},
    )


def ready_form() -> RegimenForm:
    """FOLFIRI＋BV の基本・薬・症状と、体温の質問だけ（症状は質問につながない）。"""
    from regimen_fixtures import folfiri_bv_data

    data = folfiri_bv_data()
    data["questions"] = [q for q in data["questions"] if q["key"] == "fever"]
    for row in data["side_effects"]:
        if row["question_key"] != "fever":
            row["question_key"] = None
    return RegimenForm.model_validate(data)


def _stats() -> RunStats:
    return RunStats(
        duration_ms=800, num_turns=3, tokens_in=40, tokens_out=8, cost_usd=0.04
    )


@dataclass
class ScriptChat:
    """ツールの本体を順に呼ぶ偽の chat。"""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    reply: str = "1コースを14日にしました"
    stats: RunStats = field(default_factory=_stats)
    seen: list[tuple[TurnInput, str]] = field(default_factory=list)
    before_return: Callable[[], Awaitable[None]] | None = None

    async def turn(self, draft: TurnInput, text: str) -> TurnResult:
        self.seen.append((draft, text))
        session = ChatSession(draft)
        for name, args in self.calls:
            _HANDLERS[name](args, session)
        if self.before_return is not None:
            await self.before_return()
        return session.result(self.reply, self.stats)


class SlowChat:
    """返らない chat（時間切れの確かめ）。"""

    async def turn(self, draft: TurnInput, text: str) -> TurnResult:
        await asyncio.sleep(5)
        raise AssertionError("ここには来ない")


class FailingChat:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def turn(self, draft: TurnInput, text: str) -> TurnResult:
        raise self.exc


def result_message(text: str | None = "1コースを14日にした") -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1200,
        duration_api_ms=1000,
        is_error=False,
        num_turns=3,
        session_id="s",
        total_cost_usd=0.05,
        usage={"input_tokens": 50, "output_tokens": 9},
        result=text,
    )


async def call_tool(options: ClaudeAgentOptions, name: str, args: dict) -> Any:
    """SDK MCP サーバーのツールを呼ぶ（SDK の内部の `_request_handlers` に頼る）。"""
    server = options.mcp_servers[SERVER_NAME]["instance"]  # type: ignore[index]
    entry = server._request_handlers["tools/call"]
    return await entry.handler(None, CallToolRequestParams(name=name, arguments=args))


async def run_hooks(
    options: ClaudeAgentOptions, event: str, data: dict[str, Any]
) -> list[dict[str, Any]]:
    """options の Hook（event の全て）を CLI の代わりに呼ぶ。"""
    results = []
    for matcher in (options.hooks or {}).get(event, []):  # type: ignore[call-overload]
        for hook in matcher.hooks:
            results.append(await hook(data, None, None))
    return results


def denied(results: list[dict[str, Any]]) -> bool:
    return any(
        r.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        or r.get("decision") == "block"
        for r in results
    )


DENIED = "denied_by_hook"


class ToolQuery:
    """Hook を通してツールを順に呼んでから ResultMessage を返す偽の query。"""

    def __init__(self, calls: list[tuple[str, dict]], result: Any = None) -> None:
        self.calls = calls
        self.result = result if result is not None else result_message()
        self.seen: list[tuple[str, ClaudeAgentOptions]] = []
        self.outputs: list[Any] = []

    def __call__(self, *, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator:
        self.seen.append((prompt, options))

        async def gen() -> AsyncIterator[Any]:
            cwd = Path(str(options.cwd))
            assert cwd.is_dir() and list(cwd.iterdir()) == []  # 空の一時ディレクトリ
            if denied(await run_hooks(options, "UserPromptSubmit", {"prompt": prompt})):
                self.outputs.append(DENIED)
                yield self.result
                return
            for name, args in self.calls:
                full = f"mcp__{SERVER_NAME}__{name}" if name in _HANDLERS else name
                data = {"tool_name": full, "tool_input": args}
                if denied(await run_hooks(options, "PreToolUse", data)):
                    self.outputs.append(DENIED)
                    continue
                self.outputs.append(await call_tool(options, name, args))
            yield AssistantMessage(content=[TextBlock(text="途中の文")], model="m")
            yield self.result

        return gen()
