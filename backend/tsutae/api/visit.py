"""受診の受付（docs/architecture.md §8 `POST /api/visit`・§8b）。

- Cookie の患者で受診を作る（status=generating、course_no は今コース、
  expires_at = now + report_ttl_hours）。今コースが無ければ 409 no_course
- 受付番号は NFKC → 前後の空白除去だけで正規化し 1〜32 字（制御文字は不可）
- 変換は BackgroundTasks で。新しい接続を開き、`app.state.runner_factory()` の runner で
  `tsutae.pipeline.service.generate_visit_report` を呼ぶ（呼ぶときに属性を引くので
  テストで差し替えられる）。例外は外へ出さず（型名だけログ）、生成中のままなら failed
"""

from __future__ import annotations

import logging
import sqlite3
import unicodedata
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, ConfigDict, Field

from tsutae import db
from tsutae.api.deps import ApiError, AppSettings, Conn, current_patient
from tsutae.config import Settings, now, today
from tsutae.course import CourseValidationError, current_course
from tsutae.db import VisitClosedError
from tsutae.pipeline import service

__all__ = ["RECEPTION_NO_MAX", "normalize_reception_no", "router", "run_generation"]

router = APIRouter()

RECEPTION_NO_MAX = 32
_log = logging.getLogger(__name__)


class VisitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reception_no: str = Field(max_length=256)


def normalize_reception_no(value: str) -> str | None:
    """NFKC → 前後の空白除去。1〜32 字で制御文字を含まなければその文字列、違えば None。"""
    cleaned = unicodedata.normalize("NFKC", value).strip()
    if not 1 <= len(cleaned) <= RECEPTION_NO_MAX:
        return None
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in cleaned):
        return None
    return cleaned


def _current_course_no(conn: sqlite3.Connection, pid: str) -> int:
    try:
        course = current_course(db.list_courses(conn, pid), today())
    except CourseValidationError as exc:
        raise ApiError(400, exc.code) from exc
    if course is None:
        raise ApiError(409, "no_course")
    return course.course_no


@router.post("/api/visit")
def create_visit(
    body: VisitIn,
    background: BackgroundTasks,
    request: Request,
    conn: Conn,
    settings: AppSettings,
) -> dict[str, Any]:
    patient = current_patient(request, conn)
    reception_no = normalize_reception_no(body.reception_no)
    if reception_no is None:
        raise ApiError(422, "invalid_input")
    course_no = _current_course_no(conn, patient["id"])
    visit_id = db.create_visit(
        conn,
        patient["id"],
        reception_no,
        today(),
        now() + timedelta(hours=settings.report_ttl_hours),
        course_no,
    )
    background.add_task(
        run_generation, settings, request.app.state.runner_factory, visit_id
    )
    return {"ok": True, "message_key": "visit.done"}


def _fail_if_generating(conn: sqlite3.Connection, visit_id: int) -> None:
    """生成中のまま残った受診を failed にする（印刷済み・期限切れには触らない）。"""
    try:
        visit = db.get_visit(conn, visit_id)
        if visit is None or visit["reception_no"] is None:
            return
        if visit["status"] == "generating":
            db.set_visit_status(conn, visit_id, "failed")
    except (sqlite3.Error, VisitClosedError, ValueError, LookupError) as exc:
        _log.warning("visit %s: failed にできない: %s", visit_id, type(exc).__name__)


async def run_generation(
    settings: Settings, runner_factory: Callable[[], Any], visit_id: int
) -> None:
    """バックグラウンドで1回の生成を回す（自分の接続を開いて閉じる）。"""
    try:
        conn = db.connect(settings.db_path)
    except sqlite3.Error as exc:
        _log.warning("visit %s: DB を開けない: %s", visit_id, type(exc).__name__)
        return
    try:
        await service.generate_visit_report(
            conn, visit_id, runner=runner_factory(), settings=settings
        )
    except Exception as exc:  # noqa: BLE001 — バックグラウンドの例外は外へ出さない
        _log.warning("visit %s: 生成に失敗: %s", visit_id, type(exc).__name__)
        _fail_if_generating(conn, visit_id)
    finally:
        conn.close()
