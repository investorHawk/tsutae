"""API の共通部品（docs/architecture.md §8b）。患者 API が使うので pipeline・report を import しない。

- 接続はリクエストごと（`Conn` の Depends で開いて閉じる）
- エラーは `ApiError(status, code)` を投げると `{"error": code}` になる。入力の検証
  エラー（`RequestValidationError`）は 422 `{"error": "invalid_input"}`（入力の文面を返さない）
- 想定外の例外は 500 `{"error": "internal_error"}`。このモジュールのログ
  （`tsutae.api.deps`）には固定のイベント名・例外の型名・相関ID（`X-Error-Id`
  ヘッダでも返す）だけを残す（例外の文面・traceback・入力は残さない。患者の文面を
  含みうるため）。Starlette の ServerErrorMiddleware はこの後で例外を投げ直すが、
  最も外側の `tsutae.api.error_guard.SuppressServerErrors` が握りつぶすので、サーバ
  （uvicorn）のログに文面・traceback は出ない
- 患者 Cookie `tsutae_pid` = `<仮名ID>.<base64url(HMAC-SHA256(secret_key, "patient:" +
  仮名ID))>`（パディングなし 43 字。署名が無い・違う・形が違えば 401）。発行は
  `POST /api/patient/register` だけ。医師 Cookie `tsutae_doctor` =
  `<発行時刻(秒)>.<HMAC-SHA256>`（secret_key で署名、12時間で失効）。どちらも
  HttpOnly・SameSite=Lax。Secure は public_base_url が https のときだけ
- 試行回数の上限は `AttemptLimiter`（プロセス内）。登録用は `register_limiter(app)`、
  医師ログイン用は `login_limiter(app)` で app.state に1つずつ置く。キーは
  `client_key(request)`（request.client.host）。uvicorn は既定で 127.0.0.1 から来た
  要求の X-Forwarded-For を信用して client.host を書き換えるので、手前のプロキシが
  利用者の XFF を素通しすると1クライアントの上限は迂回できる。そのため全体の失敗の
  上限（max_total）も掛ける（あふれたら全員を断る。追う相手の数もこれで抑えられる）。
  公開するときは、信用するプロキシが XFF を上書きする（追記しない）こと、または
  uvicorn を `--no-proxy-headers` / `--forwarded-allow-ips` で絞ることが前提
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
    "LOGIN_MAX_FAILURES",
    "LOGIN_MAX_TOTAL",
    "LOGIN_WINDOW",
    "REGISTER_MAX_TOTAL",
    "client_key",
    "Conn",
    "DOCTOR_COOKIE",
    "DOCTOR_TOKEN_TTL",
    "ERROR_ID_HEADER",
    "INTERNAL_ERROR_EVENT",
    "JSON_MEDIA_TYPE",
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
    "is_json_media_type",
    "is_patient_id",
    "login_limiter",
    "make_doctor_token",
    "make_patient_token",
    "register_limiter",
    "require_doctor",
    "require_json_body",
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
REGISTER_MAX_TOTAL = 100  # 全クライアントの合計（XFF を回す迂回への歯止め）
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW = timedelta(minutes=10)
LOGIN_MAX_TOTAL = 30
_LIMITER_SWEEP_AT = 1024  # 追う相手がこれより多くなったら古いものを掃除する
_LIMITER_STATE = "register_limiter"
_LOGIN_LIMITER_STATE = "login_limiter"
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
# Content-Type（CSRF の追加の守り）
# ---------------------------------------------------------------------------

JSON_MEDIA_TYPE = "application/json"


def is_json_media_type(value: str | None) -> bool:
    """Content-Type の値が application/json か（`; charset=...` などの引数は見ない）。"""
    if not value:
        return False
    return value.split(";", 1)[0].strip().lower() == JSON_MEDIA_TYPE


def require_json_body(request: Request) -> None:
    """Depends 用。本文つきの POST で Content-Type が application/json でなければ 415。

    フォームや text/plain は CORS の preflight なしに別サイトから送れる（SameSite=Lax の
    Cookie に加えた守り）。経路の dependencies に置くと、ルーターの require_doctor の後・
    本文の検証（422）の前に走る。本文の無い POST には付けない（frontend は付けない）。
    """
    if not is_json_media_type(request.headers.get("content-type")):
        raise ApiError(415, "unsupported_media_type")


# ---------------------------------------------------------------------------
# 試行回数の上限（プロセス内。登録・医師ログイン）
# ---------------------------------------------------------------------------


def client_key(request: Request) -> str:
    """上限のキー（request.client.host。プロキシの前提はモジュールの説明を参照）。"""
    client = request.client
    return client.host if client is not None and client.host else "unknown"


class AttemptLimiter:
    """クライアントごとの失敗の時刻を窓の間だけ覚える。スレッドから呼んでよい。

    失敗が窓の中で max_failures 回に達したら `is_blocked` が True（次の試行を断る）。
    max_total を渡すと、全クライアントの失敗の合計が窓の中でそれに達したときも、
    どのキーでも True（キーを使い捨てにする迂回を止め、追う相手の数も抑える）。
    成功は数えない（記録しない）。
    """

    def __init__(
        self, max_failures: int, window: timedelta, *, max_total: int | None = None
    ) -> None:
        if max_failures < 1 or window <= timedelta(0):
            raise ValueError("max_failures は 1 以上、window は正")
        if max_total is not None and max_total < 1:
            raise ValueError("max_total は 1 以上")
        self._max = max_failures
        self._window = window
        self._max_total = max_total
        self._failures: dict[str, deque[datetime]] = {}
        self._all: deque[datetime] = deque()
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

    def _total_blocked(self, at: datetime) -> bool:
        if self._max_total is None:
            return False
        cutoff = at - self._window
        while self._all and self._all[0] <= cutoff:
            self._all.popleft()
        return len(self._all) >= self._max_total

    def is_blocked(self, key: str, at: datetime) -> bool:
        with self._lock:
            if self._total_blocked(at):
                return True
            times = self._drop_old(key, at)
            return times is not None and len(times) >= self._max

    def record_failure(self, key: str, at: datetime) -> None:
        with self._lock:
            if len(self._failures) >= _LIMITER_SWEEP_AT:
                self._prune_locked(at)
            self._failures.setdefault(key, deque()).append(at)
            if self._max_total is not None:
                self._all.append(at)

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


def _limiter_for(
    app: FastAPI, state_name: str, max_failures: int, window: timedelta, total: int
) -> AttemptLimiter:
    limiter = getattr(app.state, state_name, None)
    if limiter is None:
        with _limiter_init_lock:
            limiter = getattr(app.state, state_name, None)
            if limiter is None:
                limiter = AttemptLimiter(max_failures, window, max_total=total)
                setattr(app.state, state_name, limiter)
    return limiter


def register_limiter(app: FastAPI) -> AttemptLimiter:
    """app.state の登録用の上限（無ければ作る。アプリごとに独立）。"""
    return _limiter_for(
        app, _LIMITER_STATE, REGISTER_MAX_FAILURES, REGISTER_WINDOW, REGISTER_MAX_TOTAL
    )


def login_limiter(app: FastAPI) -> AttemptLimiter:
    """app.state の医師ログイン用の上限（登録用とは別のインスタンス）。"""
    return _limiter_for(
        app, _LOGIN_LIMITER_STATE, LOGIN_MAX_FAILURES, LOGIN_WINDOW, LOGIN_MAX_TOTAL
    )
