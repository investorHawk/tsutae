"""受診・変換結果・レポートと、印刷済み／期限切れの削除。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tsutae.config import JST
from tsutae.db import (
    NotFoundError,
    VisitClosedError,
    connect,
    create_patient,
    create_visit,
    get_report,
    get_timeline,
    get_visit,
    init_db,
    list_visits,
    mark_printed,
    purge_expired,
    save_report,
    save_timeline,
    set_visit_status,
)
from tsutae.schemas import (
    Grid,
    ReportData,
    ReportHeader,
    Timeline,
    TimelineEvent,
    UnprocessedEntry,
)

VISIT_DAY = date(2026, 11, 9)
EXPIRES = datetime(2026, 11, 10, 9, 30, tzinfo=JST)
PAST = datetime(2026, 11, 8, 9, 30, tzinfo=JST)  # 固定した「今日」より前に期限切れ


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """保存は「今」と expires_at を比べるので、今日を受診日に固定する。

    固定しないと、実際の日付が EXPIRES を過ぎた日にテストが落ちる。
    """
    monkeypatch.setenv("TSUTAE_TODAY", "2026-11-09")


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    c = connect(tmp_db_path)
    init_db(c)
    return c


@pytest.fixture
def pid(conn: sqlite3.Connection) -> str:
    return create_patient(conn, "FOLFOX", patient_id="P-TEST0001")


def _visit(conn: sqlite3.Connection, pid: str, no: str = "A-023", **kw) -> int:
    return create_visit(
        conn,
        pid,
        no,
        kw.get("visit_date", VISIT_DAY),
        kw.get("expires_at", EXPIRES),
        kw.get("course_no", 3),
    )


def _timeline() -> Timeline:
    return Timeline(
        events=[
            TimelineEvent(
                entry_no=1,
                date=date(2026, 10, 31),
                day=5,
                course_no=3,
                term="下痢",
                question_key="diarrhea",
                status="present",
                source_quote="お腹がゆるい",
                confidence=0.9,
            )
        ],
        unprocessed_entries=[UnprocessedEntry(entry_id=7, reason="at_mark")],
    )


def _report() -> ReportData:
    return ReportData(
        header=ReportHeader(
            reception_no="A-023",
            patient_id="P-TEST0001",
            regimen="FOLFOX",
            course_no=3,
            course_start=date(2026, 10, 27),
            course_end=date(2026, 11, 9),
            recorded_days=10,
            total_days=14,
            no_input_days=2,
            too_sick_days=2,
            delay_note=None,
        ),
        attention=[],
        grid=Grid(days=[1, 2], columns=[], rows=[]),
        per_symptom=[],
        quotes=[],
        report_skill_version="report-format-default@1",
    )


def _with_results(conn: sqlite3.Connection, vid: int) -> None:
    save_timeline(conn, vid, _timeline())
    save_report(conn, vid, "<html>r</html>", _report())
    set_visit_status(conn, vid, "ready")


def _count(conn: sqlite3.Connection, table: str, vid: int) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE visit_id = ?", (vid,)
    ).fetchone()[0]


def test_create_and_get_visit(conn: sqlite3.Connection, pid: str, fixed_today) -> None:
    vid = _visit(conn, pid)
    visit = get_visit(conn, vid)
    assert visit is not None
    assert visit["id"] == vid
    assert visit["patient_id"] == pid
    assert visit["reception_no"] == "A-023"
    assert visit["visit_date"] == VISIT_DAY
    assert visit["expires_at"] == EXPIRES
    assert visit["status"] == "generating"
    assert visit["fallback"] is False
    assert visit["course_no"] == 3
    assert visit["created_at"].date() == date(2026, 11, 9)
    raw = conn.execute("SELECT expires_at FROM visits WHERE id=?", (vid,)).fetchone()
    assert raw[0].endswith("+09:00")


def test_get_visit_unknown_is_none(conn: sqlite3.Connection) -> None:
    assert get_visit(conn, 42) is None


def test_create_visit_unknown_patient_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        _visit(conn, "P-NOPE0000")


@pytest.mark.parametrize("bad", ["", "   ", "A" * 33])
def test_create_visit_rejects_bad_reception_no(
    conn: sqlite3.Connection, pid: str, bad: str
) -> None:
    with pytest.raises(ValueError):
        _visit(conn, pid, no=bad)


def test_create_visit_allows_no_course(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid, course_no=None)
    assert get_visit(conn, vid)["course_no"] is None


def test_set_visit_status_and_fallback(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    set_visit_status(conn, vid, "failed", fallback=True)
    visit = get_visit(conn, vid)
    assert visit["status"] == "failed"
    assert visit["fallback"] is True
    set_visit_status(conn, vid, "ready")  # fallback=None は変えない
    assert get_visit(conn, vid)["fallback"] is True
    set_visit_status(conn, vid, "ready", fallback=False)
    assert get_visit(conn, vid)["fallback"] is False


def test_set_visit_status_rejects_unknown(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    with pytest.raises(ValueError):
        set_visit_status(conn, vid, "done")


def test_set_visit_status_unknown_visit_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        set_visit_status(conn, 42, "ready")


def test_list_visits_filters_status(conn: sqlite3.Connection, pid: str) -> None:
    a = _visit(conn, pid, no="A-001")
    b = _visit(conn, pid, no="A-002")
    c = _visit(conn, pid, no="A-003")
    set_visit_status(conn, b, "ready")
    set_visit_status(conn, c, "failed")
    assert [v["id"] for v in list_visits(conn)] == [a, b, c]
    assert [v["id"] for v in list_visits(conn, ("ready", "failed"))] == [b, c]
    assert [v["id"] for v in list_visits(conn, ("generating",))] == [a]
    assert list_visits(conn, ()) == []
    with pytest.raises(ValueError):
        list_visits(conn, ("ready", "nope"))


def test_timeline_round_trip_and_overwrite(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    assert get_timeline(conn, vid) is None
    save_timeline(conn, vid, _timeline())
    assert get_timeline(conn, vid) == _timeline()
    save_timeline(conn, vid, Timeline())
    assert get_timeline(conn, vid) == Timeline()


def test_report_round_trip_and_overwrite(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    assert get_report(conn, vid) is None
    save_report(conn, vid, "<html>1</html>", _report())
    assert get_report(conn, vid) == ("<html>1</html>", _report())
    save_report(conn, vid, "<html>2</html>", _report())
    html, data = get_report(conn, vid)
    assert html == "<html>2</html>"
    assert data == _report()


def test_save_results_unknown_visit_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        save_timeline(conn, 42, Timeline())
    with pytest.raises(NotFoundError):
        save_report(conn, 42, "<html></html>", _report())


def test_mark_printed_deletes_results_and_reception_no(
    conn: sqlite3.Connection, pid: str
) -> None:
    vid = _visit(conn, pid)
    keep = _visit(conn, pid, no="A-024")
    _with_results(conn, vid)
    _with_results(conn, keep)

    mark_printed(conn, vid)

    visit = get_visit(conn, vid)
    assert visit["status"] == "printed"
    assert visit["reception_no"] is None
    assert get_report(conn, vid) is None
    assert get_timeline(conn, vid) is None
    assert _count(conn, "reports", vid) == 0
    assert _count(conn, "timelines", vid) == 0
    # 他の受診には触れない
    assert get_visit(conn, keep)["reception_no"] == "A-024"
    assert get_report(conn, keep) is not None


def test_mark_printed_unknown_visit_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        mark_printed(conn, 42)


def test_purge_expired_boundary(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    _with_results(conn, vid)

    # 期限の1秒前は消さない
    assert purge_expired(conn, EXPIRES - timedelta(seconds=1)) == 0
    assert get_report(conn, vid) is not None
    assert get_visit(conn, vid)["reception_no"] == "A-023"

    # 期限ちょうどで消す（expires_at <= now）
    assert purge_expired(conn, EXPIRES) == 1
    visit = get_visit(conn, vid)
    assert visit["reception_no"] is None
    assert visit["status"] == "ready"  # printed にはしない
    assert get_report(conn, vid) is None
    assert get_timeline(conn, vid) is None

    # 2回目は何も消さない
    assert purge_expired(conn, EXPIRES + timedelta(seconds=1)) == 0


def test_purge_expired_compares_across_timezones(
    conn: sqlite3.Connection, pid: str
) -> None:
    vid = _visit(conn, pid)
    _with_results(conn, vid)
    utc_before = datetime.fromisoformat("2026-11-10T00:29:59+00:00")  # JST 9:29:59
    assert purge_expired(conn, utc_before) == 0
    utc_after = datetime.fromisoformat("2026-11-10T00:30:00.000001+00:00")
    assert purge_expired(conn, utc_after) == 1


def test_purge_expired_has_nothing_left_on_printed_and_keeps_failed_status(
    conn: sqlite3.Connection, pid: str
) -> None:
    printed = _visit(conn, pid, no="A-001")
    failed = _visit(conn, pid, no="A-002")
    fresh = _visit(conn, pid, no="A-003", expires_at=EXPIRES + timedelta(hours=1))
    _with_results(conn, printed)
    mark_printed(conn, printed)
    set_visit_status(conn, failed, "failed", fallback=True)
    _with_results(conn, fresh)

    assert purge_expired(conn, EXPIRES + timedelta(minutes=1)) == 1
    assert get_visit(conn, failed)["status"] == "failed"
    assert get_visit(conn, failed)["reception_no"] is None
    assert get_visit(conn, printed)["status"] == "printed"
    assert get_visit(conn, fresh)["reception_no"] == "A-003"
    assert get_report(conn, fresh) is not None


def test_purge_expired_naive_now_is_jst(conn: sqlite3.Connection, pid: str) -> None:
    _visit(conn, pid)
    assert purge_expired(conn, datetime(2026, 11, 10, 9, 29)) == 0
    assert purge_expired(conn, datetime(2026, 11, 10, 9, 30)) == 1


def test_create_visit_strips_reception_no(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid, no="  A-023 ")
    assert get_visit(conn, vid)["reception_no"] == "A-023"


def test_set_visit_status_rejects_printed(conn: sqlite3.Connection, pid: str) -> None:
    # printed にする経路は mark_printed だけ（結果と受付番号を必ず消すため）
    vid = _visit(conn, pid)
    _with_results(conn, vid)
    with pytest.raises(ValueError):
        set_visit_status(conn, vid, "printed")
    visit = get_visit(conn, vid)
    assert visit["status"] == "ready"
    assert visit["reception_no"] == "A-023"


def _force_printed_with_results(conn: sqlite3.Connection, vid: int) -> None:
    """どの経路で来たかによらず「printed なのに中身が残っている」状態を作る。"""
    _with_results(conn, vid)
    with conn:
        conn.execute("UPDATE visits SET status = 'printed' WHERE id = ?", (vid,))


def test_purge_expired_erases_printed_visit_with_leftovers(
    conn: sqlite3.Connection, pid: str
) -> None:
    vid = _visit(conn, pid)
    _force_printed_with_results(conn, vid)

    assert purge_expired(conn, EXPIRES + timedelta(days=365)) == 1
    visit = get_visit(conn, vid)
    assert visit["status"] == "printed"
    assert visit["reception_no"] is None
    assert get_report(conn, vid) is None
    assert get_timeline(conn, vid) is None
    # 冪等: 2回目は消す物が無い
    assert purge_expired(conn, EXPIRES + timedelta(days=366)) == 0


def test_purge_expired_keeps_printed_leftovers_until_expiry(
    conn: sqlite3.Connection, pid: str
) -> None:
    vid = _visit(conn, pid)
    _force_printed_with_results(conn, vid)
    assert purge_expired(conn, EXPIRES - timedelta(seconds=1)) == 0
    assert get_report(conn, vid) is not None


def _assert_closed_and_empty(conn: sqlite3.Connection, vid: int) -> None:
    with pytest.raises(VisitClosedError):
        save_timeline(conn, vid, _timeline())
    with pytest.raises(VisitClosedError):
        save_report(conn, vid, "<html>late</html>", _report())
    assert get_timeline(conn, vid) is None
    assert get_report(conn, vid) is None
    assert get_visit(conn, vid)["reception_no"] is None
    assert _count(conn, "reports", vid) == 0
    assert _count(conn, "timelines", vid) == 0


def test_save_after_mark_printed_is_rejected(
    conn: sqlite3.Connection, pid: str
) -> None:
    # 生成が印刷済み操作より遅れて終わっても、中身は戻らない
    vid = _visit(conn, pid)
    mark_printed(conn, vid)
    _assert_closed_and_empty(conn, vid)
    assert get_visit(conn, vid)["status"] == "printed"


def test_save_after_purge_is_rejected(conn: sqlite3.Connection, pid: str) -> None:
    vid = _visit(conn, pid)
    assert purge_expired(conn, EXPIRES) == 1
    _assert_closed_and_empty(conn, vid)


def test_visit_closed_error_is_value_error() -> None:
    assert issubclass(VisitClosedError, ValueError)


def test_list_visits_active_only_hides_closed_visits(
    conn: sqlite3.Connection, pid: str
) -> None:
    expired = _visit(conn, pid, no="A-001")
    printed = _visit(conn, pid, no="A-002")
    active = _visit(conn, pid, no="A-003", expires_at=EXPIRES + timedelta(hours=1))
    for vid in (expired, printed, active):
        _with_results(conn, vid)
    mark_printed(conn, printed)
    assert purge_expired(conn, EXPIRES) == 1

    # 期限切れでも status は ready のまま。active_only なしでは出る
    assert [v["id"] for v in list_visits(conn, ("ready",))] == [expired, active]
    assert [v["id"] for v in list_visits(conn, ("ready",), active_only=True)] == [
        active
    ]
    assert [v["id"] for v in list_visits(conn, active_only=True)] == [active]
    assert list_visits(conn, (), active_only=True) == []


def test_set_visit_status_does_not_reopen_printed_visit(
    conn: sqlite3.Connection, pid: str, tmp_db_path: Path
) -> None:
    # 生成が終わる前に別の接続で印刷済みにされても、ready に戻さない
    vid = _visit(conn, pid)
    other = connect(tmp_db_path)
    try:
        mark_printed(other, vid)
    finally:
        other.close()
    with pytest.raises(VisitClosedError):
        set_visit_status(conn, vid, "ready", fallback=False)
    assert get_visit(conn, vid)["status"] == "printed"


# ---------------------------------------------------------------------------
# 期限切れ（expires_at を過ぎた）が、まだ purge_expired されていない受診
# ---------------------------------------------------------------------------


def _assert_untouched(conn: sqlite3.Connection, vid: int, status: str) -> None:
    visit = get_visit(conn, vid)
    assert visit["reception_no"] == "A-023"  # purge はしない（拒否するだけ）
    assert (visit["status"], visit["fallback"]) == (status, False)
    assert _count(conn, "timelines", vid) == 0
    assert _count(conn, "reports", vid) == 0
    assert conn.in_transaction is False


@pytest.mark.parametrize(
    "write",
    [
        lambda c, v: save_timeline(c, v, _timeline()),
        lambda c, v: save_report(c, v, "<html>late</html>", _report()),
        lambda c, v: set_visit_status(c, v, "ready", fallback=True),
        lambda c, v: set_visit_status(c, v, "failed"),
    ],
    ids=["save_timeline", "save_report", "set_ready", "set_failed"],
)
def test_expired_but_not_purged_is_rejected(
    conn: sqlite3.Connection, pid: str, write
) -> None:
    vid = _visit(conn, pid, expires_at=PAST)
    with pytest.raises(VisitClosedError):
        write(conn, vid)
    _assert_untouched(conn, vid, "generating")


def test_expired_but_not_purged_keeps_old_results(
    conn: sqlite3.Connection, pid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = _visit(conn, pid)
    save_timeline(conn, vid, _timeline())
    save_report(conn, vid, "<html>first</html>", _report())
    set_visit_status(conn, vid, "ready")
    monkeypatch.setattr("tsutae.db.repo_visits.clock_now", lambda: EXPIRES)
    with pytest.raises(VisitClosedError):
        save_report(conn, vid, "<html>late</html>", _report())
    with pytest.raises(VisitClosedError):
        set_visit_status(conn, vid, "failed")
    assert get_report(conn, vid)[0] == "<html>first</html>"  # 上書きしない
    assert get_visit(conn, vid)["status"] == "ready"


@pytest.mark.parametrize(
    ("now", "accepted"),
    [
        (EXPIRES - timedelta(microseconds=1), True),
        (EXPIRES, False),  # purge_expired と同じく、期限ちょうどで閉じる
        (EXPIRES.astimezone(UTC), False),  # 別のタイムゾーンでも同じ瞬間
        (datetime(2026, 11, 10, 9, 29, 59), True),  # naive は JST とみなす
    ],
)
def test_expiry_boundary_for_saves(
    conn: sqlite3.Connection,
    pid: str,
    monkeypatch: pytest.MonkeyPatch,
    now: datetime,
    accepted: bool,
) -> None:
    vid = _visit(conn, pid)
    monkeypatch.setattr("tsutae.db.repo_visits.clock_now", lambda: now)
    if accepted:
        save_timeline(conn, vid, _timeline())
        set_visit_status(conn, vid, "ready")
        assert get_visit(conn, vid)["status"] == "ready"
        return
    with pytest.raises(VisitClosedError):
        save_timeline(conn, vid, _timeline())
    with pytest.raises(VisitClosedError):
        set_visit_status(conn, vid, "ready")
    _assert_untouched(conn, vid, "generating")
