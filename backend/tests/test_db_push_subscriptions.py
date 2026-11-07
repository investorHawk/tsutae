"""通知の登録（push_subscriptions。plan-device-records §4.3・§4.4）。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from tsutae import db
from tsutae.config import JST

PID = "P-PUSH0001"
OTHER = "P-PUSH0002"
ENDPOINT = "https://web.push.apple.com/device-a"
SECOND = "https://web.push.apple.com/device-b"
AT = datetime(2026, 11, 9, 9, 0, 0, tzinfo=JST)
DAY = date(2026, 11, 9)


@pytest.fixture
def conn(tmp_db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_db_path)
    db.init_db(connection)
    db.create_patient(connection, "FOLFOX", patient_id=PID)
    db.create_patient(connection, "CAPOX", patient_id=OTHER)
    yield connection
    connection.close()


def _save(
    conn: sqlite3.Connection,
    pid: str = PID,
    endpoint: str = ENDPOINT,
    notify_time: str = "20:00",
) -> db.PushSubscription:
    return db.upsert_push_subscription(
        conn,
        pid,
        endpoint=endpoint,
        p256dh="key",
        auth="secret",
        notify_time=notify_time,
        created_at=AT,
    )


def test_save_returns_the_row(conn: sqlite3.Connection) -> None:
    saved = _save(conn)
    assert saved == db.PushSubscription(
        id=saved.id,
        patient_id=PID,
        endpoint=ENDPOINT,
        p256dh="key",
        auth="secret",
        notify_time="20:00",
        last_sent_date=None,
    )
    assert db.list_push_subscriptions(conn) == [saved]


def test_same_endpoint_changes_the_time_and_keeps_the_row(
    conn: sqlite3.Connection,
) -> None:
    first = _save(conn)
    assert db.claim_push_send(conn, first.id, DAY)
    changed = _save(conn, notify_time="07:30")
    assert changed.id == first.id
    assert changed.notify_time == "07:30"
    assert changed.last_sent_date == DAY  # 時刻を変えても1日1回まで
    assert len(db.list_push_subscriptions(conn)) == 1


def test_endpoint_moved_to_another_patient_starts_fresh(
    conn: sqlite3.Connection,
) -> None:
    first = _save(conn)
    assert db.claim_push_send(conn, first.id, DAY)
    moved = _save(conn, pid=OTHER)
    assert moved.id == first.id
    assert moved.patient_id == OTHER
    assert moved.last_sent_date is None


def test_unknown_patient_is_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(db.NotFoundError):
        _save(conn, pid="P-NOPE0000")


def test_get_is_for_the_owner_only(conn: sqlite3.Connection) -> None:
    saved = _save(conn)
    assert db.get_push_subscription(conn, PID, ENDPOINT) == saved
    assert db.get_push_subscription(conn, OTHER, ENDPOINT) is None
    assert db.get_push_subscription(conn, PID, SECOND) is None


def test_delete_is_for_the_owner_only(conn: sqlite3.Connection) -> None:
    _save(conn)
    assert db.delete_push_subscription(conn, OTHER, ENDPOINT) is False
    assert len(db.list_push_subscriptions(conn)) == 1
    assert db.delete_push_subscription(conn, PID, ENDPOINT) is True
    assert db.list_push_subscriptions(conn) == []
    assert db.delete_push_subscription(conn, PID, ENDPOINT) is False


def test_get_and_delete_by_id(conn: sqlite3.Connection) -> None:
    saved = _save(conn)
    assert db.get_push_subscription_by_id(conn, saved.id) == saved
    db.delete_push_subscription_by_id(conn, saved.id)
    assert db.get_push_subscription_by_id(conn, saved.id) is None


def test_claim_is_once_a_day(conn: sqlite3.Connection) -> None:
    saved = _save(conn)
    assert db.claim_push_send(conn, saved.id, DAY) is True
    assert db.claim_push_send(conn, saved.id, DAY) is False
    assert db.claim_push_send(conn, saved.id, date(2026, 11, 10)) is True


def test_release_puts_back_the_previous_date(conn: sqlite3.Connection) -> None:
    saved = _save(conn)
    yesterday = date(2026, 11, 8)
    assert db.claim_push_send(conn, saved.id, yesterday)
    assert db.claim_push_send(conn, saved.id, DAY)
    db.release_push_send(conn, saved.id, DAY, yesterday)
    assert db.get_push_subscription_by_id(conn, saved.id).last_sent_date == yesterday
    assert db.claim_push_send(conn, saved.id, DAY) is True


def test_release_does_not_touch_another_day(conn: sqlite3.Connection) -> None:
    saved = _save(conn)
    assert db.claim_push_send(conn, saved.id, DAY)
    db.release_push_send(conn, saved.id, date(2026, 11, 8), None)
    assert db.get_push_subscription_by_id(conn, saved.id).last_sent_date == DAY


# ---------------------------------------------------------------------------
# オフにしてからオンにしても1日1回まで（§4.1）
# ---------------------------------------------------------------------------


def test_off_then_on_keeps_the_day_already_sent(conn: sqlite3.Connection) -> None:
    """オンにし直すと endpoint が変わり新しい行になるが、送った日は引き継ぐ。"""
    saved = _save(conn)
    assert db.claim_push_send(conn, saved.id, DAY)
    assert db.delete_push_subscription(conn, PID, ENDPOINT)
    again = _save(conn, endpoint=SECOND)
    assert again.last_sent_date == DAY
    assert db.claim_push_send(conn, again.id, DAY) is False
    assert db.claim_push_send(conn, again.id, date(2026, 11, 10)) is True


def test_off_then_on_without_a_send_starts_empty(conn: sqlite3.Connection) -> None:
    _save(conn)
    db.delete_push_subscription(conn, PID, ENDPOINT)
    assert _save(conn, endpoint=SECOND).last_sent_date is None


def test_delete_by_id_also_keeps_the_day_sent(conn: sqlite3.Connection) -> None:
    saved = _save(conn)
    assert db.claim_push_send(conn, saved.id, DAY)
    db.delete_push_subscription_by_id(conn, saved.id)
    assert _save(conn, endpoint=SECOND).last_sent_date == DAY


def test_kept_day_is_per_patient(conn: sqlite3.Connection) -> None:
    saved = _save(conn)
    assert db.claim_push_send(conn, saved.id, DAY)
    db.delete_push_subscription(conn, PID, ENDPOINT)
    assert _save(conn, pid=OTHER, endpoint=SECOND).last_sent_date is None


def test_refused_delete_keeps_nothing(conn: sqlite3.Connection) -> None:
    saved = _save(conn)
    assert db.claim_push_send(conn, saved.id, DAY)
    assert db.delete_push_subscription(conn, OTHER, ENDPOINT) is False
    assert _save(conn, pid=OTHER, endpoint=SECOND).last_sent_date is None


def test_kept_day_only_moves_forward(conn: sqlite3.Connection) -> None:
    new = _save(conn)
    assert db.claim_push_send(conn, new.id, DAY)
    db.delete_push_subscription(conn, PID, ENDPOINT)
    old = _save(conn, endpoint=SECOND)
    db.release_push_send(conn, old.id, DAY, date(2026, 11, 8))
    db.delete_push_subscription(conn, PID, SECOND)
    assert _save(conn, endpoint=ENDPOINT).last_sent_date == DAY


def test_second_device_still_on_keeps_its_own_day(conn: sqlite3.Connection) -> None:
    """もう1台の登録の送り直しは、自分の送信日を保つ（端末ごとの時刻で届く）。"""
    first = _save(conn)
    second = _save(conn, endpoint=SECOND, notify_time="21:00")
    assert db.claim_push_send(conn, first.id, DAY)
    db.delete_push_subscription(conn, PID, ENDPOINT)
    resent = _save(conn, endpoint=SECOND, notify_time="21:00")
    assert resent.id == second.id
    assert resent.last_sent_date is None


def test_moving_a_device_to_another_patient_uses_that_patients_day(
    conn: sqlite3.Connection,
) -> None:
    other = _save(conn, pid=OTHER, endpoint=SECOND)
    assert db.claim_push_send(conn, other.id, DAY)
    db.delete_push_subscription(conn, OTHER, SECOND)
    saved = _save(conn)
    assert db.claim_push_send(conn, saved.id, date(2026, 11, 8))
    assert _save(conn, pid=OTHER).last_sent_date == DAY


# ---------------------------------------------------------------------------
# 送信先に消された endpoint
# ---------------------------------------------------------------------------


def test_gone_endpoint_is_remembered(conn: sqlite3.Connection) -> None:
    assert db.is_push_endpoint_gone(conn, ENDPOINT) is False
    db.mark_push_endpoint_gone(conn, ENDPOINT, AT)
    assert db.is_push_endpoint_gone(conn, ENDPOINT) is True
    assert db.is_push_endpoint_gone(conn, SECOND) is False


def test_marking_again_is_fine(conn: sqlite3.Connection) -> None:
    db.mark_push_endpoint_gone(conn, ENDPOINT, AT)
    db.mark_push_endpoint_gone(conn, ENDPOINT, AT + timedelta(days=1))
    assert db.is_push_endpoint_gone(conn, ENDPOINT) is True


def test_old_gone_endpoints_are_forgotten(conn: sqlite3.Connection) -> None:
    """30 日で忘れる。忘れた後に送り直されても、次の送信でまた覚える。"""
    db.mark_push_endpoint_gone(conn, ENDPOINT, AT)
    db.mark_push_endpoint_gone(conn, SECOND, AT + timedelta(days=29, hours=23))
    assert db.is_push_endpoint_gone(conn, ENDPOINT) is True
    db.mark_push_endpoint_gone(conn, SECOND, AT + timedelta(days=31))
    assert db.is_push_endpoint_gone(conn, ENDPOINT) is False
    assert db.is_push_endpoint_gone(conn, SECOND) is True


# ---------------------------------------------------------------------------
# 患者ごとの登録の上限（超えたら古い行から消す）
# ---------------------------------------------------------------------------


def _endpoint(n: int) -> str:
    return f"https://web.push.apple.com/device-{n}"


def _endpoints(conn: sqlite3.Connection, pid: str = PID) -> list[str]:
    return [s.endpoint for s in db.list_push_subscriptions(conn) if s.patient_id == pid]


def test_rows_per_patient_are_capped_and_the_oldest_goes(
    conn: sqlite3.Connection,
) -> None:
    limit = db.MAX_PUSH_SUBSCRIPTIONS_PER_PATIENT
    for n in range(limit + 3):
        _save(conn, endpoint=_endpoint(n))
    assert _endpoints(conn) == [_endpoint(n) for n in range(3, limit + 3)]


def test_cap_is_per_patient(conn: sqlite3.Connection) -> None:
    limit = db.MAX_PUSH_SUBSCRIPTIONS_PER_PATIENT
    _save(conn, pid=OTHER, endpoint=ENDPOINT)
    for n in range(limit + 1):
        _save(conn, endpoint=_endpoint(n))
    assert _endpoints(conn, OTHER) == [ENDPOINT]


def test_saving_again_at_the_cap_removes_nothing(conn: sqlite3.Connection) -> None:
    limit = db.MAX_PUSH_SUBSCRIPTIONS_PER_PATIENT
    for n in range(limit):
        _save(conn, endpoint=_endpoint(n))
    _save(conn, endpoint=_endpoint(0), notify_time="21:00")
    assert _endpoints(conn) == [_endpoint(n) for n in range(limit)]


def test_row_moved_from_another_patient_is_kept_at_the_cap(
    conn: sqlite3.Connection,
) -> None:
    """移ってきた行は id が古くても、今登録した端末なので消さない。"""
    limit = db.MAX_PUSH_SUBSCRIPTIONS_PER_PATIENT
    _save(conn, pid=OTHER, endpoint=ENDPOINT)
    for n in range(limit):
        _save(conn, endpoint=_endpoint(n))
    _save(conn, endpoint=ENDPOINT)
    remaining = _endpoints(conn)
    assert len(remaining) == limit
    assert ENDPOINT in remaining
    assert _endpoint(0) not in remaining


def test_removed_by_the_cap_keeps_the_one_a_day_rule(conn: sqlite3.Connection) -> None:
    """古い行の送信日は残り、新しい行が引き継ぐ（消されても同じ日に2通目を送らない）。"""
    limit = db.MAX_PUSH_SUBSCRIPTIONS_PER_PATIENT
    oldest = _save(conn, endpoint=_endpoint(0))
    assert db.claim_push_send(conn, oldest.id, DAY)
    for n in range(1, limit + 1):
        _save(conn, endpoint=_endpoint(n))
    assert _endpoint(0) not in _endpoints(conn)
    assert _save(conn, endpoint=_endpoint(99)).last_sent_date == DAY
