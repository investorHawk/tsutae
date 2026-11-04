"""D4 レジメンの Claude の1往復（SdkRegimenChat。T94、architecture 9c「1往復」）。

- `build_options` は純関数（query は呼ばない）。skillchange の書き換え係（9b）と
  pipeline と同じ部品を使う:
  - cwd は空の一時ディレクトリ・`setting_sources=[]`（ファイルの設定・Skill を読まない）
  - `--no-session-persistence`（会話を ~/.claude/projects/ に残さない）・
    `env=NO_CLAUDE_MD_ENV`（開発用の CLAUDE.md を読まない）
  - `allowed_tools` は `REGIMEN_ALLOWED_TOOLS`（MCP の3つ）だけ、`disallowed_tools` は
    `REGIMEN_DISALLOWED_TOOLS`。Hook は H1（依頼文に二次検出）と H4（3つ以外を deny。
    サブエージェントは呼ばせない）
  - `max_turns`・`max_budget_usd` は設定（`regimen_max_turns`・`regimen_max_budget_usd`）
- `SdkRegimenChat.turn(draft, text)` は依頼文（chat_prompt）で query を最後まで読み、
  ツールが当てた受け皿（ChatSession）から `TurnResult` を返す。返答の文は
  ResultMessage.result（無ければ最後の AssistantMessage の文）
- SDK の失敗（ClaudeSDKError）は、直前の ResultMessage の費用・トークン数を添えた
  `RunFailedError` にして投げ直す（振り分けは chat_turn）
- Hook とツールのログの書き先は `logging_to(logger)`（contextvars。chat_turn が
  PipelineLogger(conn, "regimen_chat", draft_id) を設定する）。無ければ捨てる
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    HookMatcher,
    ResultMessage,
    TextBlock,
    query,
)

from tsutae.config import Settings, get_settings
from tsutae.pipeline.hooks import make_h1, make_h4
from tsutae.pipeline.logs import EventLogger
from tsutae.pipeline.orchestrator import NO_CLAUDE_MD_ENV, NO_SESSION_PERSISTENCE
from tsutae.pipeline.runner import RunFailedError, stats_from_result
from tsutae.regimen.chat_args import (
    ASK_TOOL,
    PROPOSE_QUESTIONS_TOOL,
    SERVER_NAME,
    SET_FIELDS_TOOL,
)
from tsutae.regimen.chat_prompt import SYSTEM_PROMPT, build_turn_prompt
from tsutae.regimen.chat_session import ChatSession, current_logger, logging_to
from tsutae.regimen.chat_tools import build_server
from tsutae.regimen.chat_types import TurnInput, TurnResult

__all__ = [
    "REGIMEN_ALLOWED_TOOLS",
    "REGIMEN_DISALLOWED_TOOLS",
    "SdkRegimenChat",
    "build_hooks",
    "build_options",
    "current_logger",
    "logging_to",
]

QueryFn = Callable[..., AsyncIterator[Any]]

REGIMEN_ALLOWED_TOOLS: tuple[str, ...] = (
    SET_FIELDS_TOOL,
    ASK_TOOL,
    PROPOSE_QUESTIONS_TOOL,
)
REGIMEN_DISALLOWED_TOOLS: tuple[str, ...] = (
    # 9b（skillchange の書き換え係）の一覧
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
    # ファイルを読まない・書かない（9c）
    "Read",
    "Edit",
    "Write",
    # ToolSearch が使えると MCP ツールが遅延読み込みの向こうに隠れ、H4 が ToolSearch を
    # 拒否するので set_fields に届かない（pipeline の DISALLOWED_TOOLS のコメント）
    "ToolSearch",
    # 使わない組み込みツール（pipeline と同じ。説明文がコンテキストに載らないように）
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
)
_TEMP_PREFIX = "tsutae-regimen-chat-"


def _matcher(hook: Any) -> HookMatcher:
    return HookMatcher(matcher=None, hooks=[hook], on_failure="block")


def build_hooks(logger: EventLogger) -> dict[str, list[HookMatcher]]:
    """H1（依頼文の二次検出）と H4（3つのツールだけ。サブエージェント無し）。"""
    return {
        "UserPromptSubmit": [_matcher(make_h1(logger))],
        "PreToolUse": [_matcher(make_h4(REGIMEN_ALLOWED_TOOLS, (), logger))],
    }


def build_options(
    work_root: Path, settings: Settings, logger: EventLogger, session: ChatSession
) -> ClaudeAgentOptions:
    """1往復の ClaudeAgentOptions（純関数。query は呼ばない）。"""
    return ClaudeAgentOptions(
        cwd=str(work_root),
        setting_sources=[],
        model=settings.model,
        mcp_servers={SERVER_NAME: build_server(session)},
        allowed_tools=list(REGIMEN_ALLOWED_TOOLS),
        disallowed_tools=list(REGIMEN_DISALLOWED_TOOLS),
        permission_mode="dontAsk",
        hooks=build_hooks(logger),  # type: ignore[arg-type]
        max_turns=settings.regimen_max_turns,
        max_budget_usd=settings.regimen_max_budget_usd,
        system_prompt=SYSTEM_PROMPT,
        extra_args=dict(NO_SESSION_PERSISTENCE),
        env=dict(NO_CLAUDE_MD_ENV),
    )


def _text_of(message: AssistantMessage) -> str:
    return "".join(b.text for b in message.content if isinstance(b, TextBlock))


def _reply(result: ResultMessage | None, last_text: str) -> str:
    if result is not None and isinstance(result.result, str) and result.result.strip():
        return result.result
    return last_text


class SdkRegimenChat:
    """`claude_agent_sdk.query` で1往復を回す（RegimenChat）。"""

    def __init__(
        self, settings: Settings | None = None, query_fn: QueryFn | None = None
    ) -> None:
        self.settings = settings
        self.query_fn: QueryFn = query_fn if query_fn is not None else query

    async def turn(self, draft: TurnInput, text: str) -> TurnResult:
        settings = self.settings if self.settings is not None else get_settings()
        logger = current_logger()
        session = ChatSession(draft, logger)
        prompt = build_turn_prompt(draft, text)
        work_root = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX)).resolve()
        try:
            options = build_options(work_root, settings, logger, session)
            result, last_text = await self._run(prompt, options)
        finally:
            shutil.rmtree(work_root, ignore_errors=True)
        return session.result(_reply(result, last_text), stats_from_result(result))

    async def _run(
        self, prompt: str, options: ClaudeAgentOptions
    ) -> tuple[ResultMessage | None, str]:
        result: ResultMessage | None = None
        last_text = ""
        try:
            async for message in self.query_fn(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result = message
                elif isinstance(message, AssistantMessage):
                    last_text = _text_of(message) or last_text
        except ClaudeSDKError as exc:
            raise RunFailedError(exc, stats_from_result(result)) from exc
        return result, last_text
