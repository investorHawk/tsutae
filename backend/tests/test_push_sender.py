"""本物の pywebpush で、暗号化と VAPID の署名まで確かめる（送信先だけ偽物。ネットワークに出ない）。

送信先のセッションを差し替えて、出ていく要求そのものを調べる: 本文を受信側の鍵で復号でき、
Authorization の JWT が VAPID の公開鍵で検証できること。
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import http_ece
import pytest
import requests
from api_helpers import make_settings
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from push_helpers import (
    ENDPOINT,
    RFC8291_AUTH,
    RFC8291_P256DH,
    FakeResponse,
    FakeSession,
    new_subscriber,
    new_vapid_keys,
    vapid_overrides,
)

from tsutae.push.payload import notification_payload
from tsutae.push.sender import (
    PushSendError,
    PushTarget,
    WebPushSender,
    load_vapid,
)


def _decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _sender(tmp_path: Path, session: FakeSession, **overrides: Any) -> WebPushSender:
    settings = make_settings(tmp_path, **(vapid_overrides() | overrides))
    config = load_vapid(settings)
    assert config is not None
    return WebPushSender(config, session=session)


def _target() -> PushTarget:
    return PushTarget(endpoint=ENDPOINT, p256dh=RFC8291_P256DH, auth=RFC8291_AUTH)


def _claims_of(authorization: str, public_key: str) -> dict[str, Any]:
    """`vapid t=<jwt>,k=<公開鍵>` を公開鍵で検証し、JWT の中身を返す。"""
    scheme, _, rest = authorization.partition(" ")
    assert scheme == "vapid"
    parts = dict(p.split("=", 1) for p in rest.split(","))
    assert parts["k"].rstrip("=") == public_key
    head, body, signature = parts["t"].split(".")
    raw = _decode(signature)
    der = encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )
    key = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), _decode(public_key)
    )
    key.verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    assert json.loads(_decode(head))["alg"] == "ES256"
    return json.loads(_decode(body))


def test_request_is_really_encrypted_and_signed(tmp_path: Path) -> None:
    session = FakeSession()
    public, private = new_vapid_keys()
    sender = _sender(
        tmp_path,
        session,
        vapid_public_key=public,
        vapid_private_key=private,
        vapid_subject="mailto:test@example.com",
    )
    subscriber = new_subscriber()
    payload = notification_payload()
    sender(
        PushTarget(
            endpoint=ENDPOINT, p256dh=subscriber.p256dh_b64, auth=subscriber.auth_b64
        ),
        payload,
    )

    (call,) = session.calls
    assert call["url"] == ENDPOINT
    assert call["timeout"] == 10.0
    headers = call["headers"]
    assert headers["ttl"] == "3600"
    assert headers["content-encoding"] == "aes128gcm"
    assert payload.encode("utf-8") not in call["data"]

    plain = http_ece.decrypt(
        call["data"],
        private_key=subscriber.private_key,
        auth_secret=subscriber.auth,
        version="aes128gcm",
    )
    assert plain.decode("utf-8") == payload

    claims = _claims_of(headers["authorization"], public)
    assert claims["aud"] == "https://web.push.apple.com"
    assert claims["sub"] == "mailto:test@example.com"
    assert time.time() < claims["exp"] <= time.time() + 24 * 3600


def test_rfc8291_keys_are_accepted(tmp_path: Path) -> None:
    session = FakeSession()
    _sender(tmp_path, session)(_target(), "{}")
    assert len(session.calls) == 1


def test_claims_are_not_shared_between_sends(tmp_path: Path) -> None:
    """aud は送り先ごとに違う。前の送信の aud が残らない。"""
    session = FakeSession()
    public, private = new_vapid_keys()
    sender = _sender(
        tmp_path, session, vapid_public_key=public, vapid_private_key=private
    )
    sender(_target(), "{}")
    other = replace(_target(), endpoint="https://fcm.googleapis.com/fcm/send/x")
    sender(other, "{}")
    audiences = [
        _claims_of(c["headers"]["authorization"], public)["aud"] for c in session.calls
    ]
    assert audiences == ["https://web.push.apple.com", "https://fcm.googleapis.com"]


@pytest.mark.parametrize("status", [404, 410, 400, 403, 429, 500])
def test_error_status_becomes_push_send_error(tmp_path: Path, status: int) -> None:
    session = FakeSession(response=FakeResponse(status_code=status, reason="x"))
    with pytest.raises(PushSendError) as caught:
        _sender(tmp_path, session)(_target(), "{}")
    assert caught.value.status_code == status
    assert ENDPOINT not in str(caught.value)


def test_network_error_is_not_swallowed(tmp_path: Path) -> None:
    session = FakeSession(error=requests.ConnectionError("no route"))
    with pytest.raises(requests.ConnectionError):
        _sender(tmp_path, session)(_target(), "{}")


# ---------------------------------------------------------------------------
# VAPID の設定
# ---------------------------------------------------------------------------


def test_no_keys_means_unavailable_without_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert load_vapid(make_settings(tmp_path)) is None
    assert caplog.records == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"vapid_public_key": None},
        {"vapid_private_key": None},
        {"vapid_subject": None},
        {"vapid_public_key": ""},
        {"vapid_private_key": "not-a-key"},
        {"vapid_public_key": new_vapid_keys()[0]},  # 秘密鍵と組でない
        {"vapid_subject": "someone@example.com"},  # mailto: が無い
        {"vapid_subject": "http://example.com"},
    ],
)
def test_bad_settings_mean_unavailable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, overrides: dict[str, Any]
) -> None:
    settings = make_settings(tmp_path, **(vapid_overrides() | overrides))
    with caplog.at_level(logging.WARNING):
        assert load_vapid(settings) is None
    assert any("push.vapid_unavailable" in r.getMessage() for r in caplog.records)
    private = settings.vapid_private_key
    if private:
        assert private not in caplog.text


@pytest.mark.parametrize("subject", ["mailto:a@example.com", "https://example.com"])
def test_good_settings_are_available(tmp_path: Path, subject: str) -> None:
    overrides = vapid_overrides(subject=subject)
    config = load_vapid(make_settings(tmp_path, **overrides))
    assert config is not None
    assert config.public_key == overrides["vapid_public_key"]
    assert overrides["vapid_private_key"] not in repr(config)
    assert config.subject == subject


def test_padded_public_key_is_normalized(tmp_path: Path) -> None:
    overrides = vapid_overrides()
    padded = overrides["vapid_public_key"] + "="
    config = load_vapid(
        make_settings(tmp_path, **{**overrides, "vapid_public_key": padded})
    )
    assert config is not None
    assert config.public_key == overrides["vapid_public_key"]
