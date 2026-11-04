"""パイプラインのログ（D5 の可視化用）。**文面は入れない**。

- 列は `db.add_pipeline_log` と同じ固定列だけ。文字列の列は ASCII の識別子
  （`IDENTIFIER_PATTERN`、100字以内）。合わない値（日本語・空白・長すぎる値）は
  `INVALID` に置き換える（外から来たツール名などが紛れても文面を残さない）
- 理由は規則名などの短いコードだけを `decision` に `deny:<コード>` の形で入れる
- `event` は Hook の中で呼ばれる。DB の失敗で例外を出すと Hook が失敗し
  （on_failure="block"）変換全体が止まるので、PipelineLogger は失敗を数えて続ける
- 未知の列名・識別子でない event 名はプログラムの誤りなので ValueError
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
from typing import Any, Protocol

from tsutae.db import add_pipeline_log
from tsutae.db.repo_logs import IDENTIFIER_MAX, IDENTIFIER_PATTERN, RUN_KINDS

__all__ = [
    "INVALID",
    "EventLogger",
    "MemoryLogger",
    "PipelineLogger",
    "clean_fields",
    "reason_code",
]

INVALID = "invalid"
TEXT_FIELDS = ("hook_name", "agent_type", "tool_name", "decision")
INT_FIELDS = ("duration_ms", "tokens_in", "tokens_out")
FLOAT_FIELDS = ("cost_usd",)
FIELDS = TEXT_FIELDS + INT_FIELDS + FLOAT_FIELDS
_NOT_IDENTIFIER_CHAR = re.compile(r"[^A-Za-z0-9_.:/@-]")

_log = logging.getLogger(__name__)


class EventLogger(Protocol):
    def event(self, name: str, **fields: Any) -> None: ...


def reason_code(*parts: str) -> str:
    """`deny:events.2.source_quote` のような短いコード（識別子でない字は _）。"""
    joined = ":".join(parts)
    return _NOT_IDENTIFIER_CHAR.sub("_", joined)[:IDENTIFIER_MAX] or INVALID


def _text(value: object) -> str:
    if isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value):
        return value
    return INVALID


def _number(value: object, kind: type) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return kind(value)


def clean_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """固定列だけを、DB に入る形に直して返す（None・不正な数値は落とす）。"""
    unknown = sorted(set(fields) - set(FIELDS))
    if unknown:
        raise ValueError(f"ログに無い列: {', '.join(unknown)}")
    cleaned: dict[str, Any] = {}
    for name in FIELDS:
        value = fields.get(name)
        if value is None:
            continue
        if name in TEXT_FIELDS:
            cleaned[name] = _text(value)
        else:
            number = _number(value, int if name in INT_FIELDS else float)
            if number is not None:
                cleaned[name] = number
    return cleaned


def _check_event_name(name: object) -> str:
    if not isinstance(name, str) or not IDENTIFIER_PATTERN.fullmatch(name):
        raise ValueError("event 名は ASCII の識別子")
    return name


class MemoryLogger:
    """conn なしで記録だけ持つ（テスト・評価用）。"""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def event(self, name: str, **fields: Any) -> None:
        self.records.append({"event": _check_event_name(name), **clean_fields(fields)})

    def names(self) -> list[str]:
        return [r["event"] for r in self.records]

    def find(self, name: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r["event"] == name]


class PipelineLogger:
    """`db.add_pipeline_log` に書く。DB の失敗は `failures` に数えて続ける。"""

    def __init__(self, conn: sqlite3.Connection, run_kind: str, run_id: int) -> None:
        if run_kind not in RUN_KINDS:
            raise ValueError(f"unknown run_kind: {run_kind!r}")
        if isinstance(run_id, bool) or not isinstance(run_id, int):
            raise ValueError("run_id は整数")
        self._conn = conn
        self.run_kind = run_kind
        self.run_id = run_id
        self.failures = 0

    def event(self, name: str, **fields: Any) -> None:
        cleaned = clean_fields(fields)
        event = _check_event_name(name)
        try:
            add_pipeline_log(self._conn, self.run_kind, self.run_id, event, **cleaned)
        except (sqlite3.Error, ValueError):
            self.failures += 1
            _log.warning("pipeline log dropped: %s", event)
