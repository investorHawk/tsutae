"""医師 API: D4 レジメンの下書き・確認・採用（spec 9.1・16、architecture 9c・§8）。

- 全経路で医師 Cookie を検査する（`require_doctor`）。GET 以外は `require_same_origin`
  （別サイトからは 403 cross_origin）。本文つきの POST・PATCH は Content-Type が
  application/json でなければ 415（`require_json_body`。本文の無い discard は対象外）
- 読み出しの前に、working のまま `regimen_recover_after_s`（往復の上限＋余裕）を過ぎた
  下書きを open に戻す
- `POST /regimen-drafts {from: "new"} | {skill: "regimen-folfox"}` → `{draft, created}`。
  既存のレジメンに開いた下書きがあればそれを返す（created=false）
- `GET /regimen-drafts` → `{drafts: [要約]}`（開いている下書き。id 順）
- `GET /regimen-drafts/{id}` → `{draft}`
- `PATCH /regimen-drafts/{id}/fields {changes: [{field_id, value}], adds: [{section,
  row_id}], deletes: ["drugs.<row_id>"]}` → `{draft}`。検査に掛かれば 422
  `{error: "invalid_fields", issues: [{field_id, code, message}]}`（保存しない。message に
  入力の文面は入らない）。読んでから書くまでに別の書き手が変えたら 409 conflict
- `POST /regimen-drafts/{id}/discard` → `{ok: true}`
- `GET /regimen-drafts/{id}/preview` → AI の値・SKILL.md（新規は全文、既存は diff）・患者の
  見本・検査の結果・confirm_token
- `POST /regimen-drafts/{id}/adopt {confirm_token, ai_values_confirmed}` →
  `{ok: true, skill_name, version, regimen}`。止めたら 409（token_mismatch・
  ai_values_unconfirmed・stale・schedule_locked・code_taken・working・not_open・busy など）
  か 422 invalid_form（issues つき）。書き込みの失敗は 500 write_error
- `POST /regimen-drafts/{id}/turns {text}` → `{draft, turn_error}`（Claude の1往復。
  応答まで待つ。上限 `regimen_turn_timeout_s`）。turn_error は成功なら null、時間切れ・
  失敗なら timeout・max_turns・max_budget・sdk_error・internal_error など（下書きは open に
  戻り、会話に失敗の行）、遅れた結果を捨てたら discarded。入力の文・依頼文の全体に H1 が
  掛かれば 422 `{error: "h1_blocked"}`（Claude を呼ばず保存しない）。working の間は 409
  working。本体は `tsutae.regimen.chat_turn.run_turn`、Claude は `app.state.regimen_chat`
- 下書きの form は `prose`（描画用の文。画面に出さない）を除いて返す
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictStr

from tsutae import db
from tsutae.api.deps import (
    ApiError,
    AppSettings,
    Conn,
    require_doctor,
    require_json_body,
    require_same_origin,
)
from tsutae.db import repo_regimen_drafts as repo
from tsutae.regimen.adopt import adopt
from tsutae.regimen.chat_turn import run_turn
from tsutae.regimen.drafts import (
    DraftError,
    create_new_draft,
    discard,
    draft_form,
    draft_skill_name,
    draft_sources,
    load_draft,
    open_skill_draft,
    patch_draft,
    require_open,
    target_version,
)
from tsutae.regimen.edit import FieldChange, FormPatch, RowAdd
from tsutae.regimen.preview import build_preview
from tsutae.regimen.text_checks import FieldIssue
from tsutae.regimen.validate import missing_fields

__all__ = ["error_status", "router"]

router = APIRouter(
    prefix="/api/doctor",
    dependencies=[Depends(require_doctor), Depends(require_same_origin)],
)

DraftId = Annotated[int, Path(ge=1, le=2**62)]
_BASE = "/regimen-drafts"
_ISSUE_CODES = frozenset({"invalid_fields", "invalid_form"})
_STATUS = {
    "not_found": 404,
    "unknown_skill": 404,
    "invalid_name": 400,
    "h1_blocked": 422,
    "base_invalid": 500,
    "render_failed": 500,
    "write_error": 500,
}
MAX_CHANGES = 300
MAX_TURN_TEXT = 1000


class DraftCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: Literal["new"] | None = Field(default=None, alias="from")
    skill: StrictStr | None = Field(default=None, max_length=200)


class ChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: StrictStr = Field(max_length=200)
    value: JsonValue


class AddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: StrictStr = Field(max_length=50)
    row_id: StrictStr = Field(max_length=100)


class FieldsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[ChangeIn] = Field(default_factory=list, max_length=MAX_CHANGES)
    adds: list[AddIn] = Field(default_factory=list, max_length=MAX_CHANGES)
    deletes: list[Annotated[StrictStr, Field(max_length=200)]] = Field(
        default_factory=list, max_length=MAX_CHANGES
    )


class AdoptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_token: StrictStr = Field(max_length=200)
    ai_values_confirmed: StrictBool


class TurnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: StrictStr = Field(min_length=1, max_length=MAX_TURN_TEXT)


def error_status(code: str) -> int:
    if code in _ISSUE_CODES:
        return 422
    return _STATUS.get(code, 409)


def _issue_out(issue: FieldIssue) -> dict[str, str]:
    return {"field_id": issue.field_id, "code": issue.code, "message": issue.message}


def _error(exc: DraftError) -> JSONResponse:
    body: dict[str, Any] = {"error": exc.code}
    if exc.issues:
        body["issues"] = [_issue_out(i) for i in exc.issues]
    return JSONResponse(body, status_code=error_status(exc.code))


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def _summary(draft: dict[str, Any]) -> dict[str, Any]:
    form = draft_form(draft)
    return {
        "id": draft["id"],
        "regimen": draft["regimen"],
        "skill_name": draft_skill_name(draft, form),
        "display_name": form.basic.display_name,
        "base_version": draft["base_version"],
        "version": target_version(draft),
        "status": draft["status"],
        "updated_at": _iso(draft["updated_at"]),
    }


def _view(conn: Any, draft: dict[str, Any]) -> dict[str, Any]:
    form = draft_form(draft)
    locked = draft["base_version"] is not None and db.regimen_has_patients(
        conn, draft["regimen"]
    )
    return {
        **_summary(draft),
        "generation": draft["generation"],
        "form": form.model_dump(mode="json", exclude={"prose"}),
        "sources": draft_sources(draft).root,
        "chat": draft["chat"],
        "missing": [_issue_out(i) for i in missing_fields(form)],
        "schedule_locked": locked,
        "created_at": _iso(draft["created_at"]),
    }


def _patch_of(body: FieldsIn) -> FormPatch:
    return FormPatch(
        changes=tuple(FieldChange(c.field_id, c.value) for c in body.changes),
        adds=tuple(RowAdd(a.section, a.row_id) for a in body.adds),
        deletes=tuple(body.deletes),
    )


@router.post(_BASE, dependencies=[Depends(require_json_body)])
def create_draft(body: DraftCreateIn, conn: Conn, settings: AppSettings) -> Any:
    if (body.from_ is None) == (body.skill is None):
        raise ApiError(422, "invalid_input")
    repo.recover_stale_working(conn, timeout_s=settings.regimen_recover_after_s)
    try:
        if body.skill is None:
            draft, created = create_new_draft(conn), True
        else:
            draft, created = open_skill_draft(
                conn, body.skill, skills_dir=settings.skills_dir
            )
    except DraftError as exc:
        return _error(exc)
    return {"draft": _view(conn, draft), "created": created}


@router.get(_BASE)
def list_drafts(conn: Conn, settings: AppSettings) -> dict[str, Any]:
    repo.recover_stale_working(conn, timeout_s=settings.regimen_recover_after_s)
    return {"drafts": [_summary(d) for d in repo.list_active_drafts(conn)]}


@router.get(_BASE + "/{draft_id}")
def get_draft(draft_id: DraftId, conn: Conn, settings: AppSettings) -> Any:
    try:
        draft = load_draft(conn, draft_id, timeout_s=settings.regimen_recover_after_s)
    except DraftError as exc:
        return _error(exc)
    return {"draft": _view(conn, draft)}


@router.patch(_BASE + "/{draft_id}/fields", dependencies=[Depends(require_json_body)])
def patch_fields(
    draft_id: DraftId, body: FieldsIn, conn: Conn, settings: AppSettings
) -> Any:
    try:
        draft = patch_draft(
            conn,
            draft_id,
            _patch_of(body),
            skills_dir=settings.skills_dir,
            timeout_s=settings.regimen_recover_after_s,
        )
    except DraftError as exc:
        return _error(exc)
    return {"draft": _view(conn, draft)}


@router.post(_BASE + "/{draft_id}/discard")
def discard_draft(draft_id: DraftId, conn: Conn, settings: AppSettings) -> Any:
    try:
        discard(conn, draft_id, timeout_s=settings.regimen_recover_after_s)
    except DraftError as exc:
        return _error(exc)
    return {"ok": True}


@router.get(_BASE + "/{draft_id}/preview")
def preview(draft_id: DraftId, conn: Conn, settings: AppSettings) -> Any:
    try:
        draft = load_draft(conn, draft_id, timeout_s=settings.regimen_recover_after_s)
        require_open(draft)
    except DraftError as exc:
        return _error(exc)
    return build_preview(conn, draft, skills_dir=settings.skills_dir)


@router.post(_BASE + "/{draft_id}/adopt", dependencies=[Depends(require_json_body)])
def adopt_draft(
    draft_id: DraftId,
    body: AdoptIn,
    request: Request,
    conn: Conn,
    settings: AppSettings,
) -> Any:
    try:
        result = adopt(
            conn,
            draft_id,
            body.confirm_token,
            body.ai_values_confirmed,
            skills_home=request.app.state.skills_home,
            timeout_s=settings.regimen_recover_after_s,
        )
    except DraftError as exc:
        return _error(exc)
    return {
        "ok": True,
        "skill_name": result.skill_name,
        "version": result.version,
        "regimen": result.regimen,
    }


@router.post(_BASE + "/{draft_id}/turns", dependencies=[Depends(require_json_body)])
async def post_turn(
    draft_id: DraftId,
    body: TurnIn,
    request: Request,
    conn: Conn,
    settings: AppSettings,
) -> Any:
    if not body.text.strip():
        raise ApiError(422, "invalid_input")
    try:
        outcome = await run_turn(
            conn,
            draft_id,
            body.text,
            chat=request.app.state.regimen_chat,
            settings=settings,
            skills_dir=settings.skills_dir,
        )
    except DraftError as exc:
        return _error(exc)
    return {"draft": _view(conn, outcome.draft), "turn_error": outcome.error}
