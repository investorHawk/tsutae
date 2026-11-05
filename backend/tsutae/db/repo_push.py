"""通知の登録（push_subscriptions）。端末（endpoint）ごとに1行。

`claim_push_send` は「今日の分を送る権利」を先に取る。送る前に書くので、書けなければ
送らない（DB の不調で同じ通知を毎分送り続けることが無い）。送れなかったら
`release_push_send` で戻し、10 分の窓の間だけ次の周期でやり直せる。

行を消すときは送った日を `push_removed_sends` に残し、新しい行が引き継ぐ（オフにして
オンにしても1日1回まで）。送信先に消された endpoint は `push_gone_endpoints` に覚える。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from tsutae.db.connection import (
    date_from_db,
    date_to_db,
    dt_to_db,
    require_exists,
    write_transaction,
)

__all__ = [
    "PushSubscription",
    "claim_push_send",
    "delete_push_subscription",
    "delete_push_subscription_by_id",
    "get_push_subscription",
    "get_push_subscription_by_id",
    "is_push_endpoint_gone",
    "list_push_subscriptions",
    "mark_push_endpoint_gone",
    "release_push_send",
    "upsert_push_subscription",
]

_COLUMNS = "id, patient_id, endpoint, p256dh, auth, notify_time, last_sent_date"
_GONE_KEEP = timedelta(days=30)


@dataclass(frozen=True)
class PushSubscription:
    id: int
    patient_id: str
    endpoint: str
    p256dh: str
    auth: str
    notify_time: str
    last_sent_date: date | None


def _row(row: sqlite3.Row) -> PushSubscription:
    return PushSubscription(
        id=row["id"],
        patient_id=row["patient_id"],
        endpoint=row["endpoint"],
        p256dh=row["p256dh"],
        auth=row["auth"],
        notify_time=row["notify_time"],
        last_sent_date=date_from_db(row["last_sent_date"]),
    )


def upsert_push_subscription(
    conn: sqlite3.Connection,
    pid: str,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    notify_time: str,
    created_at: datetime,
) -> PushSubscription:
    """endpoint で登録・上書きする。

    同じ端末が別の番号で登録し直したら、その患者の行になる（前の患者の通知は止まる）。
    last_sent_date は同じ患者なら保つ（時刻を変えても1日1回まで）。新しい行は、その患者の
    消した登録の送信日を引き継ぐ（オフにしてオンにしても1日1回まで）。
    """
    require_exists(conn, "patients", pid, "patient")
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO push_subscriptions (patient_id, endpoint, p256dh, auth,"
            " notify_time, last_sent_date, created_at) VALUES (?, ?, ?, ?, ?,"
            " (SELECT last_sent_date FROM push_removed_sends WHERE patient_id = ?),"
            " ?)"
            " ON CONFLICT (endpoint) DO UPDATE SET"
            " last_sent_date = CASE WHEN patient_id = excluded.patient_id"
            " THEN last_sent_date ELSE excluded.last_sent_date END,"
            " patient_id = excluded.patient_id,"
            " p256dh = excluded.p256dh,"
            " auth = excluded.auth,"
            " notify_time = excluded.notify_time",
            (pid, endpoint, p256dh, auth, notify_time, pid, dt_to_db(created_at)),
        )
    saved = get_push_subscription(conn, pid, endpoint)
    if saved is None:  # pragma: no cover - 直前に書いた行が無いのは異常
        raise RuntimeError("push subscription was not saved")
    return saved


def get_push_subscription(
    conn: sqlite3.Connection, pid: str, endpoint: str
) -> PushSubscription | None:
    """その患者の登録（他の患者の endpoint なら None）。"""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM push_subscriptions"
        " WHERE endpoint = ? AND patient_id = ?",
        (endpoint, pid),
    ).fetchone()
    return None if row is None else _row(row)


def get_push_subscription_by_id(
    conn: sqlite3.Connection, subscription_id: int
) -> PushSubscription | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM push_subscriptions WHERE id = ?",
        (subscription_id,),
    ).fetchone()
    return None if row is None else _row(row)


def list_push_subscriptions(conn: sqlite3.Connection) -> list[PushSubscription]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM push_subscriptions ORDER BY id"
    ).fetchall()
    return [_row(r) for r in rows]


def _keep_sent_date(
    conn: sqlite3.Connection, where: str, args: tuple[object, ...]
) -> None:
    """これから消す行の送信日を残す（同じトランザクションの中で呼ぶ）。"""
    conn.execute(
        "INSERT INTO push_removed_sends (patient_id, last_sent_date)"
        f" SELECT patient_id, last_sent_date FROM push_subscriptions WHERE {where}"
        " AND last_sent_date IS NOT NULL"
        " ON CONFLICT (patient_id) DO UPDATE SET"
        " last_sent_date = MAX(last_sent_date, excluded.last_sent_date)",
        args,
    )


def delete_push_subscription(conn: sqlite3.Connection, pid: str, endpoint: str) -> bool:
    """その患者の登録を消す。消したら True（他の患者の endpoint は消さない）。"""
    where = "endpoint = ? AND patient_id = ?"
    with write_transaction(conn):
        _keep_sent_date(conn, where, (endpoint, pid))
        cur = conn.execute(
            f"DELETE FROM push_subscriptions WHERE {where}", (endpoint, pid)
        )
    return cur.rowcount > 0


def delete_push_subscription_by_id(
    conn: sqlite3.Connection, subscription_id: int
) -> None:
    with write_transaction(conn):
        _keep_sent_date(conn, "id = ?", (subscription_id,))
        conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (subscription_id,))


def mark_push_endpoint_gone(
    conn: sqlite3.Connection, endpoint: str, at: datetime
) -> None:
    """送信先に消された endpoint を覚える。古いもの（30 日）はここで忘れる。"""
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO push_gone_endpoints (endpoint, gone_at) VALUES (?, ?)"
            " ON CONFLICT (endpoint) DO UPDATE SET gone_at = excluded.gone_at",
            (endpoint, dt_to_db(at)),
        )
        conn.execute(
            "DELETE FROM push_gone_endpoints WHERE gone_at < ?",
            (dt_to_db(at - _GONE_KEEP),),
        )


def is_push_endpoint_gone(conn: sqlite3.Connection, endpoint: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM push_gone_endpoints WHERE endpoint = ?", (endpoint,)
    ).fetchone()
    return row is not None


def claim_push_send(conn: sqlite3.Connection, subscription_id: int, day: date) -> bool:
    """day の分を送る権利を取る。すでに day の分が取られていれば False。"""
    with write_transaction(conn):
        cur = conn.execute(
            "UPDATE push_subscriptions SET last_sent_date = ?"
            " WHERE id = ? AND (last_sent_date IS NULL OR last_sent_date <> ?)",
            (date_to_db(day), subscription_id, date_to_db(day)),
        )
    return cur.rowcount > 0


def release_push_send(
    conn: sqlite3.Connection,
    subscription_id: int,
    day: date,
    previous: date | None,
) -> None:
    """送れなかったので day の権利を戻す（day のままの行だけ。previous に戻す）。"""
    with write_transaction(conn):
        conn.execute(
            "UPDATE push_subscriptions SET last_sent_date = ?"
            " WHERE id = ? AND last_sent_date = ?",
            (date_to_db(previous), subscription_id, date_to_db(day)),
        )
