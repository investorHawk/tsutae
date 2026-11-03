"""skill_changes の条件付きの状態遷移。

`db.update_skill_change` は状態を見ずに書くので、決着の付いた行（approved・rejected・
failed）を後から上書きしうる。ここでは `WHERE id = ? AND status = 'pending'` の
UPDATE だけを使い、更新した行が無ければ False を返す（呼び出し側が not_pending にする）。
書き込みは `db.write_transaction`（プロセス内ロック＋`with conn:`）の中で行う。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from tsutae.config import now
from tsutae.db.connection import dt_to_db, write_transaction
from tsutae.pipeline.logs import EventLogger, reason_code

__all__ = ["RUN_KIND", "fail_pending", "transition"]

RUN_KIND = "skill_change"
_COLUMNS = ("diff", "new_text", "new_version", "status", "error_code", "decided_at")
_STATUSES = ("pending", "approved", "rejected", "failed")


def _cleaned(fields: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(fields) - set(_COLUMNS))
    if unknown:
        raise ValueError(f"更新できない列: {', '.join(unknown)}")
    if "status" in fields and fields["status"] not in _STATUSES:
        raise ValueError("unknown skill change status")
    cleaned = dict(fields)
    if isinstance(cleaned.get("decided_at"), datetime):
        cleaned["decided_at"] = dt_to_db(cleaned["decided_at"])
    return cleaned


def transition(conn: sqlite3.Connection, change_id: int, **fields: Any) -> bool:
    """pending の行だけを更新する。更新したら True、行が pending でなければ False。"""
    cleaned = _cleaned(fields)
    if not cleaned:
        raise ValueError("更新する列が無い")
    names = [name for name in _COLUMNS if name in cleaned]
    assignments = ", ".join(f"{name} = ?" for name in names)
    with write_transaction(conn):
        cur = conn.execute(
            f"UPDATE skill_changes SET {assignments}"
            " WHERE id = ? AND status = 'pending'",
            (*(cleaned[name] for name in names), change_id),
        )
    return cur.rowcount == 1


def fail_pending(
    conn: sqlite3.Connection, logger: EventLogger, change_id: int, code: str
) -> bool:
    """pending なら failed・code にする。既に決着していれば何もしない（False）。"""
    done = transition(
        conn, change_id, status="failed", error_code=code, decided_at=now()
    )
    if done:
        logger.event("skill_change_failed", decision=reason_code("failed", code))
    else:
        logger.event("decided_elsewhere", decision=reason_code("failed", code))
    return done
