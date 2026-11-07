"""受診の受付（docs/architecture.md §8 `POST /api/visit`・§8b）。

- Cookie の患者で受診を作る（status=generating、course_no は今コース、
  expires_at = now + report_ttl_hours）。今コースが無ければ 409 no_course
- 受付番号は NFKC → 前後の空白除去だけで正規化し 1〜32 字（制御文字は不可）
- 本文の entries はスマホに置いた記録（plan-device-records §5.5。検査は `visit_entries`）。
  1件でも不正なら全体を 422 にして何も保存しない。受診の作成と記録の保存は同じトランザクション。
  同じ ID は二重にならない。本文が 5MB を超えたら 413（`body_limit`）
- 送り直し（タイムアウトの後など）: 同じ患者で、受付番号が残っていて期限内の受診が
  今日すでにあり、正規化した受付番号が同じなら、新しく作らず同じ応答を返す
  （`db.create_visit_once`）。新しい記録が無ければ生成も起動しない（status は問わない:
  failed でも作り直さない）。受付番号が違えば新しく作る
- 2台目のスマホ（plan-device-records §6）: 新しい記録が1件以上届いたら統合して、その患者の
  今日の開いた受診を番号を問わず変換し直す（番号を間違えて2行あっても、どちらも全ての記録で
  変換する）。ready・failed はすぐ、生成中は `run_generation` の終わりに1回だけ。自動は1受診
  `db.REGEN_AUTO_MAX` 回まで。超えたら記録だけ受け取る（D3 の「追加の記録あり」）。ログは
  `regenerate_requested`（decision `added_records`。文面なし）。その患者に今日の印刷済みの受診が
  あれば、どの番号でも 409 `already_printed`（何も保存しない。記録は端末に残る）
- 費用の歯止め: 1人の患者が1日に開ける受診は `db.MAX_OPEN_VISITS_PER_DAY` 件まで。超える新しい
  番号は 409 `too_many_visits`（何も保存しない。開いている番号への送信は通す）
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
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tsutae import db
from tsutae.api.deps import ApiError, AppSettings, Conn, current_patient
from tsutae.api.visit_entries import (
    MAX_VISIT_ENTRIES,
    VisitEntryIn,
    check_unique_ids,
    received_entries,
    visit_window_of,
)
from tsutae.config import Settings, now, today
from tsutae.db import VisitClosedError
from tsutae.pipeline import service
from tsutae.pipeline.logs import PipelineLogger

__all__ = [
    "REGENERATE_EVENT",
    "RECEPTION_NO_MAX",
    "normalize_reception_no",
    "router",
    "run_generation",
]

router = APIRouter()

RECEPTION_NO_MAX = 32
REGENERATE_EVENT = "regenerate_requested"
ADDED_RECORDS = "added_records"  # 記録が増えて自動で変換し直す（ログの decision）
RUN_KIND = "visit"
_log = logging.getLogger(__name__)


class VisitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reception_no: str = Field(max_length=256)
    entries: list[VisitEntryIn] = Field(
        default_factory=list, max_length=MAX_VISIT_ENTRIES
    )

    _unique_ids = field_validator("entries")(check_unique_ids)


def normalize_reception_no(value: str) -> str | None:
    """NFKC → 前後の空白除去。1〜32 字で制御文字を含まなければその文字列、違えば None。"""
    cleaned = unicodedata.normalize("NFKC", value).strip()
    if not 1 <= len(cleaned) <= RECEPTION_NO_MAX:
        return None
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in cleaned):
        return None
    return cleaned


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
    window = visit_window_of(conn, patient["id"])
    entries = received_entries(conn, patient["regimen"], body.entries, window)
    try:
        receipt = db.create_visit_once(
            conn,
            patient["id"],
            reception_no,
            today(),
            now() + timedelta(hours=settings.report_ttl_hours),
            window.course_no,
            entries,
        )
    except db.VisitAlreadyPrintedError as exc:
        raise ApiError(409, "already_printed") from exc
    except db.TooManyOpenVisitsError as exc:
        raise ApiError(409, "too_many_visits") from exc
    for visit_id in receipt.restarted:
        _log_added_records(conn, visit_id)
    new_visit = (receipt.visit_id,) if receipt.created else ()
    for visit_id in new_visit + receipt.restarted:
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


def _log_added_records(conn: sqlite3.Connection, visit_id: int) -> None:
    PipelineLogger(conn, RUN_KIND, visit_id).event(
        REGENERATE_EVENT, decision=ADDED_RECORDS
    )


async def _generate_once(
    conn: sqlite3.Connection,
    settings: Settings,
    runner_factory: Callable[[], Any],
    visit_id: int,
) -> None:
    try:
        await service.generate_visit_report(
            conn, visit_id, runner=runner_factory(), settings=settings
        )
    except Exception as exc:  # noqa: BLE001 — バックグラウンドの例外は外へ出さない
        _log.warning("visit %s: 生成に失敗: %s", visit_id, type(exc).__name__)
        _fail_if_generating(conn, visit_id)


def _take_next_round(conn: sqlite3.Connection, visit_id: int, counted: bool) -> bool:
    """生成中に記録が増えていて、自動の回数が残っていれば次の回を始めて True。"""
    try:
        taken = db.take_regen_pending(conn, visit_id, counted=counted)
    except sqlite3.Error as exc:
        _log.warning("visit %s: 次の回を始められない: %s", visit_id, type(exc).__name__)
        _fail_if_generating(conn, visit_id)
        return False
    if taken:
        _log_added_records(conn, visit_id)
    return taken


async def run_generation(
    settings: Settings,
    runner_factory: Callable[[], Any],
    visit_id: int,
    *,
    counted: bool = True,
) -> None:
    """バックグラウンドで生成を回す（自分の接続を開いて閉じる）。

    生成中に記録が増えていれば、もう1回回す。何件増えても1回で、回数には上限がある。
    counted=False は次の回を自動の回数に数えない（Claude を呼ばない回収。`api.orphans`）。
    """
    try:
        conn = db.connect(settings.db_path)
    except sqlite3.Error as exc:
        _log.warning("visit %s: DB を開けない: %s", visit_id, type(exc).__name__)
        return
    try:
        await _generate_once(conn, settings, runner_factory, visit_id)
        while _take_next_round(conn, visit_id, counted):
            await _generate_once(conn, settings, runner_factory, visit_id)
    finally:
        conn.close()
