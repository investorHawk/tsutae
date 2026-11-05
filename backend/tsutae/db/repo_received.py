"""受付で受け取った記録（plan-device-records §5.5）。`client_entry_id` のある entries の行。

記録はスマホに置き、受診のときだけサーバーへ届く。変換は他の記録と同じく entries を読む
（`db.list_entries`）。ここは入れるのと消すのだけ。どちらも呼び出し側で write_transaction を
開いておくこと（受診の作成・印刷済み・期限切れと同じトランザクションにするため）。

- 同じ患者の同じ ID は入れない（送り直しで二重にしない）
- 日付の印（record_marks）は書かない・消さない。印はサーバーが記録のときに付けたもので、
  D1 と通知が使う
- 消すのは、その患者に開いた受診（受付番号が残り期限内）が無いときだけ。`client_entry_id` の
  無い行は消さない。回答・自由記載・医師の伏せ字は ON DELETE CASCADE で一緒に消える。
  消した行の中身は connect の secure_delete がゼロで上書きする
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from tsutae.db.repo_entries import insert_entry_row, validate_skill_version
from tsutae.schemas import EntryCreate

__all__ = ["ReceivedEntry", "erase_received_rows", "insert_received_rows"]


@dataclass(frozen=True)
class ReceivedEntry:
    """検査を通った、受付で受け取った記録1件。recorded_at はサーバーが印のときに返した値。"""

    client_entry_id: str
    entry: EntryCreate
    recorded_at: datetime
    skill_version: str


def insert_received_rows(
    conn: sqlite3.Connection, pid: str, entries: Sequence[ReceivedEntry]
) -> None:
    """まだ無い ID の記録を入れる。"""
    if not entries:
        return
    rows = conn.execute(
        "SELECT client_entry_id FROM entries"
        " WHERE patient_id = ? AND client_entry_id IS NOT NULL",
        (pid,),
    ).fetchall()
    known = {r["client_entry_id"] for r in rows}
    for item in entries:
        if item.client_entry_id in known:
            continue
        validate_skill_version(item.skill_version)
        insert_entry_row(
            conn,
            pid,
            item.entry,
            item.recorded_at,
            item.skill_version,
            item.client_entry_id,
        )


def erase_received_rows(conn: sqlite3.Connection, pid: str, now_db: str) -> None:
    """その患者に開いた受診が無ければ、受け取った記録を消す。now_db は期限と比べる「今」。"""
    still_open = conn.execute(
        "SELECT 1 FROM visits WHERE patient_id = ? AND reception_no IS NOT NULL"
        " AND expires_at > ? LIMIT 1",
        (pid, now_db),
    ).fetchone()
    if still_open is None:
        conn.execute(
            "DELETE FROM entries WHERE patient_id = ? AND client_entry_id IS NOT NULL",
            (pid,),
        )
