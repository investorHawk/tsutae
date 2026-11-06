"""受付の後に記録が増えた受診（plan-device-records §6）の DB の動き。症例は全て合成。

- 同じ番号の受診に新しい記録が届くと、generating は regen_pending を立て、ready・failed は
  すぐ generating に戻す（記録の保存と同じトランザクション）
- 自動は1受診3回まで。超えたら regen_pending（追加の記録あり）だけが立つ
- その患者に今日の印刷済みの受診があれば、番号を問わず断り、何も保存しない
- 生成の終わりに待っている分があれば ready を見せずに generating のまま次へ回す
- 競合: 追加が重なる・印刷と追加。別の接続とスレッドで確かめる
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_db_visits import _report, _timeline

from tsutae import db
from tsutae.config import now
from tsutae.db.connection import SCHEMA_PATH
from tsutae.db.repo_visit_regen import REGEN_AUTO_MAX
from tsutae.schemas import ClosedAnswer, EntryCreate

PID = "P-AAAAAAAA"
OTHER = "P-BBBBBBBB"
DAY = date(2026, 11, 9)
UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
UUID_C = "33333333-3333-4333-8333-333333333333"
SKILL = "regimen-folfox@1"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "regen.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(db_path)
    db.init_db(connection)
    db.create_patient(connection, "FOLFOX", patient_id=PID)
    db.create_patient(connection, "FOLFOX", patient_id=OTHER)
    yield connection
    connection.close()


def _received(client_id: str = UUID_A) -> db.ReceivedEntry:
    answer = ClosedAnswer(question_key="diarrhea", value="none")
    return db.ReceivedEntry(
        client_entry_id=client_id,
        entry=EntryCreate(answers=[answer]),
        recorded_at=datetime.fromisoformat("2026-11-09T09:00:00+09:00"),
        skill_version=SKILL,
    )


def _send(
    conn: sqlite3.Connection,
    *ids: str,
    pid: str = PID,
    reception_no: str = "A-023",
    day: date = DAY,
) -> db.VisitReceipt:
    expires = now() + timedelta(hours=24)
    entries = tuple(_received(i) for i in ids)
    return db.create_visit_once(conn, pid, reception_no, day, expires, 1, entries)


def _state(conn: sqlite3.Connection, vid: int) -> tuple[str, bool, int]:
    visit = db.get_visit(conn, vid)
    assert visit is not None
    return visit["status"], visit["regen_pending"], visit["regen_count"]


def _client_ids(conn: sqlite3.Connection, pid: str = PID) -> list[str]:
    rows = conn.execute(
        "SELECT client_entry_id FROM entries WHERE patient_id = ?"
        " AND client_entry_id IS NOT NULL ORDER BY client_entry_id",
        (pid,),
    ).fetchall()
    return [r["client_entry_id"] for r in rows]


def _save_result(conn: sqlite3.Connection, vid: int, fallback: bool = False) -> None:
    db.save_visit_result(
        conn,
        vid,
        timeline=_timeline(),
        html="<p>結果</p>",
        data=_report(),
        status="ready",
        fallback=fallback,
    )


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """保存は「今」と expires_at を比べるので、今日を受診日に固定する。"""
    monkeypatch.setenv("TSUTAE_TODAY", DAY.isoformat())


# ---------------------------------------------------------------------------
# 列と移行
# ---------------------------------------------------------------------------


def test_new_visit_has_no_pending(conn: sqlite3.Connection) -> None:
    receipt = _send(conn, UUID_A)
    assert (receipt.created, receipt.regenerate) == (True, False)
    assert _state(conn, receipt.visit_id) == ("generating", False, 0)


OLD_VISITS_COLUMNS = (
    "    course_no INTEGER,\n"
    "    regen_pending INTEGER NOT NULL DEFAULT 0 CHECK (regen_pending IN (0, 1)),\n"
    "    regen_count INTEGER NOT NULL DEFAULT 0 CHECK (regen_count >= 0)\n"
)


def test_old_visits_table_is_migrated_and_keeps_rows(db_path: Path) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    assert OLD_VISITS_COLUMNS in schema
    old = schema.replace(OLD_VISITS_COLUMNS, "    course_no INTEGER\n")
    ts = "2026-11-09T09:00:00.000000+09:00"
    connection = db.connect(db_path)
    connection.executescript(old)
    connection.execute(
        "INSERT INTO patients (id, regimen, created_at) VALUES (?, 'FOLFOX', ?)",
        (PID, ts),
    )
    connection.execute(
        "INSERT INTO visits (id, patient_id, reception_no, visit_date, created_at,"
        " status, expires_at, fallback, course_no)"
        " VALUES (7, ?, 'A-023', '2026-11-09', ?, 'ready', ?, 1, 3)",
        (PID, ts, "2026-11-10T09:00:00.000000+09:00"),
    )
    connection.execute(
        "INSERT INTO reports (visit_id, html, data_json) VALUES (7, '<p></p>', '{}')"
    )
    connection.commit()
    try:
        db.init_db(connection)
        db.init_db(connection)  # 何度呼んでもよい
        visit = db.get_visit(connection, 7)
        assert visit is not None
        assert (visit["status"], visit["fallback"], visit["course_no"]) == (
            "ready",
            True,
            3,
        )
        assert (visit["regen_pending"], visit["regen_count"]) == (False, 0)
        assert connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 1
        index = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'idx_visits_status_expires'"
        ).fetchone()
        assert index is not None
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# 受け取り
# ---------------------------------------------------------------------------


def test_new_record_while_generating_sets_pending_only(
    conn: sqlite3.Connection,
) -> None:
    vid = _send(conn, UUID_A).visit_id
    receipt = _send(conn, UUID_A, UUID_B)
    assert (receipt.visit_id, receipt.created, receipt.regenerate) == (
        vid,
        False,
        False,
    )
    assert _state(conn, vid) == ("generating", True, 0)
    assert _client_ids(conn) == [UUID_A, UUID_B]


def test_same_records_change_nothing(conn: sqlite3.Connection) -> None:
    vid = _send(conn, UUID_A).visit_id
    _save_result(conn, vid)
    receipt = _send(conn, UUID_A)
    assert (receipt.created, receipt.regenerate) == (False, False)
    assert _state(conn, vid) == ("ready", False, 0)


def test_no_records_change_nothing(conn: sqlite3.Connection) -> None:
    vid = _send(conn, UUID_A).visit_id
    db.set_visit_status(conn, vid, "failed")
    receipt = _send(conn)
    assert receipt.regenerate is False
    assert _state(conn, vid) == ("failed", False, 0)


@pytest.mark.parametrize("status", ["ready", "failed"])
def test_new_record_on_a_finished_visit_starts_again(
    conn: sqlite3.Connection, status: str
) -> None:
    vid = _send(conn, UUID_A).visit_id
    if status == "ready":
        _save_result(conn, vid, fallback=True)
    else:
        db.set_visit_status(conn, vid, "failed")
    receipt = _send(conn, UUID_A, UUID_B)
    assert (receipt.created, receipt.regenerate) == (False, True)
    assert _state(conn, vid) == ("generating", False, 1)
    assert db.get_visit(conn, vid)["fallback"] is False


def test_previous_report_stays_until_replaced(conn: sqlite3.Connection) -> None:
    vid = _send(conn, UUID_A).visit_id
    _save_result(conn, vid)
    assert _send(conn, UUID_B).regenerate is True
    saved = db.get_report(conn, vid)
    assert saved is not None
    assert saved[0] == "<p>結果</p>"


def test_other_number_is_a_new_visit_and_does_not_touch_the_first(
    conn: sqlite3.Connection,
) -> None:
    first = _send(conn, UUID_A).visit_id
    _save_result(conn, first)
    receipt = _send(conn, UUID_B, reception_no="A-999")
    assert (receipt.created, receipt.regenerate) == (True, False)
    assert receipt.visit_id != first
    assert _state(conn, first) == ("ready", False, 0)


def test_limit_of_automatic_runs(conn: sqlite3.Connection) -> None:
    assert REGEN_AUTO_MAX == 3
    vid = _send(conn, UUID_A).visit_id
    for n in range(REGEN_AUTO_MAX):
        _save_result(conn, vid)
        receipt = _send(conn, f"a{n}111111-1111-4111-8111-111111111111")
        assert receipt.regenerate is True
        assert _state(conn, vid) == ("generating", False, n + 1)
    _save_result(conn, vid)
    assert _state(conn, vid) == ("ready", False, REGEN_AUTO_MAX)
    receipt = _send(conn, UUID_B)
    assert (receipt.created, receipt.regenerate) == (False, False)
    assert _state(conn, vid) == ("ready", True, REGEN_AUTO_MAX)
    assert UUID_B in _client_ids(conn)


def test_failed_at_the_limit_stays_failed_with_pending(
    conn: sqlite3.Connection,
) -> None:
    vid = _send(conn, UUID_A).visit_id
    for n in range(REGEN_AUTO_MAX):
        db.set_visit_status(conn, vid, "failed")
        assert _send(conn, f"a{n}111111-1111-4111-8111-111111111111").regenerate
    db.set_visit_status(conn, vid, "failed")
    assert _send(conn, UUID_B).regenerate is False
    assert _state(conn, vid) == ("failed", True, REGEN_AUTO_MAX)


# ---------------------------------------------------------------------------
# 印刷済みの断り
# ---------------------------------------------------------------------------


def test_printed_today_refuses_every_number_and_saves_nothing(
    conn: sqlite3.Connection,
) -> None:
    vid = _send(conn, UUID_A).visit_id
    _save_result(conn, vid)
    assert db.mark_printed(conn, vid)
    assert _client_ids(conn) == []
    visits = len(db.list_visits(conn))
    for number in ("A-023", "A-999"):
        with pytest.raises(db.VisitAlreadyPrintedError):
            _send(conn, UUID_B, reception_no=number)
    assert _client_ids(conn) == []
    assert len(db.list_visits(conn)) == visits
    assert not conn.in_transaction


def test_printed_on_another_day_is_not_refused(conn: sqlite3.Connection) -> None:
    vid = _send(conn, UUID_A, day=DAY - timedelta(days=1)).visit_id
    _save_result(conn, vid)
    assert db.mark_printed(conn, vid)
    receipt = _send(conn, UUID_B)
    assert receipt.created is True


def test_printed_of_another_patient_is_not_refused(conn: sqlite3.Connection) -> None:
    vid = _send(conn, UUID_A, pid=OTHER).visit_id
    _save_result(conn, vid)
    assert db.mark_printed(conn, vid)
    assert _send(conn, UUID_B).created is True


def test_expired_visit_is_not_printed(conn: sqlite3.Connection) -> None:
    """期限切れは印刷済みではないので断らない（新しい受診になる）。"""
    expired = db.create_visit(conn, PID, "A-023", DAY, now() - timedelta(minutes=1), 1)
    db.purge_expired(conn, now())
    receipt = _send(conn, UUID_B)
    assert receipt.created is True
    assert receipt.visit_id != expired


# ---------------------------------------------------------------------------
# 生成の終わり
# ---------------------------------------------------------------------------


def test_finish_with_pending_stays_generating_and_keeps_the_result(
    conn: sqlite3.Connection,
) -> None:
    """ready を見せない（印刷が前のレポートで割り込めない）。結果は保存する。"""
    vid = _send(conn, UUID_A).visit_id
    _send(conn, UUID_B)
    _save_result(conn, vid)
    assert _state(conn, vid) == ("generating", True, 0)
    assert db.get_report(conn, vid) is not None
    assert db.mark_printed(conn, vid, refuse_generating=True) is False
    assert db.take_regen_pending(conn, vid) is True
    assert _state(conn, vid) == ("generating", False, 1)
    _save_result(conn, vid)
    assert _state(conn, vid) == ("ready", False, 1)
    assert db.take_regen_pending(conn, vid) is False


def test_finish_with_pending_at_the_limit_becomes_ready(
    conn: sqlite3.Connection,
) -> None:
    vid = _send(conn, UUID_A).visit_id
    for n in range(REGEN_AUTO_MAX):
        _save_result(conn, vid)
        _send(conn, f"a{n}111111-1111-4111-8111-111111111111")
    _send(conn, UUID_B)  # 3回目の変換の最中に届いた
    assert _state(conn, vid) == ("generating", True, REGEN_AUTO_MAX)
    _save_result(conn, vid)
    assert _state(conn, vid) == ("ready", True, REGEN_AUTO_MAX)
    assert db.take_regen_pending(conn, vid) is False
    assert _state(conn, vid) == ("ready", True, REGEN_AUTO_MAX)


def test_failed_with_pending_can_be_taken(conn: sqlite3.Connection) -> None:
    vid = _send(conn, UUID_A).visit_id
    _send(conn, UUID_B)
    db.set_visit_status(conn, vid, "failed")
    assert db.take_regen_pending(conn, vid) is True
    assert _state(conn, vid) == ("generating", False, 1)


def test_take_does_nothing_without_pending(conn: sqlite3.Connection) -> None:
    vid = _send(conn, UUID_A).visit_id
    assert db.take_regen_pending(conn, vid) is False
    assert _state(conn, vid) == ("generating", False, 0)


def test_take_does_not_reopen_a_printed_visit(conn: sqlite3.Connection) -> None:
    vid = _send(conn, UUID_A).visit_id
    _send(conn, UUID_B)
    assert db.mark_printed(conn, vid)
    assert db.take_regen_pending(conn, vid) is False
    assert db.get_visit(conn, vid)["status"] == "printed"


def test_take_does_not_reopen_an_expired_visit(conn: sqlite3.Connection) -> None:
    vid = _send(conn, UUID_A).visit_id
    _send(conn, UUID_B)
    past = (now() - timedelta(minutes=1)).isoformat(timespec="microseconds")
    with conn:
        conn.execute("UPDATE visits SET expires_at = ? WHERE id = ?", (past, vid))
    assert db.take_regen_pending(conn, vid) is False


# ---------------------------------------------------------------------------
# 医師の「AI でもう一度変換」
# ---------------------------------------------------------------------------


def test_doctor_can_regenerate_ai_ready_only_when_records_were_added(
    conn: sqlite3.Connection,
) -> None:
    vid = _send(conn, UUID_A).visit_id
    _save_result(conn, vid)
    assert db.begin_regeneration(conn, vid) is False
    for n in range(REGEN_AUTO_MAX):
        _send(conn, f"a{n}111111-1111-4111-8111-111111111111")
        _save_result(conn, vid)
    _send(conn, UUID_B)
    assert _state(conn, vid) == ("ready", True, REGEN_AUTO_MAX)
    assert db.begin_regeneration(conn, vid) is True
    # 医師が押した分は自動の回数に数えない。全ての記録で変換するので印も下ろす
    assert _state(conn, vid) == ("generating", False, REGEN_AUTO_MAX)
    _save_result(conn, vid)
    assert _state(conn, vid) == ("ready", False, REGEN_AUTO_MAX)
    assert db.begin_regeneration(conn, vid) is False


# ---------------------------------------------------------------------------
# 競合（別の接続・別のスレッド）
# ---------------------------------------------------------------------------


def _race(db_path: Path, *jobs: Callable[[sqlite3.Connection], Any]) -> list[Any]:
    """jobs を別の接続・別のスレッドで同時に始める。戻り値か例外を順に返す。"""
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)

    def run(i: int, job: Callable[[sqlite3.Connection], Any]) -> None:
        connection = db.connect(db_path)
        try:
            barrier.wait(timeout=5)
            results[i] = job(connection)
        except Exception as exc:  # noqa: BLE001 — 例外も結果として比べる
            results[i] = exc
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=(i, job)) for i, job in enumerate(jobs)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    return results


@pytest.mark.parametrize("round_no", range(5))
def test_overlapping_additions_on_ready_start_only_one_run(
    conn: sqlite3.Connection, db_path: Path, round_no: int
) -> None:
    vid = _send(conn, UUID_A).visit_id
    _save_result(conn, vid)
    first, second = _race(
        db_path,
        lambda c: _send(c, UUID_B),
        lambda c: _send(c, UUID_C),
    )
    assert sorted([first.regenerate, second.regenerate]) == [False, True]
    assert _state(conn, vid) == ("generating", True, 1)
    assert _client_ids(conn) == [UUID_A, UUID_B, UUID_C]


@pytest.mark.parametrize("round_no", range(5))
def test_overlapping_same_record_is_saved_once(
    conn: sqlite3.Connection, db_path: Path, round_no: int
) -> None:
    vid = _send(conn, UUID_A).visit_id
    _save_result(conn, vid)
    first, second = _race(
        db_path,
        lambda c: _send(c, UUID_B),
        lambda c: _send(c, UUID_B),
    )
    assert sorted([first.regenerate, second.regenerate]) == [False, True]
    assert _state(conn, vid) == ("generating", False, 1)
    assert _client_ids(conn) == [UUID_A, UUID_B]


@pytest.mark.parametrize("round_no", range(10))
def test_print_and_addition_never_lose_an_accepted_record(
    conn: sqlite3.Connection, db_path: Path, round_no: int
) -> None:
    """どちらが先でも、受け取った（200 の）記録を前のレポートの印刷で消さない。"""
    vid = _send(conn, UUID_A).visit_id
    _save_result(conn, vid)
    printed, added = _race(
        db_path,
        lambda c: db.mark_printed(c, vid, refuse_generating=True),
        lambda c: _send(c, UUID_B),
    )
    status, _pending, _count = _state(conn, vid)
    if printed is True:
        assert isinstance(added, db.VisitAlreadyPrintedError)
        assert status == "printed"
        assert _client_ids(conn) == []
    else:
        assert printed is False
        assert added.regenerate is True
        assert status == "generating"
        assert _client_ids(conn) == [UUID_A, UUID_B]
