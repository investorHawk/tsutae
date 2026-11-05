"""dump_api_fixtures.py の通知の経路の台本（plan-device-records §4.3）。

鍵は本物を使わず、`app.state` に公開鍵だけを置く。送信は `api_helpers.FakePushSender`。
endpoint と鍵は合成の値（p256dh・auth は RFC 8291 の例）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api_helpers import db_conn

from tsutae import db
from tsutae.config import JST

# RFC 8292 の例の形の値（65 バイトの点の base64url。送信には使わない）
FIXTURE_PUBLIC_KEY = "BA1Hxzyi1RUM1b5wjxsn7nGxAszw2u61m164i3MrAIxHF6YK5h4SDYic-dRuU_RCPCfA5aq9ojSwk5Y2EmClBPs"
ENDPOINT = "https://web.push.apple.com/QFixtureDeviceToken"
GONE_ENDPOINT = "https://web.push.apple.com/QFixtureGoneDeviceToken"
GONE_AT = datetime(2026, 11, 9, 9, 0, tzinfo=JST)
SUBSCRIPTION = {
    "endpoint": ENDPOINT,
    "keys": {
        "p256dh": (
            "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
        ),
        "auth": "BTBZMqHH6r4Tts7J_aSIgg",
    },
    "notify_time": "20:00",
}


def push_flow(rec: Any, pid: str) -> None:
    """通知の経路を順に呼ぶ（pid の Cookie が付いた状態で）。"""
    base = f"/api/patient/{pid}"
    subscription = f"{base}/push-subscription"
    only_endpoint = {"endpoint": ENDPOINT}
    state = rec.client.app.state
    rec.call("patient_push_config_unavailable", "GET", "/api/patient/push-config")
    rec.call(
        "patient_push_subscribe_unavailable",
        "PUT",
        subscription,
        SUBSCRIPTION,
        expect=503,
    )
    state.push_public_key = FIXTURE_PUBLIC_KEY
    state.push_test_delay_s = 0.0
    rec.call("patient_push_config", "GET", "/api/patient/push-config")
    rec.call("patient_push_subscribe", "PUT", subscription, SUBSCRIPTION)
    rec.call(
        "patient_push_subscribe_invalid",
        "PUT",
        subscription,
        {**SUBSCRIPTION, "notify_time": "20:15"},
        expect=422,
    )
    rec.call("patient_push_test", "POST", f"{base}/push-test", only_endpoint)
    rec.call(
        "patient_push_test_too_soon",
        "POST",
        f"{base}/push-test",
        only_endpoint,
        expect=429,
    )
    rec.call("patient_push_unsubscribe", "DELETE", subscription, only_endpoint)
    rec.call(
        "patient_push_test_not_found",
        "POST",
        f"{base}/push-test",
        only_endpoint,
        expect=404,
    )
    with db_conn(rec.client.app) as conn:
        db.mark_push_endpoint_gone(conn, GONE_ENDPOINT, GONE_AT)
    rec.call(
        "patient_push_subscribe_gone",
        "PUT",
        subscription,
        {**SUBSCRIPTION, "endpoint": GONE_ENDPOINT},
        expect=410,
    )
