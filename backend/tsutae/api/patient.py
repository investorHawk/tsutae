"""患者 API（docs/architecture.md §8 患者）。Cookie `tsutae_pid` で識別する。

- 変換結果（timelines・reports）とパイプラインには触れない（アーキテクチャテストで検査）
- 患者画面に出る文字列は patient_strings.json と、承認済み Skill の質問文だけ
- 記録は今の regimen Skill の skill_version で保存する。回答は Skill の質問集に照らして
  検査する（未知の質問・回答の型違いは 422 invalid_input）
- 記録の送り直し（タイムアウトの後など）: 同じ患者・同じ内容（EntryCreate を正規化した
  形が一致）の記録が直近 120 秒以内にあれば、新しく作らずその entry_id と notices を
  返す（`db.add_entry_once`）
- 取り消し（P2-5）: `POST /{pid}/entries/{entry_id}/undo` は、本人の「つらくて書けない」
  の記録で、作ってから UNDO_WINDOW 以内・その後に受診の受付が無いものだけを消す
  （`db.undo_too_sick_entry`）。他人の記録は 404 not_found、条件に合わなければ
  409 not_undoable。押し間違いを戻すためのもので、他の記録は消せない
- 記録の一覧（`GET /{pid}/entries`）には本人の受診日（`visit_date`・受付の時刻
  `received_at`）だけを添える（`db.list_visit_days`）。受付番号・状態は返さない
- 登録（Cookie の発行はここだけ）は、クライアント（request.client.host）ごとに失敗
  （unknown_patient）が 10 分で 10 回に達したら、以降の試行を 429 too_many_attempts
  で断る（正しい pid でも断る。成功・422 は数えない）。全クライアントの合計が 10 分で
  100 回に達したときも全員を断る（X-Forwarded-For を回す迂回の歯止め。deps 参照）
"""

from __future__ import annotations

import re
import sqlite3
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from tsutae import db
from tsutae.api.deps import (
    ApiError,
    AppSettings,
    Conn,
    client_key,
    is_patient_id,
    register_limiter,
    require_patient,
    set_patient_cookie,
)
from tsutae.api.fixed_rules import notices_for
from tsutae.config import Settings, now, today
from tsutae.patient_strings import load_patient_strings
from tsutae.schemas import AnswerType, Entry, EntryCreate, RegimenSkill
from tsutae.skills import SkillValidationError, load_regimen_skill

__all__ = ["router"]

router = APIRouter(prefix="/api/patient")

_VALUES: dict[AnswerType, frozenset[str]] = {
    "three_level": frozenset({"none", "present", "hard"}),
    "temperature": frozenset({"not_measured", "measured"}),
}
RESEND_WINDOW = timedelta(seconds=120)  # 同じ内容の記録を送り直しとみなす長さ
UNDO_WINDOW = timedelta(minutes=10)  # 「つらくて書けない」を取り消せる長さ
EntryId = Annotated[int, Path(ge=1, le=2**62)]
_VERSION_RE = re.compile(r"(?P<name>[a-z0-9][a-z0-9-]*)@(?P<version>[1-9][0-9]{0,8})")


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pid: str = Field(max_length=64)


def _regimen_skill(patient: dict[str, Any], settings: Settings) -> RegimenSkill:
    try:
        return load_regimen_skill(patient["regimen"], settings.skills_dir)
    except SkillValidationError as exc:
        raise ApiError(500, "skill_unavailable") from exc


def _check_answers(entry: EntryCreate, skill: RegimenSkill) -> None:
    """回答が Skill の質問集にあり、値が質問の型に合うこと。"""
    types = {q.key: q.answer_type for q in skill.questions}
    for answer in entry.answers:
        answer_type = types.get(answer.question_key)
        if answer_type is None or answer.value not in _VALUES[answer_type]:
            raise ApiError(422, "invalid_input")


@router.post("/register")
def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    conn: Conn,
    settings: AppSettings,
) -> dict[str, bool]:
    limiter = register_limiter(request.app)
    key = client_key(request)
    at = now()
    if limiter.is_blocked(key, at):
        raise ApiError(429, "too_many_attempts")
    if not is_patient_id(body.pid) or db.get_patient(conn, body.pid) is None:
        limiter.record_failure(key, at)
        raise ApiError(404, "unknown_patient")
    set_patient_cookie(response, body.pid, settings)
    return {"ok": True}


@router.get("/strings")
def strings() -> dict[str, str]:
    return dict(load_patient_strings())


@router.get("/{pid}/questions")
def questions(
    pid: str, request: Request, conn: Conn, settings: AppSettings
) -> dict[str, Any]:
    """今の質問集と、サーバーの今日（JST。今日の記録の見出しの日付に使う）。"""
    patient = require_patient(pid, request, conn)
    skill = _regimen_skill(patient, settings)
    return {
        "skill_version": skill.skill_version,
        "questions": [q.model_dump(mode="json") for q in skill.questions],
        "today": today().isoformat(),
    }


@router.post("/{pid}/entries")
def create_entry(
    pid: str, entry: EntryCreate, request: Request, conn: Conn, settings: AppSettings
) -> dict[str, Any]:
    patient = require_patient(pid, request, conn)
    skill = _regimen_skill(patient, settings)
    _check_answers(entry, skill)
    saved = db.add_entry_once(
        conn, patient["id"], entry, now(), skill.skill_version, RESEND_WINDOW
    )
    return {"entry_id": saved.id, "notices": notices_for(entry, skill)}


@router.post("/{pid}/entries/{entry_id}/undo")
def undo_entry(
    pid: str, entry_id: EntryId, request: Request, conn: Conn
) -> dict[str, bool]:
    patient = require_patient(pid, request, conn)
    result = db.undo_too_sick_entry(conn, patient["id"], entry_id, now() - UNDO_WINDOW)
    if result == "not_found":
        raise ApiError(404, "not_found")
    if result == "not_undoable":
        raise ApiError(409, "not_undoable")
    return {"ok": True}


def _question_texts(
    conn: sqlite3.Connection, skill_version: str
) -> dict[str, str] | None:
    """その版の質問集の key → 文。版が登録されていない・regimen でなければ None。"""
    match = _VERSION_RE.fullmatch(skill_version)
    if match is None:
        return None
    row = db.get_skill_version(conn, match["name"], int(match["version"]))
    if row is None or row["questions"] is None:
        return None
    return {q.key: q.text for q in row["questions"]}


def _entry_out(entry: Entry, texts: dict[str, str] | None) -> dict[str, Any]:
    data = entry.model_dump(mode="json", exclude={"patient_id"})
    data["answers"] = [
        {**a, "question_text": (texts or {}).get(a["question_key"])}
        for a in data["answers"]
    ]
    return data


def _visit_days_out(conn: sqlite3.Connection, pid: str) -> list[dict[str, str]]:
    """受診日（受付のあった日）と受付の時刻だけ。受付番号・状態・レポートは返さない。"""
    return [
        {
            "visit_date": d["visit_date"].isoformat(),
            "received_at": d["received_at"].isoformat(),
        }
        for d in db.list_visit_days(conn, pid)
    ]


@router.get("/{pid}/entries")
def list_entries(pid: str, request: Request, conn: Conn) -> dict[str, Any]:
    """自分の記録と、自分の受診日（新しい順。これまでの記録の区切りに使う）。"""
    patient = require_patient(pid, request, conn)
    entries = db.list_entries(conn, patient["id"])
    cache: dict[str, dict[str, str] | None] = {}
    for version in {e.skill_version for e in entries}:
        cache[version] = _question_texts(conn, version)
    return {
        "entries": [_entry_out(e, cache[e.skill_version]) for e in entries],
        "visits": _visit_days_out(conn, patient["id"]),
    }
