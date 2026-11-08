"""要求の本文の大きさを断る ASGI ミドルウェア（plan-device-records §5.5）。

FastAPI は依存（Depends。Cookie の検査など）より先に本文を全て読むので、経路の中では遅い。
ログインしていない `POST /api/patient/register`・`POST /api/doctor/login` にも大きな本文を
送れてしまうので、全ての HTTP 要求に上限を掛ける。

- GET・HEAD・OPTIONS は本文を読まずにそのまま通す（遅くしない）。それ以外のメソッドは
  Content-Length が上限を超えていれば読まずに、無い（chunked の）本文も読みながら数えて、
  上限を超えたら 413 `{"error": "body_too_large"}` を返す。上限の内側なら読んだ本文を
  そのまま次へ渡す。JSON を読むのは次の段（壊れた本文は 422）
- 上限は `max_bytes`（既定の上限）と、経路ごとの `overrides`（`{"/api/visit": 5MB}`）。
  経路の `{名前}` は区切り1つ（`/` を含まない1文字以上）に当たる。それ以外は完全一致
- `DEFAULT_BODY_MAX_BYTES`（1 MiB）は、正当な本文の最大より十分に大きく取った値。
  Skill の変更依頼（`request_text` 20000 字）は日本語で約 60KB、全て `\\uXXXX` に
  エスケープしても約 120KB。D4 の欄の編集（`FieldsIn`。changes・adds・deletes 各 300 件、
  `value` は JsonValue で pydantic の長さの上限が無く、ここだけが上限になる）は、検査の
  上限（備考 2000 字・他は 200 字まで）で全てエスケープしても約 0.5MB。256 KiB では
  これを断ってしまうので 1 MiB にした
- `MASKS_BODY_MAX_BYTES`（2 MiB）は伏せ字の保存（`POST /api/doctor/visits/{vid}/masks`）。
  200 件 × 200 区間（2000 字の中の4桁の位置）で、ブラウザの JSON.stringify の形で約 1.06MB、
  空白入りの JSON でも約 1.22MB になり、既定の上限を超える
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "BODY_TOO_LARGE",
    "DEFAULT_BODY_MAX_BYTES",
    "MASKS_BODY_MAX_BYTES",
    "MASKS_SAVE_PATH",
    "BodyLimit",
]

BODY_TOO_LARGE = "body_too_large"
DEFAULT_BODY_MAX_BYTES = 1024 * 1024
MASKS_BODY_MAX_BYTES = 2 * 1024 * 1024
MASKS_SAVE_PATH = "/api/doctor/visits/{vid}/masks"
_NO_BODY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_PARAM = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


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


def _path_pattern(path: str) -> re.Pattern[str]:
    """`/api/doctor/visits/{vid}/masks` → `{vid}` が区切り1つに当たる正規表現。"""
    if not path.startswith("/"):
        raise ValueError("経路は / で始める")
    parts = _PARAM.split(path)
    return re.compile("[^/]+".join(re.escape(part) for part in parts))


def _checked_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("上限は 1 以上の整数")
    return value


class BodyLimit:
    """本文が上限（経路ごとの上書き、無ければ max_bytes）を超えたら 413。"""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int = DEFAULT_BODY_MAX_BYTES,
        overrides: Mapping[str, int] | None = None,
    ) -> None:
        self._app = app
        self._max = _checked_limit(max_bytes)
        self._overrides = tuple(
            (_path_pattern(path), _checked_limit(limit))
            for path, limit in (overrides or {}).items()
        )

    def _limit_for(self, path: str) -> int:
        for pattern, limit in self._overrides:
            if pattern.fullmatch(path):
                return limit
        return self._max

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in _NO_BODY_METHODS:
            await self._app(scope, receive, send)
            return
        limit = self._limit_for(scope["path"])
        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            await _send_too_large(send)
            return
        body = await _read_within(receive, limit)
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
