"""日付の印（record_marks）。「その日に記録があった」ことだけを持つ。中身は持たない。

通知を書いた人に送らないため（plan-device-records §4.4）と、D1 の「最後の記録日」のため
（§5.7）。記録はスマホに置くので、記録のときにサーバーが付ける（`add_record_mark`）。seed と
`add_entry` は行と同じトランザクションで書く（`insert_entry_rows`）。受付で受け取った記録は
印を書かない・消さない（`repo_received`）。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from tsutae.config import to_jst_date
from tsutae.db.connection import date_from_db, date_to_db, dt_to_db, write_transaction
from tsutae.schemas import RecordMark

__all__ = [
    "add_record_mark",
    "backfill_record_marks",
    "last_record_dates",
    "list_record_marks",
    "marked_patients",
    "undo_record_mark",
    "upsert_mark_row",
]

# 押し直しの前の印とみなす長さ。これより前の印は別の端末の記録として残す
RETRY_WINDOW = timedelta(minutes=10)


def upsert_mark_row(conn: sqlite3.Connection, pid: str, at: datetime) -> None:
    """at の日の印を付ける。呼び出し側で write_transaction を開いておくこと。"""
    conn.execute(
        "INSERT INTO record_marks"
        " (patient_id, record_date, first_marked_at, last_marked_at)"
        " VALUES (?, ?, ?, ?)"
        " ON CONFLICT (patient_id, record_date) DO UPDATE SET"
        " first_marked_at = MIN(first_marked_at, excluded.first_marked_at),"
        " last_marked_at = MAX(last_marked_at, excluded.last_marked_at)",
        (pid, date_to_db(to_jst_date(at)), dt_to_db(at), dt_to_db(at)),
    )


def add_record_mark(conn: sqlite3.Connection, pid: str, at: datetime) -> None:
    """at の日の印を付ける（記録のとき。サーバーの時計で）。"""
    with write_transaction(conn):
        upsert_mark_row(conn, pid, at)


def undo_record_mark(
    conn: sqlite3.Connection,
    pid: str,
    recorded_at: datetime,
    *,
    clear_mark: bool,
    retried: bool = False,
) -> bool:
    """recorded_at の記録の取り消し。受付に届いていれば何も変えずに False。

    届いているとは、その後に受診ができたか、この時刻の記録を受付で受け取った行があること。
    同じ受付番号の送り直しは visits の行を作らずに記録だけを入れるので、行そのものも見る
    （消せると、端末と印だけが消えて「つらくて書けない」がサーバーに残る）。
    clear_mark なら recorded_at の日の印を消す。ただし recorded_at の他に印が付いていれば
    （別の端末が先か後に書いた）残す。端末は他の端末の記録を知らないので、clear_mark だけでは
    決められない。retried は端末が同じ記録を押し直したこと（1回目の印の応答が届かない、または
    保存に失敗した）で、1回目の印は端末から見えない。このときは RETRY_WINDOW の中の先の印も
    この記録の分として消す。後から付いた印は残す。
    調べるのと消すのを1つの write_transaction で行う。取り消しの窓は呼び出し側が見る。
    日時は固定幅の JST 文字列なので、文字列の比較が時刻の順と一致する
    """
    at = dt_to_db(recorded_at)
    since = dt_to_db(recorded_at - RETRY_WINDOW) if retried else at
    with write_transaction(conn):
        visited = conn.execute(
            "SELECT 1 FROM visits WHERE patient_id = ? AND created_at >= ? LIMIT 1",
            (pid, at),
        ).fetchone()
        if visited is not None:
            return False
        received = conn.execute(
            "SELECT 1 FROM entries WHERE patient_id = ? AND recorded_at = ?"
            " AND client_entry_id IS NOT NULL LIMIT 1",
            (pid, at),
        ).fetchone()
        if received is not None:
            return False
        if clear_mark:
            conn.execute(
                "DELETE FROM record_marks WHERE patient_id = ? AND record_date = ?"
                " AND first_marked_at >= ? AND last_marked_at = ?",
                (pid, date_to_db(to_jst_date(recorded_at)), since, at),
            )
    return True


def last_record_dates(conn: sqlite3.Connection) -> dict[str, date]:
    """患者ごとの最後の記録日（印の日付の最大）。印の無い患者は含まない。"""
    rows = conn.execute(
        "SELECT patient_id, MAX(record_date) AS last FROM record_marks"
        " GROUP BY patient_id"
    ).fetchall()
    return {r["patient_id"]: date_from_db(r["last"]) for r in rows}


def list_record_marks(conn: sqlite3.Connection, pid: str) -> list[RecordMark]:
    """その患者の印を日付順に。レポートの「届いていない日」に使う（§5.6）。"""
    rows = conn.execute(
        "SELECT record_date FROM record_marks WHERE patient_id = ? ORDER BY record_date",
        (pid,),
    ).fetchall()
    return [
        RecordMark(patient_id=pid, record_date=date_from_db(r["record_date"]))
        for r in rows
    ]


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
            "INSERT INTO record_marks"
            " (patient_id, record_date, first_marked_at, last_marked_at)"
            " SELECT patient_id, record_date, MIN(recorded_at), MAX(recorded_at)"
            " FROM entries"
            " WHERE client_entry_id IS NULL"
            " GROUP BY patient_id, record_date"
            " ON CONFLICT (patient_id, record_date) DO NOTHING"
        )
