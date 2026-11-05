"""migrate_db（12-step generalized ALTER TABLE。architecture 9c「DB の移行」）。

- 古い CHECK（pipeline_logs の run_kind に regimen_chat が無い）の DB を移行し、全行が残る
- 何度呼んでもよい（行数と中身が変わらない）。新しい DB では何もしない
- 外部キーで参照される表も作り直せる（T95 の patients を同じ仕組みに足すため）。
  foreign_key_check に掛かれば ROLLBACK して元の表のまま
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tsutae.db import add_pipeline_log, connect, init_db
from tsutae.db.migrate import (
    MIGRATIONS,
    MigrationError,
    TableMigration,
    migrate_db,
    schema_create_statement,
)

# 今の schema.sql の pipeline_logs を、run_kind の CHECK だけ T93 より前の形にしたもの
OLD_PIPELINE_LOGS = """
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id INTEGER PRIMARY KEY,
    run_kind TEXT NOT NULL CHECK (run_kind IN ('visit', 'skill_change')),
    run_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    hook_name TEXT,
    agent_type TEXT,
    tool_name TEXT,
    decision TEXT,
    duration_ms INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL
);

CREATE INDEX IF NOT EXISTS idx_pipeline_logs_run
    ON pipeline_logs (run_kind, run_id, id);
"""
TS = "2026-11-09T10:00:00.000000+09:00"


def _old_db(path: Path) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(OLD_PIPELINE_LOGS)
    rows = [
        (1, "visit", 7, TS, "run_start", None, None, None, None, None, 10, 20, 0.5),
        (
            2,
            "visit",
            7,
            TS,
            "hook_h1",
            "H1",
            "main",
            "Read",
            "deny",
            3,
            None,
            None,
            None,
        ),
        (5, "skill_change", 3, TS, "skill_change_approved", *([None] * 8)),
    ]
    conn.executemany(
        "INSERT INTO pipeline_logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    return conn


def _dump(conn: sqlite3.Connection, table: str) -> list[tuple]:
    return [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def _create_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row["sql"]


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?"
        " AND sql IS NOT NULL",
        (table,),
    )
    return {r["name"] for r in rows}


def test_old_pipeline_logs_is_rebuilt_and_keeps_all_rows(tmp_db_path: Path) -> None:
    conn = _old_db(tmp_db_path)
    before = _dump(conn, "pipeline_logs")
    init_db(conn)
    assert _dump(conn, "pipeline_logs") == before
    assert "regimen_chat" in _create_sql(conn, "pipeline_logs")
    assert "idx_pipeline_logs_run" in _index_names(conn, "pipeline_logs")
    add_pipeline_log(conn, "regimen_chat", 1, "turn_start")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM pipeline_logs WHERE run_kind = 'regimen_chat'"
        ).fetchone()[0]
        == 1
    )
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrate_is_idempotent(tmp_db_path: Path) -> None:
    conn = _old_db(tmp_db_path)
    init_db(conn)
    once = _dump(conn, "pipeline_logs")
    sql = _create_sql(conn, "pipeline_logs")
    assert migrate_db(conn) == []
    init_db(conn)
    assert _dump(conn, "pipeline_logs") == once
    assert _create_sql(conn, "pipeline_logs") == sql


def test_migrate_reports_rebuilt_tables(tmp_db_path: Path) -> None:
    conn = _old_db(tmp_db_path)
    assert migrate_db(conn) == ["pipeline_logs"]
    assert migrate_db(conn) == []


def test_fresh_db_needs_no_migration(tmp_db_path: Path) -> None:
    conn = connect(tmp_db_path)
    assert migrate_db(conn) == []  # 表が無ければ schema.sql が作る
    init_db(conn)
    assert migrate_db(conn) == []
    assert "regimen_chat" in _create_sql(conn, "pipeline_logs")


def test_migrations_are_listed_per_table() -> None:
    tables = [m.table for m in MIGRATIONS]
    assert "pipeline_logs" in tables
    assert len(tables) == len(set(tables))
    for m in MIGRATIONS:
        assert schema_create_statement(m.table).startswith(
            f"CREATE TABLE IF NOT EXISTS {m.table} ("
        )


OLD_RECORD_MARKS = """
CREATE TABLE IF NOT EXISTS record_marks (
    patient_id TEXT NOT NULL REFERENCES patients (id),
    record_date TEXT NOT NULL,
    last_marked_at TEXT NOT NULL,
    PRIMARY KEY (patient_id, record_date)
);

CREATE INDEX IF NOT EXISTS idx_record_marks_date ON record_marks (record_date);
"""


def _old_record_marks_db(path: Path) -> sqlite3.Connection:
    conn = connect(path)
    init_db(conn)
    conn.execute("DROP TABLE record_marks")
    conn.executescript(OLD_RECORD_MARKS)
    conn.execute(
        "INSERT INTO patients (id, regimen, created_at) VALUES (?, ?, ?)",
        ("P-MARK0001", "FOLFOX", TS),
    )
    conn.execute(
        "INSERT INTO record_marks VALUES (?, ?, ?)",
        ("P-MARK0001", "2026-11-09", TS),
    )
    conn.commit()
    return conn


def test_old_record_marks_gets_the_first_time_and_keeps_rows(
    tmp_db_path: Path,
) -> None:
    """前の形の印は last_marked_at を一番先の時刻にも写す（取り消しの窓は10分なので足りる）。"""
    conn = _old_record_marks_db(tmp_db_path)
    try:
        assert migrate_db(conn) == ["record_marks"]
        row = conn.execute("SELECT * FROM record_marks").fetchone()
        assert dict(row) == {
            "patient_id": "P-MARK0001",
            "record_date": "2026-11-09",
            "first_marked_at": TS,
            "last_marked_at": TS,
        }
        assert "idx_record_marks_date" in _index_names(conn, "record_marks")
        assert migrate_db(conn) == []
    finally:
        conn.close()


def test_migrate_refuses_inside_transaction(tmp_db_path: Path) -> None:
    conn = _old_db(tmp_db_path)
    conn.execute(
        "INSERT INTO pipeline_logs (run_kind, run_id, ts, event)"
        " VALUES ('visit', 1, ?, 'x')",
        (TS,),
    )
    assert conn.in_transaction
    with pytest.raises(MigrationError):
        migrate_db(conn)
    conn.rollback()


# --- 外部キーで参照される表（T95 の patients と同じ形）------------------------------

PARENT_OLD = """
CREATE TABLE parents (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('A', 'B'))
);
CREATE TABLE children (
    id INTEGER PRIMARY KEY,
    parent_id TEXT NOT NULL REFERENCES parents (id)
);
CREATE INDEX idx_parents_kind ON parents (kind);
"""
PARENT_NEW = """CREATE TABLE IF NOT EXISTS parents (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL
)"""


def _parent_migration(new_sql: str = PARENT_NEW) -> TableMigration:
    return TableMigration(
        table="parents",
        is_outdated=lambda sql: "CHECK (kind IN" in sql,
        create_sql=lambda: new_sql,
    )


def _parent_db(path: Path) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(PARENT_OLD)
    conn.executemany("INSERT INTO parents VALUES (?, ?)", [("p1", "A"), ("p2", "B")])
    conn.executemany("INSERT INTO children VALUES (?, ?)", [(1, "p1"), (2, "p2")])
    conn.commit()
    return conn


def test_referenced_table_is_rebuilt(tmp_db_path: Path) -> None:
    conn = _parent_db(tmp_db_path)
    assert migrate_db(conn, (_parent_migration(),)) == ["parents"]
    assert _dump(conn, "parents") == [("p1", "A"), ("p2", "B")]
    assert _dump(conn, "children") == [(1, "p1"), (2, "p2")]
    conn.execute("INSERT INTO parents VALUES ('p3', 'C')")  # CHECK が外れた
    conn.commit()
    assert "idx_parents_kind" in _index_names(conn, "parents")
    with pytest.raises(sqlite3.IntegrityError):  # 子の外部キーは今も効く
        conn.execute("INSERT INTO children VALUES (3, 'nope')")
    conn.rollback()
    assert migrate_db(conn, (_parent_migration(),)) == []


def test_foreign_key_violation_rolls_back(tmp_db_path: Path) -> None:
    conn = _parent_db(tmp_db_path)
    before = _create_sql(conn, "parents")
    # 新しい表の主キーを変え、子の参照が切れる（foreign_key_check に掛かる）
    broken = PARENT_NEW.replace("id TEXT PRIMARY KEY", "id TEXT PRIMARY KEY, x TEXT")
    migration = TableMigration(
        table="parents",
        is_outdated=lambda sql: "CHECK (kind IN" in sql,
        create_sql=lambda: broken,
        copy_sql=lambda new, cols: f"INSERT INTO {new} (id, kind, x)"
        " SELECT id || '-moved', kind, NULL FROM parents",
    )
    with pytest.raises(MigrationError):
        migrate_db(conn, (migration,))
    assert _create_sql(conn, "parents") == before
    assert _dump(conn, "parents") == [("p1", "A"), ("p2", "B")]
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert not conn.in_transaction
