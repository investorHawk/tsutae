"""本文の大きさの上限（`BodyLimit`。全ての経路、経路ごとの上書き）。

FastAPI は依存（Cookie の検査など）より先に本文を全て読むので、ログインしていない
`POST /api/patient/register`・`POST /api/doctor/login` にも上限が要る。正当な本文の最大
（Skill の変更依頼 20000 字・伏せ字の保存 200 件 × 200 区間）は断らない。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_helpers import api_client, login_doctor
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from tsutae.api.body_limit import (
    DEFAULT_BODY_MAX_BYTES,
    MASKS_BODY_MAX_BYTES,
    BodyLimit,
)
from tsutae.api.unprocessed_masks import MAX_ENTRIES
from tsutae.api.visit_entries import FREE_TEXT_MAX
from tsutae.masking.manual import MAX_SPANS

JSON = {"content-type": "application/json"}
TOO_LARGE = {"error": "body_too_large"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with api_client(tmp_path) as c:
        yield c


def _chunks(total: int) -> Iterator[bytes]:
    """Content-Length の無い（chunked の）本文。"""
    step = 64 * 1024
    sent = 0
    while sent < total:
        size = min(step, total - sent)
        sent += size
        yield b" " * size


def test_default_limit_values() -> None:
    assert DEFAULT_BODY_MAX_BYTES == 1024 * 1024
    assert MASKS_BODY_MAX_BYTES == 2 * 1024 * 1024


@pytest.mark.parametrize("path", ["/api/patient/register", "/api/doctor/login"])
def test_unauthenticated_body_over_default_is_413(
    client: TestClient, path: str
) -> None:
    big = b" " * (DEFAULT_BODY_MAX_BYTES + 1)
    r = client.post(path, content=big, headers=JSON)
    assert r.status_code == 413
    assert r.json() == TOO_LARGE


@pytest.mark.parametrize("path", ["/api/patient/register", "/api/doctor/login"])
def test_unauthenticated_chunked_body_over_default_is_413(
    client: TestClient, path: str
) -> None:
    r = client.post(path, content=_chunks(DEFAULT_BODY_MAX_BYTES + 1), headers=JSON)
    assert r.status_code == 413
    assert r.json() == TOO_LARGE


def test_body_at_the_default_goes_on_to_validation(client: TestClient) -> None:
    padded = json.dumps({"password": "x"}).encode()
    padded += b" " * (DEFAULT_BODY_MAX_BYTES - len(padded))
    r = client.post("/api/doctor/login", content=padded, headers=JSON)
    assert r.status_code == 401


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_other_methods_with_a_body_are_limited(client: TestClient, method: str) -> None:
    big = b" " * (DEFAULT_BODY_MAX_BYTES + 1)
    r = client.request(method, "/api/patient/p1/push-subscription", content=big)
    assert r.status_code == 413
    assert r.json() == TOO_LARGE


def test_largest_skill_change_request_is_not_413(client: TestClient) -> None:
    """依頼文 20000 字（日本語）を、全て \\u でエスケープした JSON でも断らない。"""
    login_doctor(client)
    body = {"skill_name": "regimen-folfox", "request_text": "あ" * 20000}
    for ensure_ascii in (False, True):
        raw = json.dumps(body, ensure_ascii=ensure_ascii).encode()
        assert len(raw) < DEFAULT_BODY_MAX_BYTES // 4
        r = client.post("/api/doctor/skill-changes", content=raw, headers=JSON)
        assert r.status_code not in (413, 422)  # 本文を読んで経路まで届いた


def _largest_masks_body(separators: tuple[str, str]) -> bytes:
    """伏せ字の保存の最大: 200 件 × 200 区間（2000 字の中で重ならない4桁の区間）。"""
    first = FREE_TEXT_MAX // 2
    width = (FREE_TEXT_MAX - first) // MAX_SPANS
    spans = [
        {"start": first + width * i, "end": first + width * (i + 1) - 1}
        for i in range(MAX_SPANS)
    ]
    entry: dict[str, Any] = {
        "entry_id": 2**62,
        "send": True,
        "spans": spans,
        "confirmed_clear": False,
    }
    body = {"entries": [entry] * MAX_ENTRIES}
    return json.dumps(body, separators=separators).encode()


def test_largest_masks_body_needs_and_fits_the_override(client: TestClient) -> None:
    compact = _largest_masks_body((",", ":"))  # ブラウザの JSON.stringify と同じ形
    spaced = _largest_masks_body((", ", ": "))
    assert DEFAULT_BODY_MAX_BYTES < len(compact) < len(spaced) < MASKS_BODY_MAX_BYTES
    login_doctor(client)
    for raw in (compact, spaced):
        r = client.post("/api/doctor/visits/1/masks", content=raw, headers=JSON)
        assert r.status_code == 404  # 本文の検査を通り、受診が無いところまで届いた
    over = b" " * (MASKS_BODY_MAX_BYTES + 1)
    r = client.post("/api/doctor/visits/1/masks", content=over, headers=JSON)
    assert r.status_code == 413
    assert r.json() == TOO_LARGE


def test_override_matches_one_path_segment_only(client: TestClient) -> None:
    """`{vid}` は1つの区切りだけ。似た経路には既定の上限が掛かる。"""
    raw = b" " * (DEFAULT_BODY_MAX_BYTES + 1)
    for path in (
        "/api/doctor/visits/1/masks/check",
        "/api/doctor/visits/1/2/masks",
        "/api/doctor/visits//masks",
    ):
        r = client.post(path, content=raw, headers=JSON)
        assert r.status_code == 413, path


# ---------------------------------------------------------------------------
# ミドルウェア単体（本文の無い要求は読まない）
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.received: list[Message] = []
        self.called = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.called = True
        self.received.append(await receive())


def _scope(method: str, path: str = "/x", headers: list | None = None) -> Scope:
    return {"type": "http", "method": method, "path": path, "headers": headers or []}


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_safe_methods_pass_through_without_reading(method: str) -> None:
    inner = _Recorder()
    calls: list[str] = []

    async def receive() -> Message:
        calls.append("receive")
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        raise AssertionError("応答は中のアプリが返す")

    middleware = BodyLimit(inner, max_bytes=10)
    await middleware(_scope(method), receive, send)
    assert inner.called and calls == ["receive"]  # 中のアプリが読んだ1回だけ


async def test_lifespan_and_websocket_scopes_pass_through() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    middleware = BodyLimit(inner, max_bytes=10)
    for kind in ("lifespan", "websocket"):
        await middleware({"type": kind}, None, None)  # type: ignore[arg-type]
    assert seen == ["lifespan", "websocket"]


def test_override_pattern_rejects_bad_keys() -> None:
    with pytest.raises(ValueError):
        BodyLimit(_Recorder(), max_bytes=10, overrides={"api/visit": 20})
    with pytest.raises(ValueError):
        BodyLimit(_Recorder(), max_bytes=0)
