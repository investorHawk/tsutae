"""パイプラインのログ（D5 用）。文面（プロンプト・記録・引用・出力）は入れない。

- 受け付ける列は固定。未知のキーワード（text, message 等）は ValueError で拒否する
- event と文字列の列（hook_name 等）は ASCII の識別子だけ（`IDENTIFIER_PATTERN`）。
  日本語・空白・改行を含む値は ValueError（患者の文や引用が紛れ込まないように）
- 数値の列は 0 以上の有限値だけ
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import datetime
from typing import Any

from tsutae.config import now as clock_now
from tsutae.db.connection import dt_from_db, dt_to_db, write_transaction

RUN_KINDS = ("visit", "skill_change", "regimen_chat")
IDENTIFIER_MAX = 100
IDENTIFIER_PATTERN = re.compile(rf"[A-Za-z0-9_.:/@-]{{1,{IDENTIFIER_MAX}}}")

_TEXT_FIELDS = ("hook_name", "agent_type", "tool_name", "decision")
_INT_FIELDS = ("duration_ms", "tokens_in", "tokens_out")
_FLOAT_FIELDS = ("cost_usd",)
_FIELDS = _TEXT_FIELDS + _INT_FIELDS + _FLOAT_FIELDS
_COLUMNS = ("id", "run_kind", "run_id", "ts", "event") + _FIELDS


def _identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(
            f"{name} は ASCII の識別子（英数字と _ . : / @ -、1〜{IDENTIFIER_MAX}文字）"
        )
    return value


def _number(name: str, value: object, kind: type) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} は数値")
    if kind is int and not isinstance(value, int):
        raise ValueError(f"{name} は整数")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} は0以上の有限値")
    return kind(value)


def _clean_fields(fields: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(fields) - set(_FIELDS) - {"ts"})
    if unknown:
        raise ValueError(f"pipeline_logs に無い列: {', '.join(unknown)}")
    cleaned: dict[str, Any] = {}
    for name in _FIELDS:
        value = fields.get(name)
        if value is None:
            cleaned[name] = None
        elif name in _TEXT_FIELDS:
            cleaned[name] = _identifier(name, value)
        else:
            cleaned[name] = _number(name, value, int if name in _INT_FIELDS else float)
    return cleaned


def add_pipeline_log(
    conn: sqlite3.Connection,
    run_kind: str,
    run_id: int,
    event: str,
    **fields: Any,
) -> None:
    """ログを1行足す。fields は hook_name 等の固定列と ts（省略時は現在時刻）。"""
    if run_kind not in RUN_KINDS:
        raise ValueError(f"unknown run_kind: {run_kind!r}")
    if isinstance(run_id, bool) or not isinstance(run_id, int):
        raise ValueError("run_id は整数")
    _identifier("event", event)
    ts = fields.get("ts")
    if ts is not None and not isinstance(ts, datetime):
        raise ValueError("ts は datetime")
    cleaned = _clean_fields(fields)
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO pipeline_logs (run_kind, run_id, ts, event,"
            f" {', '.join(_FIELDS)})"
            f" VALUES (?, ?, ?, ?, {', '.join('?' for _ in _FIELDS)})",
            (
                run_kind,
                run_id,
                dt_to_db(ts if ts is not None else clock_now()),
                event,
                *(cleaned[name] for name in _FIELDS),
            ),
        )


def list_pipeline_logs(
    conn: sqlite3.Connection, run_kind: str, run_id: int
) -> list[dict[str, Any]]:
    """1回分の実行のログを書いた順に返す（ts は datetime）。"""
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM pipeline_logs"
        " WHERE run_kind = ? AND run_id = ? ORDER BY id",
        (run_kind, run_id),
    ).fetchall()
    result = []
    for row in rows:
        item = {name: row[name] for name in _COLUMNS}
        item["ts"] = dt_from_db(row["ts"])
        result.append(item)
    return result
