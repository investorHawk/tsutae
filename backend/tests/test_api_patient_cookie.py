"""患者 Cookie の署名と、登録 API の試行回数の上限（docs/architecture.md §8・§8b）。

- Cookie `tsutae_pid` = `<pid>.<base64url(HMAC-SHA256(secret_key, "patient:" + pid))>`
- 署名が無い・違う・形が違えば 401 not_logged_in。経路の pid と違えば 403
- 登録の失敗（unknown_patient）がクライアントごとに 10 分で 10 回を超えたら 429
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from api_helpers import TEST_SECRET, add_patient, api_client, register
from fastapi.testclient import TestClient

from tsutae.api import deps
from tsutae.api import patient as patient_module
from tsutae.config import jst_datetime

C1 = [(1, date(2026, 10, 27))]
START = jst_datetime(date(2026, 11, 9), 9, 0)


@pytest.fixture
def client(tmp_path: Path, fixed_today: str):
    with api_client(tmp_path) as c:
        yield c


class Clock:
    """`tsutae.api.patient.now` の差し替え。advance で進める。"""

    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current = self.current + delta


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock(START)
    monkeypatch.setattr(patient_module, "now", fake)
    return fake


def _expected_sig(secret: str, pid: str) -> str:
    digest = hmac.new(
        secret.encode(), f"patient:{pid}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _raw_cookie(client: TestClient, value: str) -> None:
    client.cookies.clear()
    client.cookies.set(deps.PATIENT_COOKIE, value)


def _questions(client: TestClient, pid: str) -> int:
    return client.get(f"/api/patient/{pid}/questions").status_code


def _fail(client: TestClient) -> int:
    return client.post("/api/patient/register", json={"pid": "P-ZZZZZZZZ"}).status_code


# ---------------------------------------------------------------------------
# 署名つき Cookie
# ---------------------------------------------------------------------------


def test_token_is_pid_dot_base64url_hmac() -> None:
    token = deps.make_patient_token(TEST_SECRET, "P-ABCD1234")
    assert token == f"P-ABCD1234.{_expected_sig(TEST_SECRET, 'P-ABCD1234')}"
    assert deps.verify_patient_token(token, TEST_SECRET) == "P-ABCD1234"
    assert deps.verify_patient_token(token, "other-secret") is None


@pytest.mark.parametrize(
    "value",
    [None, "", "P-ABCD1234", "P-ABCD1234.", ".sig", "not-a-pid.xxxx", 12],
)
def test_verify_rejects_malformed(value: object) -> None:
    assert deps.verify_patient_token(value, TEST_SECRET) is None  # type: ignore[arg-type]


def test_register_issues_signed_cookie(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C1)
    r = register(client, pid)
    assert r.status_code == 200
    expected = f"{pid}.{_expected_sig(TEST_SECRET, pid)}"
    header = r.headers["set-cookie"]
    assert header.startswith(f"{deps.PATIENT_COOKIE}={expected};")
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
    assert client.cookies.get(deps.PATIENT_COOKIE) == expected
    assert _questions(client, pid) == 200


def test_signed_with_other_secret_is_401(tmp_path: Path, fixed_today: str) -> None:
    with api_client(tmp_path) as c:
        pid = add_patient(c.app, courses=C1)
        _raw_cookie(c, deps.make_patient_token("another-secret", pid))
        assert _questions(c, pid) == 401


def test_bad_patient_cookies_are_401(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C1)
    other = add_patient(client.app, courses=C1)
    good_sig = _expected_sig(TEST_SECRET, pid)
    flipped = ("A" if good_sig[0] != "A" else "B") + good_sig[1:]
    cases = {
        "bare_pid": pid,
        "tampered_sig": f"{pid}.{flipped}",
        "other_pid_sig": f"{pid}.{_expected_sig(TEST_SECRET, other)}",
        "swapped_pid": f"{other}.{good_sig}",
        "padded": f"{pid}.{good_sig}=",
        "hex_sig": f"{pid}.{'0' * 64}",
        "no_sig": f"{pid}.",
        "lowercase_pid": f"{pid.lower()}.{good_sig}",
    }
    for label, value in cases.items():
        _raw_cookie(client, value)
        for path in (f"/api/patient/{pid}/questions", f"/api/patient/{pid}/entries"):
            r = client.get(path)
            assert r.status_code == 401, label
            assert r.json() == {"error": "not_logged_in"}, label
        r = client.post("/api/visit", json={"reception_no": "A-1"})
        assert r.status_code == 401, label


def test_signed_cookie_for_other_pid_is_403(client: TestClient) -> None:
    pid = add_patient(client.app, courses=C1)
    other = add_patient(client.app, courses=C1)
    assert register(client, pid).status_code == 200
    r = client.get(f"/api/patient/{other}/questions")
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden"}


def test_signed_cookie_for_unknown_patient_is_404(client: TestClient) -> None:
    _raw_cookie(client, deps.make_patient_token(TEST_SECRET, "P-ZZZZZZZZ"))
    r = client.get("/api/patient/P-ZZZZZZZZ/questions")
    assert r.status_code == 404
    assert r.json() == {"error": "unknown_patient"}


# ---------------------------------------------------------------------------
# 登録の試行回数の上限
# ---------------------------------------------------------------------------


def test_eleventh_failure_is_429(client: TestClient, clock: Clock) -> None:
    for _ in range(deps.REGISTER_MAX_FAILURES):
        assert _fail(client) == 404
    r = client.post("/api/patient/register", json={"pid": "P-ZZZZZZZZ"})
    assert r.status_code == 429
    assert r.json() == {"error": "too_many_attempts"}


def test_limited_client_cannot_register_even_valid_pid(
    client: TestClient, clock: Clock
) -> None:
    pid = add_patient(client.app, courses=C1)
    for _ in range(deps.REGISTER_MAX_FAILURES):
        _fail(client)
    r = register(client, pid)
    assert r.status_code == 429
    assert deps.PATIENT_COOKIE not in client.cookies


def test_limit_lifts_after_window(client: TestClient, clock: Clock) -> None:
    pid = add_patient(client.app, courses=C1)
    for _ in range(deps.REGISTER_MAX_FAILURES):
        _fail(client)
    clock.advance(timedelta(minutes=9, seconds=59))
    assert _fail(client) == 429
    clock.advance(timedelta(seconds=2))
    assert register(client, pid).status_code == 200


def test_window_slides(client: TestClient, clock: Clock) -> None:
    """古い失敗から順に外れる（10 分より前の失敗は数えない）。"""
    for _ in range(5):
        _fail(client)
    clock.advance(timedelta(minutes=6))
    for _ in range(5):
        assert _fail(client) == 404
    assert _fail(client) == 429
    clock.advance(timedelta(minutes=4, seconds=1))  # 最初の 5 回が外れる
    for _ in range(5):
        assert _fail(client) == 404
    assert _fail(client) == 429


def test_success_is_not_counted(client: TestClient, clock: Clock) -> None:
    pid = add_patient(client.app, courses=C1)
    for _ in range(30):
        assert register(client, pid).status_code == 200
    for _ in range(deps.REGISTER_MAX_FAILURES):
        assert _fail(client) == 404
    assert _fail(client) == 429


def test_invalid_body_is_not_counted(client: TestClient, clock: Clock) -> None:
    for _ in range(20):
        r = client.post("/api/patient/register", json={"pid": 1})
        assert r.status_code == 422
    assert _fail(client) == 404


def test_malformed_pid_counts_as_failure(client: TestClient, clock: Clock) -> None:
    for _ in range(deps.REGISTER_MAX_FAILURES):
        r = client.post("/api/patient/register", json={"pid": "garbage"})
        assert r.status_code == 404
    assert _fail(client) == 429


def test_limit_is_per_client_host(client: TestClient, clock: Clock) -> None:
    for _ in range(deps.REGISTER_MAX_FAILURES):
        _fail(client)
    assert _fail(client) == 429
    other = TestClient(client.app, client=("198.51.100.7", 50000))
    assert (
        other.post("/api/patient/register", json={"pid": "P-ZZZZZZZZ"}).status_code
        == 404
    )


def test_limit_state_is_per_app(tmp_path: Path, fixed_today: str, clock: Clock) -> None:
    with api_client(tmp_path / "a") as first:
        for _ in range(deps.REGISTER_MAX_FAILURES):
            _fail(first)
        assert _fail(first) == 429
    with api_client(tmp_path / "b") as second:
        assert _fail(second) == 404


# ---------------------------------------------------------------------------
# 上限の部品（純粋な振る舞い）
# ---------------------------------------------------------------------------


def test_attempt_limiter_counts_failures_in_window() -> None:
    limiter = deps.AttemptLimiter(max_failures=2, window=timedelta(minutes=10))
    assert not limiter.is_blocked("a", START)
    limiter.record_failure("a", START)
    limiter.record_failure("a", START + timedelta(minutes=1))
    assert limiter.is_blocked("a", START + timedelta(minutes=1))
    assert not limiter.is_blocked("b", START + timedelta(minutes=1))
    assert not limiter.is_blocked("a", START + timedelta(minutes=10, seconds=1))


def test_attempt_limiter_forgets_idle_clients() -> None:
    limiter = deps.AttemptLimiter(max_failures=2, window=timedelta(minutes=10))
    for i in range(50):
        limiter.record_failure(f"c{i}", START)
    later = START + timedelta(minutes=11)
    limiter.record_failure("fresh", later)
    limiter.prune(later)
    assert limiter.tracked_clients() == 1
