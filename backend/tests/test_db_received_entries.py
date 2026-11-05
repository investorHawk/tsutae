"""受付で受け取った記録（plan-device-records §5.5）の保存と消去。

- `entries.client_entry_id` の移行: 前の DB の行は NULL で全て残り、一意索引ができる
- 受診の作成と記録の保存は同じトランザクション。同じ ID は二重にならない
- 受け取った記録は日付の印を書かない（印はサーバーが記録のときに付ける）
- 印刷済み・期限切れで、その患者に開いた受診が他に無ければ受け取った記録を消す。
  `client_entry_id` の無い行と日付の印は消さない
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from tsutae import db
from tsutae.config import JST, now
from tsutae.db.connection import SCHEMA_PATH
from tsutae.db.migrate import MIGRATIONS
from tsutae.db.repo_received import ReceivedEntry
from tsutae.schemas import ClosedAnswer, EntryCreate

PID = "P-RECV0001"
OTHER = "P-RECV0002"
SKILL = "regimen-folfox@1"
AT = datetime(2026, 11, 9, 20, 15, 0, tzinfo=JST)
DAY = date(2026, 11, 9)
UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
MIXED = EntryCreate(
    answers=[ClosedAnswer(question_key="diarrhea", value="present")],
    free_text="（合成）おなかがゆるい",
)


def _received(client_id: str = UUID_A, at: datetime = AT) -> ReceivedEntry:
    return ReceivedEntry(
        client_entry_id=client_id, entry=MIXED, recorded_at=at, skill_version=SKILL
    )


@pytest.fixture
def conn(tmp_db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_db_path)
    db.init_db(connection)
    db.create_patient(connection, "FOLFOX", patient_id=PID)
    db.create_patient(connection, "FOLFOX", patient_id=OTHER)
    yield connection
    connection.close()


def _open_visit(
    conn: sqlite3.Connection,
    pid: str = PID,
    reception_no: str = "A-023",
    entries: tuple[ReceivedEntry, ...] = (),
    expires_at: datetime | None = None,
) -> tuple[int, bool]:
    expires = expires_at or now() + timedelta(hours=24)
    return db.create_visit_once(conn, pid, reception_no, DAY, expires, 1, entries)


def _client_ids(conn: sqlite3.Connection, pid: str = PID) -> list[str | None]:
    rows = conn.execute(
        "SELECT client_entry_id FROM entries WHERE patient_id = ? ORDER BY id", (pid,)
    ).fetchall()
    return [r["client_entry_id"] for r in rows]


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


# ---------------------------------------------------------------------------
# 移行
# ---------------------------------------------------------------------------

OLD_ENTRIES_LINE = "    skill_version TEXT NOT NULL,\n    client_entry_id TEXT\n"
OLD_ENTRIES_NEW = "    skill_version TEXT NOT NULL\n"
UNIQUE_INDEX_START = "-- 受付で受け取った記録の ID"
UNIQUE_INDEX_END = "WHERE client_entry_id IS NOT NULL;\n"


def _old_schema() -> str:
    """client_entry_id と一意索引の無い、前の形の schema。"""
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert OLD_ENTRIES_LINE in text
    start = text.index(UNIQUE_INDEX_START)
    end = text.index(UNIQUE_INDEX_END, start) + len(UNIQUE_INDEX_END)
    without_index = text[:start] + text[end:]
    return without_index.replace(OLD_ENTRIES_LINE, OLD_ENTRIES_NEW)


def _old_db(path: Path) -> sqlite3.Connection:
    connection = db.connect(path)
    connection.executescript(_old_schema())
    ts = AT.isoformat(timespec="microseconds")
    connection.execute(
        "INSERT INTO patients (id, regimen, created_at) VALUES (?, 'FOLFOX', ?)",
        (PID, ts),
    )
    connection.execute(
        "INSERT INTO entries (id, patient_id, recorded_at, record_date, kind,"
        " by_proxy, skill_version) VALUES (7, ?, ?, '2026-11-09', 'mixed', 0, ?)",
        (PID, ts, SKILL),
    )
    connection.execute(
        "INSERT INTO closed_answers (entry_id, question_key, value)"
        " VALUES (7, 'diarrhea', 'present')"
    )
    connection.execute("INSERT INTO free_texts (entry_id, text) VALUES (7, 'だるい')")
    connection.execute(
        "INSERT INTO visits (id, patient_id, reception_no, visit_date, created_at,"
        " status, expires_at) VALUES (1, ?, 'A-001', '2026-11-09', ?, 'ready', ?)",
        (PID, ts, ts),
    )
    connection.execute(
        "INSERT INTO doctor_masks (visit_id, entry_id, spans_json, created_at)"
        " VALUES (1, 7, '[]', ?)",
        (ts,),
    )
    connection.commit()
    return connection


def test_entries_is_in_migrations() -> None:
    assert "entries" in [m.table for m in MIGRATIONS]


def test_old_entries_get_the_column_and_all_rows_remain(tmp_db_path: Path) -> None:
    conn = _old_db(tmp_db_path)
    db.init_db(conn)
    assert _client_ids(conn) == [None]
    assert conn.execute("SELECT id FROM entries").fetchone()["id"] == 7
    assert _count(conn, "closed_answers") == 1
    assert _count(conn, "free_texts") == 1
    assert _count(conn, "doctor_masks") == 1
    assert db.get_entry(conn, 7).free_text == "だるい"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    # 消すと子の行も消える（外部キーが新しい表を指している）
    with conn:
        conn.execute("DELETE FROM entries WHERE id = 7")
    assert _count(conn, "closed_answers") == 0
    conn.close()


def test_old_db_gets_the_unique_index_and_is_idempotent(tmp_db_path: Path) -> None:
    conn = _old_db(tmp_db_path)
    db.init_db(conn)
    db.init_db(conn)
    indexes = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
            " AND tbl_name = 'entries' AND sql IS NOT NULL"
        )
    }
    assert indexes == {"idx_entries_patient_date", "idx_entries_client_id"}
    conn.close()


def test_null_client_ids_are_not_unique_targets(conn: sqlite3.Connection) -> None:
    db.add_entry(conn, PID, MIXED, AT, SKILL)
    db.add_entry(conn, PID, MIXED, AT, SKILL)
    assert _client_ids(conn) == [None, None]


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------


def test_visit_and_entries_are_saved_together(conn: sqlite3.Connection) -> None:
    visit_id, created = _open_visit(conn, entries=(_received(),))
    assert created
    assert db.get_visit(conn, visit_id)["status"] == "generating"
    (entry,) = db.list_entries(conn, PID)
    assert entry.recorded_at == AT
    assert entry.record_date == DAY
    assert entry.kind == "mixed"
    assert entry.skill_version == SKILL
    assert entry.free_text == MIXED.free_text
    assert entry.answers == MIXED.answers


def test_same_id_is_not_doubled_on_resend(conn: sqlite3.Connection) -> None:
    first, _ = _open_visit(conn, entries=(_received(),))
    again, created = _open_visit(conn, entries=(_received(), _received(UUID_B)))
    assert again == first
    assert not created
    assert _client_ids(conn) == [UUID_A, UUID_B]
    assert _count(conn, "closed_answers") == 2
    assert _count(conn, "free_texts") == 2


def test_same_id_is_kept_per_patient(conn: sqlite3.Connection) -> None:
    _open_visit(conn, entries=(_received(),))
    _open_visit(conn, pid=OTHER, entries=(_received(),))
    assert _client_ids(conn) == [UUID_A]
    assert _client_ids(conn, OTHER) == [UUID_A]


def test_failure_leaves_neither_visit_nor_entries(conn: sqlite3.Connection) -> None:
    """途中で失敗すれば受診も記録も残らない（同じ ID 2件は一意索引で落ちる）。"""
    with pytest.raises(sqlite3.IntegrityError):
        _open_visit(conn, entries=(_received(), _received()))
    assert db.list_visits(conn) == []
    assert _client_ids(conn) == []
    assert _count(conn, "closed_answers") == 0


def test_received_entries_do_not_write_marks(conn: sqlite3.Connection) -> None:
    _open_visit(conn, entries=(_received(),))
    assert _count(conn, "record_marks") == 0


def test_backfill_ignores_received_entries(conn: sqlite3.Connection) -> None:
    """起動のたびの移行で、受け取った記録から印を作らない（印はサーバーが付けたものだけ）。"""
    _open_visit(conn, entries=(_received(),))
    db.backfill_record_marks(conn)
    assert _count(conn, "record_marks") == 0


# ---------------------------------------------------------------------------
# 消去
# ---------------------------------------------------------------------------


def test_printed_erases_received_entries_and_keeps_the_rest(
    conn: sqlite3.Connection,
) -> None:
    db.add_entry(conn, PID, MIXED, AT - timedelta(days=30), SKILL)
    db.add_entry(conn, OTHER, MIXED, AT, SKILL)
    _open_visit(conn, pid=OTHER, reception_no="B-1", entries=(_received(UUID_B),))
    visit_id, _ = _open_visit(conn, entries=(_received(),))
    assert db.mark_printed(conn, visit_id)
    assert _client_ids(conn) == [None]
    assert _client_ids(conn, OTHER) == [None, UUID_B]
    # 既存の行の2件＋他の患者の受け取った1件の分だけ残る
    assert _count(conn, "closed_answers") == 3
    assert _count(conn, "free_texts") == 3
    assert _count(conn, "record_marks") == 2


def test_printed_keeps_entries_while_another_visit_is_open(
    conn: sqlite3.Connection,
) -> None:
    first, _ = _open_visit(conn, entries=(_received(),))
    second, _ = _open_visit(conn, reception_no="A-024")
    assert db.mark_printed(conn, first)
    assert _client_ids(conn) == [UUID_A]
    assert db.mark_printed(conn, second)
    assert _client_ids(conn) == []


def test_expired_other_visit_does_not_hold_entries(conn: sqlite3.Connection) -> None:
    expired, _ = _open_visit(
        conn, reception_no="A-024", expires_at=now() - timedelta(minutes=1)
    )
    visit_id, _ = _open_visit(conn, entries=(_received(),))
    assert db.get_visit(conn, expired)["reception_no"] == "A-024"
    assert db.mark_printed(conn, visit_id)
    assert _client_ids(conn) == []


def test_refused_print_keeps_entries(conn: sqlite3.Connection) -> None:
    visit_id, _ = _open_visit(conn, entries=(_received(),))
    assert not db.mark_printed(conn, visit_id, refuse_generating=True)
    assert _client_ids(conn) == [UUID_A]


def test_purge_erases_received_entries_and_keeps_the_rest(
    conn: sqlite3.Connection,
) -> None:
    db.add_entry(conn, PID, MIXED, AT - timedelta(days=30), SKILL)
    _open_visit(conn, entries=(_received(),), expires_at=AT)
    assert db.purge_expired(conn, AT) == 1
    assert _client_ids(conn) == [None]
    assert _count(conn, "free_texts") == 1
    assert _count(conn, "record_marks") == 1
    assert db.purge_expired(conn, AT) == 0


def test_purge_keeps_entries_while_another_visit_is_open(
    conn: sqlite3.Connection,
) -> None:
    _open_visit(conn, entries=(_received(),), expires_at=AT)
    _open_visit(conn, reception_no="A-024", expires_at=AT + timedelta(hours=1))
    assert db.purge_expired(conn, AT) == 1
    assert _client_ids(conn) == [UUID_A]
    assert db.purge_expired(conn, AT + timedelta(hours=1)) == 1
    assert _client_ids(conn) == []


def test_purge_erases_after_a_printed_visit_left_entries(
    conn: sqlite3.Connection,
) -> None:
    """1件目を印刷した時に2件目が開いていて残った記録も、2件目の期限で消える。"""
    first, _ = _open_visit(conn, entries=(_received(),))
    _open_visit(conn, reception_no="A-024", expires_at=now() + timedelta(hours=1))
    assert db.mark_printed(conn, first)
    assert _client_ids(conn) == [UUID_A]
    assert db.purge_expired(conn, now() + timedelta(hours=2)) == 1
    assert _client_ids(conn) == []


def test_erased_text_does_not_stay_in_the_files(tmp_db_path: Path) -> None:
    """消した原文が DB の本体にも WAL にも残らない（secure_delete と checkpoint）。"""
    conn = db.connect(tmp_db_path)
    db.init_db(conn)
    db.create_patient(conn, "FOLFOX", patient_id=PID)
    secret = "（合成）消えるはずの原文".encode()
    entry = EntryCreate(free_text=secret.decode())
    received = ReceivedEntry(UUID_A, entry, AT, SKILL)
    visit_id, _ = _open_visit(conn, entries=(received,))
    assert db.mark_printed(conn, visit_id)
    conn.close()
    files = [p for p in tmp_db_path.parent.iterdir() if p.is_file()]
    assert files
    assert [p.name for p in files if secret in p.read_bytes()] == []
