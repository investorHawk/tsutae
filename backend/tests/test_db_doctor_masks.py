"""医師の伏せ字（doctor_masks）の保存・読み出し・保持と、やり直しの条件。症例は全て合成。

- 受診ごと・記録ごとに1行（区間・確かめ・許す区間。文面は持たない）。生の記録は変えない
- 開いている（受付番号が残り期限内・印刷済みでない）受診にだけ保存できる。閉じた受診は
  VisitClosedError、生成中は VisitGeneratingError（どちらも何も変えない）
- 印刷済み・期限切れで、レポートと同じトランザクションで消す
- 医師の伏せ字が1件以上ある開いた受診は、AI の結果で ready でもやり直せる
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from tsutae.config import JST
from tsutae.db import (
    NotFoundError,
    VisitClosedError,
    VisitGeneratingError,
    add_entry,
    begin_regeneration,
    connect,
    create_patient,
    create_visit,
    get_entry,
    get_visit,
    init_db,
    list_doctor_masks,
    mark_printed,
    purge_expired,
    save_doctor_masks,
    set_visit_status,
)
from tsutae.schemas import DoctorMask, EntryCreate, TextSpan

VISIT_DAY = date(2026, 11, 9)
EXPIRES = datetime(2026, 11, 10, 9, 30, tzinfo=JST)
RECORDED = datetime(2026, 11, 8, 20, 0, tzinfo=JST)
TEXT = "磯鷲さんにもらった漢方をのんでみた"


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-09")


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = connect(tmp_db_path)
    init_db(c)
    return c


def _setup(conn: sqlite3.Connection, status: str = "ready") -> tuple[int, int, str]:
    pid = create_patient(conn, "FOLFOX")
    entry = add_entry(
        conn, pid, EntryCreate(free_text=TEXT), RECORDED, "regimen-folfox@1"
    )
    vid = create_visit(conn, pid, "A-023", VISIT_DAY, EXPIRES, 1)
    if status != "generating":
        set_visit_status(conn, vid, status)
    return vid, entry.id, pid


def _mask(*spans: tuple[int, int], confirmed=False, allowed=()) -> DoctorMask:
    return DoctorMask(
        spans=[TextSpan(start=s, end=e) for s, e in spans],
        confirmed_clear=confirmed,
        allowed=[TextSpan(start=s, end=e) for s, e in allowed],
    )


def _count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM doctor_masks").fetchone()[0]


# --- 保存と読み出し -------------------------------------------------------------


def test_save_and_list_round_trip(conn: sqlite3.Connection) -> None:
    vid, eid, _pid = _setup(conn)
    mask = _mask((0, 2), confirmed=True, allowed=[(5, 7)])
    save_doctor_masks(conn, vid, upserts={eid: mask})
    assert list_doctor_masks(conn, vid) == {eid: mask}


def test_save_replaces_the_row_and_removes(conn: sqlite3.Connection) -> None:
    vid, eid, _pid = _setup(conn)
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 4))})
    assert list_doctor_masks(conn, vid) == {eid: _mask((0, 4))}
    save_doctor_masks(conn, vid, removals=[eid])
    assert list_doctor_masks(conn, vid) == {}


def test_save_does_not_change_the_raw_record(conn: sqlite3.Connection) -> None:
    vid, eid, _pid = _setup(conn)
    before = get_entry(conn, eid)
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    assert get_entry(conn, eid) == before
    row = conn.execute("SELECT text FROM free_texts WHERE entry_id = ?", (eid,))
    assert row.fetchone()["text"] == TEXT


def test_table_keeps_positions_only(conn: sqlite3.Connection) -> None:
    vid, eid, _pid = _setup(conn)
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    row = conn.execute("SELECT * FROM doctor_masks").fetchone()
    assert "磯鷲" not in " ".join(str(v) for v in tuple(row))


def test_entry_of_another_patient_is_rejected(conn: sqlite3.Connection) -> None:
    vid, _eid, _pid = _setup(conn)
    other = create_patient(conn, "FOLFOX")
    entry = add_entry(
        conn, other, EntryCreate(free_text=TEXT), RECORDED, "regimen-folfox@1"
    )
    with pytest.raises(ValueError):
        save_doctor_masks(conn, vid, upserts={entry.id: _mask((0, 2))})
    assert _count(conn) == 0


def test_missing_visit_is_not_found(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        save_doctor_masks(conn, 999, upserts={})


# --- 閉じた受診・生成中 ---------------------------------------------------------


def test_printed_visit_is_closed(conn: sqlite3.Connection) -> None:
    vid, eid, _pid = _setup(conn)
    mark_printed(conn, vid)
    with pytest.raises(VisitClosedError):
        save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    assert _count(conn) == 0


def test_expired_visit_is_closed_even_before_purge(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid, eid, _pid = _setup(conn)
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-11")
    with pytest.raises(VisitClosedError):
        save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    assert _count(conn) == 0


def test_generating_visit_is_refused(conn: sqlite3.Connection) -> None:
    vid, eid, _pid = _setup(conn, status="generating")
    with pytest.raises(VisitGeneratingError):
        save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    assert _count(conn) == 0


# --- 保持（印刷済み・TTL で消す） -------------------------------------------------


def test_mark_printed_erases_doctor_masks(conn: sqlite3.Connection) -> None:
    vid, eid, _pid = _setup(conn)
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    assert mark_printed(conn, vid)
    assert list_doctor_masks(conn, vid) == {}
    assert get_entry(conn, eid) is not None  # 生の記録は残る


def test_purge_erases_doctor_masks(conn: sqlite3.Connection) -> None:
    vid, eid, _pid = _setup(conn)
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    assert purge_expired(conn, datetime(2026, 11, 11, tzinfo=JST)) == 1
    assert list_doctor_masks(conn, vid) == {}
    assert get_visit(conn, vid)["reception_no"] is None


def test_purge_erases_masks_left_on_already_erased_visit(
    conn: sqlite3.Connection,
) -> None:
    vid, eid, _pid = _setup(conn)
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    # 受付番号だけが先に消えた行（古い版の purge 等）でも、残った伏せ字を消す
    with conn:
        conn.execute("UPDATE visits SET reception_no = NULL WHERE id = ?", (vid,))
    assert purge_expired(conn, datetime(2026, 11, 11, tzinfo=JST)) == 1
    assert _count(conn) == 0


# --- やり直しの条件 -------------------------------------------------------------


def test_ai_ready_visit_is_not_regenerable_without_masks(
    conn: sqlite3.Connection,
) -> None:
    vid, _eid, _pid = _setup(conn)
    assert get_visit(conn, vid)["fallback"] is False
    assert begin_regeneration(conn, vid) is False
    assert get_visit(conn, vid)["status"] == "ready"


def test_ai_ready_visit_with_masks_is_regenerable_once(
    conn: sqlite3.Connection,
) -> None:
    vid, eid, _pid = _setup(conn)
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    assert begin_regeneration(conn, vid) is True
    assert get_visit(conn, vid)["status"] == "generating"
    assert begin_regeneration(conn, vid) is False  # 二重に押しても1回だけ


def test_closed_visit_with_masks_is_not_regenerable(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid, eid, _pid = _setup(conn)
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-11")
    assert begin_regeneration(conn, vid) is False
    assert get_visit(conn, vid)["status"] == "ready"


def test_removed_masks_make_ai_ready_visit_not_regenerable(
    conn: sqlite3.Connection,
) -> None:
    vid, eid, _pid = _setup(conn)
    save_doctor_masks(conn, vid, upserts={eid: _mask((0, 2))})
    save_doctor_masks(conn, vid, removals=[eid])
    assert begin_regeneration(conn, vid) is False
