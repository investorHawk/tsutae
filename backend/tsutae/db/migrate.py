"""既存の DB の表を作り直す移行（architecture 9c「DB の移行」）。

schema.sql は `CREATE TABLE IF NOT EXISTS` だけなので、既にある表の CHECK は古いまま残る。
`migrate_db(conn)` は `init_db` の中で schema.sql の前に呼ばれ、`sqlite_master` の
CREATE 文を見て古い形の表だけを SQLite の「12-step generalized ALTER TABLE」で作り直す:

1. トランザクションの外で `PRAGMA foreign_keys = OFF`（トランザクション中は効かない）
2. `BEGIN IMMEDIATE`
3. 索引・トリガーの CREATE 文を控える
4. 新しい形の表を `_migrate_new_<表名>` で作り、全行を写す（列名を明示。id を保つ）
5. 古い表を DROP し、新しい表を元の名前に RENAME
6. 控えた索引・トリガーを作り直す
7. `PRAGMA foreign_key_check` が空でなければ ROLLBACK（`MigrationError`）
8. COMMIT。finally で `PRAGMA foreign_keys = ON`

対象は `MIGRATIONS`（表名・古いかの判定・新しい CREATE 文）。今は pipeline_logs（T93）と
patients（regimen の CHECK を外す。T95）と entries（client_entry_id を足す。
plan-device-records §5.5）と record_marks（first_marked_at を足す。§4.4）と visits（regen_pending・
regen_count を足す。§6）。新しい CREATE 文は schema.sql
から引く（同じ文を2か所に書かない）。何度呼んでもよい（新しい形なら何もしない）。
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tsutae.db.connection import SCHEMA_PATH, write_lock

__all__ = [
    "MIGRATIONS",
    "MigrationError",
    "TableMigration",
    "migrate_db",
    "schema_create_statement",
]

_NEW_PREFIX = "_migrate_new_"
_TABLE_NAME = re.compile(r"[a-z_][a-z0-9_]*")


class MigrationError(RuntimeError):
    """移行できない（トランザクションの途中・外部キーの食い違い）。表は元のまま。"""


def schema_create_statement(table: str) -> str:
    """schema.sql にある `CREATE TABLE IF NOT EXISTS <table> (...)` の文（末尾の ; は除く）。"""
    if not _TABLE_NAME.fullmatch(table):
        raise ValueError(f"bad table name: {table!r}")
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf"^CREATE TABLE IF NOT EXISTS {table} \(.*?^\);",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ValueError(f"schema.sql に {table} の CREATE 文が無い")
    return match.group(0)[:-1]


def _copy_all(new: str, old: str, columns: Sequence[str]) -> str:
    names = ", ".join(columns)
    return f"INSERT INTO {new} ({names}) SELECT {names} FROM {old}"


@dataclass(frozen=True)
class TableMigration:
    """1つの表の作り直し。

    - `is_outdated(create_sql)`: 今の CREATE 文が古い形なら True
    - `create_sql()`: 新しい形の `CREATE TABLE IF NOT EXISTS <table> (...)`
    - `copy_sql(new_table, columns)`: 行を写す INSERT 文（既定は新旧に共通の列を全て）
    """

    table: str
    is_outdated: Callable[[str], bool]
    create_sql: Callable[[], str]
    copy_sql: Callable[[str, Sequence[str]], str] | None = None


def _pipeline_logs_outdated(sql: str) -> bool:
    return "'regimen_chat'" not in sql


def _patients_outdated(sql: str) -> bool:
    return "'FOLFOX'" in sql


def _entries_outdated(sql: str) -> bool:
    return "client_entry_id" not in sql


def _record_marks_outdated(sql: str) -> bool:
    return "first_marked_at" not in sql


def _visits_outdated(sql: str) -> bool:
    return "regen_pending" not in sql


def _copy_first_mark(new: str, columns: Sequence[str]) -> str:
    """前の形は一番後の時刻しか持たないので、それを一番先の時刻にも写す。

    取り消せるのは 10 分以内の印だけなので、移行の前の印の先後が分からなくても困らない。
    """
    names = ", ".join(columns)
    return (
        f"INSERT INTO {new} ({names}, first_marked_at)"
        f" SELECT {names}, last_marked_at FROM record_marks"
    )


def _copy_with_rowid(new: str, columns: Sequence[str]) -> str:
    """rowid も写す（主キーが TEXT の表。list_patients は同じ時刻を rowid 順に並べる）。"""
    names = ", ".join(columns)
    return f"INSERT INTO {new} (rowid, {names}) SELECT rowid, {names} FROM patients"


MIGRATIONS: tuple[TableMigration, ...] = (
    # T93: run_kind に regimen_chat（T94 の会話のログ）を足す
    TableMigration(
        table="pipeline_logs",
        is_outdated=_pipeline_logs_outdated,
        create_sql=lambda: schema_create_statement("pipeline_logs"),
    ),
    # T95: regimen の CHECK（FOLFOX・CAPOX だけ）を外す。courses・entries・visits が参照する
    TableMigration(
        table="patients",
        is_outdated=_patients_outdated,
        create_sql=lambda: schema_create_statement("patients"),
        copy_sql=_copy_with_rowid,
    ),
    # スマホ保存: 受付で受け取った記録の ID。closed_answers・free_texts・doctor_masks が参照する
    TableMigration(
        table="entries",
        is_outdated=_entries_outdated,
        create_sql=lambda: schema_create_statement("entries"),
    ),
    # 取り消し: その日の一番先の時刻。先に付いた別の端末の印を消さないため
    TableMigration(
        table="record_marks",
        is_outdated=_record_marks_outdated,
        create_sql=lambda: schema_create_statement("record_marks"),
        copy_sql=_copy_first_mark,
    ),
    # 2台目のスマホ: 記録が増えた受診の変換し直し。timelines・reports・doctor_masks が参照する
    TableMigration(
        table="visits",
        is_outdated=_visits_outdated,
        create_sql=lambda: schema_create_statement("visits"),
    ),
)


def _table_sql(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return None if row is None else str(row[0])


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")]


def _dependents(conn: sqlite3.Connection, table: str) -> list[str]:
    """表に付いた索引・トリガーの CREATE 文（自動の索引は sql が NULL なので除く）。"""
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN"
        " ('index', 'trigger') AND sql IS NOT NULL ORDER BY type, name",
        (table,),
    )
    return [str(r[0]) for r in rows]


def _new_table_sql(migration: TableMigration, new: str) -> str:
    sql = migration.create_sql()
    head = re.compile(
        rf"^CREATE TABLE(?: IF NOT EXISTS)? {re.escape(migration.table)} \("
    )
    if not head.match(sql):
        raise MigrationError(f"{migration.table} の新しい CREATE 文の形が違う")
    return head.sub(f"CREATE TABLE {new} (", sql, count=1)


def _rebuild(conn: sqlite3.Connection, migration: TableMigration) -> None:
    table = migration.table
    new = _NEW_PREFIX + table
    dependents = _dependents(conn, table)
    conn.execute(f"DROP TABLE IF EXISTS {new}")
    conn.execute(_new_table_sql(migration, new))
    new_columns = set(_columns(conn, new))
    shared = [c for c in _columns(conn, table) if c in new_columns]
    if migration.copy_sql is not None:
        conn.execute(migration.copy_sql(new, shared))
    else:
        conn.execute(_copy_all(new, table, shared))
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {new} RENAME TO {table}")
    for sql in dependents:
        conn.execute(sql)


def _run_locked(conn: sqlite3.Connection, todo: Sequence[TableMigration]) -> list[str]:
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for migration in todo:
                _rebuild(conn, migration)
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise MigrationError("外部キーの食い違いがあるので移行をやめた")
        except BaseException:
            conn.rollback()
            raise
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return [m.table for m in todo]


def migrate_db(
    conn: sqlite3.Connection, migrations: Sequence[TableMigration] = MIGRATIONS
) -> list[str]:
    """古い形の表を作り直し、作り直した表の名前を返す（無ければ空。何度呼んでもよい）。"""
    if conn.in_transaction:
        raise MigrationError("トランザクションの途中では移行しない")
    with write_lock():
        todo = [
            m
            for m in migrations
            if (sql := _table_sql(conn, m.table)) is not None and m.is_outdated(sql)
        ]
        if not todo:
            return []
        return _run_locked(conn, todo)
