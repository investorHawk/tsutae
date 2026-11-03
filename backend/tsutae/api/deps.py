"""API の共通部品（docs/architecture.md §8b）。患者 API が使うので pipeline・report を import しない。

- 接続はリクエストごと（`Conn` の Depends で開いて閉じる）
- エラーは `ApiError(status, code)` を投げると `{"error": code}` になる。入力の検証
  エラー（`RequestValidationError`）は 422 `{"error": "invalid_input"}`（入力の文面を返さない）
- 想定外の例外は 500 `{"error": "internal_error"}`。このモジュールのログ
  （`tsutae.api.deps`）には固定のイベント名・例外の型名・相関ID（`X-Error-Id`
  ヘッダでも返す）だけを残す（例外の文面・traceback・入力は残さない。患者の文面を
  含みうるため）。注意: Starlette の ServerErrorMiddleware はこの後で例外を投げ直す
  ので、サーバ（uvicorn）側のログには traceback が出うる
- 患者 Cookie `tsutae_pid` = `<仮名ID>.<base64url(HMAC-SHA256(secret_key, "patient:" +
  仮名ID))>`（パディングなし 43 字。署名が無い・違う・形が違えば 401）。発行は
  `POST /api/patient/register` だけ。医師 Cookie `tsutae_doctor` =
  `<発行時刻(秒)>.<HMAC-SHA256>`（secret_key で署名、12時間で失効）。どちらも
  HttpOnly・SameSite=Lax。Secure は public_base_url が https のときだけ
- 登録の試行回数の上限は `AttemptLimiter`（プロセス内。`register_limiter(app)` で
  app.state に1つ置く）
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import sqlite3
import threading
import uuid
from collections import deque
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from tsutae import db
from tsutae.config import Settings, now
from tsutae.db import PATIENT_ID_PATTERN  # 仮名IDの形（db と同じもの。再公開する）

__all__ = [
    "AppSettings",
    "ApiError",
    "AttemptLimiter",
    "Conn",
    "DOCTOR_COOKIE",
    "DOCTOR_TOKEN_TTL",
    "ERROR_ID_HEADER",
    "INTERNAL_ERROR_EVENT",
    "PATIENT_COOKIE",
    "PATIENT_ID_PATTERN",
    "REGISTER_MAX_FAILURES",
    "REGISTER_WINDOW",
    "check_doctor_password",
    "clear_doctor_cookie",
    "clear_patient_cookie",
    "cookie_patient_id",
    "current_patient",
    "get_conn",
    "get_settings_dep",
    "install_error_handlers",
    "is_patient_id",
    "make_doctor_token",
    "make_patient_token",
    "register_limiter",
    "require_doctor",
    "require_patient",
    "set_doctor_cookie",
    "set_patient_cookie",
    "verify_doctor_token",
    "verify_patient_token",
]

PATIENT_COOKIE = "tsutae_pid"
DOCTOR_COOKIE = "tsutae_doctor"
PATIENT_COOKIE_MAX_AGE = 180 * 24 * 3600
DOCTOR_TOKEN_TTL = timedelta(hours=12)
ERROR_ID_HEADER = "X-Error-Id"
INTERNAL_ERROR_EVENT = "api.internal_error"
_log = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"(?P<issued>[0-9]{1,12})\.(?P<sig>[0-9a-f]{64})")
_PATIENT_TOKEN_RE = re.compile(r"(?P<pid>[^.]{1,64})\.(?P<sig>[A-Za-z0-9_-]{43})")
REGISTER_MAX_FAILURES = 10
REGISTER_WINDOW = timedelta(minutes=10)
_LIMITER_SWEEP_AT = 1024  # 追う相手がこれより多くなったら古いものを掃除する
_LIMITER_STATE = "register_limiter"
_limiter_init_lock = threading.Lock()
_HTTP_CODES = {
    400: "bad_request",
    401: "not_logged_in",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "invalid_input",
}


class ApiError(Exception):
    """`{"error": code}` を status で返す。code は文面ではなく短いコード。"""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def error_response(status_code: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status_code)


async def _api_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(exc.status_code, exc.code)


async def _validation_error(_request: Request, _exc: Exception) -> JSONResponse:
    return error_response(422, "invalid_input")


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code)


async def _internal_error(_request: Request, exc: Exception) -> JSONResponse:
    """型名と相関IDだけをログに残す（exc_info を付けない: 文面が traceback に出る）。"""
    error_id = uuid.uuid4().hex
    _log.error(
        "%s error_id=%s error_type=%s",
        INTERNAL_ERROR_EVENT,
        error_id,
        type(exc).__name__,
    )
    response = error_response(500, "internal_error")
    response.headers[ERROR_ID_HEADER] = error_id
    return response


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, _internal_error)
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)


# ---------------------------------------------------------------------------
# 設定と接続
# ---------------------------------------------------------------------------


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(get_settings_dep(request).db_path)
    try:
        yield conn
    finally:
        conn.close()


AppSettings = Annotated[Settings, Depends(get_settings_dep)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _secure(settings: Settings) -> bool:
    return settings.public_base_url.lower().startswith("https://")


# ---------------------------------------------------------------------------
# 患者
# ---------------------------------------------------------------------------


def is_patient_id(value: object) -> bool:
    return isinstance(value, str) and PATIENT_ID_PATTERN.fullmatch(value) is not None


def _sign_patient(secret: str, pid: str) -> str:
    message = f"patient:{pid}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def make_patient_token(secret: str, pid: str) -> str:
    """患者 Cookie の値 `<pid>.<base64url(HMAC-SHA256(secret, "patient:" + pid))>`。"""
    if not is_patient_id(pid):
        raise ValueError("pid の形が違う")
    return f"{pid}.{_sign_patient(secret, pid)}"


def verify_patient_token(token: str | None, secret: str) -> str | None:
    """署名が正しければ仮名ID、そうでなければ None（旧形式の pid だけも None）。"""
    if not isinstance(token, str):
        return None
    match = _PATIENT_TOKEN_RE.fullmatch(token)
    if match is None or not is_patient_id(match["pid"]):
        return None
    expected = _sign_patient(secret, match["pid"])
    if not hmac.compare_digest(expected.encode(), match["sig"].encode()):
        return None
    return match["pid"]


def set_patient_cookie(response: Response, pid: str, settings: Settings) -> None:
    response.set_cookie(
        PATIENT_COOKIE,
        make_patient_token(settings.secret_key, pid),
        max_age=PATIENT_COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_secure(settings),
    )


def clear_patient_cookie(response: Response) -> None:
    response.delete_cookie(PATIENT_COOKIE, path="/", httponly=True, samesite="lax")


def cookie_patient_id(request: Request) -> str:
    """署名つき Cookie の仮名ID。無い・署名が違う・形が違えば 401 not_logged_in。"""
    secret = get_settings_dep(request).secret_key
    pid = verify_patient_token(request.cookies.get(PATIENT_COOKIE), secret)
    if pid is None:
        raise ApiError(401, "not_logged_in")
    return pid


def current_patient(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """Cookie の患者（DB に無ければ 404 unknown_patient）。"""
    pid = cookie_patient_id(request)
    patient = db.get_patient(conn, pid)
    if patient is None:
        raise ApiError(404, "unknown_patient")
    return patient


def require_patient(
    pid: str, request: Request, conn: sqlite3.Connection
) -> dict[str, Any]:
    """経路の pid の患者。Cookie 無し 401、Cookie と違えば 403、DB に無ければ 404。"""
    cookie_pid = cookie_patient_id(request)
    if not hmac.compare_digest(cookie_pid.encode(), pid.encode()):
        raise ApiError(403, "forbidden")
    return current_patient(request, conn)


# ---------------------------------------------------------------------------
# 医師（HMAC-SHA256 で署名した発行時刻）
# ---------------------------------------------------------------------------


def _sign(secret: str, issued: str) -> str:
    return hmac.new(secret.encode(), issued.encode(), hashlib.sha256).hexdigest()


def make_doctor_token(secret: str, issued_at: datetime) -> str:
    issued = str(int(issued_at.timestamp()))
    return f"{issued}.{_sign(secret, issued)}"


def verify_doctor_token(token: str | None, secret: str, at: datetime) -> bool:
    """署名が正しく、発行から 12 時間以内（未来の発行は不可）なら True。"""
    if not isinstance(token, str):
        return False
    match = _TOKEN_RE.fullmatch(token)
    if match is None:
        return False
    expected = _sign(secret, match["issued"])
    if not hmac.compare_digest(expected, match["sig"]):
        return False
    age = at.timestamp() - int(match["issued"])
    return 0 <= age <= DOCTOR_TOKEN_TTL.total_seconds()


def check_doctor_password(given: str, settings: Settings) -> bool:
    if not isinstance(given, str) or not given:
        return False
    return hmac.compare_digest(given.encode(), settings.doctor_password.encode())


def set_doctor_cookie(
    response: Response, settings: Settings, issued_at: datetime | None = None
) -> None:
    token = make_doctor_token(settings.secret_key, issued_at or now())
    response.set_cookie(
        DOCTOR_COOKIE,
        token,
        max_age=int(DOCTOR_TOKEN_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=_secure(settings),
    )


def clear_doctor_cookie(response: Response) -> None:
    response.delete_cookie(DOCTOR_COOKIE, path="/", httponly=True, samesite="lax")


def require_doctor(request: Request) -> None:
    """Depends 用。医師 Cookie が無い・壊れている・失効なら 401 not_logged_in。"""
    settings = get_settings_dep(request)
    token = request.cookies.get(DOCTOR_COOKIE)
    if not verify_doctor_token(token, settings.secret_key, now()):
        raise ApiError(401, "not_logged_in")


# ---------------------------------------------------------------------------
# 登録の試行回数の上限（プロセス内）
# ---------------------------------------------------------------------------


class AttemptLimiter:
    """クライアントごとの失敗の時刻を窓の間だけ覚える。スレッドから呼んでよい。

    失敗が窓の中で max_failures 回に達したら `is_blocked` が True（次の試行を断る）。
    成功は数えない（記録しない）。
    """

    def __init__(self, max_failures: int, window: timedelta) -> None:
        if max_failures < 1 or window <= timedelta(0):
            raise ValueError("max_failures は 1 以上、window は正")
        self._max = max_failures
        self._window = window
        self._failures: dict[str, deque[datetime]] = {}
        self._lock = threading.Lock()

    def _drop_old(self, key: str, at: datetime) -> deque[datetime] | None:
        times = self._failures.get(key)
        if times is None:
            return None
        cutoff = at - self._window
        while times and times[0] <= cutoff:
            times.popleft()
        if not times:
            del self._failures[key]
            return None
        return times

    def is_blocked(self, key: str, at: datetime) -> bool:
        with self._lock:
            times = self._drop_old(key, at)
            return times is not None and len(times) >= self._max

    def record_failure(self, key: str, at: datetime) -> None:
        with self._lock:
            if len(self._failures) >= _LIMITER_SWEEP_AT:
                self._prune_locked(at)
            self._failures.setdefault(key, deque()).append(at)

    def prune(self, at: datetime) -> None:
        """窓の外の失敗だけになった相手を忘れる。"""
        with self._lock:
            self._prune_locked(at)

    def _prune_locked(self, at: datetime) -> None:
        for key in list(self._failures):
            self._drop_old(key, at)

    def tracked_clients(self) -> int:
        with self._lock:
            return len(self._failures)


def register_limiter(app: FastAPI) -> AttemptLimiter:
    """app.state の登録用の上限（無ければ作る。アプリごとに独立）。"""
    limiter = getattr(app.state, _LIMITER_STATE, None)
    if limiter is None:
        with _limiter_init_lock:
            limiter = getattr(app.state, _LIMITER_STATE, None)
            if limiter is None:
                limiter = AttemptLimiter(REGISTER_MAX_FAILURES, REGISTER_WINDOW)
                setattr(app.state, _LIMITER_STATE, limiter)
    return limiter
