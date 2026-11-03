"""患者とコースの保存・取得。"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from tsutae.db import (
    NotFoundError,
    connect,
    create_patient,
    get_patient,
    init_db,
    list_courses,
    list_patients,
    upsert_course,
)
from tsutae.schemas import Course


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = connect(tmp_db_path)
    init_db(c)
    return c


def test_create_patient_generates_pseudonymous_id(conn: sqlite3.Connection) -> None:
    pid = create_patient(conn, "FOLFOX")
    assert re.fullmatch(r"P-[A-Z0-9]{8}", pid)
    patient = get_patient(conn, pid)
    assert patient is not None
    assert patient["id"] == pid
    assert patient["regimen"] == "FOLFOX"
    assert isinstance(patient["created_at"], datetime)
    assert patient["created_at"].utcoffset() is not None


def test_create_patient_ids_are_distinct(conn: sqlite3.Connection) -> None:
    ids = {create_patient(conn, "CAPOX") for _ in range(20)}
    assert len(ids) == 20


def test_create_patient_retries_on_id_collision(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_patient(conn, "FOLFOX", patient_id="P-TAKEN001")
    ids = iter(["P-TAKEN001", "P-TAKEN001", "P-FRESH001"])
    monkeypatch.setattr("tsutae.db.repo_patients._new_patient_id", ids.__next__)
    assert create_patient(conn, "CAPOX") == "P-FRESH001"
    assert get_patient(conn, "P-FRESH001")["regimen"] == "CAPOX"
    assert get_patient(conn, "P-TAKEN001")["regimen"] == "FOLFOX"


def test_create_patient_gives_up_after_repeated_collisions(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_patient(conn, "FOLFOX", patient_id="P-TAKEN001")
    calls: list[str] = []

    def always_taken() -> str:
        calls.append("P-TAKEN001")
        return "P-TAKEN001"

    monkeypatch.setattr("tsutae.db.repo_patients._new_patient_id", always_taken)
    with pytest.raises(RuntimeError):
        create_patient(conn, "CAPOX")
    assert len(calls) == 5
    assert [p["id"] for p in list_patients(conn)] == ["P-TAKEN001"]


def test_create_patient_with_given_id(conn: sqlite3.Connection) -> None:
    assert create_patient(conn, "FOLFOX", patient_id="P-DEMO0001") == "P-DEMO0001"
    assert get_patient(conn, "P-DEMO0001") is not None


def test_create_patient_duplicate_id_raises(conn: sqlite3.Connection) -> None:
    create_patient(conn, "FOLFOX", patient_id="P-DEMO0001")
    with pytest.raises(sqlite3.IntegrityError):
        create_patient(conn, "FOLFOX", patient_id="P-DEMO0001")


@pytest.mark.parametrize("bad", ["P-demo0001", "DEMO0001", "P-123", "P-ABCDEFGHI", ""])
def test_create_patient_rejects_malformed_id(
    conn: sqlite3.Connection, bad: str
) -> None:
    with pytest.raises(ValueError):
        create_patient(conn, "FOLFOX", patient_id=bad)


def test_create_patient_rejects_unknown_regimen(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        create_patient(conn, "XELOX")


def test_get_patient_unknown_is_none(conn: sqlite3.Connection) -> None:
    assert get_patient(conn, "P-NOPE0000") is None


def test_list_patients_in_creation_order(conn: sqlite3.Connection) -> None:
    a = create_patient(conn, "FOLFOX", patient_id="P-AAAA0001")
    b = create_patient(conn, "CAPOX", patient_id="P-BBBB0002")
    rows = list_patients(conn)
    assert [r["id"] for r in rows] == [a, b]
    assert [r["regimen"] for r in rows] == ["FOLFOX", "CAPOX"]


def test_upsert_course_inserts_and_returns_id(conn: sqlite3.Connection) -> None:
    pid = create_patient(conn, "FOLFOX")
    course = Course(
        patient_id=pid,
        course_no=2,
        infusion_date=date(2026, 10, 13),
        planned_date=date(2026, 10, 11),
        next_visit=date(2026, 10, 27),
        note="延期",
    )
    saved = upsert_course(conn, course)
    assert saved.id is not None
    assert saved.model_dump(exclude={"id"}) == course.model_dump(exclude={"id"})
    assert course.id is None  # 引数は書き換えない


def test_upsert_course_updates_same_course_no(conn: sqlite3.Connection) -> None:
    pid = create_patient(conn, "FOLFOX")
    first = upsert_course(
        conn, Course(patient_id=pid, course_no=1, infusion_date=date(2026, 9, 27))
    )
    second = upsert_course(
        conn,
        Course(
            patient_id=pid,
            course_no=1,
            infusion_date=date(2026, 9, 28),
            planned_date=date(2026, 9, 27),
        ),
    )
    assert second.id == first.id
    courses = list_courses(conn, pid)
    assert len(courses) == 1
    assert courses[0].infusion_date == date(2026, 9, 28)
    assert courses[0].planned_date == date(2026, 9, 27)


def test_upsert_course_clears_optional_fields(conn: sqlite3.Connection) -> None:
    pid = create_patient(conn, "FOLFOX")
    upsert_course(
        conn,
        Course(
            patient_id=pid,
            course_no=1,
            infusion_date=date(2026, 9, 27),
            note="メモ",
        ),
    )
    upsert_course(
        conn, Course(patient_id=pid, course_no=1, infusion_date=date(2026, 9, 27))
    )
    assert list_courses(conn, pid)[0].note is None


def test_list_courses_sorted_by_course_no(conn: sqlite3.Connection) -> None:
    pid = create_patient(conn, "FOLFOX")
    other = create_patient(conn, "CAPOX")
    for no, d in [
        (3, date(2026, 10, 27)),
        (1, date(2026, 9, 27)),
        (2, date(2026, 10, 13)),
    ]:
        upsert_course(conn, Course(patient_id=pid, course_no=no, infusion_date=d))
    upsert_course(
        conn, Course(patient_id=other, course_no=1, infusion_date=date(2026, 9, 1))
    )
    courses = list_courses(conn, pid)
    assert [c.course_no for c in courses] == [1, 2, 3]
    assert all(c.patient_id == pid for c in courses)


def test_upsert_course_unknown_patient_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        upsert_course(
            conn,
            Course(
                patient_id="P-NOPE0000", course_no=1, infusion_date=date(2026, 9, 1)
            ),
        )
