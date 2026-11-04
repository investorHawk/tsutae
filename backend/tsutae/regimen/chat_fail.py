"""D4 レジメンの1往復の失敗の後始末（T94。chat_turn から分けた）。

- `fail`: 会話に先生の文と失敗の行を足して open に戻す（`fail_turn`。working かつ同じ
  generation のときだけ。当たらなければ False）
- `failed_outcome`: chat.turn の時間切れ・SDK の失敗・例外。ログを書いて `fail` し、
  往復の後の下書きを返す（POST .../turns は 200 と turn_error）
- `rescue`: begin_working の後で外に抜ける例外（結果の書き込みの DB の失敗・
  `failed_outcome` の中の失敗・取り消し）の後始末。できる範囲で `fail` してから、呼び出し側が
  元の例外を投げ直す。後始末の失敗は握りつぶして型名だけをログに残す（元の例外を隠さない。
  下書きは回復 `recover_stale_working` に任せる）

ログに文面（先生の文・例外の本文）は入れない。例外は型名だけ。
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from typing import Any

from claude_agent_sdk import ClaudeSDKError

from tsutae.config import now as clock_now
from tsutae.db import repo_regimen_drafts as repo
from tsutae.db import repo_regimen_turns as turns
from tsutae.db.connection import dt_to_db
from tsutae.pipeline.logs import EventLogger, reason_code
from tsutae.pipeline.orchestrator import sdk_error_code
from tsutae.pipeline.runner import RunFailedError
from tsutae.regimen.chat_rows import doctor_row, failed_row
from tsutae.regimen.chat_types import TurnOutcome
from tsutae.schemas import RunStats

__all__ = [
    "CANCELLED",
    "INTERNAL_ERROR",
    "fail",
    "failed_outcome",
    "log_end",
    "rescue",
    "stamp",
]

CANCELLED = "cancelled"
INTERNAL_ERROR = "internal_error"
_log = logging.getLogger("tsutae.regimen.chat_turn")


def stamp() -> str:
    return dt_to_db(clock_now())


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def log_end(logger: EventLogger, code: str, stats: RunStats, started: float) -> None:
    duration = stats.duration_ms or _elapsed_ms(started)
    logger.event(
        "turn_end",
        decision=code,
        duration_ms=duration,
        tokens_in=stats.tokens_in,
        tokens_out=stats.tokens_out,
        cost_usd=stats.cost_usd,
    )


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ClaudeSDKError):
        return sdk_error_code(exc)
    return INTERNAL_ERROR


def _error_type(exc: BaseException) -> str:
    cause = exc.cause if isinstance(exc, RunFailedError) else exc
    return type(cause).__name__


def fail(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    generation: int,
    text: str,
    code: str,
) -> bool:
    """会話に先生の文と失敗の行を足して open に戻す。当たらなければ False。"""
    at = stamp()
    chat = [
        *draft["chat"],
        doctor_row(text, generation, at),
        failed_row(code, generation, at),
    ]
    return turns.fail_turn(conn, draft["id"], generation, chat=chat)


def failed_outcome(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    generation: int,
    text: str,
    exc: BaseException,
    logger: EventLogger,
    started: float,
) -> TurnOutcome:
    """chat.turn の失敗。open に戻して失敗のコードつきの下書きを返す。"""
    code = _error_code(exc)
    if code == INTERNAL_ERROR:
        logger.event(
            "internal_error", decision=reason_code("error_type", _error_type(exc))
        )
        _log.warning("regimen_chat internal_error: %s", _error_type(exc))
    stats = exc.stats if isinstance(exc, RunFailedError) else RunStats()
    log_end(logger, code, stats, started)
    if not fail(conn, draft, generation, text, code):
        logger.event("turn_discarded", decision=code)
    return TurnOutcome(repo.get_draft(conn, draft["id"]) or {}, code)


def rescue(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    generation: int,
    text: str,
    exc: BaseException,
    logger: EventLogger,
) -> None:
    """外に抜ける例外の後始末。working・同じ generation なら open に戻して失敗の行。"""
    cancelled = isinstance(exc, asyncio.CancelledError)
    code = CANCELLED if cancelled else INTERNAL_ERROR
    try:
        if fail(conn, draft, generation, text, code):
            decision = (
                code
                if cancelled
                else reason_code(code, "error_type", type(exc).__name__)
            )
            logger.event("turn_failed", decision=decision)
    except Exception as inner:  # noqa: BLE001 — 元の例外を隠さない
        _log.warning(
            "regimen_chat rescue failed: %s (after %s)",
            type(inner).__name__,
            type(exc).__name__,
        )
