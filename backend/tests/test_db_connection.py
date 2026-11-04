"""接続の設定（WAL・busy_timeout・:memory:）と、共有接続での書き込みの直列化。"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import pytest

from tsutae.config import JST
from tsutae.db import (
    add_entry,
    add_pipeline_log,
    connect,
    create_patient,
    get_patient,
    init_db,
    list_pipeline_logs,
)
from tsutae.db.connection import BUSY_TIMEOUT_MS
from tsutae.schemas import ClosedAnswer, EntryCreate

AT = datetime(2026, 11, 4, 9, 0, tzinfo=JST)
WAIT_S = 5.0


def test_connect_file_uses_wal_and_busy_timeout(tmp_db_path: Path) -> None:
    conn = connect(tmp_db_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
    assert BUSY_TIMEOUT_MS >= 1000


def test_connect_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    conn = connect(Path(":memory:"))
    init_db(conn)
    assert conn.row_factory is sqlite3.Row
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "memory"
    pid = create_patient(conn, "FOLFOX")
    assert get_patient(conn, pid) is not None
    assert list(tmp_path.iterdir()) == []  # ファイルを作らない


class _PausingConnection(sqlite3.Connection):
    """executemany（add_entry の2文目）の手前で止まり、そのあと失敗する接続。

    止まるのは文と文の間（sqlite3_step の外）なので、別スレッドの書き込みが
    割り込めるかどうかを決定的に確かめられる。
    """

    entered: threading.Event
    gate: threading.Event

    def executemany(self, sql: str, params: object) -> sqlite3.Cursor:  # type: ignore[override]
        self.entered.set()
        self.gate.wait(WAIT_S)
        raise sqlite3.OperationalError("boom")


def _pausing_conn(path: Path) -> _PausingConnection:
    conn = sqlite3.connect(
        str(path), factory=_PausingConnection, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.entered = threading.Event()
    conn.gate = threading.Event()
    init_db(conn)
    return conn


def test_shared_connection_does_not_commit_half_written_entry(
    tmp_db_path: Path,
) -> None:
    conn = _pausing_conn(tmp_db_path)
    pid = create_patient(conn, "FOLFOX", patient_id="P-TEST0001")
    errors: list[str] = []

    def write_entry() -> None:
        entry = EntryCreate(answers=[ClosedAnswer(question_key="fever", value="none")])
        try:
            add_entry(conn, pid, entry, AT, "regimen-folfox@1")
        except sqlite3.OperationalError as exc:
            errors.append(str(exc))

    writer = threading.Thread(target=write_entry)
    writer.start()
    assert conn.entered.wait(WAIT_S)  # entries は書いたが closed_answers はまだ

    logger = threading.Thread(
        target=add_pipeline_log, args=(conn, "visit", 1, "run.start")
    )
    logger.start()
    try:
        logger.join(0.3)
        assert logger.is_alive()  # 書き込み中のトランザクションが終わるまで待つ
    finally:
        conn.gate.set()
    writer.join(WAIT_S)
    logger.join(WAIT_S)
    assert not writer.is_alive() and not logger.is_alive()

    assert errors == ["boom"]
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
    assert len(list_pipeline_logs(conn, "visit", 1)) == 1


def test_connect_enables_secure_delete(tmp_db_path: Path) -> None:
    """消した行（期限切れのレポート等）をファイルに残さない。"""
    conn = connect(tmp_db_path)
    assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
