"""日付の印（record_marks）。「その日に記録があった」ことだけを持つ。中身は持たない。

通知を書いた人に送らないため（plan-device-records §4.4）。記録の行を入れるときに同じ
トランザクションで印も書く（`insert_entry_rows`）ので、どの経路で記録を入れても印が付く。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from tsutae.config import to_jst_date
from tsutae.db.connection import date_to_db, dt_to_db, write_transaction

__all__ = [
    "backfill_record_marks",
    "clear_mark_if_no_entries",
    "marked_patients",
    "upsert_mark_row",
]


def upsert_mark_row(conn: sqlite3.Connection, pid: str, at: datetime) -> None:
    """at の日の印を付ける。呼び出し側で write_transaction を開いておくこと。"""
    conn.execute(
        "INSERT INTO record_marks (patient_id, record_date, last_marked_at)"
        " VALUES (?, ?, ?)"
        " ON CONFLICT (patient_id, record_date) DO UPDATE SET"
        " last_marked_at = MAX(last_marked_at, excluded.last_marked_at)",
        (pid, date_to_db(to_jst_date(at)), dt_to_db(at)),
    )


def clear_mark_if_no_entries(
    conn: sqlite3.Connection, pid: str, record_date: str
) -> None:
    """記録を消した後に呼ぶ。その日の記録が残っていなければ印を消し、残っていれば
    last_marked_at を残りの最後の時刻に戻す。呼び出し側で write_transaction を開いておく。
    """
    row = conn.execute(
        "SELECT MAX(recorded_at) AS last FROM entries"
        " WHERE patient_id = ? AND record_date = ?",
        (pid, record_date),
    ).fetchone()
    if row["last"] is None:
        conn.execute(
            "DELETE FROM record_marks WHERE patient_id = ? AND record_date = ?",
            (pid, record_date),
        )
        return
    conn.execute(
        "UPDATE record_marks SET last_marked_at = ?"
        " WHERE patient_id = ? AND record_date = ?",
        (row["last"], pid, record_date),
    )


def marked_patients(conn: sqlite3.Connection, day: date) -> set[str]:
    """day の印がある患者の仮名ID。"""
    rows = conn.execute(
        "SELECT patient_id FROM record_marks WHERE record_date = ?",
        (date_to_db(day),),
    ).fetchall()
    return {r["patient_id"] for r in rows}


def backfill_record_marks(conn: sqlite3.Connection) -> None:
    """既存の entries から印を作る。今ある印は変えない（何度呼んでもよい）。

    受付で受け取った記録（client_entry_id のある行）は数えない。印はサーバーが記録のときに
    付けるもので、取り消した日の印が起動のたびに戻らないように。
    """
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO record_marks (patient_id, record_date, last_marked_at)"
            " SELECT patient_id, record_date, MAX(recorded_at) FROM entries"
            " WHERE client_entry_id IS NULL"
            " GROUP BY patient_id, record_date"
            " ON CONFLICT (patient_id, record_date) DO NOTHING"
        )
