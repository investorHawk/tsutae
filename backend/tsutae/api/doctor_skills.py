"""医師 API: Skill の一覧と書き換え（D4。docs/architecture.md §8・§8b・§9b）。

- 全経路で医師 Cookie を検査する（`require_doctor`）
- `POST /skill-changes` は Content-Type が application/json でなければ 415
  `{"error": "unsupported_media_type"}`（`require_json_body`。本文の無い approve・reject
  は frontend が Content-Type を付けないので対象外）
- 書き換えは `tsutae.skillchange`（editor は `app.state.skill_editor`、置き場所は
  `app.state.skills_home`）。依頼の受付前の失敗は `SkillChangeError` の code を
  `{"error": code}` にする（400 invalid_name・invalid_request／404 unknown_skill・
  not_found／500 base_invalid／他は 409。pending 以外の承認・却下は 409 not_pending）
- 依頼を受け付けた後の失敗（no_change・h1_blocked 等）は HTTP の失敗にしない:
  `{id, status: "failed", diff: null}` を返し、理由は一覧の error_code に出る
- editor が無い（`tsutae.skillchange` を読めない）ときは 503 editor_unavailable
- 却下も承認と同じ Skill のロック（`skills_home`）の内側で行う（承認の途中で却下して
  本体は新しい版・行は rejected、という食い違いを作らない。握られていれば 409 busy）
- `GET /skills` は壊れた SKILL.md・欠けた必須 Skill を黙って落とさず `invalid` に
  `{name, error_code, required}` で載せる（200 のまま。ログインの確認にも使う経路なので
  500 にして医師画面全体を止めない）。必須は regimen の2本と report-format-default
"""

from __future__ import annotations

import sqlite3
from pathlib import Path as FsPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from tsutae import db
from tsutae.api.deps import (
    ApiError,
    AppSettings,
    Conn,
    require_doctor,
    require_json_body,
)
from tsutae.skillchange import (
    BAD_REQUEST_CODES,
    NOT_FOUND_CODES,
    SkillChangeError,
    approve_change,
    reject_change,
    request_change,
)
from tsutae.skills import (
    DEFAULT_REPORT_SKILL,
    REGIMEN_SKILL_NAMES,
    SKILL_FILE_NAME,
    SkillValidationError,
    is_valid_skill_name,
    load_skill,
)

__all__ = ["error_status", "router"]

router = APIRouter(prefix="/api/doctor", dependencies=[Depends(require_doctor)])

ChangeId = Annotated[int, Path(ge=1, le=2**62)]
_CHANGE_FIELDS = (
    "id",
    "skill_name",
    "requested_text",
    "diff",
    "status",
    "base_version",
    "new_version",
    "error_code",
)
_SERVER_ERROR_CODES = frozenset({"base_invalid"})
REQUIRED_SKILLS = frozenset({*REGIMEN_SKILL_NAMES.values(), DEFAULT_REPORT_SKILL})


class SkillChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 長さ・書式の検査は skillchange が行う（400 invalid_name・invalid_request）
    skill_name: str = Field(max_length=200)
    request_text: str = Field(max_length=20000)


def error_status(code: str) -> int:
    """SkillChangeError の code に対応する HTTP の状態。"""
    if code in BAD_REQUEST_CODES:
        return 400
    if code in NOT_FOUND_CODES:
        return 404
    if code in _SERVER_ERROR_CODES:
        return 500
    return 409


def _api_error(exc: SkillChangeError) -> ApiError:
    return ApiError(error_status(exc.code), exc.code)


def _change_out(change: dict[str, Any]) -> dict[str, Any]:
    """一覧の1件（new_text は返さない。差分で足りる）。"""
    decided = change["decided_at"]
    return {
        **{k: change[k] for k in _CHANGE_FIELDS},
        "created_at": change["created_at"].isoformat(),
        "decided_at": decided.isoformat() if decided is not None else None,
    }


def _skill_dirs(base: FsPath) -> list[str]:
    """SKILL.md を置いた Skill 名（名前順）。書式の違う名前・ファイルは数えない。"""
    return sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir()
        and is_valid_skill_name(p.name)
        and (p / SKILL_FILE_NAME).is_file()
    )


def _invalid(name: str, code: str) -> dict[str, Any]:
    return {"name": name, "error_code": code, "required": name in REQUIRED_SKILLS}


@router.get("/skills")
def list_skills(settings: AppSettings) -> dict[str, Any]:
    """skills_dir の Skill（名前順）と、読めない Skill（`invalid`、名前順）。"""
    base = settings.skills_dir
    present = _skill_dirs(base)
    skills: list[dict[str, Any]] = []
    invalid = [_invalid(n, "missing") for n in REQUIRED_SKILLS - set(present)]
    for name in present:
        try:
            skills.append({"name": name, "version": load_skill(name, base).version})
        except SkillValidationError as exc:
            invalid.append(_invalid(name, exc.code))
    return {"skills": skills, "invalid": sorted(invalid, key=lambda i: i["name"])}


@router.post("/skill-changes", dependencies=[Depends(require_json_body)])
async def create_skill_change(
    body: SkillChangeIn, request: Request, conn: Conn, settings: AppSettings
) -> dict[str, Any]:
    editor = request.app.state.skill_editor
    if editor is None:
        raise ApiError(503, "editor_unavailable")
    try:
        change_id = await request_change(
            conn,
            body.skill_name,
            body.request_text,
            editor=editor,
            settings=settings,
            skills_home=request.app.state.skills_home,
        )
    except SkillChangeError as exc:
        raise _api_error(exc) from exc
    change = _change_or_404(conn, change_id)
    return {"id": change["id"], "status": change["status"], "diff": change["diff"]}


def _change_or_404(conn: sqlite3.Connection, change_id: int) -> dict[str, Any]:
    change = db.get_skill_change(conn, change_id)
    if change is None:
        raise ApiError(404, "not_found")
    return change


@router.get("/skill-changes")
def list_skill_changes(conn: Conn) -> dict[str, Any]:
    return {"skill_changes": [_change_out(c) for c in db.list_skill_changes(conn)]}


@router.post("/skill-changes/{change_id}/approve")
def approve(change_id: ChangeId, request: Request, conn: Conn) -> dict[str, Any]:
    try:
        new_version = approve_change(
            conn, change_id, skills_home=request.app.state.skills_home
        )
    except SkillChangeError as exc:
        raise _api_error(exc) from exc
    return {"ok": True, "new_version": new_version}


@router.post("/skill-changes/{change_id}/reject")
def reject(change_id: ChangeId, request: Request, conn: Conn) -> dict[str, bool]:
    try:
        reject_change(conn, change_id, skills_home=request.app.state.skills_home)
    except SkillChangeError as exc:
        raise _api_error(exc) from exc
    return {"ok": True}
