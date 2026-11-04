"""医師 API: 未処理の記載（D6）の伏せ字（docs/architecture.md §8）。症例は全て合成。

医師は文を書かない。原文（生の自由記載）の中の伏せる区間だけを送る。区間は Python の
str の位置（code point）の [start, end)（`GET /unprocessed` の marks と同じ単位）。
サーバーが区間を検査し（範囲内・空でない・昇順・重ならない）、自分で伏せた文を作る。

- `POST /visits/{id}/masks/check {entry_id, spans}`: 区間を当てた後の、送られる文
  （masked_text）とまだ疑われる区間（suspects。masked_text の位置）を返す。保存しない。
  `sendable` はそのまま送れる、`confirmable` は「個人を特定する語は無いことを確かめた」で
  送れる（仮名ID・受付番号は確かめても送れない）
- `POST /visits/{id}/masks {entries: [{entry_id, send, spans, confirmed_clear}]}`:
  送る記録は医師の伏せ字を保存（確かめた記録は、今まだ疑われている区間ちょうどを
  サーバーが許す区間として記録）、送らない記録は消す。応答は `{ok, sendable}`
  （保存した記録のうち、変換で送られる件数）。この後に `POST /visits/{id}/regenerate`
- 対象の記録は、その受診の今の未処理（timeline の unprocessed）か、既に医師の伏せ字が
  ある記録だけ（それ以外は 404 unknown_entry）
- 区間が合わない 422 invalid_spans、確かめて送れない記録の confirmed_clear は 422
  not_confirmable、同じ記録が2回・空の entries は 422 invalid_input
- 受診が無い 404 not_found。印刷済み・期限切れは check が 404 not_found、保存が 409
  visit_closed（db の VisitClosedError）。生成中の保存は 409 generating
- ログ（run_kind=visit、文面なし。decision は `entry:<entries.id>` だけ）:
  `doctor_mask_saved`・`doctor_mask_confirmed`（確かめた）・`doctor_mask_removed`
- ルーターは `tsutae.api.doctor` の router に載る（医師 Cookie・同じオリジン・
  application/json の検査はそちらと同じ）
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from tsutae import db
from tsutae.api.deps import (
    ApiError,
    Conn,
    require_doctor,
    require_json_body,
    require_same_origin,
)
from tsutae.config import now
from tsutae.masking.manual import MAX_SPANS, ManualSpanError, Span
from tsutae.pipeline.logs import PipelineLogger, reason_code
from tsutae.pipeline.manual_review import (
    MaskReview,
    confirmed_mask,
    review_doctor_mask,
)
from tsutae.schemas import DoctorMask, Entry

__all__ = ["doctor_mask_view", "router"]

router = APIRouter(
    dependencies=[
        Depends(require_doctor),
        Depends(require_same_origin),
        Depends(require_json_body),
    ]
)

VisitId = Annotated[int, Path(ge=1, le=2**62)]
EntryId = Annotated[StrictInt, Field(ge=1, le=2**62)]
Position = Annotated[StrictInt, Field(ge=0, le=1_000_000)]
MAX_ENTRIES = 200
RUN_KIND = "visit"


class SpanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: Position
    end: Position


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: EntryId
    spans: list[SpanIn] = Field(default_factory=list, max_length=MAX_SPANS)


class MaskEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: EntryId
    send: StrictBool
    spans: list[SpanIn] = Field(default_factory=list, max_length=MAX_SPANS)
    confirmed_clear: StrictBool = False


class SaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[MaskEntryIn] = Field(min_length=1, max_length=MAX_ENTRIES)


def doctor_mask_view(mask: DoctorMask | None) -> dict[str, Any] | None:
    """`GET /unprocessed` の各記録の doctor_mask（区間と確かめ。許す区間は出さない）。"""
    if mask is None:
        return None
    return {
        "spans": [{"start": s.start, "end": s.end} for s in mask.spans],
        "confirmed_clear": mask.confirmed_clear,
    }


def _visit(conn: sqlite3.Connection, vid: int) -> dict[str, Any]:
    db.purge_expired(conn, now())
    visit = db.get_visit(conn, vid)
    if visit is None:
        raise ApiError(404, "not_found")
    return visit


def _is_open(visit: dict[str, Any]) -> bool:
    return visit["reception_no"] is not None and visit["status"] != "printed"


def _eligible_ids(conn: sqlite3.Connection, vid: int) -> set[int]:
    timeline = db.get_timeline(conn, vid)
    ids = {u.entry_id for u in timeline.unprocessed_entries} if timeline else set()
    return ids | set(db.list_doctor_masks(conn, vid))


def _entry(
    conn: sqlite3.Connection, visit: dict[str, Any], entry_id: int, eligible: set[int]
) -> Entry:
    entry = db.get_entry(conn, entry_id) if entry_id in eligible else None
    if entry is None or entry.patient_id != visit["patient_id"]:
        raise ApiError(404, "unknown_entry")
    if not entry.free_text:
        raise ApiError(404, "unknown_entry")
    return entry


def _spans(items: list[SpanIn]) -> list[Span]:
    return [(s.start, s.end) for s in items]


def _review(visit: dict[str, Any], entry: Entry, spans: list[Span]) -> MaskReview:
    literals = [visit["patient_id"], visit["reception_no"] or ""]
    try:
        return review_doctor_mask(entry.free_text or "", spans, literals)
    except ManualSpanError as exc:
        raise ApiError(422, "invalid_spans") from exc


def _sendable(review: MaskReview, mask: DoctorMask) -> bool:
    return review.reason is None or (mask.confirmed_clear and review.confirmable)


@router.post("/visits/{vid}/masks/check")
def check_masks(vid: VisitId, body: CheckIn, conn: Conn) -> dict[str, Any]:
    """区間を当てた後の、送られる文とまだ疑われる区間（保存しない）。"""
    visit = _visit(conn, vid)
    if not _is_open(visit):
        raise ApiError(404, "not_found")
    entry = _entry(conn, visit, body.entry_id, _eligible_ids(conn, vid))
    review = _review(visit, entry, _spans(body.spans))
    return {
        "entry_id": entry.id,
        "masked_text": review.masked_text,
        "suspects": [
            {"start": s.start, "end": s.end, "rule": s.rule} for s in review.suspects
        ],
        "reason": review.reason,
        "sendable": review.reason is None,
        "confirmable": review.confirmable,
    }


def _plan(
    conn: sqlite3.Connection, visit: dict[str, Any], body: SaveIn
) -> tuple[dict[int, DoctorMask], list[int], int]:
    """保存する伏せ字・消す記録・送られる件数。検査に通らなければ ApiError。"""
    ids = [item.entry_id for item in body.entries]
    if len(set(ids)) != len(ids):
        raise ApiError(422, "invalid_input")
    eligible = _eligible_ids(conn, visit["id"])
    upserts: dict[int, DoctorMask] = {}
    removals: list[int] = []
    sendable = 0
    for item in body.entries:
        entry = _entry(conn, visit, item.entry_id, eligible)
        if not item.send:
            removals.append(entry.id)
            continue
        spans = _spans(item.spans)
        review = _review(visit, entry, spans)
        try:
            mask = confirmed_mask(spans, review, confirmed=item.confirmed_clear)
        except ValueError as exc:
            raise ApiError(422, "not_confirmable") from exc
        upserts[entry.id] = mask
        sendable += 1 if _sendable(review, mask) else 0
    return upserts, removals, sendable


def _log(
    logger: PipelineLogger,
    upserts: dict[int, DoctorMask],
    removed: list[int],
) -> None:
    for entry_id, mask in upserts.items():
        decision = reason_code("entry", str(entry_id))
        logger.event("doctor_mask_saved", decision=decision)
        if mask.confirmed_clear:
            logger.event("doctor_mask_confirmed", decision=decision)
    for entry_id in removed:
        logger.event(
            "doctor_mask_removed", decision=reason_code("entry", str(entry_id))
        )


@router.post("/visits/{vid}/masks")
def save_masks(vid: VisitId, body: SaveIn, conn: Conn) -> dict[str, Any]:
    """医師の伏せ字を保存する（送らない記録は消す）。この後に regenerate を呼ぶ。"""
    visit = _visit(conn, vid)
    if not _is_open(visit):
        raise ApiError(409, "visit_closed")
    upserts, removals, sendable = _plan(conn, visit, body)
    before = set(db.list_doctor_masks(conn, vid))
    try:
        db.save_doctor_masks(conn, vid, upserts=upserts, removals=removals)
    except db.VisitGeneratingError as exc:
        raise ApiError(409, "generating") from exc
    except db.VisitClosedError as exc:
        raise ApiError(409, "visit_closed") from exc
    except db.NotFoundError as exc:
        raise ApiError(404, "not_found") from exc
    except ValueError as exc:
        raise ApiError(404, "unknown_entry") from exc
    removed = [entry_id for entry_id in removals if entry_id in before]
    _log(PipelineLogger(conn, RUN_KIND, vid), upserts, removed)
    return {"ok": True, "sendable": sendable}
