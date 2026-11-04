"""起動時の設定の検査・医師ログインの上限・上限の総量・例外の投げ直しの抑止。

- 既定の署名鍵（`dev-secret-change-me`）・既定の医師パスワード（`demo-doctor`）・空の
  鍵は、public_base_url が localhost/127.0.0.1/::1 でなければ create_app が止める
  （手元では警告だけ）。短い鍵（16 字未満）は警告だけ
- `POST /api/doctor/login` はクライアントごとに失敗 5 回/10 分で 429
  too_many_attempts（正しいパスワードでも断る）。全体でも上限がある
- 登録の上限は X-Forwarded-For を回して迂回しても、全体の失敗の上限で 429 になる
- 想定外の例外は 500 を返した後、サーバ（uvicorn）へ投げ直さない（文面が traceback に
  出ないように）
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_helpers import TEST_PASSWORD, api_client, make_app, make_settings
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from tsutae.api import app as app_module
from tsutae.api import deps, settings_check
from tsutae.api import doctor as doctor_module
from tsutae.config import get_settings, jst_datetime

START = jst_datetime(date(2026, 11, 9), 9, 0)
LONG_SECRET = "x" * 40


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


class Clock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current = self.current + delta


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock(START)
    monkeypatch.setattr(doctor_module, "now", fake)
    return fake


# ---------------------------------------------------------------------------
# 1. 既定の鍵・パスワードでは公開の構成で起動しない
# ---------------------------------------------------------------------------


def test_defaults_match_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TSUTAE_SECRET", raising=False)
    monkeypatch.delenv("DOCTOR_PASSWORD", raising=False)
    s = get_settings()
    assert s.secret_key == settings_check.DEFAULT_SECRET
    assert s.doctor_password == settings_check.DEFAULT_DOCTOR_PASSWORD


@pytest.mark.parametrize(
    "overrides",
    [
        {"secret_key": settings_check.DEFAULT_SECRET},
        {"secret_key": ""},
        {"doctor_password": settings_check.DEFAULT_DOCTOR_PASSWORD},
    ],
    ids=["default_secret", "empty_secret", "default_password"],
)
@pytest.mark.parametrize(
    "url", ["https://tsutae.example/", "http://192.168.0.5:5173", "http://testserver"]
)
def test_public_url_with_default_refuses_to_start(
    tmp_path: Path, overrides: dict[str, str], url: str
) -> None:
    settings = make_settings(tmp_path, public_base_url=url, **overrides)
    with pytest.raises(settings_check.InsecureSettingsError):
        app_module.create_app(settings)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://[::1]:5173",
        "http://LOCALHOST",
    ],
)
def test_local_url_with_defaults_only_warns(
    tmp_path: Path, url: str, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(
        tmp_path,
        public_base_url=url,
        secret_key=settings_check.DEFAULT_SECRET,
        doctor_password=settings_check.DEFAULT_DOCTOR_PASSWORD,
    )
    with caplog.at_level(logging.WARNING, logger=settings_check.__name__):
        app_module.create_app(settings)
    text = caplog.text
    assert "default_secret" in text and "default_doctor_password" in text
    assert settings_check.DEFAULT_SECRET not in text  # 値そのものは出さない


def test_lookalike_host_is_not_local(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        public_base_url="http://localhost.evil.example",
        secret_key=settings_check.DEFAULT_SECRET,
    )
    with pytest.raises(settings_check.InsecureSettingsError):
        app_module.create_app(settings)


def test_short_secret_only_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(
        tmp_path, public_base_url="https://tsutae.example/", secret_key="short-key"
    )
    with caplog.at_level(logging.WARNING, logger=settings_check.__name__):
        app_module.create_app(settings)
    assert "short_secret" in caplog.text


def test_strong_settings_start_quietly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(
        tmp_path, public_base_url="https://tsutae.example/", secret_key=LONG_SECRET
    )
    with caplog.at_level(logging.WARNING, logger=settings_check.__name__):
        app_module.create_app(settings)
    assert caplog.text == ""


def test_insecure_reasons() -> None:
    base = make_settings(Path("/nonexistent"), secret_key=LONG_SECRET)
    assert settings_check.insecure_reasons(base) == []
    assert settings_check.insecure_reasons(replace(base, secret_key="abc")) == [
        "short_secret"
    ]


# ---------------------------------------------------------------------------
# 2. 医師ログインの試行回数の上限
# ---------------------------------------------------------------------------


def _login(client: TestClient, password: str) -> int:
    return client.post("/api/doctor/login", json={"password": password}).status_code


def test_login_blocks_after_five_failures(client: TestClient, clock: Clock) -> None:
    codes = [_login(client, f"x{i}") for i in range(deps.LOGIN_MAX_FAILURES)]
    assert codes == [401] * deps.LOGIN_MAX_FAILURES
    r = client.post("/api/doctor/login", json={"password": TEST_PASSWORD})
    assert r.status_code == 429 and r.json() == {"error": "too_many_attempts"}
    assert deps.DOCTOR_COOKIE not in r.cookies
    assert _login(client, "y") == 429


def test_login_unblocks_after_window(client: TestClient, clock: Clock) -> None:
    for i in range(deps.LOGIN_MAX_FAILURES):
        _login(client, f"x{i}")
    assert _login(client, TEST_PASSWORD) == 429
    clock.advance(deps.LOGIN_WINDOW + timedelta(seconds=1))
    assert _login(client, TEST_PASSWORD) == 200


def test_login_success_and_422_are_not_counted(
    client: TestClient, clock: Clock
) -> None:
    for _ in range(deps.LOGIN_MAX_FAILURES + 2):
        assert _login(client, TEST_PASSWORD) == 200
        assert client.post("/api/doctor/login", json={}).status_code == 422
    assert _login(client, "x") == 401


def test_login_limiter_is_separate_from_register(
    client: TestClient, clock: Clock
) -> None:
    for i in range(deps.LOGIN_MAX_FAILURES):
        _login(client, f"x{i}")
    assert deps.login_limiter(client.app) is not deps.register_limiter(client.app)
    r = client.post("/api/patient/register", json={"pid": "P-ZZZZZZZZ"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. X-Forwarded-For を回しても全体の上限で止まる
# ---------------------------------------------------------------------------


def test_limiter_total_cap_blocks_every_key() -> None:
    limiter = deps.AttemptLimiter(
        max_failures=3, window=timedelta(minutes=10), max_total=5
    )
    for i in range(5):
        assert not limiter.is_blocked(f"k{i}", START)
        limiter.record_failure(f"k{i}", START)
    assert limiter.is_blocked("fresh", START)
    assert limiter.tracked_clients() == 5
    assert not limiter.is_blocked("fresh", START + timedelta(minutes=10, seconds=1))


def test_limiter_rejects_bad_total() -> None:
    with pytest.raises(ValueError):
        deps.AttemptLimiter(max_failures=3, window=timedelta(minutes=1), max_total=0)


async def _register_via_proxy(app: Any, count: int, rotate: bool) -> list[int]:
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")
    transport = httpx.ASGITransport(app=wrapped, client=("127.0.0.1", 5555))
    codes = []
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as ac:
        for i in range(count):
            headers = (
                {"X-Forwarded-For": f"10.0.{i // 250}.{i % 250}"} if rotate else {}
            )
            r = await ac.post(
                "/api/patient/register", json={"pid": "P-ZZZZZZZZ"}, headers=headers
            )
            codes.append(r.status_code)
    return codes


def test_rotating_forwarded_for_hits_total_cap(
    tmp_path: Path, fixed_today: str
) -> None:
    app = make_app(tmp_path)
    with TestClient(app):  # 表を作る
        pass
    total = deps.REGISTER_MAX_TOTAL
    codes = asyncio.run(_register_via_proxy(app, total + 5, rotate=True))
    assert codes[:total] == [404] * total
    assert codes[total:] == [429] * 5
    assert deps.register_limiter(app).tracked_clients() <= total


def test_same_client_via_proxy_still_blocked(tmp_path: Path, fixed_today: str) -> None:
    app = make_app(tmp_path)
    with TestClient(app):
        pass
    codes = asyncio.run(_register_via_proxy(app, 12, rotate=False))
    assert codes == [404] * 10 + [429] * 2


# ---------------------------------------------------------------------------
# 4. 想定外の例外を 500 にした後、サーバへ投げ直さない
# ---------------------------------------------------------------------------

SECRET_TEXT = "患者の自由記載: 吐き気がつらい"


def _boom_app(tmp_path: Path) -> Any:
    app = make_app(tmp_path)

    @app.get("/boom")
    def boom() -> None:
        raise ValueError(SECRET_TEXT)

    return app


async def _call(app: Any, path: str) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "headers": [],
        "query_string": b"",
        "http_version": "1.1",
        "scheme": "http",
        "server": ("x", 80),
        "client": ("1.2.3.4", 1),
        "root_path": "",
    }
    await app(scope, receive, send)
    return sent


def test_unexpected_error_is_not_reraised_to_server(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = _boom_app(tmp_path)
    with caplog.at_level(logging.DEBUG):
        sent = asyncio.run(_call(app, "/boom"))  # 例外が上がらない
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 500
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    assert body == b'{"error":"internal_error"}'
    assert SECRET_TEXT not in caplog.text
    assert "ValueError" in caplog.text


def test_unexpected_error_via_testclient_is_500(tmp_path: Path) -> None:
    app = _boom_app(tmp_path)
    with TestClient(app) as c:  # raise_server_exceptions=True でも上がらない
        r = c.get("/boom")
    assert r.status_code == 500 and r.json() == {"error": "internal_error"}
    assert r.headers.get(deps.ERROR_ID_HEADER)


def test_error_before_response_start_sends_500(tmp_path: Path) -> None:
    """ServerErrorMiddleware が送れなかった（送信で落ちた）ときも投げ直さない。"""
    from tsutae.api.error_guard import SuppressServerErrors

    async def broken_app(scope: Any, receive: Any, send: Any) -> None:
        raise RuntimeError(SECRET_TEXT)

    sent = asyncio.run(_call(SuppressServerErrors(broken_app), "/x"))
    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [500]


def test_lifespan_errors_are_not_swallowed() -> None:
    from tsutae.api.error_guard import SuppressServerErrors

    async def broken_app(scope: Any, receive: Any, send: Any) -> None:
        raise RuntimeError("startup")

    async def run() -> None:
        await SuppressServerErrors(broken_app)({"type": "lifespan"}, None, None)

    with pytest.raises(RuntimeError):
        asyncio.run(run())
