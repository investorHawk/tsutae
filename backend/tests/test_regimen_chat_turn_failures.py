"""tsutae.regimen.chat_turn: begin_working の後で外に抜ける失敗（T94 の確かめ直し）。

working にした後は、どこで例外が起きても（結果の書き込みの DB の失敗・失敗の行の
書き込みの失敗・取り消し）できる範囲で open に戻し、会話に先生の文と失敗の行を残して
から例外を投げ直す。working のまま残すと、回復の上限（約 105 秒）まで PATCH・確認・
採用・次の往復が全て 409 になり、回復は誤った理由（timeout）の行を足す。
"""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from regimen_chat_fakes import FailingChat, ScriptChat, SlowChat, change

from tsutae import db
from tsutae.config import SKILLS_HOME, get_settings
from tsutae.db import repo_regimen_drafts as repo
from tsutae.db import repo_regimen_turns as turns
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.regimen.chat_turn import run_turn
from tsutae.regimen.drafts import create_new_draft, draft_form

TEXT = "1コースは14日"


@dataclass
class Env:
    conn: sqlite3.Connection
    skills_dir: Path


@pytest.fixture
def env(tmp_path: Path, fixed_today: str) -> Iterator[Env]:
    home = tmp_path / "skills_home"
    shutil.copytree(SKILLS_HOME, home)
    conn = db.connect(tmp_path / "t.db")
    db.init_db(conn)
    skills_dir = home / ".claude" / "skills"
    ensure_skill_versions(conn, skills_dir)
    db.seed_question_library(conn)
    yield Env(conn, skills_dir)
    conn.close()


def _turn(env: Env, draft_id: int, chat: Any, **kw: Any) -> Any:
    return run_turn(
        env.conn,
        draft_id,
        TEXT,
        chat=chat,
        settings=dataclasses.replace(get_settings(), **kw),
        skills_dir=env.skills_dir,
    )


def _events(env: Env, draft_id: int) -> list[tuple[str, str | None]]:
    rows = env.conn.execute(
        "SELECT event, decision FROM pipeline_logs WHERE run_kind = 'regimen_chat'"
        " AND run_id = ? ORDER BY id",
        (draft_id,),
    ).fetchall()
    return [(r["event"], r["decision"]) for r in rows]


def _assert_failed(env: Env, draft_id: int, reason: str) -> dict[str, Any]:
    got = repo.get_draft(env.conn, draft_id)
    assert got["status"] == "open" and got["working_since"] is None
    doctor, failed = got["chat"]
    assert doctor["role"] == "doctor" and doctor["text"] == TEXT
    assert (failed["role"], failed["kind"], failed["reason"]) == (
        "system",
        "turn_failed",
        reason,
    )
    assert failed["generation"] == got["generation"] == 1
    return got


def _locked(*args: Any, **kwargs: Any) -> Any:
    raise sqlite3.OperationalError("database is locked")


def test_finish_failure_returns_to_open(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """結果の書き込みが DB の失敗で落ちても working に残さない。"""
    monkeypatch.setattr(turns, "finish_turn", _locked)
    draft = create_new_draft(env.conn)
    chat = ScriptChat([change("basic.cycle_days", 14)])
    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(_turn(env, draft["id"], chat))
    got = _assert_failed(env, draft["id"], "internal_error")
    assert draft_form(got).basic.cycle_days is None
    assert ("turn_failed", "internal_error:error_type:OperationalError") in _events(
        env, draft["id"]
    )
    assert "database is locked" not in repr(_events(env, draft["id"]))


def test_failure_while_writing_the_failed_row_is_retried(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """失敗の行の書き込みが1度落ちても、外側の後始末でもう一度書く。"""
    real = turns.fail_turn
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(*args, **kwargs)

    monkeypatch.setattr(turns, "fail_turn", flaky)
    draft = create_new_draft(env.conn)
    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(_turn(env, draft["id"], FailingChat(RuntimeError("x"))))
    _assert_failed(env, draft["id"], "internal_error")
    assert calls["n"] == 2


def test_rescue_failure_does_not_hide_the_original_error(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """後始末も落ちたら元の例外を投げる（下書きは回復に任せる）。"""
    monkeypatch.setattr(turns, "finish_turn", _locked)
    monkeypatch.setattr(turns, "fail_turn", _locked)
    draft = create_new_draft(env.conn)
    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(_turn(env, draft["id"], ScriptChat()))
    assert repo.get_draft(env.conn, draft["id"])["status"] == "working"


def test_cancel_returns_to_open_with_cancelled_row(env: Env) -> None:
    """取り消し（クライアントの切断）でも open に戻して cancelled の行を残す。"""
    draft = create_new_draft(env.conn)

    async def main() -> None:
        task = asyncio.create_task(_turn(env, draft["id"], SlowChat()))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if repo.get_draft(env.conn, draft["id"])["status"] == "working":
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    _assert_failed(env, draft["id"], "cancelled")
    events = _events(env, draft["id"])
    assert ("turn_end", "cancelled") in events


def test_failure_after_finish_does_not_add_a_failed_row(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """書き終えた後（最後の読み出し）で落ちても、書いた結果に失敗の行を足さない。"""
    real_get, real_finish = repo.get_draft, turns.finish_turn
    finished = {"done": False}

    def finish(*args: Any, **kwargs: Any) -> bool:
        written = real_finish(*args, **kwargs)
        finished["done"] = True
        return written

    def get_draft(conn: sqlite3.Connection, draft_id: int) -> Any:
        if finished["done"]:
            raise sqlite3.OperationalError("database is locked")
        return real_get(conn, draft_id)

    draft = create_new_draft(env.conn)
    monkeypatch.setattr(turns, "finish_turn", finish)
    monkeypatch.setattr(repo, "get_draft", get_draft)
    chat = ScriptChat([change("basic.cycle_days", 14)])
    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(_turn(env, draft["id"], chat))
    monkeypatch.setattr(repo, "get_draft", real_get)
    got = real_get(env.conn, draft["id"])
    assert got["status"] == "open"
    assert [r["role"] for r in got["chat"]] == ["doctor", "assistant"]
    assert draft_form(got).basic.cycle_days == 14
