"""通知のテストの共通の部品（ネットワークに出ない）。

- `RFC8291_P256DH`・`RFC8291_AUTH`: RFC 8291 の例の受信側の公開鍵と auth（本物の形の値）
- `new_subscriber()`: 復号の確認に使う受信側の鍵の組
- `vapid_overrides()`: `make_settings` に渡す VAPID の設定（毎回新しい鍵）
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

RFC8291_P256DH = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
RFC8291_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
ENDPOINT = "https://web.push.apple.com/QFixtureDeviceToken"
SECOND_ENDPOINT = "https://fcm.googleapis.com/fcm/send/fixture-device"


@dataclass
class FakeResponse:
    status_code: int = 201
    reason: str = "Created"
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class FakeSession:
    """requests.Session の代わり（送信先の差し替え）。post の引数を覚える。"""

    response: FakeResponse = field(default_factory=FakeResponse)
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def public_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def new_vapid_keys() -> tuple[str, str]:
    """(公開鍵, 秘密鍵)。どちらも base64url（パディングなし）。"""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return b64url(public_bytes(key)), b64url(private)


def vapid_overrides(subject: str = "mailto:test@example.com") -> dict[str, Any]:
    public, private = new_vapid_keys()
    return {
        "vapid_public_key": public,
        "vapid_private_key": private,
        "vapid_subject": subject,
    }


@dataclass(frozen=True)
class Subscriber:
    """ブラウザ側の鍵（p256dh の秘密鍵と auth）。"""

    private_key: ec.EllipticCurvePrivateKey
    auth: bytes

    @property
    def p256dh_b64(self) -> str:
        return b64url(public_bytes(self.private_key))

    @property
    def auth_b64(self) -> str:
        return b64url(self.auth)


def new_subscriber() -> Subscriber:
    return Subscriber(ec.generate_private_key(ec.SECP256R1()), secrets.token_bytes(16))


def subscription_body(
    endpoint: str = ENDPOINT, notify_time: str | None = "20:00"
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "endpoint": endpoint,
        "keys": {"p256dh": RFC8291_P256DH, "auth": RFC8291_AUTH},
    }
    if notify_time is not None:
        body["notify_time"] = notify_time
    return body
