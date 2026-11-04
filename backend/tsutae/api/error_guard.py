"""想定外の例外をサーバ（uvicorn）へ投げ直さない、最も外側の ASGI ガード。

Starlette の ServerErrorMiddleware は 500 を送った後で例外を投げ直し、uvicorn はそれを
`logger.error(..., exc_info=exc)` で記録する（例外の文面と traceback がサーバのログに
出る。患者の文面を含みうる）。FastAPI の例外ハンドラ（`deps._internal_error`）が型名と
相関IDを既に記録しているので、ここでは型名だけを debug で残して握りつぶす。

- `http` だけを扱う。lifespan・websocket はそのまま通す（起動の失敗は隠さない）
- 応答をまだ始めていなければ 500 `{"error": "internal_error"}` を送る（送れなければ諦める）
- BaseException（CancelledError など）は握らない
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["SUPPRESSED_EVENT", "SuppressServerErrors"]

SUPPRESSED_EVENT = "api.exception_suppressed"
_log = logging.getLogger(__name__)
_BODY = b'{"error":"internal_error"}'


class SuppressServerErrors:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:  # noqa: BLE001 — 文面をサーバのログに出さない
            _log.debug("%s error_type=%s", SUPPRESSED_EVENT, type(exc).__name__)
            if not started:
                await _send_500(send)


async def _send_500(send: Send) -> None:
    headers: list[Any] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(_BODY)).encode()),
    ]
    try:
        await send({"type": "http.response.start", "status": 500, "headers": headers})
        await send({"type": "http.response.body", "body": _BODY})
    except Exception as exc:  # noqa: BLE001 — 切断済みなど。送れなければ諦める
        _log.debug("%s send_failed=%s", SUPPRESSED_EVENT, type(exc).__name__)
