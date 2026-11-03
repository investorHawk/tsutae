"""患者の記録（クローズ回答・自由記載の原文）。

recorded_at は JST で保存し、record_date は config.to_jst_date(recorded_at)。
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime

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
from tsutae.schemas import ClosedAnswer, Entry, EntryCreate

SKILL_VERSION_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*@[1-9][0-9]*")

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
    if not isinstance(skill_version, str) or not SKILL_VERSION_PATTERN.fullmatch(
        skill_version
    ):
        raise ValueError("skill_version は <skill-name>@<version>")
    require_exists(conn, "patients", pid, "patient")
    at = to_jst(recorded_at)
    with write_transaction(conn):
        cur = conn.execute(
            "INSERT INTO entries (patient_id, recorded_at, record_date, kind,"
            " by_proxy, skill_version) VALUES (?, ?, ?, ?, ?, ?)",
            (
                pid,
                dt_to_db(at),
                date_to_db(to_jst_date(at)),
                entry.kind,
                int(entry.by_proxy),
                skill_version,
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
    saved = get_entry(conn, entry_id)
    if saved is None:  # pragma: no cover - 直前に書いた行が無いのは異常
        raise RuntimeError("entry was not saved")
    return saved


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
