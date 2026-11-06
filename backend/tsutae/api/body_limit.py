"""決まった経路の本文の大きさを断る ASGI ミドルウェア（plan-device-records §5.5）。

FastAPI は依存（Depends）より先に本文を全て読むので、経路の中では遅い。Content-Length が
無い（chunked の）本文も数えられるよう、読みながら数えて、上限を超えたら 413 を返す。
上限の内側なら読んだ本文をそのまま次へ渡す。JSON を読むのは次の段（壊れた本文は 422）。
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["BODY_TOO_LARGE", "BodyLimit"]

BODY_TOO_LARGE = "body_too_large"


async def _send_too_large(send: Send) -> None:
    payload = json.dumps({"error": BODY_TOO_LARGE}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _read_within(receive: Receive, limit: int) -> bytes | None:
    """本文を読む。上限を超えた・途中で切れたら None。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return None
        chunk = message.get("body", b"")
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks)


class BodyLimit:
    """path への POST の本文が max_bytes を超えたら 413 `{"error": "body_too_large"}`。"""

    def __init__(self, app: ASGIApp, *, path: str, max_bytes: int) -> None:
        self._app = app
        self._path = path
        self._max = max_bytes

    def _applies(self, scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] == self._path
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._applies(scope):
            await self._app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self._max:
            await _send_too_large(send)
            return
        body = await _read_within(receive, self._max)
        if body is None:
            await _send_too_large(send)
            return

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self._app(scope, replay, send)
