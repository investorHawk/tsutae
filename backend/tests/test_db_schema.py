"""schema.sql の制約（CHECK・FK・CASCADE・UNIQUE）と init_db の冪等性。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from tsutae.config import JST
from tsutae.db import add_entry, connect, create_patient, init_db
from tsutae.schemas import ClosedAnswer, EntryCreate

AT = datetime(2026, 11, 9, 10, 0, tzinfo=JST)


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = connect(tmp_db_path)
    init_db(c)
    return c


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_connect_sets_row_factory_and_foreign_keys(conn: sqlite3.Connection) -> None:
    assert conn.row_factory is sqlite3.Row
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_connect_creates_parent_dir(tmp_path: Path) -> None:
    c = connect(tmp_path / "nested" / "dir" / "x.db")
    init_db(c)
    assert (tmp_path / "nested" / "dir" / "x.db").exists()


def test_init_db_is_idempotent(conn: sqlite3.Connection) -> None:
    pid = create_patient(conn, "FOLFOX")
    init_db(conn)
    init_db(conn)
    assert conn.execute("SELECT id FROM patients").fetchone()["id"] == pid
    expected = {
        "patients",
        "courses",
        "entries",
        "closed_answers",
        "free_texts",
        "visits",
        "timelines",
        "reports",
        "pipeline_logs",
        "skill_changes",
        "doctor_masks",
        "skill_versions",
    }
    assert expected <= _tables(conn)


def test_pipeline_logs_has_no_text_columns(conn: sqlite3.Connection) -> None:
    assert _columns(conn, "pipeline_logs") == [
        "id",
        "run_kind",
        "run_id",
        "ts",
        "event",
        "hook_name",
        "agent_type",
        "tool_name",
        "decision",
        "duration_ms",
        "tokens_in",
        "tokens_out",
        "cost_usd",
    ]
    forbidden = {"text", "message", "prompt", "content", "quote", "html", "json"}
    assert forbidden.isdisjoint(_columns(conn, "pipeline_logs"))


def _insert_entry(conn: sqlite3.Connection, pid: str) -> int:
    cur = conn.execute(
        "INSERT INTO entries (patient_id, recorded_at, record_date, kind, by_proxy,"
        " skill_version) VALUES (?, ?, ?, 'answers', 0, 'regimen-folfox@1')",
        (pid, AT.isoformat(), AT.date().isoformat()),
    )
    return int(cur.lastrowid)


def test_measured_without_temperature_is_rejected_by_db(
    conn: sqlite3.Connection,
) -> None:
    pid = create_patient(conn, "FOLFOX")
    eid = _insert_entry(conn, pid)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO closed_answers (entry_id, question_key, value, temperature)"
            " VALUES (?, 'fever', 'measured', NULL)",
            (eid,),
        )


def test_temperature_without_measured_is_rejected_by_db(
    conn: sqlite3.Connection,
) -> None:
    pid = create_patient(conn, "FOLFOX")
    eid = _insert_entry(conn, pid)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO closed_answers (entry_id, question_key, value, temperature)"
            " VALUES (?, 'fever', 'not_measured', 37.2)",
            (eid,),
        )


def test_measured_with_temperature_is_accepted(conn: sqlite3.Connection) -> None:
    pid = create_patient(conn, "FOLFOX")
    eid = _insert_entry(conn, pid)
    conn.execute(
        "INSERT INTO closed_answers (entry_id, question_key, value, temperature)"
        " VALUES (?, 'fever', 'measured', 37.9)",
        (eid,),
    )


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        (
            "INSERT INTO patients (id, regimen, created_at) VALUES ('P-X', 'XELOX', 'x')",
            (),
        ),
        (
            "INSERT INTO entries (patient_id, recorded_at, record_date, kind, by_proxy,"
            " skill_version) VALUES (?, 'x', 'x', 'chat', 0, 'v')",
            ("PID",),
        ),
        (
            "INSERT INTO visits (patient_id, reception_no, visit_date, created_at,"
            " status, expires_at) VALUES (?, 'A-1', 'x', 'x', 'done', 'x')",
            ("PID",),
        ),
        (
            "INSERT INTO pipeline_logs (run_kind, run_id, ts, event)"
            " VALUES ('report', 1, 'x', 'e')",
            (),
        ),
        (
            "INSERT INTO skill_changes (skill_name, requested_text, base_version,"
            " status, created_at) VALUES ('s', 'r', 1, 'merged', 'x')",
            (),
        ),
    ],
)
def test_check_constraints_reject_unknown_enum(
    conn: sqlite3.Connection, sql: str, params: tuple[str, ...]
) -> None:
    pid = create_patient(conn, "FOLFOX")
    real = tuple(pid if p == "PID" else p for p in params)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, real)


def test_foreign_key_rejects_unknown_patient(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert_entry(conn, "P-NOPE0000")


def test_courses_unique_per_patient_and_course_no(conn: sqlite3.Connection) -> None:
    pid = create_patient(conn, "FOLFOX")
    sql = (
        "INSERT INTO courses (patient_id, course_no, infusion_date)"
        " VALUES (?, 1, '2026-10-27')"
    )
    conn.execute(sql, (pid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (pid,))


def test_deleting_entry_cascades_answers_and_free_text(
    conn: sqlite3.Connection,
) -> None:
    pid = create_patient(conn, "FOLFOX")
    entry = add_entry(
        conn,
        pid,
        EntryCreate(
            answers=[
                ClosedAnswer(question_key="diarrhea", value="present"),
                ClosedAnswer(question_key="fever", value="measured", temperature=37.9),
            ],
            free_text="お腹がゆるい",
        ),
        AT,
        "regimen-folfox@1",
    )
    other = add_entry(
        conn,
        pid,
        EntryCreate(answers=[ClosedAnswer(question_key="numbness", value="none")]),
        AT,
        "regimen-folfox@1",
    )
    with conn:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry.id,))
    count = conn.execute(
        "SELECT COUNT(*) FROM closed_answers WHERE entry_id = ?", (entry.id,)
    ).fetchone()[0]
    texts = conn.execute(
        "SELECT COUNT(*) FROM free_texts WHERE entry_id = ?", (entry.id,)
    ).fetchone()[0]
    assert count == 0
    assert texts == 0
    # 患者と他の記録は残る
    assert conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 1
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM closed_answers WHERE entry_id = ?", (other.id,)
        ).fetchone()[0]
        == 1
    )
