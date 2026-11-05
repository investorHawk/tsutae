"""D4 レジメンの下書き（regimen_drafts）と採用した版の form JSON（regimen_forms）。

architecture 9c「下書き」。値の検査・描画は `tsutae.regimen`（ここは行の読み書きだけ）。

- 状態 open → working（Claude の1往復の間）→ open。adopted・discarded で閉じる
- 書き換え（`update_draft_form`）・破棄は open のときだけ（条件付きの UPDATE。working・
  閉じた下書きは False）。1つのレジメンに開いている下書きは1つまで（部分 UNIQUE 索引。
  ぶつかれば `DraftConflictError`）
- `begin_working` は generation を上げて working にする（T94 の1往復の始まり。読んだ時の
  form_json・sources_json と同じときだけ）。
  `recover_stale_working` は working のまま上限を過ぎた行を open に戻し、会話に失敗の行
  `{role: system, kind: turn_failed, reason: timeout, generation, at}` を足す
- 採用は呼び出し側が1つの write_transaction で `insert_skill_version_row`・
  `insert_regimen_form_row`・`insert_question_row`・`mark_adopted_row` を呼ぶ
- 採用・破棄で chat_json を '[]' にする（会話の文面を残さない）
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from tsutae.config import now as clock_now
from tsutae.db.connection import dt_from_db, dt_to_db, write_transaction

__all__ = [
    "ACTIVE_STATUSES",
    "DRAFT_STATUSES",
    "DraftConflictError",
    "begin_working",
    "create_draft",
    "discard_draft",
    "find_active_draft",
    "get_draft",
    "get_regimen_form",
    "insert_regimen_form_row",
    "list_active_drafts",
    "mark_adopted_row",
    "recover_stale_working",
    "update_draft_form",
]

DRAFT_STATUSES = ("open", "working", "adopted", "discarded")
ACTIVE_STATUSES = ("open", "working")
TURN_FAILED = "turn_failed"
_COLUMNS = (
    "id, regimen, base_version, status, generation, form_json, sources_json,"
    " chat_json, adopted_version, created_at, updated_at, working_since, closed_at"
)


class DraftConflictError(Exception):
    """開いている下書きが既にある（draft_exists）・識別名が使われている（code_taken）。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _is_active_conflict(exc: sqlite3.IntegrityError) -> bool:
    text = str(exc)
    return "UNIQUE" in text and "regimen_drafts.regimen" in text


def _row(row: sqlite3.Row) -> dict[str, Any]:
    item: dict[str, Any] = dict(row)
    item["chat"] = json.loads(item.pop("chat_json"))
    for key in ("created_at", "updated_at", "working_since", "closed_at"):
        item[key] = dt_from_db(row[key])
    return item


def create_draft(
    conn: sqlite3.Connection,
    *,
    regimen: str | None,
    base_version: int | None,
    form_json: str,
    sources_json: str = "{}",
) -> int:
    """open の下書きを作り id を返す。同じ regimen の開いた下書きがあれば draft_exists。"""
    at = dt_to_db(clock_now())
    try:
        with write_transaction(conn):
            cur = conn.execute(
                "INSERT INTO regimen_drafts (regimen, base_version, form_json,"
                " sources_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (regimen, base_version, form_json, sources_json, at, at),
            )
    except sqlite3.IntegrityError as exc:
        if _is_active_conflict(exc):
            raise DraftConflictError("draft_exists") from None
        raise
    return int(cur.lastrowid)


def get_draft(conn: sqlite3.Connection, draft_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM regimen_drafts WHERE id = ?", (draft_id,)
    ).fetchone()
    return None if row is None else _row(row)


def find_active_draft(conn: sqlite3.Connection, regimen: str) -> dict[str, Any] | None:
    """その regimen の開いている（open・working）下書き。"""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM regimen_drafts"
        " WHERE regimen = ? AND status IN ('open', 'working')",
        (regimen,),
    ).fetchone()
    return None if row is None else _row(row)


def list_active_drafts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """開いている下書き（id 昇順）。"""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM regimen_drafts"
        " WHERE status IN ('open', 'working') ORDER BY id"
    ).fetchall()
    return [_row(r) for r in rows]


def update_draft_form(
    conn: sqlite3.Connection,
    draft_id: int,
    *,
    form_json: str,
    sources_json: str,
    regimen: str | None,
    expected_form_json: str | None = None,
    expected_sources_json: str | None = None,
) -> bool:
    """open の下書きのフォーム・出どころ・識別名を書き換える。open でなければ False。

    `expected_*` を渡すと、今の値がそれと同じときだけ書く（読んでから書くまでの間に別の
    書き手が変えていれば False。楽観的な検査）。識別名が別の開いた下書きとぶつかれば
    `DraftConflictError("code_taken")`。
    """
    sql = (
        "UPDATE regimen_drafts SET form_json = ?, sources_json = ?,"
        " regimen = ?, updated_at = ? WHERE id = ? AND status = 'open'"
    )
    params: list[object] = [
        form_json,
        sources_json,
        regimen,
        dt_to_db(clock_now()),
        draft_id,
    ]
    if expected_form_json is not None:
        sql += " AND form_json = ?"
        params.append(expected_form_json)
    if expected_sources_json is not None:
        sql += " AND sources_json = ?"
        params.append(expected_sources_json)
    try:
        with write_transaction(conn):
            cur = conn.execute(sql, params)
    except sqlite3.IntegrityError as exc:
        if _is_active_conflict(exc):
            raise DraftConflictError("code_taken") from None
        raise
    return cur.rowcount > 0


def begin_working(
    conn: sqlite3.Connection,
    draft_id: int,
    *,
    at: datetime | None = None,
    expected_form_json: str | None = None,
    expected_sources_json: str | None = None,
) -> int | None:
    """open → working にし、上げた generation を返す。open でなければ None。

    `expected_*` を渡すと、今の値がそれと同じときだけ working にする（往復が読んでから
    始めるまでの間に PATCH が入っていれば None。`update_draft_form` と同じ楽観的な検査）。
    """
    stamp = dt_to_db(at if at is not None else clock_now())
    sql = (
        "UPDATE regimen_drafts SET status = 'working', generation = generation + 1,"
        " working_since = ?, updated_at = ? WHERE id = ? AND status = 'open'"
    )
    params: list[object] = [stamp, stamp, draft_id]
    if expected_form_json is not None:
        sql += " AND form_json = ?"
        params.append(expected_form_json)
    if expected_sources_json is not None:
        sql += " AND sources_json = ?"
        params.append(expected_sources_json)
    with write_transaction(conn):
        cur = conn.execute(sql, params)
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT generation FROM regimen_drafts WHERE id = ?", (draft_id,)
        ).fetchone()
    return int(row["generation"])


def _failed_row(generation: int, at: str) -> dict[str, Any]:
    return {
        "role": "system",
        "kind": TURN_FAILED,
        "reason": "timeout",
        "generation": generation,
        "at": at,
    }


def recover_stale_working(
    conn: sqlite3.Connection, *, timeout_s: float, now: datetime | None = None
) -> int:
    """working のまま timeout_s を過ぎた下書きを open に戻し、戻した数を返す。

    working_since が今より先の行・無い行も取り残されたとみなす（TSUTAE_TODAY の時計は
    プロセスの起動を基準にするので、起動し直すと過去に戻ることがある）。
    遅れて届いた往復の結果は、working・同じ generation でないので反映されない（T94）。
    """
    at = now if now is not None else clock_now()
    limit = dt_to_db(at - timedelta(seconds=timeout_s))
    stamp = dt_to_db(at)
    with write_transaction(conn):
        rows = conn.execute(
            "SELECT id, generation, chat_json FROM regimen_drafts"
            " WHERE status = 'working' AND (working_since IS NULL"
            " OR working_since <= ? OR working_since > ?)",
            (limit, stamp),
        ).fetchall()
        for row in rows:
            chat = [
                *json.loads(row["chat_json"]),
                _failed_row(row["generation"], stamp),
            ]
            conn.execute(
                "UPDATE regimen_drafts SET status = 'open', working_since = NULL,"
                " chat_json = ?, updated_at = ? WHERE id = ? AND status = 'working'",
                (json.dumps(chat, ensure_ascii=False), stamp, row["id"]),
            )
    return len(rows)


def discard_draft(conn: sqlite3.Connection, draft_id: int) -> bool:
    """open の下書きを discarded にし、会話の文面を消す。open でなければ False。"""
    stamp = dt_to_db(clock_now())
    with write_transaction(conn):
        cur = conn.execute(
            "UPDATE regimen_drafts SET status = 'discarded', chat_json = '[]',"
            " closed_at = ?, updated_at = ? WHERE id = ? AND status = 'open'",
            (stamp, stamp, draft_id),
        )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 採用（呼び出し側で write_transaction を開く）
# ---------------------------------------------------------------------------


def mark_adopted_row(
    conn: sqlite3.Connection,
    draft_id: int,
    *,
    form_json: str,
    sources_json: str,
    adopted_version: int,
) -> bool:
    """確かめた時と同じフォーム・出どころの open の下書きだけを adopted にする。"""
    stamp = dt_to_db(clock_now())
    cur = conn.execute(
        "UPDATE regimen_drafts SET status = 'adopted', adopted_version = ?,"
        " chat_json = '[]', closed_at = ?, updated_at = ?"
        " WHERE id = ? AND status = 'open' AND form_json = ? AND sources_json = ?",
        (adopted_version, stamp, stamp, draft_id, form_json, sources_json),
    )
    return cur.rowcount > 0


def insert_regimen_form_row(
    conn: sqlite3.Connection, skill_name: str, version: int, form_json: str
) -> None:
    """採用した版の form JSON を入れる（skill_versions に同じ版が要る。外部キー）。"""
    conn.execute(
        "INSERT INTO regimen_forms (skill_name, version, form_json, created_at)"
        " VALUES (?, ?, ?, ?)",
        (skill_name, version, form_json, dt_to_db(clock_now())),
    )


def get_regimen_form(
    conn: sqlite3.Connection, skill_name: str, version: int
) -> str | None:
    row = conn.execute(
        "SELECT form_json FROM regimen_forms WHERE skill_name = ? AND version = ?",
        (skill_name, version),
    ).fetchone()
    return None if row is None else str(row["form_json"])
