"""通知の患者 API と送信のループ（plan-device-records §4.3。送信は偽物）。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import http_ece
import pytest
import requests
from api_helpers import (
    FakePushSender,
    add_patient,
    api_client,
    db_conn,
    make_app,
    make_settings,
    register,
    set_patient_cookie,
)
from fastapi.testclient import TestClient
from push_helpers import (
    ENDPOINT,
    RFC8291_AUTH,
    SECOND_ENDPOINT,
    FakeResponse,
    FakeSession,
    new_subscriber,
    subscription_body,
    vapid_overrides,
)

from tsutae import db
from tsutae.api import app as app_module
from tsutae.api import patient_push
from tsutae.api.app import create_app
from tsutae.api.deps import PATIENT_COOKIE, make_patient_token
from tsutae.config import JST
from tsutae.push.dispatch import PushCounts, send_due_once
from tsutae.push.payload import notification_payload
from tsutae.push.sender import PushSendError, WebPushSender, load_vapid

DAY1 = date(2026, 11, 1)


def _url(pid: str, leaf: str = "push-subscription") -> str:
    return f"/api/patient/{pid}/{leaf}"


def _delete(client: TestClient, pid: str, endpoint: str = ENDPOINT) -> Any:
    return client.request("DELETE", _url(pid), json={"endpoint": endpoint})


def _ready(client: TestClient) -> str:
    """登録済みの患者を作り、Cookie を付ける。試送はすぐ送る。"""
    client.app.state.push_test_delay_s = 0.0
    pid = add_patient(client.app, courses=[(1, DAY1)])
    register(client, pid)
    return pid


@pytest.fixture
def sender() -> FakePushSender:
    return FakePushSender()


@pytest.fixture
def client(tmp_path: Path, sender: FakePushSender) -> Any:
    with api_client(tmp_path, push_sender=sender, **vapid_overrides()) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /push-config
# ---------------------------------------------------------------------------


def test_push_config_with_keys(client: TestClient) -> None:
    r = client.get("/api/patient/push-config")
    assert r.status_code == 200
    public = client.app.state.settings.vapid_public_key
    assert r.json() == {"available": True, "public_key": public}


def test_push_config_without_keys_starts_and_says_unavailable(tmp_path: Path) -> None:
    with api_client(tmp_path) as c:
        r = c.get("/api/patient/push-config")
        assert r.json() == {"available": False, "public_key": None}


def test_bad_keys_start_and_say_unavailable(tmp_path: Path) -> None:
    overrides = {**vapid_overrides(), "vapid_private_key": "broken"}
    settings = make_settings(tmp_path, **overrides)
    app = create_app(settings)
    assert app.state.push_sender is None
    with TestClient(app) as c:
        assert c.get("/api/patient/push-config").json()["available"] is False


def test_real_sender_is_used_when_keys_are_good(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, **vapid_overrides()))
    assert isinstance(app.state.push_sender, WebPushSender)


def test_no_keys_means_no_sender(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    assert app.state.push_sender is None


# ---------------------------------------------------------------------------
# PUT /push-subscription
# ---------------------------------------------------------------------------


def test_subscribe_saves_the_row(client: TestClient) -> None:
    pid = _ready(client)
    r = client.put(_url(pid), json=subscription_body(notify_time="07:30"))
    assert r.status_code == 200
    assert r.json() == {"ok": True, "notify_time": "07:30"}
    with db_conn(client.app) as conn:
        (saved,) = db.list_push_subscriptions(conn)
    assert saved.patient_id == pid
    assert saved.endpoint == ENDPOINT
    assert saved.auth == RFC8291_AUTH
    assert saved.notify_time == "07:30"


def test_default_time_is_eight_pm(client: TestClient) -> None:
    pid = _ready(client)
    r = client.put(_url(pid), json=subscription_body(notify_time=None))
    assert r.json()["notify_time"] == "20:00"


def test_second_put_changes_the_time(client: TestClient) -> None:
    pid = _ready(client)
    client.put(_url(pid), json=subscription_body())
    client.put(_url(pid), json=subscription_body(notify_time="21:30"))
    with db_conn(client.app) as conn:
        (saved,) = db.list_push_subscriptions(conn)
    assert saved.notify_time == "21:30"


@pytest.mark.parametrize(
    "time_value", ["20:15", "24:00", "8:00", "20:00:00", "", "abc"]
)
def test_time_must_be_on_the_half_hour(client: TestClient, time_value: str) -> None:
    pid = _ready(client)
    r = client.put(_url(pid), json=subscription_body(notify_time=time_value))
    assert r.status_code == 422
    assert r.json() == {"error": "invalid_input"}


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://web.push.apple.com/x",
        "https://example.com/x",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/x",
        "https://web.push.apple.com.evil.example/x",
        "https://evilweb.push.apple.com.example/x",
        "https://user:pw@web.push.apple.com/x",
        "https://evil.example\\@web.push.apple.com/x",
        # 「\\」: urlsplit はホストの一部と読むが、requests は手前までをホストと読む
        "https://evil.example\\.push.apple.com/x",
        "https://internal.example\\.push.apple.com/x",
        "https://127.0.0.1\\.push.apple.com/x",
        "https://169.254.169.254\\.push.apple.com/x",
        "https://localhost\\.notify.windows.com/x",
        "https://web.push.apple.com\\x",
        "https://web.push.apple.com/x\\y",
        "https://evil.example?.push.apple.com/x",
        "https://evil.example#.push.apple.com/x",
        "https://evil.example;.push.apple.com/x",
        "https://evil%2Eexample.push.apple.com/x",
        "https://.push.apple.com/x",
        "https://web.push.apple.com:8443/x",
        "https://web.push.apple.com/x\ny",
        "https://web.push.apple.com/ x",
        "https://",
        "",
        "https://web.push.apple.com/" + "x" * 2048,
    ],
)
def test_endpoint_must_be_a_push_service(client: TestClient, endpoint: str) -> None:
    """サーバーがこの URL へ要求を出すので、決まった送信先だけを受ける（SSRF の守り）。"""
    pid = _ready(client)
    r = client.put(_url(pid), json=subscription_body(endpoint=endpoint))
    assert r.status_code == 422
    with db_conn(client.app) as conn:
        assert db.list_push_subscriptions(conn) == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://web.push.apple.com/QAbc",
        "https://fcm.googleapis.com/fcm/send/abc:def",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
        "https://web.push.apple.com:443/QAbc",
    ],
)
def test_known_push_services_are_accepted(client: TestClient, endpoint: str) -> None:
    pid = _ready(client)
    r = client.put(_url(pid), json=subscription_body(endpoint=endpoint))
    assert r.status_code == 200


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://web.push.apple.com/QAbc",
        "https://fcm.googleapis.com/fcm/send/abc:def",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
        "https://evil.example\\.push.apple.com/x",
        "https://127.0.0.1\\.push.apple.com/x",
        "https://evil.example?.push.apple.com/x",
        "https://evil.example#.push.apple.com/x",
        "https://user:pw@web.push.apple.com/x",
        "https://evil.example\\@web.push.apple.com/x",
        "https://web.push.apple.com.evil.example/x",
    ],
)
def test_accepted_url_goes_to_the_same_host_when_sent(endpoint: str) -> None:
    """検査を通る URL は、実際に送る requests でも送信サービスのホストになる。"""
    if not patient_push.is_push_service_url(endpoint):
        return
    sent_to = urlsplit(requests.Request("POST", endpoint).prepare().url).hostname
    assert sent_to == "fcm.googleapis.com" or sent_to.endswith(
        (".push.apple.com", ".notify.windows.com")
    )


@pytest.mark.parametrize(
    "keys",
    [
        {"p256dh": "short", "auth": RFC8291_AUTH},
        {"p256dh": "A" * 87, "auth": RFC8291_AUTH},  # 長さは合うが曲線の点でない
        {"p256dh": subscription_body()["keys"]["p256dh"], "auth": "short"},
        {"p256dh": subscription_body()["keys"]["p256dh"], "auth": "!" * 22},
        {"p256dh": subscription_body()["keys"]["p256dh"]},
    ],
)
def test_keys_are_checked(client: TestClient, keys: dict[str, str]) -> None:
    pid = _ready(client)
    body = {**subscription_body(), "keys": keys}
    assert client.put(_url(pid), json=body).status_code == 422


def test_extra_fields_are_refused(client: TestClient) -> None:
    pid = _ready(client)
    body = {**subscription_body(), "symptom": "下痢"}
    assert client.put(_url(pid), json=body).status_code == 422


def test_subscribe_needs_the_right_cookie(client: TestClient) -> None:
    pid = add_patient(client.app)
    other = add_patient(client.app)
    assert client.put(_url(pid), json=subscription_body()).status_code == 401
    set_patient_cookie(client, other)
    assert client.put(_url(pid), json=subscription_body()).status_code == 403


def test_subscribe_without_keys_is_unavailable(tmp_path: Path) -> None:
    with api_client(tmp_path) as c:
        pid = add_patient(c.app)
        register(c, pid)
        r = c.put(_url(pid), json=subscription_body())
        assert r.status_code == 503
        assert r.json() == {"error": "push_unavailable"}


# ---------------------------------------------------------------------------
# DELETE /push-subscription
# ---------------------------------------------------------------------------


def test_unsubscribe_removes_this_device_only(client: TestClient) -> None:
    pid = _ready(client)
    client.put(_url(pid), json=subscription_body())
    client.put(_url(pid), json=subscription_body(endpoint=SECOND_ENDPOINT))
    r = _delete(client, pid)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    with db_conn(client.app) as conn:
        assert [s.endpoint for s in db.list_push_subscriptions(conn)] == [
            SECOND_ENDPOINT
        ]


def test_unsubscribe_twice_is_fine(client: TestClient) -> None:
    pid = _ready(client)
    assert _delete(client, pid).status_code == 200


def test_unsubscribe_does_not_touch_other_patients(client: TestClient) -> None:
    pid = _ready(client)
    client.put(_url(pid), json=subscription_body())
    other = add_patient(client.app)
    client.cookies.clear()
    set_patient_cookie(client, other)
    assert _delete(client, other).status_code == 200
    with db_conn(client.app) as conn:
        assert len(db.list_push_subscriptions(conn)) == 1


def test_unsubscribe_needs_a_cookie_and_works_without_keys(tmp_path: Path) -> None:
    with api_client(tmp_path) as c:
        pid = add_patient(c.app)
        assert _delete(c, pid).status_code == 401
        register(c, pid)
        assert _delete(c, pid).status_code == 200


# ---------------------------------------------------------------------------
# POST /push-test
# ---------------------------------------------------------------------------


def _test_send(client: TestClient, pid: str, endpoint: str = ENDPOINT) -> Any:
    return client.post(_url(pid, "push-test"), json={"endpoint": endpoint})


def test_push_test_sends_the_same_words_once(
    client: TestClient, sender: FakePushSender
) -> None:
    pid = _ready(client)
    client.put(_url(pid), json=subscription_body())
    r = _test_send(client, pid)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    (call,) = sender.calls
    assert json.loads(call[1])["body"].startswith("今日の記録をお願いします。")


def test_push_test_is_once_a_minute_per_device(
    client: TestClient, sender: FakePushSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = _ready(client)
    client.put(_url(pid), json=subscription_body())
    client.put(_url(pid), json=subscription_body(endpoint=SECOND_ENDPOINT))
    clock = {"at": datetime(2026, 11, 9, 9, 0, 0, tzinfo=JST)}
    monkeypatch.setattr(patient_push, "now", lambda: clock["at"])
    assert _test_send(client, pid).status_code == 200
    second = _test_send(client, pid)
    assert second.status_code == 429
    assert second.json() == {"error": "push_test_too_soon"}
    # 別の端末は別に数える
    assert _test_send(client, pid, SECOND_ENDPOINT).status_code == 200
    clock["at"] = datetime(2026, 11, 9, 9, 0, 59, tzinfo=JST)
    assert _test_send(client, pid).status_code == 429
    clock["at"] = datetime(2026, 11, 9, 9, 1, 0, tzinfo=JST)
    assert _test_send(client, pid).status_code == 200
    assert len(sender.calls) == 3


def test_push_test_needs_a_registered_device(client: TestClient) -> None:
    pid = _ready(client)
    r = _test_send(client, pid)
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


def test_push_test_refuses_another_patients_device(
    client: TestClient, sender: FakePushSender
) -> None:
    pid = _ready(client)
    client.put(_url(pid), json=subscription_body())
    other = add_patient(client.app)
    client.cookies.clear()
    set_patient_cookie(client, other)
    assert _test_send(client, other).status_code == 404
    assert sender.calls == []


def test_push_test_without_keys_is_unavailable(tmp_path: Path) -> None:
    with api_client(tmp_path) as c:
        pid = add_patient(c.app)
        register(c, pid)
        assert _test_send(c, pid).status_code == 503


def test_push_test_removes_a_gone_device(
    client: TestClient, sender: FakePushSender
) -> None:
    pid = _ready(client)
    client.put(_url(pid), json=subscription_body())
    sender.errors[ENDPOINT] = PushSendError(410)
    assert _test_send(client, pid).status_code == 200
    with db_conn(client.app) as conn:
        assert db.list_push_subscriptions(conn) == []


def test_push_test_failure_does_not_reach_the_patient(
    client: TestClient, sender: FakePushSender, caplog: pytest.LogCaptureFixture
) -> None:
    pid = _ready(client)
    client.put(_url(pid), json=subscription_body())
    sender.errors[ENDPOINT] = RuntimeError(f"boom {ENDPOINT}")
    with caplog.at_level(logging.WARNING):
        assert _test_send(client, pid).status_code == 200
    assert "RuntimeError" in caplog.text
    assert ENDPOINT not in caplog.text


def test_push_test_waits_ten_seconds_by_default(client: TestClient) -> None:
    assert patient_push.PUSH_TEST_DELAY_S == 10.0


async def test_send_test_later_sleeps_then_sends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = FakePushSender()
    settings = make_settings(tmp_path, **vapid_overrides())
    app = create_app(settings, push_sender=sender)
    conn = db.connect(settings.db_path)
    db.init_db(conn)
    db.create_patient(conn, "FOLFOX", patient_id="P-LATE0001")
    saved = db.upsert_push_subscription(
        conn,
        "P-LATE0001",
        endpoint=ENDPOINT,
        p256dh=subscription_body()["keys"]["p256dh"],
        auth=RFC8291_AUTH,
        notify_time="20:00",
        created_at=datetime(2026, 11, 9, 9, 0, tzinfo=JST),
    )
    conn.close()
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        await real_sleep(0)
        assert sender.calls == []  # 待つ間は送らない

    monkeypatch.setattr(patient_push.asyncio, "sleep", fake_sleep)
    await patient_push.send_test_later(app, saved.id)
    assert slept == [10.0]
    assert len(sender.calls) == 1


async def test_push_test_answers_first_and_sends_later(tmp_path: Path) -> None:
    """応答を返した後で待って送る（画面を 10 秒待たせない）。TestClient を通さず ASGI で見る。"""
    sender = FakePushSender()
    settings = make_settings(tmp_path, **vapid_overrides())
    app = create_app(settings, push_sender=sender)
    app_module.startup(settings)
    pid = "P-LATE0002"
    with db_conn(app) as conn:
        db.create_patient(conn, "FOLFOX", patient_id=pid)
        db.upsert_push_subscription(
            conn,
            pid,
            endpoint=ENDPOINT,
            p256dh=subscription_body()["keys"]["p256dh"],
            auth=RFC8291_AUTH,
            notify_time="20:00",
            created_at=datetime(2026, 11, 9, 9, 0, tzinfo=JST),
        )
    app.state.push_test_delay_s = 0.05
    token = make_patient_token(settings.secret_key, pid)
    body = json.dumps({"endpoint": ENDPOINT}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": _url(pid, "push-test"),
        "raw_path": _url(pid, "push-test").encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"cookie", f"{PATIENT_COOKIE}={token}".encode()),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    answered = asyncio.Event()
    status: list[int] = []
    calls_when_answered: list[int] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])
        if message["type"] == "http.response.body" and not message.get("more_body"):
            calls_when_answered.append(len(sender.calls))
            answered.set()

    await app(scope, receive, send)
    assert answered.is_set()
    assert status == [200]
    assert calls_when_answered == [0]
    assert len(sender.calls) == 1


# ---------------------------------------------------------------------------
# 登録から暗号化された要求まで（本物の sender。送信先だけ偽物）
# ---------------------------------------------------------------------------


def test_subscribe_then_daily_send_reaches_the_device_encrypted(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path, **vapid_overrides())
    session = FakeSession()
    config = load_vapid(settings)
    assert config is not None
    device = new_subscriber()
    body = {
        "endpoint": ENDPOINT,
        "keys": {"p256dh": device.p256dh_b64, "auth": device.auth_b64},
        "notify_time": "20:00",
    }
    real = WebPushSender(config, session=session)
    app = make_app(tmp_path, settings=settings, push_sender=real)
    with TestClient(app) as c:
        pid = add_patient(c.app, courses=[(1, DAY1)])
        register(c, pid)
        assert c.put(_url(pid), json=body).status_code == 200
    at = datetime(2026, 11, 9, 20, 0, tzinfo=JST)
    assert send_due_once(settings, real, at) == PushCounts(sent=1)
    (call,) = session.calls
    assert call["url"] == ENDPOINT
    assert call["headers"]["ttl"] == "3600"
    plain = http_ece.decrypt(
        call["data"],
        private_key=device.private_key,
        auth_secret=device.auth,
        version="aes128gcm",
    )
    assert plain.decode("utf-8") == notification_payload()


def test_gone_answer_from_the_service_removes_the_device(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, **vapid_overrides())
    session = FakeSession(response=FakeResponse(status_code=410, reason="Gone"))
    config = load_vapid(settings)
    assert config is not None
    real = WebPushSender(config, session=session)
    app = make_app(tmp_path, settings=settings, push_sender=real)
    with TestClient(app) as c:
        pid = add_patient(c.app, courses=[(1, DAY1)])
        register(c, pid)
        assert c.put(_url(pid), json=subscription_body()).status_code == 200
        at = datetime(2026, 11, 9, 20, 0, tzinfo=JST)
        assert send_due_once(settings, real, at) == PushCounts(gone=1)
        with db_conn(c.app) as conn:
            assert db.list_push_subscriptions(conn) == []


# ---------------------------------------------------------------------------
# 印と POST /entries
# ---------------------------------------------------------------------------


def test_post_entries_writes_a_mark(client: TestClient) -> None:
    pid = _ready(client)
    r = client.post(f"/api/patient/{pid}/entries", json={"too_sick": True})
    assert r.status_code == 200
    with db_conn(client.app) as conn:
        today = db.list_entries(conn, pid)[0].record_date
        assert pid in db.marked_patients(conn, today)


def test_undo_entry_clears_the_mark(client: TestClient) -> None:
    pid = _ready(client)
    saved = client.post(f"/api/patient/{pid}/entries", json={"too_sick": True}).json()
    with db_conn(client.app) as conn:
        today = db.list_entries(conn, pid)[0].record_date
    undo = client.post(f"/api/patient/{pid}/entries/{saved['entry_id']}/undo")
    assert undo.status_code == 200
    with db_conn(client.app) as conn:
        assert pid not in db.marked_patients(conn, today)
