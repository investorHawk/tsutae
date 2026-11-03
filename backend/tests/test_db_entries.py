"""記録の保存・取得（JST の record_date、期間指定、回答の順序）。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from tsutae.config import JST
from tsutae.db import (
    NotFoundError,
    add_entry,
    connect,
    create_patient,
    get_entry,
    init_db,
    list_entries,
)
from tsutae.schemas import ClosedAnswer, EntryCreate

SV = "regimen-folfox@1"


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = connect(tmp_db_path)
    init_db(c)
    return c


@pytest.fixture
def pid(conn: sqlite3.Connection) -> str:
    return create_patient(conn, "FOLFOX", patient_id="P-TEST0001")


def _at(d: date, hh: int = 9, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=JST)


def _answers_only() -> EntryCreate:
    return EntryCreate(answers=[ClosedAnswer(question_key="numbness", value="none")])


def test_add_entry_returns_entry_with_answers_in_order(
    conn: sqlite3.Connection, pid: str
) -> None:
    answers = [
        ClosedAnswer(question_key="stomatitis", value="hard"),
        ClosedAnswer(question_key="fever", value="measured", temperature=37.9),
        ClosedAnswer(question_key="diarrhea", value="present"),
        ClosedAnswer(question_key="numbness", value="none"),
    ]
    entry = add_entry(
        conn,
        pid,
        EntryCreate(answers=answers, free_text="  口の中が痛い  ", by_proxy=True),
        _at(date(2026, 11, 4), 20, 15),
        SV,
    )
    assert entry.id > 0
    assert entry.patient_id == pid
    assert entry.kind == "mixed"
    assert entry.by_proxy is True
    assert entry.skill_version == SV
    assert entry.answers == answers
    assert entry.free_text == "口の中が痛い"
    assert entry.record_date == date(2026, 11, 4)
    assert entry.recorded_at == _at(date(2026, 11, 4), 20, 15)
    assert get_entry(conn, entry.id) == entry


@pytest.mark.parametrize(
    ("create", "kind"),
    [
        (EntryCreate(too_sick=True), "too_sick"),
        (EntryCreate(free_text="だるい"), "free_text"),
        (
            EntryCreate(
                answers=[ClosedAnswer(question_key="fever", value="not_measured")]
            ),
            "answers",
        ),
    ],
)
def test_kind_comes_from_entry_create(
    conn: sqlite3.Connection, pid: str, create: EntryCreate, kind: str
) -> None:
    entry = add_entry(conn, pid, create, _at(date(2026, 11, 4)), SV)
    assert entry.kind == kind
    assert get_entry(conn, entry.id).kind == kind


def test_too_sick_entry_has_no_answers_or_text(
    conn: sqlite3.Connection, pid: str
) -> None:
    entry = add_entry(conn, pid, EntryCreate(too_sick=True), _at(date(2026, 11, 4)), SV)
    assert entry.answers == []
    assert entry.free_text is None
    assert entry.by_proxy is False


def test_recorded_at_is_stored_as_jst_iso(conn: sqlite3.Connection, pid: str) -> None:
    utc = datetime.fromisoformat("2026-11-08T15:30:00+00:00")
    entry = add_entry(conn, pid, _answers_only(), utc, SV)
    raw = conn.execute(
        "SELECT recorded_at, record_date FROM entries WHERE id = ?", (entry.id,)
    ).fetchone()
    assert raw["recorded_at"].endswith("+09:00")
    assert datetime.fromisoformat(raw["recorded_at"]) == utc
    assert raw["record_date"] == "2026-11-09"
    assert entry.recorded_at == utc
    assert entry.recorded_at.utcoffset().total_seconds() == 9 * 3600


@pytest.mark.parametrize(
    ("recorded_at", "expected"),
    [
        (datetime(2026, 11, 8, 23, 59, 59, tzinfo=JST), date(2026, 11, 8)),
        (datetime(2026, 11, 9, 0, 0, 0, tzinfo=JST), date(2026, 11, 9)),
        (datetime(2026, 11, 9, 0, 0, 1, tzinfo=JST), date(2026, 11, 9)),
        # UTC 14:59 は JST 23:59（同じ日）、UTC 15:00 は JST 翌 0:00
        (datetime.fromisoformat("2026-11-08T14:59:00+00:00"), date(2026, 11, 8)),
        (datetime.fromisoformat("2026-11-08T15:00:00+00:00"), date(2026, 11, 9)),
        # naive は JST とみなす
        (datetime(2026, 11, 8, 23, 59), date(2026, 11, 8)),
    ],
)
def test_record_date_around_midnight(
    conn: sqlite3.Connection, pid: str, recorded_at: datetime, expected: date
) -> None:
    entry = add_entry(conn, pid, _answers_only(), recorded_at, SV)
    assert entry.record_date == expected
    assert get_entry(conn, entry.id).record_date == expected


def test_list_entries_filters_by_record_date(
    conn: sqlite3.Connection, pid: str
) -> None:
    other = create_patient(conn, "FOLFOX", patient_id="P-TEST0002")
    # 11/8 23:30 JST, 11/9 0:30 JST（UTC では 11/8）, 11/10, 11/11
    stamps = [
        datetime(2026, 11, 8, 23, 30, tzinfo=JST),
        datetime.fromisoformat("2026-11-08T15:30:00+00:00"),
        datetime(2026, 11, 10, 9, 0, tzinfo=JST),
        datetime(2026, 11, 11, 9, 0, tzinfo=JST),
    ]
    ids = [add_entry(conn, pid, _answers_only(), s, SV).id for s in stamps]
    add_entry(conn, other, _answers_only(), stamps[1], SV)

    assert [e.id for e in list_entries(conn, pid)] == ids
    in_range = list_entries(conn, pid, start=date(2026, 11, 9), end=date(2026, 11, 10))
    assert [e.id for e in in_range] == ids[1:3]
    assert [e.id for e in list_entries(conn, pid, start=date(2026, 11, 10))] == ids[2:]
    assert [e.id for e in list_entries(conn, pid, end=date(2026, 11, 8))] == ids[:1]
    assert list_entries(conn, pid, start=date(2026, 12, 1)) == []


def test_list_entries_sorted_by_recorded_at(conn: sqlite3.Connection, pid: str) -> None:
    late = add_entry(conn, pid, _answers_only(), _at(date(2026, 11, 5), 21), SV)
    early = add_entry(conn, pid, _answers_only(), _at(date(2026, 11, 5), 8), SV)
    # 回想入力などで後から前の時刻の記録が入っても recorded_at 順
    earliest = add_entry(
        conn,
        pid,
        EntryCreate(free_text="昨日から下痢"),
        datetime.fromisoformat("2026-11-04T12:00:00+00:00"),
        SV,
    )
    result = list_entries(conn, pid)
    assert [e.id for e in result] == [earliest.id, early.id, late.id]
    assert result[0].free_text == "昨日から下痢"


def test_list_entries_includes_answers_per_entry(
    conn: sqlite3.Connection, pid: str
) -> None:
    a = add_entry(
        conn,
        pid,
        EntryCreate(
            answers=[
                ClosedAnswer(question_key="diarrhea", value="none"),
                ClosedAnswer(question_key="fever", value="measured", temperature=38.1),
            ]
        ),
        _at(date(2026, 11, 5)),
        SV,
    )
    b = add_entry(
        conn,
        pid,
        EntryCreate(answers=[ClosedAnswer(question_key="numbness", value="hard")]),
        _at(date(2026, 11, 6)),
        SV,
    )
    assert list_entries(conn, pid) == [a, b]


def test_get_entry_unknown_is_none(conn: sqlite3.Connection) -> None:
    assert get_entry(conn, 999) is None


def test_add_entry_unknown_patient_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        add_entry(conn, "P-NOPE0000", _answers_only(), _at(date(2026, 11, 4)), SV)


@pytest.mark.parametrize("bad", ["", "folfox", "regimen-folfox@", "regimen-folfox@0"])
def test_add_entry_rejects_malformed_skill_version(
    conn: sqlite3.Connection, pid: str, bad: str
) -> None:
    with pytest.raises(ValueError):
        add_entry(conn, pid, _answers_only(), _at(date(2026, 11, 4)), bad)


def test_failed_add_entry_leaves_nothing(conn: sqlite3.Connection, pid: str) -> None:
    # 回答の挿入で失敗したら entries の行も残らない（トランザクション）
    conn.execute(
        "CREATE TRIGGER fail_answers BEFORE INSERT ON closed_answers"
        " BEGIN SELECT RAISE(ABORT, 'boom'); END"
    )
    with pytest.raises(sqlite3.DatabaseError):
        add_entry(conn, pid, _answers_only(), _at(date(2026, 11, 4)), SV)
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
