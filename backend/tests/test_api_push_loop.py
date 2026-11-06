"""送信のループと試送のつなぎ目（plan-device-records §4.3）。

ループが設定をどう渡すか・別のスレッドで呼ぶかを確かめる。送信そのものは偽物。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from api_helpers import FakePushSender, add_patient, api_client, make_settings
from push_helpers import ENDPOINT, RFC8291_AUTH, RFC8291_P256DH, vapid_overrides

from tsutae import db
from tsutae.api import app as app_module
from tsutae.api import patient_push
from tsutae.api.app import PUSH_INTERVAL_S, create_app
from tsutae.config import JST
from tsutae.push import dispatch
from tsutae.push.dispatch import PushCounts

DAY1 = date(2026, 11, 1)
AT = datetime(2026, 11, 9, 20, 0, tzinfo=JST)


def _subscribed_app(tmp_path: Path, sender: Any) -> tuple[Any, int]:
    """通知の登録が1件ある DB と app。(app, 登録の id) を返す。"""
    settings = make_settings(tmp_path, **vapid_overrides())
    app = create_app(settings, push_sender=sender)
    app_module.startup(settings)
    pid = add_patient(app, courses=[(1, DAY1)])
    conn = db.connect(settings.db_path)
    try:
        saved = db.upsert_push_subscription(
            conn,
            pid,
            endpoint=ENDPOINT,
            p256dh=RFC8291_P256DH,
            auth=RFC8291_AUTH,
            notify_time="20:00",
            created_at=AT,
        )
    finally:
        conn.close()
    return app, saved.id


async def _run_loop_until(app: Any, done: asyncio.Event) -> None:
    task = asyncio.create_task(app_module._push_loop(app, 0.001))
    await asyncio.wait_for(done.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_lifespan_runs_the_loop_and_stops_it(tmp_path: Path) -> None:
    assert PUSH_INTERVAL_S == 60.0
    with api_client(tmp_path) as c:
        task = c.app.state.push_task
        assert not task.done()
    assert task.cancelled()


async def test_loop_survives_exceptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sender = FakePushSender()
    app = create_app(make_settings(tmp_path), push_sender=sender)
    calls: list[Any] = []
    done = asyncio.Event()
    loop = asyncio.get_running_loop()

    def flaky(settings: Any, used: Any) -> PushCounts:
        calls.append(used)
        if len(calls) == 1:
            raise RuntimeError("boom P-SECRET0")
        if len(calls) >= 3:
            loop.call_soon_threadsafe(done.set)
        return PushCounts()

    monkeypatch.setattr(app_module, "send_due_once", flaky)
    with caplog.at_level(logging.WARNING):
        await _run_loop_until(app, done)
    assert calls[0] is sender
    assert "api.push_failed error_type=RuntimeError" in caplog.text
    assert "P-SECRET0" not in caplog.text


async def test_loop_reads_the_sender_each_time_and_skips_when_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(make_settings(tmp_path))
    assert app.state.push_sender is None
    used: list[Any] = []
    done = asyncio.Event()
    loop = asyncio.get_running_loop()

    def record(settings: Any, sender: Any) -> PushCounts:
        used.append(sender)
        loop.call_soon_threadsafe(done.set)
        return PushCounts()

    monkeypatch.setattr(app_module, "send_due_once", record)
    task = asyncio.create_task(app_module._push_loop(app, 0.001))
    await asyncio.sleep(0.02)
    assert used == []
    replacement = FakePushSender()
    app.state.push_sender = replacement
    await asyncio.wait_for(done.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert used[0] is replacement


async def test_loop_passes_settings_and_leaves_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1件 10 秒かかりうるので、別のスレッドで送る（他の API を待たせない）。"""
    sender = FakePushSender()
    app = create_app(make_settings(tmp_path), push_sender=sender)
    seen: list[tuple[Any, Any, int]] = []
    done = asyncio.Event()
    loop = asyncio.get_running_loop()

    def record(settings: Any, used: Any) -> PushCounts:
        seen.append((settings, used, threading.get_ident()))
        loop.call_soon_threadsafe(done.set)
        return PushCounts()

    monkeypatch.setattr(app_module, "send_due_once", record)
    await _run_loop_until(app, done)
    settings, used, thread_id = seen[0]
    assert settings is app.state.settings
    assert used is sender
    assert thread_id != threading.get_ident()


async def test_real_send_due_once_reaches_the_sender_through_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """本物の send_due_once をループ経由で動かす（渡し方が違えば毎分の例外で1通も届かない）。"""
    calls: list[tuple[Any, str]] = []
    done = asyncio.Event()
    loop = asyncio.get_running_loop()

    def deliver(target: Any, payload: str) -> None:
        calls.append((target, payload))
        loop.call_soon_threadsafe(done.set)

    app, _ = _subscribed_app(tmp_path, deliver)
    monkeypatch.setattr(dispatch, "now", lambda: AT)
    with caplog.at_level(logging.WARNING):
        await _run_loop_until(app, done)
    assert [target.endpoint for target, _ in calls] == [ENDPOINT]
    assert "api.push_failed" not in caplog.text


async def test_send_test_later_passes_settings_and_leaves_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = FakePushSender()
    app, subscription_id = _subscribed_app(tmp_path, sender)
    app.state.push_test_delay_s = 0.0
    seen: list[tuple[Any, Any, int, int]] = []

    def record(settings: Any, used: Any, sent_id: int) -> str:
        seen.append((settings, used, sent_id, threading.get_ident()))
        return "sent"

    monkeypatch.setattr(patient_push, "send_test_once", record)
    await patient_push.send_test_later(app, subscription_id)
    ((settings, used, sent_id, thread_id),) = seen
    assert settings is app.state.settings
    assert used is sender
    assert sent_id == subscription_id
    assert thread_id != threading.get_ident()
