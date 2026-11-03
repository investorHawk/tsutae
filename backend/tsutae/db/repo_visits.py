"""受診（受付番号・状態・期限）と、変換結果（timelines）・レポート（reports）。

印刷済み・期限切れでは reports と timelines を削除し reception_no を NULL にする。
visits の行そのものは残す（状態の履歴として）。

消した中身が戻らないように:
- status=printed にする経路は mark_printed だけ（set_visit_status は printed を拒否）
- reception_no が NULL の受診（印刷済み・期限切れ）には save_timeline / save_report
  できない（VisitClosedError）。生成が印刷済み操作や期限より遅れて終わる場合に備える
- purge_expired は status を問わず、期限を過ぎて中身が残っている受診を全て消す
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from tsutae.config import now as clock_now
from tsutae.db.connection import (
    NotFoundError,
    VisitClosedError,
    date_from_db,
    date_to_db,
    dt_from_db,
    dt_to_db,
    placeholders,
    require_exists,
    write_transaction,
)
from tsutae.schemas import ReportData, Timeline

VISIT_STATUSES = ("generating", "ready", "printed", "failed")
RECEPTION_NO_MAX = 32

_VISIT_COLUMNS = (
    "id, patient_id, reception_no, visit_date, created_at, status, expires_at,"
    " fallback, course_no"
)


def _validate_status(status: str) -> None:
    if status not in VISIT_STATUSES:
        raise ValueError(f"unknown visit status: {status!r}")


def _clean_reception_no(reception_no: str) -> str:
    if not isinstance(reception_no, str):
        raise ValueError("reception_no は文字列")
    cleaned = reception_no.strip()
    if not cleaned or len(cleaned) > RECEPTION_NO_MAX:
        raise ValueError(f"reception_no は1〜{RECEPTION_NO_MAX}文字")
    return cleaned


def _visit_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "reception_no": row["reception_no"],
        "visit_date": date_from_db(row["visit_date"]),
        "created_at": dt_from_db(row["created_at"]),
        "status": row["status"],
        "expires_at": dt_from_db(row["expires_at"]),
        "fallback": bool(row["fallback"]),
        "course_no": row["course_no"],
    }


def create_visit(
    conn: sqlite3.Connection,
    pid: str,
    reception_no: str,
    visit_date: date,
    expires_at: datetime,
    course_no: int | None,
) -> int:
    """受診を status=generating で作り、id を返す。"""
    cleaned = _clean_reception_no(reception_no)
    if course_no is not None and (not isinstance(course_no, int) or course_no < 1):
        raise ValueError("course_no は1以上の整数")
    require_exists(conn, "patients", pid, "patient")
    with write_transaction(conn):
        cur = conn.execute(
            "INSERT INTO visits (patient_id, reception_no, visit_date, created_at,"
            " status, expires_at, fallback, course_no)"
            " VALUES (?, ?, ?, ?, 'generating', ?, 0, ?)",
            (
                pid,
                cleaned,
                date_to_db(visit_date),
                dt_to_db(clock_now()),
                dt_to_db(expires_at),
                course_no,
            ),
        )
    return int(cur.lastrowid)


def get_visit(conn: sqlite3.Connection, vid: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_VISIT_COLUMNS} FROM visits WHERE id = ?", (vid,)
    ).fetchone()
    return None if row is None else _visit_row(row)


def list_visits(
    conn: sqlite3.Connection,
    statuses: tuple[str, ...] | None = None,
    *,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """受診を id 昇順（受付順）で返す。

    statuses で状態を絞れる。active_only=True なら受付番号が残っている受診だけ
    （印刷済み・期限切れを除く。期限切れは status を変えないので、印刷待ちの一覧は
    これで絞る）。
    """
    clauses: list[str] = []
    params: tuple[str, ...] = ()
    if statuses is not None:
        params = tuple(statuses)
        for status in params:
            _validate_status(status)
        if not params:
            return []
        clauses.append(f"status IN ({placeholders(len(params))})")
    if active_only:
        clauses.append("reception_no IS NOT NULL")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT {_VISIT_COLUMNS} FROM visits{where} ORDER BY id", params
    )
    return [_visit_row(r) for r in rows.fetchall()]


def set_visit_status(
    conn: sqlite3.Connection, vid: int, status: str, fallback: bool | None = None
) -> None:
    """状態を変える。fallback=None なら fallback は変えない。

    printed は受け付けない（中身を消さずに印刷済みにしないよう mark_printed を使う）。
    受診が無ければ NotFoundError、印刷済み・期限切れなら VisitClosedError。
    """
    if status == "printed":
        raise ValueError("printed にするのは mark_printed だけ")
    _validate_status(status)
    # 印刷済み・期限切れ（受付番号を消した受診）は条件付き UPDATE で触らない。
    # 別の接続の mark_printed と競合しても printed を ready に戻さない
    guard = " AND reception_no IS NOT NULL AND status != 'printed'"
    with write_transaction(conn):
        if fallback is None:
            cur = conn.execute(
                "UPDATE visits SET status = ? WHERE id = ?" + guard, (status, vid)
            )
        else:
            cur = conn.execute(
                "UPDATE visits SET status = ?, fallback = ? WHERE id = ?" + guard,
                (status, int(bool(fallback)), vid),
            )
    if cur.rowcount == 0:
        _raise_not_open(conn, vid)


def _raise_not_open(conn: sqlite3.Connection, vid: int) -> None:
    """保存できなかった理由を例外にする（受診が無い／受付番号を消した受診）。"""
    if get_visit(conn, vid) is None:
        raise NotFoundError("visit not found")
    raise VisitClosedError("visit is printed or expired")


def _save_result(
    conn: sqlite3.Connection, vid: int, sql: str, values: tuple[object, ...]
) -> None:
    """受付番号が残っている受診にだけ書く（確認と書き込みを1文で行う）。

    sql は `INSERT INTO <表> (...) SELECT id, ?... FROM visits WHERE id = ?
    AND reception_no IS NOT NULL ON CONFLICT ...` の形の内部の固定文。
    """
    with write_transaction(conn):
        cur = conn.execute(sql, (*values, vid))
        if cur.rowcount == 0:
            _raise_not_open(conn, vid)


_OPEN_VISIT = " FROM visits WHERE id = ? AND reception_no IS NOT NULL"


def save_timeline(conn: sqlite3.Connection, vid: int, timeline: Timeline) -> None:
    """変換結果を保存する（再生成に備えて上書き可）。

    受診が無ければ NotFoundError、印刷済み・期限切れなら VisitClosedError。
    """
    _save_result(
        conn,
        vid,
        "INSERT INTO timelines (visit_id, json) SELECT id, ?"
        + _OPEN_VISIT
        + " ON CONFLICT (visit_id) DO UPDATE SET json = excluded.json",
        (timeline.model_dump_json(),),
    )


def get_timeline(conn: sqlite3.Connection, vid: int) -> Timeline | None:
    row = conn.execute(
        "SELECT json FROM timelines WHERE visit_id = ?", (vid,)
    ).fetchone()
    return None if row is None else Timeline.model_validate_json(row["json"])


def save_report(
    conn: sqlite3.Connection, vid: int, html: str, data: ReportData
) -> None:
    """レポート（描画済み HTML と描画の入力）を保存する（上書き可）。

    受診が無ければ NotFoundError、印刷済み・期限切れなら VisitClosedError。
    """
    if not isinstance(html, str):
        raise ValueError("html は文字列")
    _save_result(
        conn,
        vid,
        "INSERT INTO reports (visit_id, html, data_json) SELECT id, ?, ?"
        + _OPEN_VISIT
        + " ON CONFLICT (visit_id) DO UPDATE SET"
        " html = excluded.html, data_json = excluded.data_json",
        (html, data.model_dump_json()),
    )


def get_report(conn: sqlite3.Connection, vid: int) -> tuple[str, ReportData] | None:
    row = conn.execute(
        "SELECT html, data_json FROM reports WHERE visit_id = ?", (vid,)
    ).fetchone()
    if row is None:
        return None
    return row["html"], ReportData.model_validate_json(row["data_json"])


def _erase_results(conn: sqlite3.Connection, vid: int) -> None:
    """reports・timelines を消し reception_no を NULL にする。

    呼び出し側で write_transaction を開いておくこと。
    """
    conn.execute("DELETE FROM reports WHERE visit_id = ?", (vid,))
    conn.execute("DELETE FROM timelines WHERE visit_id = ?", (vid,))
    conn.execute("UPDATE visits SET reception_no = NULL WHERE id = ?", (vid,))


def mark_printed(conn: sqlite3.Connection, vid: int) -> None:
    """印刷済みにする。レポート・変換結果・受付番号を削除し status=printed。"""
    require_exists(conn, "visits", vid, "visit")
    with write_transaction(conn):
        _erase_results(conn, vid)
        conn.execute("UPDATE visits SET status = 'printed' WHERE id = ?", (vid,))


def purge_expired(conn: sqlite3.Connection, now: datetime) -> int:
    """expires_at <= now で中身が残っている受診から結果と受付番号を消し、件数を返す。

    status は問わない（printed でも中身が残っていれば消す）し、変えもしない
    （failed/ready/generating のまま）。既に消した受診は数えない（冪等）。
    """
    with write_transaction(conn):
        rows = conn.execute(
            "SELECT v.id FROM visits v"
            " WHERE v.expires_at <= ?"
            " AND (v.reception_no IS NOT NULL"
            " OR EXISTS (SELECT 1 FROM reports r WHERE r.visit_id = v.id)"
            " OR EXISTS (SELECT 1 FROM timelines t WHERE t.visit_id = v.id))"
            " ORDER BY v.id",
            (dt_to_db(now),),
        ).fetchall()
        ids = [int(r["id"]) for r in rows]
        for vid in ids:
            _erase_results(conn, vid)
    return len(ids)
