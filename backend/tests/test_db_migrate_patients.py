"""T95: patients の regimen の CHECK（FOLFOX・CAPOX だけ）を外す移行。

- CHECK のある既存 DB を起動（init_db）で移行し、全ての表の全行が残る（patients の rowid と
  並びも。courses・entries・visits などが patients を参照したまま）
- 移行の後は D4 で採用したレジメン（RAM-WPTX）の患者を入れられる
- 何度呼んでもよい。新しい DB の patients には CHECK が無い
- repo は識別名の書式だけを見る（一覧との照合は API の入口）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tsutae import db
from tsutae.db import connect, init_db
from tsutae.db.connection import SCHEMA_PATH
from tsutae.db.migrate import MIGRATIONS, migrate_db

OLD_PATIENTS = """CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    regimen TEXT NOT NULL CHECK (regimen IN ('FOLFOX', 'CAPOX')),
    created_at TEXT NOT NULL
);"""
NEW_PATIENTS_HEAD = "CREATE TABLE IF NOT EXISTS patients ("
TS = "2026-11-09T10:00:00.000000+09:00"
EARLY = "2026-11-01T10:00:00.000000+09:00"
TABLES = (
    "patients",
    "courses",
    "entries",
    "closed_answers",
    "free_texts",
    "visits",
    "timelines",
    "reports",
)


def _old_schema() -> str:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    start = text.index(NEW_PATIENTS_HEAD)
    end = text.index(");", start) + 2
    return text[:start] + OLD_PATIENTS + text[end:]


def _old_db(path: Path) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(_old_schema())
    conn.executemany(
        "INSERT INTO patients (id, regimen, created_at) VALUES (?, ?, ?)",
        [
            ("P-BBBBBBBB", "CAPOX", TS),
            ("P-AAAAAAAA", "FOLFOX", EARLY),
            ("P-CCCCCCCC", "FOLFOX", TS),
        ],
    )
    conn.execute(
        "INSERT INTO courses (id, patient_id, course_no, infusion_date)"
        " VALUES (1, 'P-AAAAAAAA', 1, '2026-11-02')"
    )
    conn.execute(
        "INSERT INTO entries (id, patient_id, recorded_at, record_date, kind,"
        " by_proxy, skill_version) VALUES (1, 'P-AAAAAAAA', ?, '2026-11-09',"
        " 'mixed', 0, 'regimen-folfox@1')",
        (TS,),
    )
    conn.execute(
        "INSERT INTO closed_answers (entry_id, question_key, value)"
        " VALUES (1, 'diarrhea', 'present')"
    )
    conn.execute("INSERT INTO free_texts (entry_id, text) VALUES (1, 'だるい')")
    conn.execute(
        "INSERT INTO visits (id, patient_id, reception_no, visit_date, created_at,"
        " status, expires_at) VALUES (1, 'P-BBBBBBBB', 'A-001', '2026-11-09', ?,"
        " 'ready', ?)",
        (TS, TS),
    )
    conn.execute("INSERT INTO timelines (visit_id, json) VALUES (1, '{}')")
    conn.execute(
        "INSERT INTO reports (visit_id, html, data_json) VALUES (1, '<p>', '{}')"
    )
    conn.commit()
    return conn


def _dump(conn: sqlite3.Connection, table: str) -> list[tuple]:
    return [
        tuple(r) for r in conn.execute(f"SELECT rowid, * FROM {table} ORDER BY rowid")
    ]


def _patients_sql(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'patients'"
    ).fetchone()
    return str(row[0])


def test_patients_is_in_migrations() -> None:
    assert "patients" in [m.table for m in MIGRATIONS]


def test_old_patients_check_is_removed_and_all_rows_remain(tmp_db_path: Path) -> None:
    conn = _old_db(tmp_db_path)
    before = {t: _dump(conn, t) for t in TABLES}
    listed = [p["id"] for p in db.list_patients(conn)]
    init_db(conn)
    assert {t: _dump(conn, t) for t in TABLES} == before
    assert "'FOLFOX'" not in _patients_sql(conn)
    assert [p["id"] for p in db.list_patients(conn)] == listed
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    pid = db.create_patient(conn, "RAM-WPTX")
    assert db.get_patient(conn, pid)["regimen"] == "RAM-WPTX"
    with pytest.raises(sqlite3.IntegrityError):  # 参照の検査は効いたまま
        conn.execute(
            "INSERT INTO courses (patient_id, course_no, infusion_date)"
            " VALUES ('P-ZZZZZZZZ', 1, '2026-11-02')"
        )


def test_patients_migration_is_idempotent(tmp_db_path: Path) -> None:
    conn = _old_db(tmp_db_path)
    init_db(conn)
    once = {t: _dump(conn, t) for t in TABLES}
    assert migrate_db(conn) == []
    init_db(conn)
    assert {t: _dump(conn, t) for t in TABLES} == once


def test_new_db_patients_has_no_regimen_check(tmp_db_path: Path) -> None:
    conn = connect(tmp_db_path)
    init_db(conn)
    assert migrate_db(conn) == []
    assert "CHECK" not in _patients_sql(conn)
    pid = db.create_patient(conn, "FOLFIRI-BV")
    assert db.get_patient(conn, pid)["regimen"] == "FOLFIRI-BV"


@pytest.mark.parametrize("bad", ["", "folfox", "RAM WPTX", "-RAM", "A" * 31, None, 1])
def test_repo_rejects_bad_regimen_codes(tmp_db_path: Path, bad: object) -> None:
    conn = connect(tmp_db_path)
    init_db(conn)
    with pytest.raises(ValueError):
        db.create_patient(conn, bad)  # type: ignore[arg-type]
    assert db.list_patients(conn) == []
