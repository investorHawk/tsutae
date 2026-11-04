"""患者（仮名ID）とコース（実投与日）。"""

from __future__ import annotations

import re
import secrets
import sqlite3
import string
from typing import Any

from tsutae.config import now
from tsutae.db.connection import (
    NotFoundError,
    date_from_db,
    date_to_db,
    dt_from_db,
    dt_to_db,
    require_exists,
    write_transaction,
)
from tsutae.schemas import Course

PATIENT_ID_PATTERN = re.compile(r"P-[A-Z0-9]{8}")
REGIMENS = ("FOLFOX", "CAPOX")
_ID_ALPHABET = string.ascii_uppercase + string.digits
_ID_ATTEMPTS = 5


def _new_patient_id() -> str:
    return "P-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))


def _validate_patient_id(patient_id: str) -> None:
    if not isinstance(patient_id, str) or not PATIENT_ID_PATTERN.fullmatch(patient_id):
        raise ValueError("patient_id は P- + 英大文字数字8桁")


def create_patient(
    conn: sqlite3.Connection, regimen: str, patient_id: str | None = None
) -> str:
    """患者を登録して仮名IDを返す。patient_id 指定時はそれを使う（合成データ用）。"""
    if regimen not in REGIMENS:
        raise ValueError(f"unknown regimen: {regimen!r}")
    if patient_id is not None:
        validate_new_patient(regimen, patient_id)
        _insert_patient(conn, patient_id, regimen)
        return patient_id
    for _ in range(_ID_ATTEMPTS):
        candidate = _new_patient_id()
        try:
            _insert_patient(conn, candidate, regimen)
        except sqlite3.IntegrityError:
            continue
        return candidate
    raise RuntimeError("仮名IDの生成に失敗した")


def validate_new_patient(regimen: str, patient_id: str) -> None:
    """regimen と（指定された）仮名IDの形を検査する。違えば ValueError。"""
    if regimen not in REGIMENS:
        raise ValueError(f"unknown regimen: {regimen!r}")
    _validate_patient_id(patient_id)


def _insert_patient(conn: sqlite3.Connection, pid: str, regimen: str) -> None:
    with write_transaction(conn):
        insert_patient_row(conn, pid, regimen)


def insert_patient_row(
    conn: sqlite3.Connection, pid: str, regimen: str, *, skip_existing: bool = False
) -> bool:
    """患者の行を入れ、入れたら True。呼び出し側で write_transaction を開いておくこと。

    skip_existing=True なら、同じ仮名IDがいれば何もせず False（確認と挿入を1文で行う）。
    """
    conflict = " ON CONFLICT (id) DO NOTHING" if skip_existing else ""
    cur = conn.execute(
        "INSERT INTO patients (id, regimen, created_at) VALUES (?, ?, ?)" + conflict,
        (pid, regimen, dt_to_db(now())),
    )
    return cur.rowcount > 0


def _patient_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "regimen": row["regimen"],
        "created_at": dt_from_db(row["created_at"]),
    }


def get_patient(conn: sqlite3.Connection, pid: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, regimen, created_at FROM patients WHERE id = ?", (pid,)
    ).fetchone()
    return None if row is None else _patient_row(row)


def list_patients(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, regimen, created_at FROM patients ORDER BY created_at, rowid"
    ).fetchall()
    return [_patient_row(r) for r in rows]


# ---------------------------------------------------------------------------
# コース
# ---------------------------------------------------------------------------

_COURSE_COLUMNS = (
    "id, patient_id, course_no, infusion_date, planned_date, next_visit, note"
)


def _course_row(row: sqlite3.Row) -> Course:
    return Course(
        id=row["id"],
        patient_id=row["patient_id"],
        course_no=row["course_no"],
        infusion_date=date_from_db(row["infusion_date"]),
        planned_date=date_from_db(row["planned_date"]),
        next_visit=date_from_db(row["next_visit"]),
        note=row["note"],
    )


def upsert_course(conn: sqlite3.Connection, course: Course) -> Course:
    """(patient_id, course_no) で登録・上書きし、id 付きの新しい Course を返す。"""
    require_exists(conn, "patients", course.patient_id, "patient")
    with write_transaction(conn):
        upsert_course_row(conn, course)
    row = conn.execute(
        f"SELECT {_COURSE_COLUMNS} FROM courses WHERE patient_id = ? AND course_no = ?",
        (course.patient_id, course.course_no),
    ).fetchone()
    if row is None:  # pragma: no cover - 直前に書いた行が無いのは異常
        raise NotFoundError("course not found")
    return _course_row(row)


def upsert_course_row(conn: sqlite3.Connection, course: Course) -> None:
    """コースの行を入れる・上書きする。呼び出し側で write_transaction を開いておくこと。"""
    conn.execute(
        "INSERT INTO courses (patient_id, course_no, infusion_date, planned_date,"
        " next_visit, note) VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (patient_id, course_no) DO UPDATE SET"
        " infusion_date = excluded.infusion_date,"
        " planned_date = excluded.planned_date,"
        " next_visit = excluded.next_visit,"
        " note = excluded.note",
        (
            course.patient_id,
            course.course_no,
            date_to_db(course.infusion_date),
            date_to_db(course.planned_date),
            date_to_db(course.next_visit),
            course.note,
        ),
    )


def list_courses(conn: sqlite3.Connection, pid: str) -> list[Course]:
    rows = conn.execute(
        f"SELECT {_COURSE_COLUMNS} FROM courses WHERE patient_id = ?"
        " ORDER BY course_no",
        (pid,),
    ).fetchall()
    return [_course_row(r) for r in rows]
