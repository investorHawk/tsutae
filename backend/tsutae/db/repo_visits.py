"""受診（受付番号・状態・期限）と、変換結果（timelines）・レポート（reports）。

印刷済み・期限切れでは reports と timelines を削除し reception_no を NULL にする。
visits の行そのものは残す（状態の履歴として）。

消した中身が戻らないように:
- status=printed にする経路は mark_printed だけ（set_visit_status は printed を拒否）
- 閉じた受診（印刷済み、または期限切れ）には save_timeline / save_report /
  save_visit_result / set_visit_status できない（VisitClosedError）。期限切れは
  `expires_at <= 今`（`config.now()`）で決める。purge_expired がまだ受付番号を
  消していなくても拒否する（purge はしない。消すのは purge_expired だけ）。
  生成が印刷済み操作や期限より遅れて終わる場合に備える
- save_visit_result は timeline・report・status を1つのトランザクションで書く（途中で
  失敗すれば何も残らない）。生成の終わりはこれを使う
- purge_expired は status を問わず、期限を過ぎて中身が残っている受診を全て消す
- create_visit_once は同じ患者・日・受付番号の期限内の受診があれば作らない（送り直し）
- begin_regeneration は開いている failed・ready（fallback=True）の受診だけを
  generating に戻す（医師の「AI でもう一度変換」。確認と書き込みを1文で行う）
"""

from __future__ import annotations

import contextlib
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
    cleaned = _check_new_visit(conn, pid, reception_no, course_no)
    with write_transaction(conn):
        return _insert_visit(conn, pid, cleaned, visit_date, expires_at, course_no)


def create_visit_once(
    conn: sqlite3.Connection,
    pid: str,
    reception_no: str,
    visit_date: date,
    expires_at: datetime,
    course_no: int | None,
) -> tuple[int, bool]:
    """同じ患者・同じ日・同じ受付番号で、受付番号が残り期限内の受診があればその id と
    False を、無ければ作って (id, True) を返す（送り直しで二重にしない）。

    探すのと入れるのを1つの write_transaction で行う。期限内は `expires_at > 今`
    （`config.now()`）。印刷済み・期限切れ（受付番号を消した受診）は使わない。
    """
    cleaned = _check_new_visit(conn, pid, reception_no, course_no)
    with write_transaction(conn):
        row = conn.execute(
            "SELECT id FROM visits WHERE patient_id = ? AND reception_no = ?"
            " AND visit_date = ? AND expires_at > ? ORDER BY id LIMIT 1",
            (pid, cleaned, date_to_db(visit_date), dt_to_db(clock_now())),
        ).fetchone()
        if row is not None:
            return int(row["id"]), False
        vid = _insert_visit(conn, pid, cleaned, visit_date, expires_at, course_no)
    return vid, True


def _check_new_visit(
    conn: sqlite3.Connection, pid: str, reception_no: str, course_no: int | None
) -> str:
    cleaned = _clean_reception_no(reception_no)
    if course_no is not None and (not isinstance(course_no, int) or course_no < 1):
        raise ValueError("course_no は1以上の整数")
    require_exists(conn, "patients", pid, "patient")
    return cleaned


def _insert_visit(
    conn: sqlite3.Connection,
    pid: str,
    cleaned: str,
    visit_date: date,
    expires_at: datetime,
    course_no: int | None,
) -> int:
    """write_transaction の内側で呼ぶ。"""
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
    patient_id: str | None = None,
) -> list[dict[str, Any]]:
    """受診を id 昇順（受付順）で返す。

    statuses で状態を絞れる。active_only=True なら受付番号が残っている受診だけ
    （印刷済み・期限切れを除く。期限切れは status を変えないので、印刷待ちの一覧は
    これで絞る）。patient_id があればその患者の受診だけ。
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
    if patient_id is not None:
        clauses.append("patient_id = ?")
        params = (*params, patient_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT {_VISIT_COLUMNS} FROM visits{where} ORDER BY id", params
    )
    return [_visit_row(r) for r in rows.fetchall()]


def list_visit_days(conn: sqlite3.Connection, pid: str) -> list[dict[str, Any]]:
    """その患者の受診日（受付のあった日）と、その日の最初の受付の時刻を新しい順で返す。

    患者の「これまでの記録」の区切りに使う。状態・期限（印刷済み・期限切れ）を問わず
    受付があれば受診日とする。返すのは `visit_date`（date）と `received_at`
    （datetime）だけ（受付番号・状態・変換結果は読まない）。
    """
    rows = conn.execute(
        "SELECT visit_date, MIN(created_at) AS received_at FROM visits"
        " WHERE patient_id = ? GROUP BY visit_date ORDER BY visit_date DESC",
        (pid,),
    )
    return [
        {
            "visit_date": date_from_db(r["visit_date"]),
            "received_at": dt_from_db(r["received_at"]),
        }
        for r in rows.fetchall()
    ]


def set_visit_status(
    conn: sqlite3.Connection, vid: int, status: str, fallback: bool | None = None
) -> None:
    """状態を変える。fallback=None なら fallback は変えない。

    printed は受け付けない（中身を消さずに印刷済みにしないよう mark_printed を使う）。
    受診が無ければ NotFoundError、印刷済み・期限切れ（purge 前を含む）なら
    VisitClosedError。
    """
    _validate_settable_status(status)
    with write_transaction(conn):
        changed = _update_status(conn, vid, status, fallback, _now_db())
    if not changed:
        _raise_not_open(conn, vid)


def _validate_settable_status(status: str) -> None:
    if status == "printed":
        raise ValueError("printed にするのは mark_printed だけ")
    _validate_status(status)


# 閉じた受診（印刷済み・受付番号を消した・期限を過ぎた）は条件付き UPDATE で触らない。
# 別の接続の mark_printed と競合しても printed を ready に戻さない。期限の比較は
# purge_expired（expires_at <= now で消す）と同じ境界: expires_at > now の間だけ開いている。
# 日時は固定幅の JST 文字列なので、文字列の比較が時刻の順と一致する（connection.py）
_STATUS_GUARD = (
    " AND reception_no IS NOT NULL AND status != 'printed' AND expires_at > ?"
)


def _now_db() -> str:
    """条件付き書き込みで expires_at と比べる「今」。"""
    return dt_to_db(clock_now())


def _update_status(
    conn: sqlite3.Connection,
    vid: int,
    status: str,
    fallback: bool | None,
    now_db: str,
) -> bool:
    """条件付きで状態を変え、変えたら True。呼び出し側で write_transaction を開く。"""
    if fallback is None:
        cur = conn.execute(
            "UPDATE visits SET status = ? WHERE id = ?" + _STATUS_GUARD,
            (status, vid, now_db),
        )
    else:
        cur = conn.execute(
            "UPDATE visits SET status = ?, fallback = ? WHERE id = ?" + _STATUS_GUARD,
            (status, int(bool(fallback)), vid, now_db),
        )
    return cur.rowcount > 0


# やり直せるのは、生成が終わって AI の結果が無い受診（failed か、AI 変換なしの ready）
_REGENERABLE = " AND (status = 'failed' OR (status = 'ready' AND fallback = 1))"


def begin_regeneration(conn: sqlite3.Connection, vid: int) -> bool:
    """開いている failed・ready（fallback=True）の受診を generating に戻し True を返す。

    fallback は False に戻す（結果は次の save_visit_result が決める）。レポートと変換
    結果は残す（新しい生成が上書きする）。それ以外（generating・AI の結果で ready・
    印刷済み・期限切れ（purge 前を含む））は何も変えずに False。条件の確認と書き込みを
    1つの UPDATE で行うので、二重に押されても generating にするのは1回だけ。
    受診が無ければ NotFoundError。
    """
    with write_transaction(conn):
        cur = conn.execute(
            "UPDATE visits SET status = 'generating', fallback = 0 WHERE id = ?"
            + _STATUS_GUARD
            + _REGENERABLE,
            (vid, _now_db()),
        )
    if cur.rowcount > 0:
        return True
    if get_visit(conn, vid) is None:
        raise NotFoundError("visit not found")
    return False


def _raise_not_open(conn: sqlite3.Connection, vid: int) -> None:
    """保存できなかった理由を例外にする（受診が無い／閉じた受診）。"""
    if get_visit(conn, vid) is None:
        raise NotFoundError("visit not found")
    raise VisitClosedError("visit is printed or expired")


_OPEN_VISIT = (
    " FROM visits WHERE id = ? AND reception_no IS NOT NULL AND expires_at > ?"
)
_TIMELINE_SQL = (
    "INSERT INTO timelines (visit_id, json) SELECT id, ?"
    + _OPEN_VISIT
    + " ON CONFLICT (visit_id) DO UPDATE SET json = excluded.json"
)
_REPORT_SQL = (
    "INSERT INTO reports (visit_id, html, data_json) SELECT id, ?, ?"
    + _OPEN_VISIT
    + " ON CONFLICT (visit_id) DO UPDATE SET"
    " html = excluded.html, data_json = excluded.data_json"
)


def _write_if_open(
    conn: sqlite3.Connection,
    vid: int,
    sql: str,
    values: tuple[object, ...],
    now_db: str,
) -> None:
    """受付番号が残っていて期限前の受診にだけ書く（確認と書き込みを1文で行う）。

    sql は `_TIMELINE_SQL` / `_REPORT_SQL`（内部の固定文）。書けなければ例外を出す。
    呼び出し側で write_transaction を開いておくこと（例外で rollback される）。
    """
    cur = conn.execute(sql, (*values, vid, now_db))
    if cur.rowcount == 0:
        _raise_not_open(conn, vid)


def _check_html(html: object) -> None:
    if not isinstance(html, str):
        raise ValueError("html は文字列")


def save_timeline(conn: sqlite3.Connection, vid: int, timeline: Timeline) -> None:
    """変換結果を保存する（再生成に備えて上書き可）。

    受診が無ければ NotFoundError、印刷済み・期限切れなら VisitClosedError。
    """
    values = (timeline.model_dump_json(),)
    with write_transaction(conn):
        _write_if_open(conn, vid, _TIMELINE_SQL, values, _now_db())


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
    _check_html(html)
    values = (html, data.model_dump_json())
    with write_transaction(conn):
        _write_if_open(conn, vid, _REPORT_SQL, values, _now_db())


def save_visit_result(
    conn: sqlite3.Connection,
    vid: int,
    *,
    timeline: Timeline,
    html: str,
    data: ReportData,
    status: str,
    fallback: bool,
) -> None:
    """変換結果・レポート・状態（と fallback）を1つのトランザクションで保存する。

    どれかが失敗すれば全て rollback する（timeline だけ残る、などは起きない）。
    受診が無ければ NotFoundError、印刷済み・期限切れ（purge 前を含む）なら
    VisitClosedError（何も変えない）。
    status は set_visit_status と同じく printed を受け付けない。
    """
    _validate_settable_status(status)
    _check_html(html)
    values = (timeline.model_dump_json(), html, data.model_dump_json())
    with write_transaction(conn):
        now_db = _now_db()  # ロックを取った後の「今」を3つの文で共有する
        # 先に条件付きで状態を変える（閉じた受診なら何も書かずに例外）
        if not _update_status(conn, vid, status, bool(fallback), now_db):
            _raise_not_open(conn, vid)
        _write_if_open(conn, vid, _TIMELINE_SQL, values[:1], now_db)
        _write_if_open(conn, vid, _REPORT_SQL, values[1:], now_db)


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


def mark_printed(
    conn: sqlite3.Connection, vid: int, *, refuse_generating: bool = False
) -> bool:
    """印刷済みにする。レポート・変換結果・受付番号を削除し status=printed。

    refuse_generating=True なら、生成中（やり直しの最中を含む）は何も変えずに False。
    状態の確認と削除は同じ書き込みロックの中で行う（AI でもう一度変換との競合で、
    生成中の受診を印刷済みにしない）。
    """
    require_exists(conn, "visits", vid, "visit")
    guard = " AND status != 'generating'" if refuse_generating else ""
    with write_transaction(conn):
        # 状態の確認は UPDATE の条件で行う（最初の書き込みで SQLite のトランザクションが
        # 始まるので、確認と削除の間に別の接続が generating にすることはできない）
        cur = conn.execute(
            "UPDATE visits SET status = 'printed' WHERE id = ?" + guard, (vid,)
        )
        if cur.rowcount == 0:
            return False
        _erase_results(conn, vid)
    _checkpoint(conn)
    return True


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
    if ids:
        _checkpoint(conn)
    return len(ids)


def _checkpoint(conn: sqlite3.Connection) -> None:
    """消した行が WAL に残らないよう、本体へ書き戻して WAL を切り詰める（できる範囲で）。

    secure_delete は本体の中身を消すが、WAL の古い記録は checkpoint まで残る。
    他の接続が読んでいると全部は書き戻せないが、その場合も次の checkpoint で消える。
    """
    with contextlib.suppress(sqlite3.Error):
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
