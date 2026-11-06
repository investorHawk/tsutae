"""患者 API（docs/architecture.md §8 患者）。Cookie `tsutae_pid` で識別する。

- 変換結果（timelines・reports）とパイプラインには触れない（アーキテクチャテストで検査）
- 患者画面に出る文字列は patient_strings.json と、承認済み Skill の質問文だけ
- 記録はスマホに置く（plan-device-records §5）。ここには記録の本文を受ける経路が無い。
  印・取り消し・受診の範囲などは `patient_device`、受付で受け取るのは `visit`
- `GET /{pid}/questions` の fixed_rules は画面のコードで比べる規則（§5.3。体温をサーバーに
  送らない。モデルは関わらない）
- 登録（Cookie の発行はここだけ）は、クライアント（request.client.host）ごとに失敗
  （unknown_patient）が 10 分で 10 回に達したら、以降の試行を 429 too_many_attempts
  で断る（正しい pid でも断る。成功・422 は数えない）。全クライアントの合計が 10 分で
  100 回に達したときも全員を断る（X-Forwarded-For を回す迂回の歯止め。deps 参照）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
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
from tsutae.config import Settings, now, today
from tsutae.patient_strings import load_patient_strings
from tsutae.schemas import RegimenSkill
from tsutae.skills import SkillValidationError, load_regimen_skill

__all__ = ["router"]

router = APIRouter(prefix="/api/patient")


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pid: str = Field(max_length=64)


def _regimen_skill(patient: dict[str, Any], settings: Settings) -> RegimenSkill:
    try:
        return load_regimen_skill(patient["regimen"], settings.skills_dir)
    except SkillValidationError as exc:
        raise ApiError(500, "skill_unavailable") from exc


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
    """今の質問集と固定規則、サーバーの今日（JST。今日の記録の見出しの日付に使う）。"""
    patient = require_patient(pid, request, conn)
    skill = _regimen_skill(patient, settings)
    return {
        "skill_version": skill.skill_version,
        "questions": [q.model_dump(mode="json") for q in skill.questions],
        "fixed_rules": [
            {
                "question_key": rule.question_key,
                "threshold_celsius": rule.threshold_celsius,
                "patient_string_key": rule.patient_string_key,
            }
            for rule in skill.fixed_rules
        ],
        "today": today().isoformat(),
    }
