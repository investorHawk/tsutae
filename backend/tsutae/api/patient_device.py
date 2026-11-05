"""スマホ保存の患者 API（docs/plan-device-records.md §5）。Cookie `tsutae_pid` で識別する。

記録の中身はスマホに置くので、ここの経路の本文に回答・自由記載の欄は無い（受付だけが受け取る。
アーキテクチャテストで検査）。時刻はサーバーの時計（端末の時計は使わない）。

- `POST /{pid}/record-marks`（本文なし）: 今日の印を付け、record_date・recorded_at を返す
- `POST /{pid}/record-marks/undo`（recorded_at・clear_mark）: 押し間違いの取り消し。サーバーは
  記録の種類を持たないので、種類は端末が見る。recorded_at から UNDO_WINDOW 以内で、その後に
  受付が無く、その記録を受付で受け取っていないときだけ通す（外れれば 409 not_undoable）。
  clear_mark（その日に端末の記録が他に無い）なら印を消す。他の時刻の印があれば（別の端末の分）
  残す。端末の記録を消すのは、この応答を見た端末
- `GET /{pid}/visit-window`: 受診で送る範囲（`visit_entries.visit_window_of`）
- `GET /{pid}/visit-days`: 受診日と受付の時刻だけ（受付番号・状態は返さない）
- `POST /{pid}/unregister`（endpoint か null）: この端末の通知の登録と Cookie を消す。
  日付の印は消さない（他の端末と D1 が使う）
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from tsutae import db
from tsutae.api.deps import (
    ApiError,
    Conn,
    clear_patient_cookie,
    require_patient,
)
from tsutae.api.patient_push import ENDPOINT_MAX
from tsutae.api.visit_entries import visit_window_of
from tsutae.config import now, to_jst_date

__all__ = ["UNDO_WINDOW", "router"]

router = APIRouter(prefix="/api/patient")

UNDO_WINDOW = timedelta(minutes=10)  # 「つらくて書けない」を取り消せる長さ


class UndoMarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recorded_at: AwareDatetime
    clear_mark: bool


class UnregisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str | None = Field(max_length=ENDPOINT_MAX)


@router.post("/{pid}/record-marks")
def add_record_mark(pid: str, request: Request, conn: Conn) -> dict[str, str]:
    patient = require_patient(pid, request, conn)
    current = now()
    # ミリ秒に揃える: ブラウザの Date を通っても同じ時刻に戻り、取り消しの比較がずれない
    at = current.replace(microsecond=current.microsecond // 1000 * 1000)
    db.add_record_mark(conn, patient["id"], at)
    return {
        "record_date": to_jst_date(at).isoformat(),
        "recorded_at": at.isoformat(timespec="microseconds"),
    }


@router.post("/{pid}/record-marks/undo")
def undo_record_mark(
    pid: str, body: UndoMarkIn, request: Request, conn: Conn
) -> dict[str, bool]:
    patient = require_patient(pid, request, conn)
    elapsed = now() - body.recorded_at
    if not timedelta(0) <= elapsed <= UNDO_WINDOW:
        raise ApiError(409, "not_undoable")
    if not db.undo_record_mark(
        conn, patient["id"], body.recorded_at, clear_mark=body.clear_mark
    ):
        raise ApiError(409, "not_undoable")
    return {"ok": True}


@router.get("/{pid}/visit-window")
def visit_window(pid: str, request: Request, conn: Conn) -> dict[str, str]:
    patient = require_patient(pid, request, conn)
    window = visit_window_of(conn, patient["id"])
    return {"start": window.start.isoformat(), "end": window.end.isoformat()}


@router.get("/{pid}/visit-days")
def visit_days(pid: str, request: Request, conn: Conn) -> dict[str, Any]:
    """受診日（受付のあった日）と受付の時刻（新しい順。これまでの記録の区切りに使う）。"""
    patient = require_patient(pid, request, conn)
    return {
        "visits": [
            {
                "visit_date": d["visit_date"].isoformat(),
                "received_at": d["received_at"].isoformat(),
            }
            for d in db.list_visit_days(conn, patient["id"])
        ]
    }


@router.post("/{pid}/unregister")
def unregister(
    pid: str, body: UnregisterIn, request: Request, response: Response, conn: Conn
) -> dict[str, bool]:
    patient = require_patient(pid, request, conn)
    if body.endpoint is not None:
        db.delete_push_subscription(conn, patient["id"], body.endpoint)
    clear_patient_cookie(response)
    return {"ok": True}
