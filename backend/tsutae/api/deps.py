"""API の共通部品（docs/architecture.md §8b）。患者 API が使うので pipeline・report を import しない。

- 接続はリクエストごと（`Conn` の Depends で開いて閉じる）
- エラーは `ApiError(status, code)` を投げると `{"error": code}` になる。入力の検証
  エラー（`RequestValidationError`）は 422 `{"error": "invalid_input"}`（入力の文面を返さない）
- 想定外の例外は 500 `{"error": "internal_error"}`。このモジュールのログ
  （`tsutae.api.deps`）には固定のイベント名・例外の型名・相関ID（`X-Error-Id`
  ヘッダでも返す）だけを残す（例外の文面・traceback・入力は残さない。患者の文面を
  含みうるため）。注意: Starlette の ServerErrorMiddleware はこの後で例外を投げ直す
  ので、サーバ（uvicorn）側のログには traceback が出うる
- 患者 Cookie `tsutae_pid` = 仮名ID。医師 Cookie `tsutae_doctor` = `<発行時刻(秒)>.<HMAC-SHA256>`
  （secret_key で署名、12時間で失効）。どちらも HttpOnly・SameSite=Lax。Secure は
  public_base_url が https のときだけ
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import sqlite3
import uuid
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
    "Conn",
    "DOCTOR_COOKIE",
    "DOCTOR_TOKEN_TTL",
    "ERROR_ID_HEADER",
    "INTERNAL_ERROR_EVENT",
    "PATIENT_COOKIE",
    "PATIENT_ID_PATTERN",
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
    "require_doctor",
    "require_patient",
    "set_doctor_cookie",
    "set_patient_cookie",
    "verify_doctor_token",
]

PATIENT_COOKIE = "tsutae_pid"
DOCTOR_COOKIE = "tsutae_doctor"
PATIENT_COOKIE_MAX_AGE = 180 * 24 * 3600
DOCTOR_TOKEN_TTL = timedelta(hours=12)
ERROR_ID_HEADER = "X-Error-Id"
INTERNAL_ERROR_EVENT = "api.internal_error"
_log = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"(?P<issued>[0-9]{1,12})\.(?P<sig>[0-9a-f]{64})")
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


def set_patient_cookie(response: Response, pid: str, settings: Settings) -> None:
    response.set_cookie(
        PATIENT_COOKIE,
        pid,
        max_age=PATIENT_COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_secure(settings),
    )


def clear_patient_cookie(response: Response) -> None:
    response.delete_cookie(PATIENT_COOKIE, path="/", httponly=True, samesite="lax")


def cookie_patient_id(request: Request) -> str:
    """Cookie の仮名ID。無い・形が違えば 401 not_logged_in。"""
    value = request.cookies.get(PATIENT_COOKIE)
    if not is_patient_id(value):
        raise ApiError(401, "not_logged_in")
    assert value is not None
    return value


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
