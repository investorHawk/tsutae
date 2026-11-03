"""医師 API（docs/architecture.md §8 医師・§8b。Skill の書き換えは doctor_skills.py）。

- ログインはクライアントごとに失敗（bad_password）が 10 分で 5 回、全体で 30 回に
  達したら、以降の試行を 429 too_many_attempts で断る（正しいパスワードでも断る。
  成功・422 は数えない。`deps.login_limiter`。キーの前提は deps の説明を参照）
- ログイン・ログアウト以外の全経路で医師 Cookie を検査する（`require_doctor`。
  無い・改ざん・期限切れは 401 not_logged_in。本文の検証より先に走る）。ログアウトは
  Cookie を消すだけなので検査しない（失効後でもログアウトできる）
- `GET /visits`・`GET /visits/{id}/report`・`GET /visits/{id}/unprocessed` の前に
  `purge_expired`。印刷済み・期限切れ（受付番号を消した受診）は一覧に載せず、
  レポートと未処理は 404
- レポートは `HTMLResponse` に `Cache-Control: no-store` と CSP
- 未処理（D6）は記録の原文を返す（院内画面だけ。紙には載せない）
- `POST /courses` は保存前に既存＋新規で `validate_courses`（矛盾は 400 `{"error": code}`）
- 本文つきの `POST /patients`・`POST /courses` は Content-Type が application/json で
  なければ 415 `{"error": "unsupported_media_type"}`（`require_json_body`。Cookie の検査の
  後、本文の検証の前）。本文の無い POST（printed）は frontend が Content-Type を付けない
  ので対象外
- 状態を変える POST（login を除く。本文の無い printed・logout も）は
  `require_same_origin`（Sec-Fetch-Site が cross-site・same-site、または Origin が
  Host・public_base_url の origin と違えば 403 `{"error": "cross_origin"}`。Cookie の
  検査の後、本文の検証の前）。GET は見ない
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from tsutae import db
from tsutae.api.deps import (
    ApiError,
    AppSettings,
    Conn,
    check_doctor_password,
    clear_doctor_cookie,
    client_key,
    is_patient_id,
    login_limiter,
    require_doctor,
    require_json_body,
    require_same_origin,
    set_doctor_cookie,
)
from tsutae.config import Settings, now
from tsutae.course import CourseValidationError, validate_courses
from tsutae.schemas import Course, Regimen

__all__ = ["REPORT_HEADERS", "register_url", "router"]

router = APIRouter(prefix="/api/doctor")
# require_same_origin は GET を見ないので、ルーター全体に付ける（POST の付け忘れを防ぐ）
_protected = APIRouter(
    dependencies=[Depends(require_doctor), Depends(require_same_origin)]
)

REPORT_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    ),
}
_EVENT_FIELDS = (
    "event",
    "hook_name",
    "agent_type",
    "tool_name",
    "decision",
    "duration_ms",
)
VisitId = Annotated[int, Path(ge=1, le=2**62)]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(max_length=1024)


class PatientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regimen: Regimen


# ---------------------------------------------------------------------------
# ログイン・ログアウト（Cookie の検査なし）
# ---------------------------------------------------------------------------


@router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, settings: AppSettings
) -> dict[str, bool]:
    limiter = login_limiter(request.app)
    key = client_key(request)
    at = now()
    if limiter.is_blocked(key, at):
        raise ApiError(429, "too_many_attempts")
    if not check_doctor_password(body.password, settings):
        limiter.record_failure(key, at)
        raise ApiError(401, "bad_password")
    set_doctor_cookie(response, settings)
    return {"ok": True}


@router.post("/logout", dependencies=[Depends(require_same_origin)])
def logout(response: Response) -> dict[str, bool]:
    clear_doctor_cookie(response)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 患者・コース（D1・D2）
# ---------------------------------------------------------------------------


def register_url(settings: Settings, pid: str) -> str:
    """`{public_base_url}/register?pid=<id>`（QR はフロントで描く）。"""
    base = settings.public_base_url.rstrip("/")
    return f"{base}/register?pid={quote(pid, safe='')}"


def _patient_or_404(conn: sqlite3.Connection, pid: str) -> dict[str, Any]:
    patient = db.get_patient(conn, pid) if is_patient_id(pid) else None
    if patient is None:
        raise ApiError(404, "unknown_patient")
    return patient


@_protected.get("/patients")
def list_patients(conn: Conn, settings: AppSettings) -> dict[str, Any]:
    return {
        "patients": [
            {
                "id": p["id"],
                "regimen": p["regimen"],
                "created_at": p["created_at"].isoformat(),
                "register_url": register_url(settings, p["id"]),
            }
            for p in db.list_patients(conn)
        ]
    }


@_protected.post("/patients", dependencies=[Depends(require_json_body)])
def create_patient(
    body: PatientIn, conn: Conn, settings: AppSettings
) -> dict[str, str]:
    pid = db.create_patient(conn, body.regimen)
    return {"id": pid, "register_url": register_url(settings, pid)}


@_protected.get("/patients/{pid}/courses")
def list_courses(pid: str, conn: Conn) -> dict[str, Any]:
    patient = _patient_or_404(conn, pid)
    courses = db.list_courses(conn, patient["id"])
    return {"courses": [c.model_dump(mode="json") for c in courses]}


@_protected.post("/courses", dependencies=[Depends(require_json_body)])
def save_course(body: Course, conn: Conn) -> dict[str, Any]:
    """既存＋新規（同じ course_no は置き換え）で矛盾が無ければ保存する。"""
    patient = _patient_or_404(conn, body.patient_id)
    new = body.model_copy(update={"id": None})  # 送られた id は使わない
    existing = db.list_courses(conn, patient["id"])
    merged = [c for c in existing if c.course_no != new.course_no] + [new]
    try:
        validate_courses(merged)
    except CourseValidationError as exc:
        raise ApiError(400, exc.code) from exc
    return db.upsert_course(conn, new).model_dump(mode="json")


# ---------------------------------------------------------------------------
# 受診（D3・D5・D6）
# ---------------------------------------------------------------------------


def _visit_or_404(conn: sqlite3.Connection, vid: int) -> dict[str, Any]:
    visit = db.get_visit(conn, vid)
    if visit is None:
        raise ApiError(404, "not_found")
    return visit


def _open_visit(conn: sqlite3.Connection, vid: int) -> dict[str, Any]:
    """期限切れを消してから読む。印刷済み・期限切れ（受付番号なし）は 404。"""
    db.purge_expired(conn, now())
    visit = _visit_or_404(conn, vid)
    if visit["reception_no"] is None or visit["status"] == "printed":
        raise ApiError(404, "not_found")
    return visit


def _unprocessed(conn: sqlite3.Connection, vid: int) -> list[Any]:
    timeline = db.get_timeline(conn, vid)
    return [] if timeline is None else list(timeline.unprocessed_entries)


def _visit_summary(conn: sqlite3.Connection, visit: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": visit["id"],
        "reception_no": visit["reception_no"],
        "patient_id": visit["patient_id"],
        "status": visit["status"],
        "fallback": visit["fallback"],
        "created_at": visit["created_at"].isoformat(),
        "expires_at": visit["expires_at"].isoformat(),
        "unprocessed_count": len(_unprocessed(conn, visit["id"])),
    }


@_protected.get("/visits")
def list_visits(conn: Conn) -> dict[str, Any]:
    """印刷待ちの一覧（受付順）。期限切れを消してから、受付番号の残る受診だけ。

    出るのは generating・ready・failed。印刷済み・期限切れ（受付番号を消した受診）は
    載せない（仮名IDを出し続けない。D5 のイベントは経路の id で引ける）。
    """
    db.purge_expired(conn, now())
    visits = db.list_visits(conn, active_only=True)
    return {"visits": [_visit_summary(conn, v) for v in visits]}


@_protected.get("/visits/{vid}/report", response_class=HTMLResponse)
def get_report(vid: VisitId, conn: Conn) -> HTMLResponse:
    _open_visit(conn, vid)
    saved = db.get_report(conn, vid)
    if saved is None:
        raise ApiError(404, "not_found")
    html, _data = saved
    return HTMLResponse(html, headers=REPORT_HEADERS)


@_protected.post("/visits/{vid}/printed")
def mark_printed(vid: VisitId, conn: Conn) -> dict[str, bool]:
    """レポート・変換結果・受付番号を消して printed にする（何度呼んでもよい）。"""
    try:
        db.mark_printed(conn, vid)
    except db.NotFoundError as exc:
        raise ApiError(404, "not_found") from exc
    return {"ok": True}


@_protected.get("/visits/{vid}/unprocessed")
def list_unprocessed(vid: VisitId, conn: Conn) -> dict[str, Any]:
    """D6: 送信から外した記録の原文（伏せ字前）と規則名。"""
    visit = _open_visit(conn, vid)
    entries = []
    for item in _unprocessed(conn, vid):
        entry = db.get_entry(conn, item.entry_id)
        if entry is None or entry.patient_id != visit["patient_id"]:
            continue
        entries.append(
            {
                "entry_id": entry.id,
                "record_date": entry.record_date.isoformat(),
                "reason": item.reason,
                "text": entry.free_text or "",
            }
        )
    return {"entries": entries}


@_protected.get("/pipeline/{vid}/events")
def pipeline_events(vid: VisitId, conn: Conn) -> dict[str, Any]:
    """D5（ポーリング）。ログには文面が無い。トークン・費用は返さない。"""
    visit = _visit_or_404(conn, vid)
    logs = db.list_pipeline_logs(conn, "visit", vid)
    return {
        "status": visit["status"],
        "events": [
            {"ts": log["ts"].isoformat(), **{k: log[k] for k in _EVENT_FIELDS}}
            for log in logs
        ],
    }


router.include_router(_protected)
