"""通知の登録（push_subscriptions。plan-device-records §4.3・§4.4）。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime
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
