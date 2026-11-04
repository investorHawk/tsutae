"""医師 API: 質問の部品集（spec 9.1・16、docs/architecture.md §8）。

D4 レジメンの画面の小窓で選ぶ候補。SKILL.md・採用済みの版には影響しない。

- 全経路で医師 Cookie を検査する（`require_doctor`。無ければ 401 not_logged_in）。
  POST・DELETE はその後で `require_same_origin`（別サイトからなら 403 cross_origin。
  GET は見ない）。本文つきの POST は Content-Type が application/json でなければ 415
  （`require_json_body`。本文の無い DELETE は対象外）
- `GET /question-library` → `{questions: [{key, label, text, answer_type, origin}]}`
  （外した問を含めない。入れた順で初期の6問が先）
- `POST /question-library {key, label, text, answer_type?}` → `{question: {...}}`。
  回答の型は3択だけ（体温は初期の fever だけ）。検査は `db.add_library_question`:
  形・H1 に掛かれば 422 `{error: code, field}`、key の重複（外した key も）は 409
  key_taken。本文の形の誤り（未知の鍵・型違い）は 422 invalid_input
- `DELETE /question-library/{key}` → `{ok: true}`（選択肢から外すだけ。何度呼んでもよい）。
  初期の6問は 409 seed_question、どれかの版が使っている key は 409 in_use、無い key は
  404 not_found、key の形が違えば 422 invalid_input
- 初期の6問は起動時（`app.startup`）に `db.seed_question_library` で入れる
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from tsutae import db
from tsutae.api.deps import (
    ApiError,
    Conn,
    require_doctor,
    require_json_body,
    require_same_origin,
)
from tsutae.schemas import QUESTION_KEY_PATTERN

__all__ = ["router"]

router = APIRouter(
    prefix="/api/doctor",
    dependencies=[Depends(require_doctor), Depends(require_same_origin)],
)

QuestionKey = Annotated[str, Path(pattern=QUESTION_KEY_PATTERN)]
_OUT_FIELDS = ("key", "label", "text", "answer_type", "origin")


class QuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 長さ・形の細かい検査は db.add_library_question（欄つきの 422）。ここは大枠だけ
    key: StrictStr = Field(max_length=100)
    label: StrictStr = Field(max_length=200)
    text: StrictStr = Field(max_length=1000)
    answer_type: StrictStr = Field(default="three_level", max_length=50)


def _out(item: dict[str, Any]) -> dict[str, Any]:
    return {k: item[k] for k in _OUT_FIELDS}


@router.get("/question-library")
def list_questions(conn: Conn) -> dict[str, Any]:
    return {"questions": [_out(q) for q in db.list_library_questions(conn)]}


@router.post("/question-library", dependencies=[Depends(require_json_body)])
def add_question(body: QuestionIn, conn: Conn) -> Any:
    try:
        added = db.add_library_question(
            conn,
            key=body.key,
            label=body.label,
            text=body.text,
            answer_type=body.answer_type,
        )
    except db.QuestionInputError as exc:
        return JSONResponse({"error": exc.code, "field": exc.field}, status_code=422)
    except db.QuestionConflictError as exc:
        raise ApiError(409, exc.code) from None
    return {"question": _out(added)}


@router.delete("/question-library/{key}")
def hide_question(key: QuestionKey, conn: Conn) -> dict[str, bool]:
    try:
        db.hide_library_question(conn, key)
    except db.NotFoundError:
        raise ApiError(404, "not_found") from None
    except db.QuestionConflictError as exc:
        raise ApiError(409, exc.code) from None
    return {"ok": True}
