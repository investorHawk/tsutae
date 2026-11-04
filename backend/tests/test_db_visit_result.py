"""save_visit_result: 変換結果・レポート・状態を1つのトランザクションで保存する。"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from test_db_visits import EXPIRES, PAST, _report, _timeline, _visit

from tsutae.db import (
    NotFoundError,
    VisitClosedError,
    connect,
    create_patient,
    get_report,
    get_timeline,
    get_visit,
    init_db,
    mark_printed,
    purge_expired,
    save_visit_result,
)
from tsutae.schemas import Timeline

HTML = "<html>r</html>"


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """保存は「今」と expires_at を比べるので、今日を受診日に固定する。"""
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-09")


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = connect(tmp_db_path)
    init_db(c)
    return c


@pytest.fixture
def pid(conn: sqlite3.Connection) -> str:
    return create_patient(conn, "FOLFOX", patient_id="P-TEST0001")


def _save(conn: sqlite3.Connection, vid: int, **kw) -> None:
    save_visit_result(
        conn,
        vid,
        timeline=kw.get("timeline", _timeline()),
        html=kw.get("html", HTML),
        data=kw.get("data", _report()),
        status=kw.get("status", "ready"),
        fallback=kw.get("fallback", False),
    )


def _fail_inserts_into(conn: sqlite3.Connection, table: str) -> None:
    """この接続で table への INSERT を本物の DB の失敗にする（一時トリガ）。"""
    assert table in {"timelines", "reports"}
    conn.execute(
        f"CREATE TEMP TRIGGER fail_{table} BEFORE INSERT ON main.{table}"
        " BEGIN SELECT RAISE(ABORT, 'injected'); END"
    )


def _count(conn: sqlite3.Connection, table: str, vid: int) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE visit_id = ?", (vid,)
    ).fetchone()[0]


def test_saves_timeline_report_and_status(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    _save(conn, vid, fallback=True)
    assert get_timeline(conn, vid) == _timeline()
    html, data = get_report(conn, vid)
    assert html == HTML
    assert data == _report()
    visit = get_visit(conn, vid)
    assert visit["status"] == "ready"
    assert visit["fallback"] is True
    assert conn.in_transaction is False


def test_overwrites_previous_result(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    _save(conn, vid, fallback=True)
    empty = Timeline()
    _save(conn, vid, timeline=empty, html="<html>2</html>", fallback=False)
    assert get_timeline(conn, vid) == empty
    assert get_report(conn, vid)[0] == "<html>2</html>"
    assert get_visit(conn, vid)["fallback"] is False


def test_failed_status_is_allowed(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    _save(conn, vid, status="failed")
    assert get_visit(conn, vid)["status"] == "failed"


@pytest.mark.parametrize("table", ["timelines", "reports"])
def test_db_error_leaves_nothing(
    conn: sqlite3.Connection, pid: str, table: str
) -> None:
    vid = _visit(conn, pid)
    _fail_inserts_into(conn, table)
    with pytest.raises(sqlite3.Error):
        _save(conn, vid)
    assert conn.in_transaction is False
    assert _count(conn, "timelines", vid) == 0
    assert _count(conn, "reports", vid) == 0
    visit = get_visit(conn, vid)
    assert visit["status"] == "generating"
    assert visit["fallback"] is False


def test_db_error_keeps_previous_result(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    _save(conn, vid, fallback=True)
    _fail_inserts_into(conn, "reports")
    with pytest.raises(sqlite3.Error):
        _save(conn, vid, timeline=Timeline(), status="failed", fallback=False)
    assert get_timeline(conn, vid) == _timeline()  # timeline だけ書き換わらない
    visit = get_visit(conn, vid)
    assert (visit["status"], visit["fallback"]) == ("ready", True)


def test_printed_visit_is_rejected_and_unchanged(
    conn: sqlite3.Connection, pid: str, tmp_db_path: Path
) -> None:
    vid = _visit(conn, pid)
    other = connect(tmp_db_path)  # 別の接続で印刷済みにされる
    try:
        mark_printed(other, vid)
    finally:
        other.close()
    with pytest.raises(VisitClosedError):
        _save(conn, vid)
    assert conn.in_transaction is False
    assert _count(conn, "timelines", vid) == 0
    assert _count(conn, "reports", vid) == 0
    visit = get_visit(conn, vid)
    assert (visit["status"], visit["reception_no"]) == ("printed", None)


def test_expired_visit_is_rejected_and_unchanged(
    conn: sqlite3.Connection, pid: str
) -> None:
    vid = _visit(conn, pid)
    assert purge_expired(conn, EXPIRES) == 1
    with pytest.raises(VisitClosedError):
        _save(conn, vid)
    assert _count(conn, "timelines", vid) == 0
    assert _count(conn, "reports", vid) == 0
    assert get_visit(conn, vid)["status"] == "generating"


def test_expired_but_not_purged_is_rejected_and_unchanged(
    conn: sqlite3.Connection, pid: str
) -> None:
    """expires_at を過ぎていれば、purge_expired の前でも保存しない（purge もしない）。"""
    vid = _visit(conn, pid, expires_at=PAST)
    with pytest.raises(VisitClosedError):
        _save(conn, vid, fallback=True)
    assert conn.in_transaction is False
    assert _count(conn, "timelines", vid) == 0
    assert _count(conn, "reports", vid) == 0
    visit = get_visit(conn, vid)
    assert (visit["status"], visit["fallback"]) == ("generating", False)
    assert visit["reception_no"] == "A-023"


def test_expires_during_generation_keeps_previous_result(
    conn: sqlite3.Connection, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = _visit(conn, pid)
    _save(conn, vid, html="<html>first</html>", fallback=True)
    monkeypatch.setattr(
        "tsutae.db.repo_visits.clock_now", lambda: EXPIRES + timedelta(seconds=1)
    )
    with pytest.raises(VisitClosedError):
        _save(conn, vid, html="<html>second</html>", status="failed", fallback=False)
    assert get_report(conn, vid)[0] == "<html>first</html>"
    visit = get_visit(conn, vid)
    assert (visit["status"], visit["fallback"]) == ("ready", True)


def test_unknown_visit_raises_not_found(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        _save(conn, 999)


@pytest.mark.parametrize("status", ["printed", "generating?", ""])
def test_rejects_bad_status(conn: sqlite3.Connection, pid: str, status: str) -> None:
    vid = _visit(conn, pid)
    with pytest.raises(ValueError):
        _save(conn, vid, status=status)
    assert _count(conn, "timelines", vid) == 0
    assert get_visit(conn, vid)["status"] == "generating"


def test_rejects_non_string_html(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    with pytest.raises(ValueError):
        _save(conn, vid, html=b"<html></html>")
    assert _count(conn, "timelines", vid) == 0
