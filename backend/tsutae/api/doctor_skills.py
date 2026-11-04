"""医師 API: Skill の一覧と書き換え（D4。docs/architecture.md §8・§8b・§9b）。

- 全経路で医師 Cookie を検査する（`require_doctor`）。POST（依頼・承認・却下）は
  その後で `require_same_origin`（別サイトからの要求は 403 `{"error": "cross_origin"}`。
  GET は見ない）
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
- 同じ Skill の書き換えが作業中（pending・diff なし）なら依頼は 409 busy。作業中のまま
  pipeline_timeout_s を過ぎた行（再起動などで取り残された）は、依頼と
  `GET /skill-changes`（こちらは STALE_GRACE_S の余裕を足す）の前に
  failed・stale_request にする（画面が「生成中」のまま止まらないように）
- `GET /skills` は壊れた SKILL.md・欠けた必須 Skill を黙って落とさず `invalid` に
  `{name, error_code, required}` で載せる（200 のまま。ログインの確認にも使う経路なので
  500 にして医師画面全体を止めない）。必須は regimen の2本と report-format-default
- `GET /skills/{name}` は1つの Skill の今の中身（読み取り専用。設定画面で依頼の前に
  見せる）。名前は書式（400 invalid_name）と、`GET /skills` と同じ置かれた Skill の一覧
  （許可リスト。無ければ 404 unknown_skill）で検査してから読む。skills_dir の外を指す
  シンボリックリンクは `skill_path` が invalid_name にする。壊れた SKILL.md は
  `SkillValidationError` の code（`error_status` の対応）
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
    require_same_origin,
)
from tsutae.schemas import RegimenSkill
from tsutae.skillchange import (
    BAD_REQUEST_CODES,
    NOT_FOUND_CODES,
    SkillChangeError,
    approve_change,
    reject_change,
    request_change,
)
from tsutae.skillchange.state import STALE_GRACE_S, fail_stale_requests
from tsutae.skills import (
    DEFAULT_REPORT_SKILL,
    REGIMEN_SKILL_NAMES,
    SKILL_FILE_NAME,
    SkillValidationError,
    is_valid_skill_name,
    load_skill,
    read_skill_text,
    validate_skill_text,
)

__all__ = ["error_status", "router"]

router = APIRouter(
    prefix="/api/doctor",
    dependencies=[Depends(require_doctor), Depends(require_same_origin)],
)

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


@router.get("/skills/{name}")
def skill_content(name: str, settings: AppSettings) -> dict[str, Any]:
    """1つの Skill の今の中身。questions は regimen の質問（report-format は空）。"""
    base = settings.skills_dir
    if not is_valid_skill_name(name):
        raise ApiError(400, "invalid_name")
    if name not in _skill_dirs(base):
        raise ApiError(404, "unknown_skill")
    try:
        text = read_skill_text(name, base)
        skill = validate_skill_text(name, text)
    except SkillValidationError as exc:
        raise ApiError(error_status(exc.code), exc.code) from exc
    questions = (
        [q.model_dump() for q in skill.questions]
        if isinstance(skill, RegimenSkill)
        else []
    )
    return {
        "name": skill.name,
        "version": skill.version,
        "description": skill.description,
        "questions": questions,
        "text": text,
    }


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
def list_skill_changes(conn: Conn, settings: AppSettings) -> dict[str, Any]:
    """一覧（id 昇順）。取り残された作業中の行は先に failed・stale_request にする。"""
    fail_stale_requests(conn, settings.pipeline_timeout_s, grace_s=STALE_GRACE_S)
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
