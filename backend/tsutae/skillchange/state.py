"""skill_changes の条件付きの状態遷移。

`db.update_skill_change` は状態を見ずに書くので、決着の付いた行（approved・rejected・
failed）を後から上書きしうる。ここでは `WHERE id = ? AND status = 'pending'` の
UPDATE だけを使い、更新した行が無ければ False を返す（呼び出し側が not_pending にする）。
書き込みは `db.write_transaction`（プロセス内ロック＋`with conn:`）の中で行う。

作業中（pending で diff がまだ無い。editor が動いている）の行は、同じ Skill の新しい
依頼を busy にする（`has_working`）。サーバーの再起動などで取り残された作業中の行が
永遠に busy にしないよう、created_at から timeout を過ぎたものは
`fail_stale_requests` で failed・`stale_request` にする（editor はその時間で打ち切られて
いるので、まだ動いていることはない）。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from tsutae import db
from tsutae.config import now
from tsutae.db.connection import dt_to_db, write_transaction
from tsutae.pipeline.logs import EventLogger, PipelineLogger, reason_code

__all__ = [
    "RUN_KIND",
    "STALE_GRACE_S",
    "STALE_REQUEST",
    "fail_pending",
    "fail_stale_requests",
    "has_working",
    "transition",
]

RUN_KIND = "skill_change"
# 作業中のまま timeout を過ぎた行の error_code
STALE_REQUEST = "stale_request"
# 別スレッド（一覧の GET）から取り残しを片付けるときの余裕（秒）
STALE_GRACE_S = 30.0
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


def _working(conn: sqlite3.Connection, skill_name: str | None) -> list[dict[str, Any]]:
    """作業中（pending・diff なし）の行。skill_name が None なら全ての Skill。"""
    pending = db.list_skill_changes(conn, skill_name, ("pending",))
    return [c for c in pending if c["diff"] is None]


def has_working(conn: sqlite3.Connection, skill_name: str) -> bool:
    """その Skill に作業中の行があるか。"""
    return bool(_working(conn, skill_name))


def _fail_if_still_working(conn: sqlite3.Connection, change_id: int) -> bool:
    """まだ作業中（pending・diff なし）なら failed・stale_request にする。"""
    with write_transaction(conn):
        cur = conn.execute(
            "UPDATE skill_changes SET status = 'failed', error_code = ?,"
            " decided_at = ?"
            " WHERE id = ? AND status = 'pending' AND diff IS NULL",
            (STALE_REQUEST, dt_to_db(now()), change_id),
        )
    return cur.rowcount == 1


def fail_stale_requests(
    conn: sqlite3.Connection,
    timeout_s: float,
    skill_name: str | None = None,
    *,
    grace_s: float = 0.0,
) -> list[int]:
    """created_at から timeout_s（＋grace_s）を過ぎた作業中の行を failed にし、id を返す。

    grace_s は別スレッドから呼ぶとき（`GET /skill-changes` は同期の経路でスレッドで動く）
    の余裕。editor が打ち切りの直前に返り、diff を保存するまでの間に失敗にしない。
    request_change の中（同じイベントループで、確かめてから行を作るまで await が無い）
    では 0 でよい。
    """
    limit = now() - timedelta(seconds=timeout_s + grace_s)
    failed: list[int] = []
    for change in _working(conn, skill_name):
        if change["created_at"] > limit:
            continue
        if _fail_if_still_working(conn, change["id"]):
            PipelineLogger(conn, RUN_KIND, change["id"]).event(
                "skill_change_failed",
                decision=reason_code("failed", STALE_REQUEST),
            )
            failed.append(change["id"])
    return failed
