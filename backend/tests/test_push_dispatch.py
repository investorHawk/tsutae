"""対象を探して送る1回分（`send_due_once`・`send_test_once`。送信は偽物）。"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_helpers import FakePushSender, make_settings
from push_helpers import ENDPOINT, RFC8291_AUTH, RFC8291_P256DH, SECOND_ENDPOINT

from tsutae import db
from tsutae.config import JST, Settings
from tsutae.push.dispatch import PushCounts, send_due_once, send_test_once
from tsutae.push.sender import PushSendError
from tsutae.schemas import Course, EntryCreate

PID = "P-DISP0001"
OTHER = "P-DISP0002"
BROKEN = "P-DISP0003"
DAY1 = date(2026, 11, 1)  # FOLFOX は 14 日。送る期間は 11/29 まで
AT = datetime(2026, 11, 9, 20, 5, 0, tzinfo=JST)
SKILL = "regimen-folfox@1"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def conn(settings: Settings) -> Iterator[sqlite3.Connection]:
    connection = db.connect(settings.db_path)
    db.init_db(connection)
    db.create_patient(connection, "FOLFOX", patient_id=PID)
    db.create_patient(connection, "CAPOX", patient_id=OTHER)
    db.upsert_course(
        connection, Course(patient_id=PID, course_no=1, infusion_date=DAY1)
    )
    db.upsert_course(
        connection, Course(patient_id=OTHER, course_no=1, infusion_date=DAY1)
    )
    yield connection
    connection.close()


def _subscribe(
    conn: sqlite3.Connection,
    pid: str = PID,
    endpoint: str = ENDPOINT,
    notify_time: str = "20:00",
) -> db.PushSubscription:
    return db.upsert_push_subscription(
        conn,
        pid,
        endpoint=endpoint,
        p256dh=RFC8291_P256DH,
        auth=RFC8291_AUTH,
        notify_time=notify_time,
        created_at=AT,
    )


def test_sends_once_and_remembers_the_day(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    saved = _subscribe(conn)
    sender = FakePushSender()
    assert send_due_once(settings, sender, AT) == PushCounts(sent=1)
    assert send_due_once(settings, sender, AT + timedelta(minutes=1)) == PushCounts()
    assert len(sender.calls) == 1
    target, payload = sender.calls[0]
    assert target.endpoint == ENDPOINT
    assert target.p256dh == RFC8291_P256DH
    assert target.auth == RFC8291_AUTH
    assert json.loads(payload)["url"] == "/today"
    assert db.get_push_subscription_by_id(conn, saved.id).last_sent_date == AT.date()


def test_sends_again_the_next_day(settings: Settings, conn: sqlite3.Connection) -> None:
    _subscribe(conn)
    sender = FakePushSender()
    send_due_once(settings, sender, AT)
    send_due_once(settings, sender, AT + timedelta(days=1))
    assert len(sender.calls) == 2


def test_each_device_has_its_own_time(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    _subscribe(conn, endpoint=ENDPOINT, notify_time="20:00")
    _subscribe(conn, endpoint=SECOND_ENDPOINT, notify_time="21:00")
    sender = FakePushSender()
    send_due_once(settings, sender, AT)
    assert [c[0].endpoint for c in sender.calls] == [ENDPOINT]
    send_due_once(settings, sender, AT + timedelta(hours=1))
    assert [c[0].endpoint for c in sender.calls] == [ENDPOINT, SECOND_ENDPOINT]


def test_marked_patient_is_not_sent(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    saved = _subscribe(conn)
    db.add_entry(conn, PID, EntryCreate(too_sick=True), AT, SKILL)
    sender = FakePushSender()
    assert send_due_once(settings, sender, AT) == PushCounts()
    assert sender.calls == []
    assert db.get_push_subscription_by_id(conn, saved.id).last_sent_date is None


def test_undo_brings_the_notification_back(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    _subscribe(conn)
    marked_at = AT - timedelta(hours=1)
    db.add_record_mark(conn, PID, marked_at)
    assert db.undo_record_mark(conn, PID, marked_at, clear_mark=True)
    sender = FakePushSender()
    assert send_due_once(settings, sender, AT) == PushCounts(sent=1)


def test_no_course_is_not_sent(settings: Settings, conn: sqlite3.Connection) -> None:
    db.create_patient(conn, "FOLFOX", patient_id="P-DISP0009")
    _subscribe(conn, pid="P-DISP0009")
    sender = FakePushSender()
    assert send_due_once(settings, sender, AT) == PushCounts()
    assert sender.calls == []


def test_period_end_uses_the_skill_cycle(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    _subscribe(conn, pid=PID, endpoint=ENDPOINT)  # FOLFOX 14 日: 11/29 まで
    _subscribe(conn, pid=OTHER, endpoint=SECOND_ENDPOINT)  # CAPOX 21 日: 12/6 まで
    sender = FakePushSender()
    send_due_once(settings, sender, datetime(2026, 11, 30, 20, 5, tzinfo=JST))
    assert [c[0].endpoint for c in sender.calls] == [SECOND_ENDPOINT]
    send_due_once(settings, sender, datetime(2026, 12, 7, 20, 5, tzinfo=JST))
    assert len(sender.calls) == 1


def test_next_course_restarts_notifications(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    _subscribe(conn)
    late = datetime(2026, 11, 30, 20, 5, tzinfo=JST)
    sender = FakePushSender()
    send_due_once(settings, sender, late)
    assert sender.calls == []
    db.upsert_course(
        conn,
        Course(patient_id=PID, course_no=2, infusion_date=date(2026, 11, 28)),
    )
    send_due_once(settings, sender, late)
    assert len(sender.calls) == 1


@pytest.mark.parametrize("status", [404, 410])
def test_gone_subscription_is_deleted(
    settings: Settings, conn: sqlite3.Connection, status: int
) -> None:
    _subscribe(conn)
    sender = FakePushSender(errors={ENDPOINT: PushSendError(status)})
    assert send_due_once(settings, sender, AT) == PushCounts(gone=1)
    assert db.list_push_subscriptions(conn) == []


def test_failed_send_keeps_the_row_and_tries_again_inside_the_window(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    saved = _subscribe(conn)
    db_before = db.get_push_subscription_by_id(conn, saved.id)
    sender = FakePushSender(errors={ENDPOINT: PushSendError(500)})
    assert send_due_once(settings, sender, AT) == PushCounts(failed=1)
    assert db.get_push_subscription_by_id(conn, saved.id) == db_before
    sender.errors.clear()
    assert send_due_once(settings, sender, AT + timedelta(minutes=1)) == PushCounts(
        sent=1
    )
    # 送れた後は送らない
    assert send_due_once(settings, sender, AT + timedelta(minutes=2)) == PushCounts()
    assert len(sender.calls) == 2


def test_failed_send_is_not_tried_after_the_window(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    _subscribe(conn)
    sender = FakePushSender(errors={ENDPOINT: PushSendError(500)})
    send_due_once(settings, sender, AT)
    sender.errors.clear()
    assert send_due_once(settings, sender, AT + timedelta(minutes=6)) == PushCounts()
    assert len(sender.calls) == 1


def test_failed_send_restores_the_previous_date(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    saved = _subscribe(conn)
    yesterday = AT.date() - timedelta(days=1)
    assert db.claim_push_send(conn, saved.id, yesterday)
    sender = FakePushSender(errors={ENDPOINT: RuntimeError("boom")})
    send_due_once(settings, sender, AT)
    assert db.get_push_subscription_by_id(conn, saved.id).last_sent_date == yesterday


def test_one_failure_does_not_stop_the_others(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    _subscribe(conn, endpoint=ENDPOINT)
    _subscribe(conn, pid=OTHER, endpoint=SECOND_ENDPOINT)
    sender = FakePushSender(errors={ENDPOINT: RuntimeError("boom")})
    assert send_due_once(settings, sender, AT) == PushCounts(sent=1, failed=1)
    assert [c[0].endpoint for c in sender.calls] == [ENDPOINT, SECOND_ENDPOINT]


def test_unreadable_skill_is_skipped_with_a_warning(
    settings: Settings,
    conn: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db.create_patient(conn, "NOPE-REGIMEN", patient_id=BROKEN)
    db.upsert_course(conn, Course(patient_id=BROKEN, course_no=1, infusion_date=DAY1))
    saved = _subscribe(conn, pid=BROKEN, endpoint=SECOND_ENDPOINT)
    _subscribe(conn, pid=PID, endpoint=ENDPOINT)
    sender = FakePushSender()
    with caplog.at_level(logging.WARNING):
        counts = send_due_once(settings, sender, AT)
    assert counts == PushCounts(sent=1, skipped=1)
    assert [c[0].endpoint for c in sender.calls] == [ENDPOINT]
    assert db.get_push_subscription_by_id(conn, saved.id).last_sent_date is None
    assert "push.skill_unreadable error_type=SkillValidationError" in caplog.text
    assert "NOPE-REGIMEN" not in caplog.text
    assert BROKEN not in caplog.text


def test_unreadable_skill_is_not_read_outside_the_window(
    settings: Settings,
    conn: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """時刻の外では Skill を読まない（毎分の警告で埋めない）。"""
    db.create_patient(conn, "NOPE-REGIMEN", patient_id=BROKEN)
    db.upsert_course(conn, Course(patient_id=BROKEN, course_no=1, infusion_date=DAY1))
    _subscribe(conn, pid=BROKEN, notify_time="08:00")
    with caplog.at_level(logging.WARNING):
        assert send_due_once(settings, FakePushSender(), AT) == PushCounts()
    assert caplog.text == ""


def test_logs_have_counts_and_type_names_only(
    settings: Settings,
    conn: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _subscribe(conn, endpoint=ENDPOINT)
    _subscribe(conn, pid=OTHER, endpoint=SECOND_ENDPOINT)
    sender = FakePushSender(
        errors={ENDPOINT: RuntimeError(f"boom {ENDPOINT} {PID} {RFC8291_AUTH}")}
    )
    with caplog.at_level(logging.DEBUG):
        send_due_once(settings, sender, AT)
    assert "RuntimeError" in caplog.text
    assert "sent=1" in caplog.text and "failed=1" in caplog.text
    for secret in (ENDPOINT, SECOND_ENDPOINT, PID, OTHER, RFC8291_AUTH, "boom"):
        assert secret not in caplog.text


def test_clock_comes_from_config(
    settings: Settings, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _subscribe(conn)
    monkeypatch.setattr("tsutae.push.dispatch.now", lambda: AT)
    assert send_due_once(settings, FakePushSender()) == PushCounts(sent=1)


def test_bad_row_does_not_stop_the_others(
    settings: Settings, conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    bad = _subscribe(conn, endpoint=SECOND_ENDPOINT)
    _subscribe(conn, pid=OTHER, endpoint=ENDPOINT)
    conn.execute(
        "UPDATE push_subscriptions SET notify_time = 'xx' WHERE id = ?", (bad.id,)
    )
    conn.commit()
    sender = FakePushSender()
    with caplog.at_level(logging.WARNING):
        assert send_due_once(settings, sender, AT) == PushCounts(sent=1, failed=1)
    assert "ValueError" in caplog.text


# ---------------------------------------------------------------------------
# 試送
# ---------------------------------------------------------------------------


def test_test_send_ignores_mark_period_and_time(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    saved = _subscribe(conn, notify_time="08:00")
    db.add_entry(conn, PID, EntryCreate(too_sick=True), AT, SKILL)
    sender = FakePushSender()
    assert send_test_once(settings, sender, saved.id) == "sent"
    assert len(sender.calls) == 1
    # その日の通知の分を使わない
    assert db.get_push_subscription_by_id(conn, saved.id).last_sent_date is None


def test_test_send_without_course_still_goes(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    db.create_patient(conn, "FOLFOX", patient_id="P-DISP0009")
    saved = _subscribe(conn, pid="P-DISP0009")
    assert send_test_once(settings, FakePushSender(), saved.id) == "sent"


def test_test_send_after_unsubscribe_is_dropped(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    saved = _subscribe(conn)
    db.delete_push_subscription(conn, PID, ENDPOINT)
    sender = FakePushSender()
    assert send_test_once(settings, sender, saved.id) is None
    assert sender.calls == []


@pytest.mark.parametrize(
    "error, expected",
    [(PushSendError(410), "gone"), (PushSendError(500), "failed")],
)
def test_test_send_result(
    settings: Settings, conn: sqlite3.Connection, error: Any, expected: str
) -> None:
    saved = _subscribe(conn)
    sender = FakePushSender(errors={ENDPOINT: error})
    assert send_test_once(settings, sender, saved.id) == expected
    remaining = db.get_push_subscription_by_id(conn, saved.id)
    assert (remaining is None) == (expected == "gone")


# ---------------------------------------------------------------------------
# オフにしてからオンにしても1日1回まで（§4.1）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("new_time", ["20:00", "21:00"])
def test_off_then_on_does_not_send_twice_a_day(
    settings: Settings, conn: sqlite3.Connection, new_time: str
) -> None:
    _subscribe(conn)
    sender = FakePushSender()
    assert send_due_once(settings, sender, AT) == PushCounts(sent=1)
    db.delete_push_subscription(conn, PID, ENDPOINT)
    _subscribe(conn, endpoint=SECOND_ENDPOINT, notify_time=new_time)
    assert send_due_once(settings, sender, AT + timedelta(minutes=5)) == PushCounts()
    assert send_due_once(settings, sender, AT + timedelta(hours=1)) == PushCounts()
    assert len(sender.calls) == 1
    next_day = AT + timedelta(days=1, hours=1 if new_time == "21:00" else 0)
    assert send_due_once(settings, sender, next_day) == PushCounts(sent=1)


# ---------------------------------------------------------------------------
# 送信先に消された登録（端末がオンのまま、送り直しで行が戻るのを防ぐ）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [404, 410])
def test_gone_daily_send_remembers_the_endpoint(
    settings: Settings, conn: sqlite3.Connection, status: int
) -> None:
    _subscribe(conn)
    sender = FakePushSender(errors={ENDPOINT: PushSendError(status)})
    send_due_once(settings, sender, AT)
    assert db.is_push_endpoint_gone(conn, ENDPOINT) is True


def test_gone_daily_send_does_not_use_up_the_day(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    """届かなかったので、オンにし直した新しい登録にはその日の分を送る。"""
    _subscribe(conn)
    sender = FakePushSender(errors={ENDPOINT: PushSendError(410)})
    send_due_once(settings, sender, AT)
    _subscribe(conn, endpoint=SECOND_ENDPOINT)
    later = AT + timedelta(minutes=1)
    assert send_due_once(settings, sender, later) == PushCounts(sent=1)


def test_failed_daily_send_does_not_remember_the_endpoint(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    _subscribe(conn)
    sender = FakePushSender(errors={ENDPOINT: PushSendError(500)})
    send_due_once(settings, sender, AT)
    assert db.is_push_endpoint_gone(conn, ENDPOINT) is False


def test_gone_test_send_remembers_and_keeps_the_day_already_sent(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    saved = _subscribe(conn)
    sender = FakePushSender()
    assert send_due_once(settings, sender, AT) == PushCounts(sent=1)
    sender.errors[ENDPOINT] = PushSendError(410)
    assert send_test_once(settings, sender, saved.id) == "gone"
    assert db.is_push_endpoint_gone(conn, ENDPOINT) is True
    assert _subscribe(conn, endpoint=SECOND_ENDPOINT).last_sent_date == AT.date()


# ---------------------------------------------------------------------------
# 送る前に今日の分を取る（書けなければ送らない。DB の不調で毎分届かないように）
# ---------------------------------------------------------------------------


def test_claim_failure_sends_nothing(
    settings: Settings, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _subscribe(conn)

    def locked(*_args: Any, **_kwargs: Any) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "claim_push_send", locked)
    sender = FakePushSender()
    assert send_due_once(settings, sender, AT) == PushCounts(failed=1)
    assert sender.calls == []


def test_claim_refused_sends_nothing(
    settings: Settings, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _subscribe(conn)
    monkeypatch.setattr(db, "claim_push_send", lambda *_args: False)
    sender = FakePushSender()
    assert send_due_once(settings, sender, AT) == PushCounts(skipped=1)
    assert sender.calls == []


def test_the_day_is_taken_before_sending(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    saved = _subscribe(conn)
    seen: list[date | None] = []

    def sender(_target: Any, _payload: str) -> None:
        current = db.get_push_subscription_by_id(conn, saved.id)
        seen.append(current.last_sent_date)

    assert send_due_once(settings, sender, AT) == PushCounts(sent=1)
    assert seen == [AT.date()]


# ---------------------------------------------------------------------------
# 試送は送る期間を見ない（§4.3。撮影の日付でも必ず届くように）
# ---------------------------------------------------------------------------


def test_test_send_after_the_period_still_goes(
    settings: Settings, conn: sqlite3.Connection
) -> None:
    db.create_patient(conn, "FOLFOX", patient_id="P-DISP0009")
    db.upsert_course(
        conn,
        Course(patient_id="P-DISP0009", course_no=1, infusion_date=date(2020, 1, 1)),
    )
    saved = _subscribe(conn, pid="P-DISP0009")
    sender = FakePushSender()
    assert send_test_once(settings, sender, saved.id) == "sent"
    assert len(sender.calls) == 1


# ---------------------------------------------------------------------------
# ログの状態コード（403 と 5xx を見分ける。仮名ID・endpoint は出さない）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [403, 429, 503])
def test_daily_failure_logs_the_status_code(
    settings: Settings,
    conn: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    _subscribe(conn)
    sender = FakePushSender(errors={ENDPOINT: PushSendError(status)})
    with caplog.at_level(logging.WARNING):
        send_due_once(settings, sender, AT)
    assert f"push.send_failed error_type=PushSendError status={status}" in caplog.text
    assert ENDPOINT not in caplog.text
    assert PID not in caplog.text


def test_test_send_logs_the_status_code_and_the_result(
    settings: Settings, conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    saved = _subscribe(conn)
    sender = FakePushSender(errors={ENDPOINT: PushSendError(403)})
    with caplog.at_level(logging.INFO):
        assert send_test_once(settings, sender, saved.id) == "failed"
    assert "push.send_failed error_type=PushSendError status=403" in caplog.text
    assert "push.test_done result=failed" in caplog.text
    assert ENDPOINT not in caplog.text
    assert PID not in caplog.text


def test_test_send_logs_success_without_the_device(
    settings: Settings, conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    saved = _subscribe(conn)
    with caplog.at_level(logging.INFO):
        assert send_test_once(settings, FakePushSender(), saved.id) == "sent"
    assert "push.test_done result=sent" in caplog.text
    assert ENDPOINT not in caplog.text


@pytest.mark.parametrize(
    ("errors", "result"),
    [
        ({}, "sent"),
        ({ENDPOINT: PushSendError(410)}, "gone"),
        ({ENDPOINT: PushSendError(403)}, "failed"),
    ],
)
def test_test_send_result_stays_at_the_default_log_level(
    settings: Settings,
    conn: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
    errors: dict[str, Exception],
    result: str,
) -> None:
    """uvicorn の既定は root を設定せず、実効レベルは WARNING のまま。それでも残る。"""
    saved = _subscribe(conn)
    with caplog.at_level(logging.WARNING):
        assert send_test_once(settings, FakePushSender(errors=errors), saved.id) == (
            result
        )
    assert f"push.test_done result={result}" in caplog.text
    assert ENDPOINT not in caplog.text
    assert PID not in caplog.text


def test_daily_counts_stay_at_the_default_log_level(
    settings: Settings, conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    _subscribe(conn)
    with caplog.at_level(logging.WARNING):
        send_due_once(settings, FakePushSender(), AT)
    assert "push.done sent=1 gone=0 failed=0 skipped=0" in caplog.text
    assert ENDPOINT not in caplog.text
    assert PID not in caplog.text
