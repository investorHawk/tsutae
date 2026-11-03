"""患者 API（docs/architecture.md §8 患者）。Cookie `tsutae_pid` で識別する。

- 変換結果（timelines・reports）とパイプラインには触れない（アーキテクチャテストで検査）
- 患者画面に出る文字列は patient_strings.json と、承認済み Skill の質問文だけ
- 記録は今の regimen Skill の skill_version で保存する。回答は Skill の質問集に照らして
  検査する（未知の質問・回答の型違いは 422 invalid_input）
- 登録（Cookie の発行はここだけ）は、クライアント（request.client.host）ごとに失敗
  （unknown_patient）が 10 分で 10 回に達したら、以降の試行を 429 too_many_attempts
  で断る（正しい pid でも断る。成功・422 は数えない）
"""

from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from tsutae import db
from tsutae.api.deps import (
    ApiError,
    AppSettings,
    Conn,
    is_patient_id,
    register_limiter,
    require_patient,
    set_patient_cookie,
)
from tsutae.api.fixed_rules import notices_for
from tsutae.config import PATIENT_STRINGS_PATH, Settings, now
from tsutae.schemas import AnswerType, Entry, EntryCreate, RegimenSkill
from tsutae.skills import SkillValidationError, load_regimen_skill

__all__ = ["router"]

router = APIRouter(prefix="/api/patient")

_VALUES: dict[AnswerType, frozenset[str]] = {
    "three_level": frozenset({"none", "present", "hard"}),
    "temperature": frozenset({"not_measured", "measured"}),
}
_VERSION_RE = re.compile(r"(?P<name>[a-z0-9][a-z0-9-]*)@(?P<version>[1-9][0-9]{0,8})")


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pid: str = Field(max_length=64)


@lru_cache(maxsize=1)
def _patient_strings() -> dict[str, str]:
    data = json.loads(PATIENT_STRINGS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError("patient_strings.json は文字列→文字列の対応")
    return data


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


def _client_key(request: Request) -> str:
    client = request.client
    return client.host if client is not None and client.host else "unknown"


@router.post("/register")
def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    conn: Conn,
    settings: AppSettings,
) -> dict[str, bool]:
    limiter = register_limiter(request.app)
    key = _client_key(request)
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
    return dict(_patient_strings())


@router.get("/{pid}/questions")
def questions(
    pid: str, request: Request, conn: Conn, settings: AppSettings
) -> dict[str, Any]:
    patient = require_patient(pid, request, conn)
    skill = _regimen_skill(patient, settings)
    return {
        "skill_version": skill.skill_version,
        "questions": [q.model_dump(mode="json") for q in skill.questions],
    }


@router.post("/{pid}/entries")
def create_entry(
    pid: str, entry: EntryCreate, request: Request, conn: Conn, settings: AppSettings
) -> dict[str, Any]:
    patient = require_patient(pid, request, conn)
    skill = _regimen_skill(patient, settings)
    _check_answers(entry, skill)
    saved = db.add_entry(conn, patient["id"], entry, now(), skill.skill_version)
    return {"entry_id": saved.id, "notices": notices_for(entry, skill)}


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


@router.get("/{pid}/entries")
def list_entries(pid: str, request: Request, conn: Conn) -> dict[str, Any]:
    patient = require_patient(pid, request, conn)
    entries = db.list_entries(conn, patient["id"])
    cache: dict[str, dict[str, str] | None] = {}
    for version in {e.skill_version for e in entries}:
        cache[version] = _question_texts(conn, version)
    return {"entries": [_entry_out(e, cache[e.skill_version]) for e in entries]}
