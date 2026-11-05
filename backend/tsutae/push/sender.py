"""VAPID の鍵の読み込みと、pywebpush で1通送る処理。

- 送る処理は `PushSender`（`sender(target, payload)`）の形で、`app.state.push_sender` に
  置く（テストでは偽物に差し替える）。送れなければ例外を投げる。送信先の答えが
  エラーなら `PushSendError(status_code)`。呼び出し側は pywebpush の型を知らなくてよい
- 鍵は設定から読み、無い・壊れている・組でないときは None（通知を「使えない」にする。
  起動は止めない）。警告に鍵の値を出さない
- `webpush` の `timeout` の既定は None（待ち続ける）なので必ず渡す。`vapid_claims` は
  中で書き換えられる（aud が残る）ので毎回新しい dict を渡す。秘密鍵を文字列で渡すと
  ファイルのパスとしても調べられるので、読み込んだ `Vapid` を渡す
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

from tsutae.config import Settings

__all__ = [
    "PUSH_TTL_S",
    "SEND_TIMEOUT_S",
    "PushSendError",
    "PushSender",
    "PushTarget",
    "VapidConfig",
    "WebPushSender",
    "load_vapid",
]

PUSH_TTL_S = 3600
SEND_TIMEOUT_S = 10.0
_SUBJECT_PREFIXES = ("mailto:", "https://")
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushTarget:
    """送り先の端末。"""

    endpoint: str
    p256dh: str
    auth: str


class PushSendError(Exception):
    """送信先がエラーを返した。文面に endpoint を入れない。"""

    def __init__(self, status_code: int | None = None) -> None:
        super().__init__(f"push failed: {status_code}")
        self.status_code = status_code


class PushSender(Protocol):
    def __call__(self, target: PushTarget, payload: str) -> None: ...


@dataclass(frozen=True)
class VapidConfig:
    public_key: str  # base64url（パディングなし）。ブラウザの applicationServerKey
    subject: str
    signer: Vapid = field(repr=False)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _public_key_of(signer: Vapid) -> str:
    return _b64url(
        signer.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    )


def _unavailable(reason: str) -> None:
    _log.warning("push.vapid_unavailable reason=%s", reason)


def load_vapid(settings: Settings) -> VapidConfig | None:
    """設定の鍵を読む。使えなければ None（全て無いときは警告も出さない）。"""
    public = (settings.vapid_public_key or "").rstrip("=")
    private = settings.vapid_private_key or ""
    subject = settings.vapid_subject or ""
    if not public and not private and not subject:
        return None
    if not public or not private or not subject:
        _unavailable("missing")
        return None
    if not subject.startswith(_SUBJECT_PREFIXES):
        _unavailable("bad_subject")
        return None
    try:
        signer = Vapid.from_string(private_key=private)
        derived = _public_key_of(signer)
    except (
        Exception
    ) as exc:  # noqa: BLE001 — 壊れた鍵で起動を止めない。文面に鍵が出うる
        _unavailable(type(exc).__name__)
        return None
    if derived != public:
        _unavailable("key_mismatch")
        return None
    return VapidConfig(public_key=public, subject=subject, signer=signer)


class WebPushSender:
    """本物の送信。session は requests.Session の形のもの（テストで送信先を差し替える）。"""

    def __init__(self, config: VapidConfig, *, session: Any = None) -> None:
        self._config = config
        self._session = session

    def __call__(self, target: PushTarget, payload: str) -> None:
        try:
            webpush(
                subscription_info={
                    "endpoint": target.endpoint,
                    "keys": {"p256dh": target.p256dh, "auth": target.auth},
                },
                data=payload,
                vapid_private_key=self._config.signer,
                vapid_claims={"sub": self._config.subject},
                ttl=PUSH_TTL_S,
                timeout=SEND_TIMEOUT_S,
                requests_session=self._session,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            raise PushSendError(status) from exc
