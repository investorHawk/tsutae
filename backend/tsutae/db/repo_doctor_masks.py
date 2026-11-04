"""医師の伏せ字（doctor_masks。D6 で医師が選んだ区間と「確かめた」の印）。

- 受診ごと・記録ごとに1行。持つのは位置（原文の区間・許す区間）と確かめの真偽だけで、
  文面は持たない。生の記録（entries・free_texts）は変えない（spec 13.3）
- 保存できるのは開いている受診（受付番号が残り、印刷済みでなく、expires_at > 今）で、
  生成中でないものだけ。閉じた受診は VisitClosedError、生成中は VisitGeneratingError
  （どちらも何も変えない）。確認は最初の UPDATE の条件で行うので、確認と書き込みの間に
  別の接続が状態を変えることはできない
- 記録はその受診の患者のものだけ（違えば ValueError で何も変えない）
- 消すのは repo_visits の `_erase_results`（印刷済み・期限切れ。レポートと同じ
  トランザクション）と、医師の「送らない」（removals）
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Mapping

from tsutae.config import now as clock_now
from tsutae.db.connection import (
    NotFoundError,
    VisitClosedError,
    dt_to_db,
    write_transaction,
)
from tsutae.schemas import DoctorMask, TextSpan

__all__ = [
    "VisitGeneratingError",
    "erase_doctor_masks",
    "list_doctor_masks",
    "save_doctor_masks",
]


class VisitGeneratingError(ValueError):
    """生成中（やり直しの最中を含む）の受診に医師の伏せ字を保存しようとした。"""


# 開いていて生成中でない受診だけを「触る」（SET id = id は何も変えない。最初の書き込みで
# SQLite のトランザクションを始め、確認と書き込みの間に別の接続が入れないようにする）
_LOCK_OPEN_VISIT = (
    "UPDATE visits SET id = id WHERE id = ? AND reception_no IS NOT NULL"
    " AND status NOT IN ('printed', 'generating') AND expires_at > ?"
)
_UPSERT = (
    "INSERT INTO doctor_masks"
    " (visit_id, entry_id, spans_json, confirmed_clear, allowed_json, created_at)"
    " SELECT v.id, e.id, ?, ?, ?, ? FROM visits v JOIN entries e"
    " ON e.patient_id = v.patient_id WHERE v.id = ? AND e.id = ?"
    " ON CONFLICT (visit_id, entry_id) DO UPDATE SET"
    " spans_json = excluded.spans_json, confirmed_clear = excluded.confirmed_clear,"
    " allowed_json = excluded.allowed_json, created_at = excluded.created_at"
)


def _spans_json(spans: list[TextSpan]) -> str:
    return json.dumps([[s.start, s.end] for s in spans])


def _spans_from(value: str) -> list[TextSpan]:
    return [TextSpan(start=int(s), end=int(e)) for s, e in json.loads(value)]


def _raise_not_saveable(conn: sqlite3.Connection, vid: int) -> None:
    row = conn.execute(
        "SELECT status, reception_no FROM visits WHERE id = ?", (vid,)
    ).fetchone()
    if row is None:
        raise NotFoundError("visit not found")
    if row["status"] == "generating" and row["reception_no"] is not None:
        # 期限切れの生成中は閉じた受診として扱う（もう一度確かめる）
        expires = conn.execute(
            "SELECT 1 FROM visits WHERE id = ? AND expires_at > ?",
            (vid, dt_to_db(clock_now())),
        ).fetchone()
        if expires is not None:
            raise VisitGeneratingError("visit is generating")
    raise VisitClosedError("visit is printed or expired")


def save_doctor_masks(
    conn: sqlite3.Connection,
    vid: int,
    *,
    upserts: Mapping[int, DoctorMask] | None = None,
    removals: Collection[int] = (),
) -> None:
    """医師の伏せ字を1つのトランザクションで保存する（upserts は置き換え、removals は削除）。

    受診が無ければ NotFoundError、閉じていれば VisitClosedError、生成中なら
    VisitGeneratingError、別の患者の記録があれば ValueError（どれも何も変えない）。
    """
    items = dict(upserts or {})
    created = dt_to_db(clock_now())
    with write_transaction(conn):
        cur = conn.execute(_LOCK_OPEN_VISIT, (vid, created))
        if cur.rowcount == 0:
            _raise_not_saveable(conn, vid)
        for entry_id, mask in items.items():
            values = (
                _spans_json(mask.spans),
                int(bool(mask.confirmed_clear)),
                _spans_json(mask.allowed),
                created,
                vid,
                entry_id,
            )
            if conn.execute(_UPSERT, values).rowcount == 0:
                raise ValueError("記録がこの受診の患者のものでない")
        for entry_id in removals:
            conn.execute(
                "DELETE FROM doctor_masks WHERE visit_id = ? AND entry_id = ?",
                (vid, entry_id),
            )


def list_doctor_masks(conn: sqlite3.Connection, vid: int) -> dict[int, DoctorMask]:
    """その受診の医師の伏せ字（entries.id → DoctorMask）。無ければ空。"""
    rows = conn.execute(
        "SELECT entry_id, spans_json, confirmed_clear, allowed_json FROM doctor_masks"
        " WHERE visit_id = ? ORDER BY entry_id",
        (vid,),
    ).fetchall()
    return {
        int(r["entry_id"]): DoctorMask(
            spans=_spans_from(r["spans_json"]),
            confirmed_clear=bool(r["confirmed_clear"]),
            allowed=_spans_from(r["allowed_json"]),
        )
        for r in rows
    }


def erase_doctor_masks(conn: sqlite3.Connection, vid: int) -> None:
    """その受診の医師の伏せ字を全て消す。呼び出し側で write_transaction を開いておく。"""
    conn.execute("DELETE FROM doctor_masks WHERE visit_id = ?", (vid,))
