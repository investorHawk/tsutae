"""seed_patient: 患者・コース・記録を1つのトランザクションで入れる（合成データの投入用）。

記録は schemas.py の `Entry`（`tsutae.dataset.to_entries` の結果）で受け取る。
db の中に専用の型を作らない（§0「共通の型は schemas.py」）。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from tsutae import db
from tsutae.config import JST, to_jst_date
from tsutae.db import (
    connect,
    create_patient,
    get_patient,
    init_db,
    list_courses,
    list_entries,
    seed_patient,
)
from tsutae.schemas import ClosedAnswer, Course, Entry

PID = "P-SEED0001"
AT = datetime(2026, 10, 28, 20, 0, tzinfo=JST)


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = connect(tmp_db_path)
    init_db(c)
    return c


def _courses(pid: str = PID) -> list[Course]:
    return [
        Course(patient_id=pid, course_no=1, infusion_date=date(2026, 9, 27)),
        Course(
            patient_id=pid,
            course_no=2,
            infusion_date=date(2026, 10, 13),
            planned_date=date(2026, 10, 11),
            note="延期",
        ),
    ]


def _entry(
    seq: int,
    recorded_at: datetime,
    *,
    pid: str = PID,
    skill_version: str = "regimen-folfox@1",
    **kw,
) -> Entry:
    """投入する記録（id は合成データの seq。DB の id は入れた順に振られる）。"""
    return Entry(
        id=seq,
        patient_id=pid,
        recorded_at=recorded_at,
        record_date=to_jst_date(recorded_at),
        kind=kw.get("kind", "free_text"),
        by_proxy=kw.get("by_proxy", False),
        skill_version=skill_version,
        answers=kw.get("answers", []),
        free_text=kw.get("free_text", f"記録{seq}"),
    )


def _entries(count: int = 3) -> list[Entry]:
    made = [_entry(i + 1, AT.replace(day=AT.day - i)) for i in range(count)]
    made[0] = _entry(
        1,
        AT,
        kind="answers",
        free_text=None,
        answers=[
            ClosedAnswer(question_key="fever", value="measured", temperature=37.9)
        ],
    )
    return made


def _seed(conn: sqlite3.Connection, **kw) -> bool:
    return seed_patient(
        conn,
        patient_id=kw.get("patient_id", PID),
        regimen=kw.get("regimen", "FOLFOX"),
        courses=kw.get("courses", _courses()),
        entries=kw.get("entries", _entries()),
    )


def _fail_on_nth_entry(conn: sqlite3.Connection, nth: int) -> None:
    """この接続で、表に既に nth-1 件あるときの entries への INSERT を失敗させる。"""
    conn.execute(
        "CREATE TEMP TRIGGER fail_entries BEFORE INSERT ON main.entries"
        f" WHEN (SELECT COUNT(*) FROM main.entries) >= {int(nth) - 1}"
        " BEGIN SELECT RAISE(ABORT, 'injected'); END"
    )


def _totals(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
    return tuple(
        conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("patients", "courses", "entries", "closed_answers")
    )


def test_inserts_patient_courses_and_entries(conn: sqlite3.Connection) -> None:
    entries = _entries()
    assert _seed(conn, entries=entries) is True
    assert conn.in_transaction is False
    assert get_patient(conn, PID)["regimen"] == "FOLFOX"
    courses = list_courses(conn, PID)
    assert [
        (c.course_no, c.infusion_date, c.planned_date, c.note) for c in courses
    ] == [
        (1, date(2026, 9, 27), None, None),
        (2, date(2026, 10, 13), date(2026, 10, 11), "延期"),
    ]
    saved = sorted(list_entries(conn, PID), key=lambda e: e.id)
    assert [e.id for e in saved] == [1, 2, 3]  # 渡した順に id を振る
    assert [e.recorded_at for e in saved] == [e.recorded_at for e in entries]
    assert saved[0].answers[0].temperature == 37.9
    assert saved[1].free_text == "記録2"
    assert {e.skill_version for e in saved} == {"regimen-folfox@1"}
    assert [e.kind for e in saved] == ["answers", "free_text", "free_text"]
    assert [e.record_date for e in saved] == [e.record_date for e in entries]


def test_db_has_no_own_seed_type() -> None:
    """投入の型は schemas.py の Entry を使う（db の中に dataclass を作らない）。"""
    assert not hasattr(db, "SeedEntry")
    assert "SeedEntry" not in db.__all__


def test_too_sick_and_by_proxy_round_trip(conn: sqlite3.Connection) -> None:
    entries = [
        _entry(1, AT, kind="too_sick", free_text=None),
        _entry(
            2,
            AT.replace(hour=21),
            kind="mixed",
            by_proxy=True,
            answers=[ClosedAnswer(question_key="diarrhea", value="present")],
        ),
    ]
    assert _seed(conn, entries=entries) is True
    saved = sorted(list_entries(conn, PID), key=lambda e: e.id)
    assert [(e.kind, e.by_proxy) for e in saved] == [
        ("too_sick", False),
        ("mixed", True),
    ]
    assert saved[1].free_text == "記録2"


def test_existing_patient_is_skipped_untouched(conn: sqlite3.Connection) -> None:
    create_patient(conn, "CAPOX", patient_id=PID)
    assert _seed(conn) is False
    assert conn.in_transaction is False
    assert get_patient(conn, PID)["regimen"] == "CAPOX"
    assert list_courses(conn, PID) == []
    assert list_entries(conn, PID) == []


def test_seed_twice_adds_once(conn: sqlite3.Connection) -> None:
    assert _seed(conn) is True
    first = _totals(conn)
    assert _seed(conn) is False
    assert _totals(conn) == first


def test_failure_mid_entries_leaves_nothing(
    conn: sqlite3.Connection, tmp_db_path: Path
) -> None:
    _fail_on_nth_entry(conn, 3)
    with pytest.raises(sqlite3.Error):
        _seed(conn)
    assert conn.in_transaction is False
    assert _totals(conn) == (0, 0, 0, 0)
    other = connect(tmp_db_path)  # 別の接続から見ても残っていない
    try:
        assert _totals(other) == (0, 0, 0, 0)
    finally:
        other.close()
    conn.execute("DROP TRIGGER temp.fail_entries")
    assert _seed(conn) is True  # 入れ直せる
    assert _totals(conn)[:3] == (1, 2, 3)


def test_failure_keeps_other_patients(conn: sqlite3.Connection) -> None:
    other = create_patient(conn, "CAPOX")
    _fail_on_nth_entry(conn, 1)
    with pytest.raises(sqlite3.Error):
        _seed(conn)
    assert get_patient(conn, other) is not None
    assert get_patient(conn, PID) is None


@pytest.mark.parametrize(
    "override",
    [
        {"regimen": "XELOX"},
        {"patient_id": "P-short"},
        {"patient_id": "p-seed0001"},
        {"courses": _courses("P-OTHER001")},
        {"entries": [_entry(1, AT, skill_version="regimen folfox")]},
        {"entries": [_entry(1, AT, pid="P-OTHER001")]},
        {"entries": [_entry(1, AT, kind="mixed")]},  # 自由記載だけなのに mixed
        {"entries": [_entry(1, AT, kind="too_sick")]},  # too_sick に自由記載
        {"entries": [("not", "a", "seed entry")]},
    ],
)
def test_invalid_input_raises_and_writes_nothing(
    conn: sqlite3.Connection, override: dict
) -> None:
    with pytest.raises(ValueError):
        _seed(conn, **override)
    assert conn.in_transaction is False
    assert _totals(conn) == (0, 0, 0, 0)


def test_no_courses_or_entries_is_allowed(conn: sqlite3.Connection) -> None:
    assert _seed(conn, courses=[], entries=[]) is True
    assert _totals(conn) == (1, 0, 0, 0)


def test_does_not_mutate_arguments(conn: sqlite3.Connection) -> None:
    courses = _courses()
    entries = _entries()
    before = (list(courses), list(entries))
    _seed(conn, courses=courses, entries=entries)
    assert (courses, entries) == before
    assert all(c.id is None for c in courses)
