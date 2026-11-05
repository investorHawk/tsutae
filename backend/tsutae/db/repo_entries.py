"""患者の記録（クローズ回答・自由記載の原文）。

recorded_at は JST で保存し、record_date は config.to_jst_date(recorded_at)。
`add_entry_once` は同じ患者・同じ内容（`entry_content` が一致）の記録が直近 window
以内にあれば、新しく作らずそれを返す（送り直しで二重にしない）。
`undo_too_sick_entry` は患者が押し間違えた「つらくて書けない」を消す（取り消し。P2-5）。
記録の行を入れると日付の印（record_marks）も同じトランザクションで付き、取り消しでその日の
記録が無くなれば印も消える（通知の判定が使う。plan-device-records §4.4）。
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Literal

from tsutae.config import to_jst_date
from tsutae.db.connection import (
    date_from_db,
    date_to_db,
    dt_from_db,
    dt_to_db,
    require_exists,
    to_jst,
    write_transaction,
)
from tsutae.db.repo_record_marks import clear_mark_if_no_entries, upsert_mark_row
from tsutae.schemas import ClosedAnswer, Entry, EntryCreate

SKILL_VERSION_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*@[1-9][0-9]*")

UndoResult = Literal["deleted", "not_found", "not_undoable"]

_ENTRY_COLUMNS = (
    "e.id, e.patient_id, e.recorded_at, e.record_date, e.kind, e.by_proxy,"
    " e.skill_version, f.text AS free_text"
)


def add_entry(
    conn: sqlite3.Connection,
    pid: str,
    entry: EntryCreate,
    recorded_at: datetime,
    skill_version: str,
) -> Entry:
    """記録を1件保存し、保存した内容を Entry で返す。"""
    validate_skill_version(skill_version)
    require_exists(conn, "patients", pid, "patient")
    with write_transaction(conn):
        entry_id = insert_entry_rows(conn, pid, entry, recorded_at, skill_version)
    saved = get_entry(conn, entry_id)
    if saved is None:  # pragma: no cover - 直前に書いた行が無いのは異常
        raise RuntimeError("entry was not saved")
    return saved


def add_entry_once(
    conn: sqlite3.Connection,
    pid: str,
    entry: EntryCreate,
    recorded_at: datetime,
    skill_version: str,
    window: timedelta,
) -> Entry:
    """同じ内容の記録が recorded_at の前 window 以内にあればそれを、無ければ保存して返す。

    探すのと入れるのを1つの write_transaction で行う（同時の送り直しでも1件）。
    同じとみなすのは、内容に加えて記録日（JST）と skill_version も同じときだけ
    （日をまたいだ記録・D4 の承認で版が変わった後の記録は別の記録。spec 4.1・4.3）。
    """
    validate_skill_version(skill_version)
    if window < timedelta(0):
        raise ValueError("window は 0 以上")
    require_exists(conn, "patients", pid, "patient")
    wanted = entry_content(entry)
    since = dt_to_db(recorded_at - window)
    with write_transaction(conn):
        recent = _load_entries(
            conn, "e.patient_id = ? AND e.recorded_at >= ?", (pid, since)
        )
        day = to_jst_date(recorded_at)
        found = next(
            (
                e
                for e in recent
                if saved_content(e) == wanted
                and e.record_date == day
                and e.skill_version == skill_version
            ),
            None,
        )
        if found is not None:
            return found
        entry_id = insert_entry_rows(conn, pid, entry, recorded_at, skill_version)
    saved = get_entry(conn, entry_id)
    if saved is None:  # pragma: no cover - 直前に書いた行が無いのは異常
        raise RuntimeError("entry was not saved")
    return saved


def undo_too_sick_entry(
    conn: sqlite3.Connection, pid: str, entry_id: int, since: datetime
) -> UndoResult:
    """本人の「つらくて書けない」の記録を1件消す（取り消し）。

    消すのは pid の記録で、kind が too_sick、recorded_at が since 以降、その記録の後に
    その患者の受診の受付（visits）が無いものだけ（受付の後はレポートの材料になりうる）。
    pid の記録でなければ "not_found"（他人の記録の有る無しを明かさない）、条件に
    合わなければ "not_undoable"。調べるのと消すのを1つの write_transaction で行う。
    回答・自由記載の行は ON DELETE CASCADE で一緒に消える（too_sick には無い）。
    """
    with write_transaction(conn):
        row = conn.execute(
            "SELECT kind, recorded_at, record_date FROM entries"
            " WHERE id = ? AND patient_id = ?",
            (entry_id, pid),
        ).fetchone()
        if row is None:
            return "not_found"
        if row["kind"] != "too_sick" or row["recorded_at"] < dt_to_db(since):
            return "not_undoable"
        # 日時は固定幅の JST 文字列なので、文字列の比較が時刻の順と一致する
        visited = conn.execute(
            "SELECT 1 FROM visits WHERE patient_id = ? AND created_at >= ? LIMIT 1",
            (pid, row["recorded_at"]),
        ).fetchone()
        if visited is not None:
            return "not_undoable"
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        clear_mark_if_no_entries(conn, pid, row["record_date"])
    return "deleted"


def _content(
    too_sick: bool, by_proxy: bool, answers: list[ClosedAnswer], free_text: str | None
) -> dict[str, Any]:
    ordered = sorted(answers, key=lambda a: a.question_key)
    return {
        "too_sick": too_sick,
        "by_proxy": by_proxy,
        "answers": [a.model_dump(mode="json") for a in ordered],
        "free_text": free_text,
    }


def entry_content(entry: EntryCreate) -> dict[str, Any]:
    """記録の内容の正規化した形（回答は question_key 順。JSON にできる値だけ）。"""
    return _content(
        entry.too_sick, entry.by_proxy, list(entry.answers), entry.free_text
    )


def saved_content(entry: Entry) -> dict[str, Any]:
    """保存済みの記録の内容（`entry_content` と比べられる形）。"""
    return _content(
        entry.kind == "too_sick", entry.by_proxy, list(entry.answers), entry.free_text
    )


def validate_skill_version(skill_version: str) -> None:
    if not isinstance(skill_version, str) or not SKILL_VERSION_PATTERN.fullmatch(
        skill_version
    ):
        raise ValueError("skill_version は <skill-name>@<version>")


def insert_entry_rows(
    conn: sqlite3.Connection,
    pid: str,
    entry: EntryCreate,
    recorded_at: datetime,
    skill_version: str,
) -> int:
    """記録の行（回答・自由記載を含む）と日付の印を入れて id を返す。

    検査（validate_skill_version・患者の有無）は呼び出し側で済ませ、
    write_transaction を開いておくこと。
    """
    entry_id = insert_entry_row(conn, pid, entry, recorded_at, skill_version)
    upsert_mark_row(conn, pid, to_jst(recorded_at))
    return entry_id


def insert_entry_row(
    conn: sqlite3.Connection,
    pid: str,
    entry: EntryCreate,
    recorded_at: datetime,
    skill_version: str,
    client_entry_id: str | None = None,
) -> int:
    """記録の行（回答・自由記載を含む）だけを入れて id を返す。印は書かない。

    write_transaction を開いておくこと。
    """
    at = to_jst(recorded_at)
    cur = conn.execute(
        "INSERT INTO entries (patient_id, recorded_at, record_date, kind,"
        " by_proxy, skill_version, client_entry_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            pid,
            dt_to_db(at),
            date_to_db(to_jst_date(at)),
            entry.kind,
            int(entry.by_proxy),
            skill_version,
            client_entry_id,
        ),
    )
    entry_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO closed_answers (entry_id, question_key, value, temperature)"
        " VALUES (?, ?, ?, ?)",
        [(entry_id, a.question_key, a.value, a.temperature) for a in entry.answers],
    )
    if entry.free_text is not None:
        conn.execute(
            "INSERT INTO free_texts (entry_id, text) VALUES (?, ?)",
            (entry_id, entry.free_text),
        )
    return entry_id


def get_entry(conn: sqlite3.Connection, entry_id: int) -> Entry | None:
    entries = _load_entries(conn, "e.id = ?", (entry_id,))
    return entries[0] if entries else None


def list_entries(
    conn: sqlite3.Connection,
    pid: str,
    start: date | None = None,
    end: date | None = None,
) -> list[Entry]:
    """患者の記録を recorded_at 昇順で返す。start/end は record_date（両端含む）。"""
    clauses = ["e.patient_id = ?"]
    params: list[object] = [pid]
    if start is not None:
        clauses.append("e.record_date >= ?")
        params.append(date_to_db(start))
    if end is not None:
        clauses.append("e.record_date <= ?")
        params.append(date_to_db(end))
    return _load_entries(conn, " AND ".join(clauses), tuple(params))


def last_record_dates(conn: sqlite3.Connection) -> dict[str, date]:
    """患者ごとの最後の記録日（record_date の最大）。記録の無い患者は含まない。"""
    rows = conn.execute(
        "SELECT patient_id, MAX(record_date) AS last FROM entries GROUP BY patient_id"
    ).fetchall()
    return {r["patient_id"]: date_from_db(r["last"]) for r in rows}


def _load_entries(
    conn: sqlite3.Connection, where: str, params: tuple[object, ...]
) -> list[Entry]:
    """where は内部の固定句のみ（値は params）。"""
    rows = conn.execute(
        f"SELECT {_ENTRY_COLUMNS} FROM entries e"
        " LEFT JOIN free_texts f ON f.entry_id = e.id"
        f" WHERE {where} ORDER BY e.recorded_at, e.id",
        params,
    ).fetchall()
    if not rows:
        return []
    answers = _load_answers(conn, where, params)
    return [
        Entry(
            id=r["id"],
            patient_id=r["patient_id"],
            recorded_at=dt_from_db(r["recorded_at"]),
            record_date=date_from_db(r["record_date"]),
            kind=r["kind"],
            by_proxy=bool(r["by_proxy"]),
            skill_version=r["skill_version"],
            answers=answers.get(r["id"], []),
            free_text=r["free_text"],
        )
        for r in rows
    ]


def _load_answers(
    conn: sqlite3.Connection, where: str, params: tuple[object, ...]
) -> dict[int, list[ClosedAnswer]]:
    rows = conn.execute(
        "SELECT a.entry_id, a.question_key, a.value, a.temperature"
        " FROM closed_answers a"
        f" WHERE a.entry_id IN (SELECT e.id FROM entries e WHERE {where})"
        " ORDER BY a.entry_id, a.rowid",
        params,
    ).fetchall()
    grouped: dict[int, list[ClosedAnswer]] = defaultdict(list)
    for r in rows:
        grouped[r["entry_id"]].append(
            ClosedAnswer(
                question_key=r["question_key"],
                value=r["value"],
                temperature=r["temperature"],
            )
        )
    return dict(grouped)
