"""D4 レジメンの Claude の1往復の実行と反映（POST .../turns の本体。T94、architecture 9c）。

`run_turn(conn, draft_id, text, *, chat, settings, skills_dir) -> TurnOutcome` の手順:

1. 取り残された working を戻してから下書きを読む（上限は `regimen_recover_after_s`）。
   open でなければ `DraftError`（working・not_open・not_found）
2. 往復の始まりの値（`TurnInput`）と依頼文（`build_turn_prompt`）を作り、入力の文と
   依頼文の全体に detect_identifiers。掛かれば Claude を呼ばず `h1_blocked`
   （下書きは何も変えない。issues は掛かった場所 text / prompt と規則の名前だけ。ログも
   規則の名前だけ）
3. working にして generation を上げる（`begin_working`）。1〜3 の間に await を挟まない。
   読んだ時と form_json・sources_json が違えば（間に PATCH が入った）409 `conflict`
4. `asyncio.wait_for(chat.turn(...), regimen_turn_timeout_s)`
5. 成功: 結果を検査し直し（validate_form・識別名・体温・prose）、返答の文と ask に H1、
   先生の文と Claude の返答を会話に足して `finish_turn`（working・同じ generation の
   ときだけ）。当たらなければ捨てる（error="discarded"）
6. 時間切れ・SDK の失敗・例外: 会話に先生の文と失敗の行を足して `fail_turn`（フォームは
   変えない。chat_fail）。3 より後で外に抜ける例外（取り消し・結果の書き込みの DB の
   失敗・失敗の行の書き込みの失敗）も、できる範囲で同じく戻してから投げ直す（`rescue`）

ログは `PipelineLogger(conn, "regimen_chat", draft_id)` に種類・回数・費用・秒・拒否の
回数だけ（`h1_check`・`turn_start`・`regimen_tool`・Hook・`turn_end`・`turn_counts`・
`reply_hidden`・`turn_discarded`・`turn_failed`・`internal_error`）。文面（先生の文・返答・
欄の値・例外の本文）は入れない。
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any

from tsutae.config import Settings
from tsutae.db import repo_regimen_drafts as repo
from tsutae.db import repo_regimen_turns as turns
from tsutae.db.repo_question_library import list_library_questions
from tsutae.masking import detect_identifiers
from tsutae.pipeline.logs import EventLogger, PipelineLogger, reason_code
from tsutae.regimen.chat_fail import (
    fail,
    failed_outcome,
    log_end,
    rescue,
    stamp,
)
from tsutae.regimen.chat_prompt import ask_line, build_turn_prompt
from tsutae.regimen.chat_rows import REPLY_HIDDEN, assistant_row, doctor_row
from tsutae.regimen.chat_session import logging_to
from tsutae.regimen.chat_types import (
    AskOut,
    LibraryItem,
    RegimenChat,
    TurnInput,
    TurnOutcome,
    TurnResult,
)
from tsutae.regimen.drafts import (
    DraftError,
    code_taken,
    draft_form,
    draft_sources,
    load_draft,
    reload_failure,
    require_open,
)
from tsutae.regimen.form import RegimenForm, prune_sources
from tsutae.regimen.source import canonical_form_json, canonical_sources_json
from tsutae.regimen.text_checks import identifier_issue
from tsutae.regimen.validate import validate_form
from tsutae.schemas import RunStats

__all__ = ["RUN_KIND", "TurnOutcome", "run_turn", "turn_input"]

RUN_KIND = "regimen_chat"
DISCARDED = "discarded"


def turn_input(
    conn: sqlite3.Connection, draft: dict[str, Any], *, skills_dir: Path
) -> TurnInput:
    """下書きの今の値・会話・部品集から、往復の始まりの値を作る。"""
    library = tuple(
        LibraryItem(r["key"], r["label"], r["text"], r["answer_type"])
        for r in list_library_questions(conn)
    )
    draft_id = int(draft["id"])

    def taken(code: str) -> bool:
        return code_taken(conn, code, skills_dir=skills_dir, draft_id=draft_id)

    return TurnInput(
        draft_id=draft_id,
        form=draft_form(draft),
        sources=draft_sources(draft),
        history=tuple(draft["chat"]),
        library=library,
        allow_code=draft["base_version"] is None,
        code_taken=taken,
    )


def _check_h1(text: str, prompt: str, logger: EventLogger) -> None:
    """先生の文、次に依頼文の全体に H1。掛かれば掛かった場所（text か prompt）と規則の
    名前だけを issues に入れた h1_blocked（文面は返さない）。"""
    issue = identifier_issue("text", text) or identifier_issue("prompt", prompt)
    if issue is not None:
        found = detect_identifiers(text) or detect_identifiers(prompt)
        logger.event(
            "h1_check", hook_name="H1", decision=reason_code("block", found[0].rule)
        )
        raise DraftError("h1_blocked", [issue])
    logger.event("h1_check", hook_name="H1", decision="allow")


# ---------------------------------------------------------------------------
# 成功
# ---------------------------------------------------------------------------


def _has_temperature(form: RegimenForm) -> bool:
    return any(q.answer_type == "temperature" for q in form.questions)


def _result_problem(
    draft: dict[str, Any], before: RegimenForm, result: TurnResult
) -> bool:
    """chat の結果がツールの検査を通った形でなければ True（偽物・不具合の守り）。"""
    form = result.form
    code_changed = form.basic.code != before.basic.code
    return bool(
        validate_form(form)
        or form.prose != before.prose
        or (draft["base_version"] is not None and code_changed)
        or (_has_temperature(before) and not _has_temperature(form))
    )


def _ask_ok(ask: AskOut | None) -> AskOut | None:
    """ask の文と、次の依頼文に入る形（ask_line）に H1。掛かれば落とす。"""
    if ask is None:
        return None
    texts = [ask.question, *ask.options, ask_line(ask.question, ask.options)]
    return None if any(detect_identifiers(t) for t in texts) else ask


def _reply(result: TurnResult, logger: EventLogger) -> tuple[str, bool]:
    found = detect_identifiers(result.reply)
    if not found:
        return result.reply, False
    logger.event("reply_hidden", decision=reason_code("block", found[0].rule))
    return REPLY_HIDDEN, True


def _new_regimen(draft: dict[str, Any], form: RegimenForm) -> str | None:
    if draft["base_version"] is not None:
        return draft["regimen"]
    return form.basic.code or None


def _finish(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    generation: int,
    text: str,
    result: TurnResult,
    logger: EventLogger,
) -> str | None:
    """結果を書く。書けなければ失敗のコード（書いた失敗の行の reason）か discarded。"""
    if _result_problem(draft, draft_form(draft), result):
        return (
            "invalid_result"
            if fail(conn, draft, generation, text, "invalid_result")
            else DISCARDED
        )
    reply, hidden = _reply(result, logger)
    at = stamp()
    chat = [
        *draft["chat"],
        doctor_row(text, generation, at),
        assistant_row(
            reply,
            changed=result.changed,
            ask=_ask_ok(result.ask),
            proposed=result.proposed,
            reply_hidden=hidden,
            generation=generation,
            at=at,
        ),
    ]
    try:
        written = turns.finish_turn(
            conn,
            draft["id"],
            generation,
            form_json=canonical_form_json(result.form),
            sources_json=canonical_sources_json(
                prune_sources(result.form, result.sources)
            ),
            regimen=_new_regimen(draft, result.form),
            chat=chat,
        )
    except repo.DraftConflictError:
        return (
            "code_taken"
            if fail(conn, draft, generation, text, "code_taken")
            else DISCARDED
        )
    return None if written else DISCARDED


def _log_counts(logger: EventLogger, result: TurnResult) -> None:
    logger.event(
        "turn_counts",
        decision=reason_code(
            "calls",
            str(result.tool_calls),
            "rejected",
            str(result.rejected),
            "turns",
            str(result.stats.num_turns),
            "changed",
            str(len(result.changed)),
        ),
    )


# ---------------------------------------------------------------------------
# 公開
# ---------------------------------------------------------------------------


def _start(
    conn: sqlite3.Connection,
    draft_id: int,
    text: str,
    settings: Settings,
    skills_dir: Path,
    logger: EventLogger,
) -> tuple[dict[str, Any], TurnInput, int]:
    draft = load_draft(conn, draft_id, timeout_s=settings.regimen_recover_after_s)
    require_open(draft)
    start = turn_input(conn, draft, skills_dir=skills_dir)
    _check_h1(text, build_turn_prompt(start, text), logger)
    generation = repo.begin_working(
        conn,
        draft_id,
        expected_form_json=draft["form_json"],
        expected_sources_json=draft["sources_json"],
    )
    if generation is None:  # 読んでから始めるまでに PATCH が入った: conflict
        raise reload_failure(conn, draft_id, otherwise="conflict")
    return draft, start, generation


async def run_turn(
    conn: sqlite3.Connection,
    draft_id: int,
    text: str,
    *,
    chat: RegimenChat,
    settings: Settings,
    skills_dir: Path,
) -> TurnOutcome:
    """1往復を実行して反映し、往復の後の下書きを返す。始められなければ DraftError。"""
    logger = PipelineLogger(conn, RUN_KIND, draft_id)
    draft, start, generation = _start(
        conn, draft_id, text, settings, skills_dir, logger
    )
    try:
        return await _run_started(
            conn, draft, start, generation, text, chat, settings, logger
        )
    except BaseException as exc:
        rescue(conn, draft, generation, text, exc, logger)
        raise


async def _run_started(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    start: TurnInput,
    generation: int,
    text: str,
    chat: RegimenChat,
    settings: Settings,
    logger: EventLogger,
) -> TurnOutcome:
    """working にした後の手順。外に抜ける例外は run_turn が rescue する。"""
    logger.event("turn_start")
    started = time.monotonic()
    try:
        with logging_to(logger):
            result = await asyncio.wait_for(
                chat.turn(start, text), timeout=settings.regimen_turn_timeout_s
            )
    except asyncio.CancelledError:
        log_end(logger, "cancelled", RunStats(), started)
        raise
    except Exception as exc:  # noqa: BLE001 — 失敗は会話に残して open に戻す
        return failed_outcome(conn, draft, generation, text, exc, logger, started)
    log_end(logger, "ok", result.stats, started)
    _log_counts(logger, result)
    error = _finish(conn, draft, generation, text, result, logger)
    if error is not None:
        logger.event(
            "turn_discarded" if error == DISCARDED else "turn_failed", decision=error
        )
    return TurnOutcome(repo.get_draft(conn, draft["id"]) or {}, error)
