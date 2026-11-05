"""通知の患者 API（docs/plan-device-records.md §4.3）。Cookie `tsutae_pid` で識別する。

- `GET /push-config`: 公開鍵と、通知を使えるか（鍵が無ければ available=false）
- `PUT /{pid}/push-subscription`: 登録・時刻の変更（endpoint で一意）。鍵が無ければ 503
- `DELETE /{pid}/push-subscription`: この端末の通知を切る（無くても 200）
- `POST /{pid}/push-test`: 試しに送る。10 秒後に同じ文を1回。登録ごとに1分に1回まで（超えたら
  429 push_test_too_soon）。印・送る期間・時刻の条件を見ない
- endpoint は本文で受ける（URL に入れるとアクセスログに残る）
- サーバーは endpoint へ要求を出すので、決まった送信サービスの https だけを受ける（SSRF の守り）
- 変換結果（reports・timelines）と D4 の下書きを読まない（アーキテクチャテストで検査）
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, BackgroundTasks, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tsutae import db
from tsutae.api.deps import ApiError, AppSettings, Conn, require_patient
from tsutae.config import now
from tsutae.push.dispatch import send_test_once

__all__ = [
    "PUSH_TEST_DELAY_S",
    "PUSH_TEST_INTERVAL",
    "PushTestLimiter",
    "is_push_service_url",
    "router",
    "send_test_later",
]

router = APIRouter(prefix="/api/patient")

PUSH_TEST_DELAY_S = 10.0
PUSH_TEST_INTERVAL = timedelta(minutes=1)
DEFAULT_NOTIFY_TIME = "20:00"
ENDPOINT_MAX = 2048
# ブラウザが返す送信サービス: Apple・Google（FCM）・Mozilla・Microsoft（WNS）
_PUSH_HOSTS = frozenset({"fcm.googleapis.com"})
_PUSH_HOST_SUFFIXES = (
    ".push.apple.com",
    ".push.services.mozilla.com",
    ".notify.windows.com",
)
_URL_CHARS = re.compile(r"[\x21-\x7e]+")
_B64URL = re.compile(r"[A-Za-z0-9_-]+")
_NOTIFY_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):(?:00|30)")
_P256DH_LENGTH = 65
_AUTH_LENGTH = 16
_log = logging.getLogger(__name__)


def is_push_service_url(url: str) -> bool:
    """既知の送信サービスの https の URL か（他の宛先へサーバーから要求を出さない）。"""
    if not _URL_CHARS.fullmatch(url):
        return False
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username is not None or port not in (None, 443):
        return False
    return host in _PUSH_HOSTS or host.endswith(_PUSH_HOST_SUFFIXES)


def _decode_b64url(value: str) -> bytes:
    """base64url を読む（パディングなしの形だけ）。違えば ValueError。"""
    if not _B64URL.fullmatch(value):
        raise ValueError("base64url でない")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except binascii.Error as exc:
        raise ValueError("base64url でない") from exc


class SubscriptionKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p256dh: str = Field(max_length=256)
    auth: str = Field(max_length=64)

    @field_validator("p256dh")
    @classmethod
    def _check_p256dh(cls, value: str) -> str:
        stripped = value.rstrip("=")
        raw = _decode_b64url(stripped)
        if len(raw) != _P256DH_LENGTH:
            raise ValueError("p256dh の長さが違う")
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
        return stripped

    @field_validator("auth")
    @classmethod
    def _check_auth(cls, value: str) -> str:
        stripped = value.rstrip("=")
        if len(_decode_b64url(stripped)) != _AUTH_LENGTH:
            raise ValueError("auth の長さが違う")
        return stripped


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(max_length=ENDPOINT_MAX)
    keys: SubscriptionKeys
    notify_time: str = DEFAULT_NOTIFY_TIME

    @field_validator("endpoint")
    @classmethod
    def _check_endpoint(cls, value: str) -> str:
        if not is_push_service_url(value):
            raise ValueError("送信サービスの URL でない")
        return value

    @field_validator("notify_time")
    @classmethod
    def _check_notify_time(cls, value: str) -> str:
        if not _NOTIFY_TIME.fullmatch(value):
            raise ValueError("notify_time は 30 分刻みの HH:MM")
        return value


class EndpointIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(max_length=ENDPOINT_MAX)


class PushTestLimiter:
    """登録ごとの試送の時刻を覚える（プロセス内。`--workers 1` が前提）。"""

    def __init__(self, interval: timedelta = PUSH_TEST_INTERVAL) -> None:
        self._interval = interval
        self._last: dict[int, datetime] = {}
        self._lock = threading.Lock()

    def allow(self, subscription_id: int, at: datetime) -> bool:
        with self._lock:
            self._last = {
                key: when
                for key, when in self._last.items()
                if at - when < self._interval
            }
            if subscription_id in self._last:
                return False
            self._last[subscription_id] = at
            return True


def _public_key(app: FastAPI) -> str | None:
    """通知を使えるときの公開鍵。使えなければ None。"""
    if app.state.push_sender is None:
        return None
    return app.state.push_public_key


def _require_available(app: FastAPI) -> None:
    if _public_key(app) is None:
        raise ApiError(503, "push_unavailable")


async def send_test_later(app: FastAPI, subscription_id: int) -> None:
    """待ってから試送を1通送る。失敗は型名だけ残す（応答はもう返している）。"""
    await asyncio.sleep(app.state.push_test_delay_s)
    sender = app.state.push_sender
    if sender is None:
        return
    try:
        await asyncio.to_thread(
            send_test_once, app.state.settings, sender, subscription_id
        )
    except Exception as exc:  # noqa: BLE001 — バックグラウンドの例外は外へ出さない
        _log.warning("push.test_failed error_type=%s", type(exc).__name__)


@router.get("/push-config")
def push_config(request: Request) -> dict[str, Any]:
    public_key = _public_key(request.app)
    return {"available": public_key is not None, "public_key": public_key}


@router.put("/{pid}/push-subscription")
def put_subscription(
    pid: str, body: SubscriptionIn, request: Request, conn: Conn
) -> dict[str, Any]:
    patient = require_patient(pid, request, conn)
    _require_available(request.app)
    saved = db.upsert_push_subscription(
        conn,
        patient["id"],
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        notify_time=body.notify_time,
        created_at=now(),
    )
    return {"ok": True, "notify_time": saved.notify_time}


@router.delete("/{pid}/push-subscription")
def delete_subscription(
    pid: str, body: EndpointIn, request: Request, conn: Conn
) -> dict[str, bool]:
    patient = require_patient(pid, request, conn)
    db.delete_push_subscription(conn, patient["id"], body.endpoint)
    return {"ok": True}


@router.post("/{pid}/push-test")
def push_test(
    pid: str,
    body: EndpointIn,
    background: BackgroundTasks,
    request: Request,
    conn: Conn,
    settings: AppSettings,
) -> dict[str, bool]:
    patient = require_patient(pid, request, conn)
    _require_available(request.app)
    subscription = db.get_push_subscription(conn, patient["id"], body.endpoint)
    if subscription is None:
        raise ApiError(404, "not_found")
    if not request.app.state.push_test_limiter.allow(subscription.id, now()):
        raise ApiError(429, "push_test_too_soon")
    background.add_task(send_test_later, request.app, subscription.id)
    return {"ok": True}
