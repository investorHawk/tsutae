"""日付の印（record_marks。plan-device-records §4.4）。

- 記録を書く経路（add_entry・seed_patient）が同じトランザクションで印も書く
- 記録のときに印だけを付けられ、取り消しで消せる（add_record_mark・undo_record_mark）
- D1 の最後の記録日は印から出す（last_record_dates）
- 既存の entries から印を作る移行は何度流してもよく、前の DB でも起動で印ができる
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from tsutae import db
from tsutae.config import JST, now
from tsutae.db.connection import SCHEMA_PATH, write_transaction
from tsutae.db.repo_received import ReceivedEntry, insert_received_rows
from tsutae.schemas import Entry, EntryCreate

PID = "P-MARK0001"
OTHER = "P-MARK0002"
SKILL = "regimen-folfox@1"
AT = datetime(2026, 11, 9, 20, 15, 0, tzinfo=JST)
TOO_SICK = EntryCreate(too_sick=True)
FREE = EntryCreate(free_text="夜に熱っぽかった")
CLIENT_ENTRY_ID = "6f1d3a52-8c47-4b1e-9a60-2f5b7c1d0e34"


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


def test_list_record_marks_is_for_one_patient_by_date(
    conn: sqlite3.Connection,
) -> None:
    db.add_record_mark(conn, PID, AT)
    db.add_record_mark(conn, PID, AT - timedelta(days=2))
    db.add_record_mark(conn, OTHER, AT - timedelta(days=1))
    marks = db.list_record_marks(conn, PID)
    assert [(m.patient_id, m.record_date) for m in marks] == [
        (PID, date(2026, 11, 7)),
        (PID, date(2026, 11, 9)),
    ]
    assert db.list_record_marks(conn, "P-NONE0000") == []


def test_add_record_mark_writes_only_a_mark(conn: sqlite3.Connection) -> None:
    db.add_record_mark(conn, PID, AT)
    assert _marks(conn) == [(PID, "2026-11-09", AT.isoformat(timespec="microseconds"))]
    assert db.list_entries(conn, PID) == []


def test_undo_clears_the_mark(conn: sqlite3.Connection) -> None:
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)
    assert _marks(conn) == []


def test_undo_without_clear_keeps_the_mark(conn: sqlite3.Connection) -> None:
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=False)
    assert len(_marks(conn)) == 1


def test_undo_keeps_a_later_mark(conn: sqlite3.Connection) -> None:
    db.add_record_mark(conn, PID, AT)
    db.add_record_mark(conn, PID, AT + timedelta(minutes=1))
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)
    assert len(_marks(conn)) == 1


def test_undo_keeps_an_earlier_mark(conn: sqlite3.Connection) -> None:
    """別の端末が先に書いた日は、端末から他の記録が見えなくても（clear_mark）印を消さない。"""
    earlier = AT - timedelta(hours=1)
    db.add_record_mark(conn, PID, earlier)
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)
    assert db.marked_patients(conn, AT.date()) == {PID}
    assert db.last_record_dates(conn) == {PID: AT.date()}
    assert [m.record_date for m in db.list_record_marks(conn, PID)] == [AT.date()]


def test_undo_keeps_an_earlier_mark_written_out_of_order(
    conn: sqlite3.Connection,
) -> None:
    """付いた順が時刻の順と違っても、その日の一番先の時刻を覚えている。"""
    db.add_record_mark(conn, PID, AT)
    db.add_record_mark(conn, PID, AT - timedelta(hours=1))
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)
    assert len(_marks(conn)) == 1


def test_undo_again_keeps_an_earlier_mark(conn: sqlite3.Connection) -> None:
    """押し直しても（応答が届かなかったとき）先の印は残る。"""
    db.add_record_mark(conn, PID, AT - timedelta(hours=1))
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)
    assert len(_marks(conn)) == 1


def test_undo_clears_a_mark_written_again_after_an_undo(
    conn: sqlite3.Connection,
) -> None:
    """取り消して印が消えた後に書き直せば、その時刻がその日の唯一の印になる。"""
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)
    again = AT + timedelta(minutes=1)
    db.add_record_mark(conn, PID, again)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)  # 前の分の押し直し
    assert len(_marks(conn)) == 1
    assert db.undo_record_mark(conn, PID, again, clear_mark=True)
    assert _marks(conn) == []


def test_undo_of_a_retried_mark_clears_the_earlier_try(
    conn: sqlite3.Connection,
) -> None:
    """応答が届かず押し直した日は、1回目の印も端末が付けたもの。取り消せば何も残らない。"""
    db.add_record_mark(conn, PID, AT - timedelta(seconds=30))
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True, retried=True)
    assert _marks(conn) == []
    assert db.marked_patients(conn, AT.date()) == set()
    assert db.last_record_dates(conn) == {}
    assert db.list_record_marks(conn, PID) == []


def test_undo_of_a_retried_mark_reaches_back_ten_minutes(
    conn: sqlite3.Connection,
) -> None:
    db.add_record_mark(conn, PID, AT - timedelta(minutes=10))
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True, retried=True)
    assert _marks(conn) == []


def test_undo_of_a_retried_mark_keeps_a_mark_older_than_the_retry(
    conn: sqlite3.Connection,
) -> None:
    """押し直しでも、10 分より前の印は別の端末の記録として残す。"""
    db.add_record_mark(conn, PID, AT - timedelta(minutes=10, milliseconds=1))
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True, retried=True)
    assert db.marked_patients(conn, AT.date()) == {PID}


def test_undo_of_a_retried_mark_keeps_a_later_mark(conn: sqlite3.Connection) -> None:
    """押し直しの後に別の端末が書いた印は残す。"""
    db.add_record_mark(conn, PID, AT - timedelta(seconds=30))
    db.add_record_mark(conn, PID, AT)
    db.add_record_mark(conn, PID, AT + timedelta(seconds=1))
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True, retried=True)
    assert db.marked_patients(conn, AT.date()) == {PID}


def test_undo_of_a_retried_mark_keeps_the_mark_without_clear(
    conn: sqlite3.Connection,
) -> None:
    """端末に同じ日の記録が他にあれば（clear_mark が false）、押し直しでも印を残す。"""
    db.add_record_mark(conn, PID, AT - timedelta(seconds=30))
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=False, retried=True)
    assert db.marked_patients(conn, AT.date()) == {PID}


def test_undo_of_a_retried_mark_is_refused_once_received(
    conn: sqlite3.Connection,
) -> None:
    db.add_record_mark(conn, PID, AT - timedelta(seconds=30))
    db.add_record_mark(conn, PID, AT)
    _receive(conn, PID, AT)
    assert not db.undo_record_mark(conn, PID, AT, clear_mark=True, retried=True)
    assert db.marked_patients(conn, AT.date()) == {PID}


def test_undo_refused_after_a_visit_leaves_the_mark(conn: sqlite3.Connection) -> None:
    db.add_record_mark(conn, PID, AT)
    expires = now() + timedelta(hours=24)
    db.create_visit(conn, PID, "A-1", AT.date(), expires, None)
    earlier = min(AT, now() - timedelta(seconds=1))
    assert not db.undo_record_mark(conn, PID, earlier, clear_mark=True)
    assert len(_marks(conn)) == 1


def _receive(conn: sqlite3.Connection, pid: str, recorded_at: datetime) -> None:
    received = ReceivedEntry(CLIENT_ENTRY_ID, TOO_SICK, recorded_at, SKILL)
    with write_transaction(conn):
        insert_received_rows(conn, pid, [received])


def test_undo_refused_once_the_record_was_received(conn: sqlite3.Connection) -> None:
    """同じ受付番号の送り直しは visits の行を作らないので、受け取った行そのものを見る。"""
    db.add_record_mark(conn, PID, AT)
    _receive(conn, PID, AT)
    assert not db.undo_record_mark(conn, PID, AT, clear_mark=True)
    assert len(_marks(conn)) == 1
    assert len(db.list_entries(conn, PID)) == 1


def test_undo_ignores_other_received_rows(conn: sqlite3.Connection) -> None:
    db.add_record_mark(conn, PID, AT)
    _receive(conn, PID, AT - timedelta(minutes=1))
    _receive(conn, OTHER, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)
    assert _marks(conn) == []


def test_undo_ignores_a_row_without_client_entry_id(conn: sqlite3.Connection) -> None:
    """受付で受け取っていない行（seed など）は、これまでどおり取り消しを止めない。"""
    db.add_record_mark(conn, PID, AT)
    db.add_entry(conn, PID, TOO_SICK, AT, SKILL)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=False)


def test_undo_only_touches_its_own_day_and_patient(conn: sqlite3.Connection) -> None:
    db.add_record_mark(conn, PID, AT - timedelta(days=1))
    db.add_record_mark(conn, OTHER, AT)
    db.add_record_mark(conn, PID, AT)
    assert db.undo_record_mark(conn, PID, AT, clear_mark=True)
    assert [(m[0], m[1]) for m in _marks(conn)] == [
        (PID, "2026-11-08"),
        (OTHER, "2026-11-09"),
    ]


def test_last_record_dates_come_from_marks(conn: sqlite3.Connection) -> None:
    db.add_record_mark(conn, PID, AT - timedelta(days=2))
    db.add_record_mark(conn, PID, AT)
    assert db.last_record_dates(conn) == {PID: AT.date()}
    assert db.list_entries(conn, PID) == []


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


def test_backfilled_mark_keeps_the_earlier_entry_of_the_day(tmp_db_path: Path) -> None:
    """移行で作った印も、同じ日に先の記録があれば取り消しで消えない。"""
    conn = _old_db(tmp_db_path)
    try:
        db.init_db(conn)
        latest = datetime(2026, 11, 8, 21, 0, 0, tzinfo=JST)
        assert db.undo_record_mark(conn, PID, latest, clear_mark=True)
        assert date(2026, 11, 8) in {
            m.record_date for m in db.list_record_marks(conn, PID)
        }
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
