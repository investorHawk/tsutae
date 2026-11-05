"""日付の印（record_marks。plan-device-records §4.4）。

- 記録を書く全ての経路（add_entry・add_entry_once・seed_patient）が同じトランザクションで印も書く
- 取り消しでその日の記録が無くなれば印も消す（残っていれば残す）
- 既存の entries から印を作る移行は何度流してもよく、前の DB でも起動で印ができる
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from tsutae import db
from tsutae.config import JST
from tsutae.db.connection import SCHEMA_PATH
from tsutae.schemas import Entry, EntryCreate

PID = "P-MARK0001"
OTHER = "P-MARK0002"
SKILL = "regimen-folfox@1"
AT = datetime(2026, 11, 9, 20, 15, 0, tzinfo=JST)
TOO_SICK = EntryCreate(too_sick=True)
FREE = EntryCreate(free_text="夜に熱っぽかった")


@pytest.fixture
def conn(tmp_db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_db_path)
    db.init_db(connection)
    db.create_patient(connection, "FOLFOX", patient_id=PID)
    db.create_patient(connection, "CAPOX", patient_id=OTHER)
    yield connection
    connection.close()


def _marks(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT patient_id, record_date, last_marked_at FROM record_marks"
        " ORDER BY patient_id, record_date"
    ).fetchall()
    return [tuple(r) for r in rows]


def test_add_entry_writes_a_mark(conn: sqlite3.Connection) -> None:
    db.add_entry(conn, PID, FREE, AT, SKILL)
    assert _marks(conn) == [(PID, "2026-11-09", AT.isoformat(timespec="microseconds"))]


def test_later_entry_moves_last_marked_at_forward(conn: sqlite3.Connection) -> None:
    later = AT + timedelta(hours=1)
    db.add_entry(conn, PID, FREE, later, SKILL)
    db.add_entry(conn, PID, TOO_SICK, AT, SKILL)
    assert _marks(conn) == [
        (PID, "2026-11-09", later.isoformat(timespec="microseconds"))
    ]


def test_add_entry_once_writes_a_mark_only_once(conn: sqlite3.Connection) -> None:
    window = timedelta(seconds=120)
    first = db.add_entry_once(conn, PID, FREE, AT, SKILL, window)
    again = db.add_entry_once(conn, PID, FREE, AT + timedelta(seconds=5), SKILL, window)
    assert first.id == again.id
    assert _marks(conn) == [(PID, "2026-11-09", AT.isoformat(timespec="microseconds"))]


def test_seed_patient_writes_marks(conn: sqlite3.Connection) -> None:
    entry = Entry(
        id=1,
        patient_id="P-MARK0003",
        recorded_at=AT,
        record_date=AT.date(),
        kind="too_sick",
        by_proxy=False,
        skill_version=SKILL,
    )
    assert db.seed_patient(
        conn, patient_id="P-MARK0003", regimen="FOLFOX", courses=[], entries=[entry]
    )
    assert _marks(conn) == [
        ("P-MARK0003", "2026-11-09", AT.isoformat(timespec="microseconds"))
    ]


def test_marked_patients_is_for_one_day(conn: sqlite3.Connection) -> None:
    db.add_entry(conn, PID, FREE, AT, SKILL)
    db.add_entry(conn, OTHER, FREE, AT - timedelta(days=1), SKILL)
    assert db.marked_patients(conn, date(2026, 11, 9)) == {PID}
    assert db.marked_patients(conn, date(2026, 11, 8)) == {OTHER}
    assert db.marked_patients(conn, date(2026, 11, 7)) == set()


def test_undo_clears_the_mark_when_nothing_is_left(conn: sqlite3.Connection) -> None:
    saved = db.add_entry(conn, PID, TOO_SICK, AT, SKILL)
    assert db.undo_too_sick_entry(conn, PID, saved.id, AT) == "deleted"
    assert _marks(conn) == []


def test_undo_keeps_the_mark_when_another_entry_is_left(
    conn: sqlite3.Connection,
) -> None:
    kept = AT - timedelta(hours=2)
    db.add_entry(conn, PID, FREE, kept, SKILL)
    saved = db.add_entry(conn, PID, TOO_SICK, AT, SKILL)
    assert db.undo_too_sick_entry(conn, PID, saved.id, AT) == "deleted"
    assert _marks(conn) == [
        (PID, "2026-11-09", kept.isoformat(timespec="microseconds"))
    ]


def test_undo_refused_leaves_the_mark(conn: sqlite3.Connection) -> None:
    saved = db.add_entry(conn, PID, TOO_SICK, AT, SKILL)
    refused = db.undo_too_sick_entry(conn, PID, saved.id, AT + timedelta(minutes=1))
    assert refused == "not_undoable"
    assert len(_marks(conn)) == 1


def test_undo_only_touches_its_own_day_and_patient(conn: sqlite3.Connection) -> None:
    db.add_entry(conn, PID, FREE, AT - timedelta(days=1), SKILL)
    db.add_entry(conn, OTHER, FREE, AT, SKILL)
    saved = db.add_entry(conn, PID, TOO_SICK, AT, SKILL)
    assert db.undo_too_sick_entry(conn, PID, saved.id, AT) == "deleted"
    assert [(m[0], m[1]) for m in _marks(conn)] == [
        (PID, "2026-11-08"),
        (OTHER, "2026-11-09"),
    ]


# ---------------------------------------------------------------------------
# 既存の entries から印を作る移行
# ---------------------------------------------------------------------------


def _old_db(path: Path) -> sqlite3.Connection:
    """record_marks の無い DB（前の版）を作り、entries を生の SQL で入れる。"""
    conn = db.connect(path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("DROP TABLE record_marks")
    conn.execute(
        "INSERT INTO patients (id, regimen, created_at) VALUES (?, ?, ?)",
        (PID, "FOLFOX", "2026-10-01T09:00:00.000000+09:00"),
    )
    rows = [
        ("2026-11-08T08:00:00.000000+09:00", "2026-11-08"),
        ("2026-11-08T21:00:00.000000+09:00", "2026-11-08"),
        ("2026-11-09T10:00:00.000000+09:00", "2026-11-09"),
    ]
    conn.executemany(
        "INSERT INTO entries (patient_id, recorded_at, record_date, kind, skill_version)"
        " VALUES (?, ?, ?, 'too_sick', ?)",
        [(PID, at, day, SKILL) for at, day in rows],
    )
    conn.commit()
    return conn


def test_init_db_makes_marks_from_old_entries(tmp_db_path: Path) -> None:
    conn = _old_db(tmp_db_path)
    try:
        db.init_db(conn)
        expected = [
            (PID, "2026-11-08", "2026-11-08T21:00:00.000000+09:00"),
            (PID, "2026-11-09", "2026-11-09T10:00:00.000000+09:00"),
        ]
        assert _marks(conn) == expected
        db.init_db(conn)  # 何度流しても同じ
        assert _marks(conn) == expected
    finally:
        conn.close()


def test_backfill_does_not_overwrite_existing_marks(conn: sqlite3.Connection) -> None:
    db.add_entry(conn, PID, FREE, AT, SKILL)
    newer = "2026-11-09T23:00:00.000000+09:00"
    conn.execute("UPDATE record_marks SET last_marked_at = ?", (newer,))
    conn.commit()
    db.init_db(conn)
    assert _marks(conn) == [(PID, "2026-11-09", newer)]


def test_backfill_ignores_patients_without_entries(conn: sqlite3.Connection) -> None:
    db.init_db(conn)
    assert _marks(conn) == []
